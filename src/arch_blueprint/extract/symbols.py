"""Definitions and the names they reference, read from source with libcst.

The one user of libcst. Grimp answers "which module imports which"; this answers
the question one level down — which class or function uses which — for
extractors whose nodes are definitions rather than modules.

Nothing is imported or executed: files are found through
``GrimpSource.module_file`` and parsed, and names are resolved by reading the
modules they point into. libcst keeps no cache between runs either, so another
checkout of the same package cannot leak into this one; the parse cache here
is keyed by a file's content, not its name.
"""

from __future__ import annotations

import hashlib
import sys
from collections import OrderedDict
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, Optional

import libcst as cst
from libcst import helpers
from libcst.metadata import (
    ClassScope,
    QualifiedName,
    QualifiedNameProvider,
    QualifiedNameSource,
    Scope,
    ScopeProvider,
)

from arch_blueprint.domain.node import NodeKind
from arch_blueprint.extract.source import GrimpSource

#: How many parsed modules the content-keyed cache keeps, across runs.
_CACHE_SIZE: Final = 8192


@dataclass(frozen=True)
class ModuleSymbols:
    """What one module defines, re-exports and references, as absolute names.

    ``definitions`` maps each top-level class and function (async ones
    included) to its kind, in source order. A nested class or function is not a
    definition of its own: it belongs to the outer one, and what it references
    counts for it.

    ``exports`` maps each name a module-level import binds to what it names —
    ``import a.b as c`` binds ``c`` to ``a.b``. Imports under ``if
    TYPE_CHECKING:``, ``try:`` or any ``if`` are module-level too, and a name
    imported in two branches names both: which branch runs is not read. This
    is what a package facade re-exports, and what a string annotation's names
    mean.

    ``aliases`` maps each other module-level variable to every name its values
    mention — ``Alias = Foo | Bar``, ``T = TypeVar("T", bound=Foo)``, ``type
    A = Foo``, ``HANDLERS = {"a": Foo}``, ``settings = Settings()``, and
    what later assignments add: ``HANDLERS |= {...}``, ``ITEMS += [Foo]``, or a
    function's ``global settings; settings = Settings()``. A variable is no
    definition and no node: what uses it depends on its value.

    ``stars`` are the modules ``from m import *`` pulls every public name of
    (``public``: a static ``__all__``, or None for "every name without a
    leading underscore"), and ``names`` is every name the module binds itself —
    what a star import cannot be the source of.

    ``references`` maps each definition to every name its code mentions:
    bases, metaclass, decorators, class-level annotations and values, and
    every method's parameters, defaults, return annotation and body; for a
    function, its decorators, type parameters, signature and body. A name local
    to a function (a parameter, even one named like an import, a type parameter,
    a match capture) and a builtin are left out; what is left is absolute but
    unresolved — see ``SymbolIndex.resolve``. The catalogue of forms is
    ``tests/test_symbols.py:_FORMS``.
    """

    module: str
    definitions: dict[str, NodeKind]
    exports: dict[str, tuple[str, ...]]
    references: dict[str, frozenset[str]]
    aliases: dict[str, frozenset[str]] = field(default_factory=dict)
    stars: tuple[str, ...] = ()
    names: frozenset[str] = frozenset()
    public: Optional[frozenset[str]] = None

    @classmethod
    def parse(cls, module: str, path: Path, *, is_package: bool) -> ModuleSymbols:
        """Read ``path`` as module ``module``; ``is_package`` for an ``__init__.py``.

        Raises ``libcst.ParserSyntaxError`` for a file libcst cannot parse, and
        ``RecursionError`` for an expression nested too deep to walk.
        """
        source = path.read_bytes()
        key = (module, is_package, hashlib.sha256(source).digest())
        cached = _PARSED.get(key)
        if cached is not None:
            _PARSED.move_to_end(key)
            return cached
        tree = cst.parse_module(source)
        package = module if is_package else module.rpartition(".")[0]
        collector = _Collector(module, package)
        # The tree is only read, so the copy MetadataWrapper makes by default
        # (to keep node identity its own) is a waste of most of the parse time.
        cst.MetadataWrapper(tree, unsafe_skip_copy=True).visit(collector)
        symbols = collector.symbols()
        _PARSED[key] = symbols
        if len(_PARSED) > _CACHE_SIZE:
            _PARSED.popitem(last=False)
        return symbols

    def star_exports(self, name: str) -> bool:
        """Whether ``from <this module> import *`` binds ``name``."""
        if self.public is not None:
            return name in self.public
        return not name.startswith("_")


#: Parsed modules by (name, is package, content digest): what a parse depends
#: on, so a file unchanged across the commits of a ``history`` run — or across
#: runs in one process — is read once. Never keyed by name alone (#39).
_PARSED: OrderedDict[tuple[str, bool, bytes], ModuleSymbols] = OrderedDict()


class SymbolIndex:
    """Every module of a source, parsed on first use, and name resolution.

    One index serves one run, like the ``GrimpSource`` it reads through.
    """

    def __init__(self, source: GrimpSource) -> None:
        self._source = source
        self._symbols: dict[str, Optional[ModuleSymbols]] = {}
        self._resolved: dict[str, frozenset[str]] = {}

    def symbols(self, module: str) -> Optional[ModuleSymbols]:
        """What ``module`` defines, or None when no analysed file holds it."""
        if module not in self._symbols:
            self._symbols[module] = self._parse(module)
        return self._symbols[module]

    def resolve(self, qualified: str) -> frozenset[str]:
        """The definitions an absolute name ends on — none, one, or several.

        A name under a definition is that definition — ``m.Foo.create`` is
        ``m.Foo`` — and a name a package facade re-exports, by name or with
        ``import *``, is followed to where it is defined. A module-level
        variable is followed to every name its value mentions, so ``Alias =
        Foo | Bar`` ends on both. The deepest module the name lies in decides:
        a name it neither defines, imports nor assigns is nothing we draw.
        """
        found = self._resolved.get(qualified)
        if found is None:
            found = self._resolve(qualified, frozenset())
            self._resolved[qualified] = found
        return found

    def _resolve(
        self,
        qualified: str,
        seen: frozenset[tuple[str, str]],
    ) -> frozenset[str]:
        parts = qualified.split(".")
        for cut in range(len(parts) - 1, 0, -1):
            symbols = self.symbols(".".join(parts[:cut]))
            if symbols is None:
                continue
            head = parts[cut]
            name = f"{symbols.module}.{head}"
            if name in symbols.definitions:
                return frozenset({name})
            # Keyed by where the name is looked up, not by the whole name: a
            # facade re-exporting from a path that is no module rewrites the
            # name longer each time (a.x.Q → a.x.x.Q → ...), and never repeats.
            key = (symbols.module, head)
            if key in seen:
                return frozenset()  # re-exported or assigned in a circle
            seen |= {key}
            rest = parts[cut + 1 :]
            targets = (*symbols.exports.get(head, ()), *symbols.aliases.get(head, ()))
            if targets:
                return frozenset().union(
                    *(self._resolve(".".join([t, *rest]), seen) for t in targets),
                )
            if head in symbols.names:
                return frozenset()  # bound here, to nothing a star import brought
            return self._resolve_star(symbols, head, rest, seen)
        return frozenset()

    def _resolve_star(
        self,
        symbols: ModuleSymbols,
        name: str,
        rest: list[str],
        seen: frozenset[tuple[str, str]],
    ) -> frozenset[str]:
        """``name`` in ``symbols``' module, bound by one of its ``import *``."""
        for star in reversed(symbols.stars):  # the last one binding it wins
            source = self.symbols(star)
            if source is None or not source.star_exports(name):
                continue
            found = self._resolve(".".join([star, name, *rest]), seen)
            if found:
                return found
        return frozenset()

    def _parse(self, module: str) -> Optional[ModuleSymbols]:
        path = self._source.module_file(module)
        if path is None:
            return None
        try:
            return ModuleSymbols.parse(
                module,
                path,
                is_package=path.name == "__init__.py",
            )
        except (cst.ParserSyntaxError, UnicodeDecodeError, RecursionError) as error:
            lines = str(error).strip().splitlines()
            reason = lines[0] if lines else type(error).__name__
            sys.stderr.write(
                f"warning: cannot parse '{path}' ({reason}); "
                f"its definitions are left out.\n",
            )
            return ModuleSymbols(module, {}, {}, {})


#: A name as written, and every name libcst says it may mean. The written
#: form is only read when libcst knows no meaning: a star import may bind it.
_Access = tuple[str, frozenset[QualifiedName]]

#: What a frame of names local to a definition belongs to. A class body's
#: names are not seen by the functions in it; a function body's and type
#: parameters are seen by everything nested inside.
_Frame = Literal["class body", "function body", "type parameters"]

#: Where a string in square brackets is a type, not a key: a subscript of one
#: of these is a generic (``Optional["Foo"]``, ``list["Foo"]``), even outside
#: an annotation — in an alias's value or a base class.
_GENERIC_MODULES: Final = ("typing.", "typing_extensions.", "collections.abc.")
_GENERIC_BUILTINS: Final = frozenset(
    f"builtins.{name}" for name in ("list", "dict", "set", "frozenset", "tuple", "type")
)


class _Collector(cst.CSTVisitor):
    """One pass over a module, filling a ``ModuleSymbols``."""

    METADATA_DEPENDENCIES = (QualifiedNameProvider, ScopeProvider)

    def __init__(self, module: str, package: str) -> None:
        super().__init__()
        self._module = module
        self._package = package
        self._definitions: dict[str, NodeKind] = {}
        self._exports: dict[str, list[str]] = {}
        self._stars: list[str] = []
        self._names: frozenset[str] = frozenset()
        self._public: Optional[frozenset[str]] = None
        # What each definition's code mentions, resolved once the module's
        # imports, definitions and star imports are all known: a definition
        # may be used above the line that defines it.
        self._accesses: dict[str, list[_Access]] = {}
        # What each module-level variable's values mention, likewise.
        self._alias_accesses: dict[str, list[_Access]] = {}
        # Where a mention goes: the definition walked, or the values of the
        # module-level variables being assigned. None at module level.
        self._sink: Optional[list[_Access]] = None
        self._aliases: tuple[str, ...] = ()  # the variables being assigned
        # Inside a definition, an assignment to a name it declares ``global``:
        # the module-level variables it adds to, and what its value mentions.
        self._global_targets: tuple[str, ...] = ()
        self._global_sink: Optional[list[_Access]] = None
        # The names each enclosing class or function body declares ``global``.
        self._globals: list[frozenset[str]] = []
        self._depth = 0  # enclosing classes and functions
        # Names local to what encloses a node and libcst's scopes miss: type
        # parameters (``def f[T]``) and match captures (``case [x]``), each
        # frame with what it belongs to.
        self._locals: list[tuple[frozenset[str], _Frame]] = []
        # Whether a string is a type (a forward reference) or a value, by the
        # innermost place that says: an annotation, ``Literal[...]``, the
        # metadata of ``Annotated[...]``, a call's arguments, ``cast``'s first.
        self._contexts: list[bool] = []
        self._marks: dict[int, bool] = {}
        # The names of definitions and assignment targets: what they bind, not
        # what they mention.
        self._definition_names: set[int] = set()

    def symbols(self) -> ModuleSymbols:
        return ModuleSymbols(
            module=self._module,
            definitions=self._definitions,
            exports={name: tuple(targets) for name, targets in self._exports.items()},
            references={
                owner: self._resolved(accesses)
                for owner, accesses in self._accesses.items()
            },
            aliases={
                name: self._resolved(accesses)
                for name, accesses in self._alias_accesses.items()
            },
            stars=tuple(self._stars),
            names=self._names,
            public=self._public,
        )

    def _resolved(self, accesses: list[_Access]) -> frozenset[str]:
        return frozenset(name for access in accesses for name in self._meanings(access))

    def _meanings(self, access: _Access) -> set[str]:
        """What one name may mean, made absolute.

        libcst's names are scope-based, not flow-sensitive: ``from m import F``
        followed by ``def F()`` gives ``F`` both meanings. A module-level
        definition is the one that stands, so the import is dropped.
        """
        written, qualified = access
        if not qualified:
            # Unbound anywhere in the module: a name only a star import brings.
            return {f"{self._module}.{written}"} if self._stars else set()
        local = {q.name for q in qualified if q.source is QualifiedNameSource.LOCAL}
        shadowed = any(
            f"{self._module}.{name.split('.', 1)[0]}" in self._definitions
            for name in local
        )
        meanings: set[str] = set()
        for name in qualified:
            if shadowed and name.source is QualifiedNameSource.IMPORT:
                continue
            absolute = self._absolute(name)
            if absolute is not None:
                meanings.add(absolute)
        return meanings

    # --- contexts: every node may open one ---------------------------------

    def on_visit(self, node: cst.CSTNode) -> bool:
        # Marked by its parent — a bound, an alias's value — the node's own
        # handler already sits in the context; marked by that handler (an
        # annotation, ``Literal[...]``), only its children do.
        mark = self._marks.get(id(node))
        if mark is not None:
            self._contexts.append(mark)
        visit_children = super().on_visit(node)
        if mark is None:
            mark = self._marks.get(id(node))
            if mark is not None:
                self._contexts.append(mark)
        return visit_children

    def on_leave(self, original_node: cst.CSTNode) -> None:
        super().on_leave(original_node)
        if self._marks.pop(id(original_node), None) is not None:
            self._contexts.pop()

    def _mark(self, node: Optional[cst.CSTNode], is_type: bool) -> None:
        if node is not None:
            self._marks[id(node)] = is_type

    # --- module scope -----------------------------------------------------

    def visit_Module(self, node: cst.Module) -> None:
        scope = self.get_metadata(ScopeProvider, node, None)
        if scope is not None:
            self._names = frozenset(assignment.name for assignment in scope.assignments)

    def visit_Assign(self, node: cst.Assign) -> None:
        """A module-level variable, or a static ``__all__``."""
        if self._depth:
            self._enter_global([t.target for t in node.targets])
            return
        if any(_is_all(t.target) for t in node.targets):
            public = _strings(node.value)
            # Anything but a literal list of strings: which names are public
            # cannot be read, so fall back to "no leading underscore".
            self._public = None if public is None else frozenset(public)
            return
        self._enter_alias([t.target for t in node.targets])

    def leave_Assign(self, original_node: cst.Assign) -> None:
        self._leave_alias()
        self._leave_global()

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        """``x: Foo = ...``; the value of ``Alias: TypeAlias = ...`` is a type."""
        if _named(node.annotation.annotation, "TypeAlias"):
            self._mark(node.value, is_type=True)
        if self._depth:
            self._enter_global([node.target])
        else:
            self._enter_alias([node.target])

    def leave_AnnAssign(self, original_node: cst.AnnAssign) -> None:
        self._leave_alias()
        self._leave_global()

    def visit_TypeAlias(self, node: cst.TypeAlias) -> None:
        """``type Alias[T] = ...``: a variable whose value is a type."""
        self._mark(node.value, is_type=True)
        self._enter_type_parameters(node.type_parameters)
        if not self._depth:
            self._enter_alias([node.name])

    def leave_TypeAlias(self, original_node: cst.TypeAlias) -> None:
        self._leave_alias()
        self._leave_type_parameters(original_node.type_parameters)

    def _enter_alias(self, targets: list[cst.BaseExpression]) -> None:
        """Mentions in a module-level assignment's value go to its variables.

        ``HANDLERS["a"] = Foo`` adds to ``HANDLERS``. A target of any other
        shape (``a, b = ...``, ``Foo.attr = ...``) binds nothing we follow.
        """
        if self._depth:
            return
        names: list[str] = []
        for target in targets:
            base = target.value if isinstance(target, cst.Subscript) else target
            if isinstance(base, cst.Name):
                self._definition_names.add(id(base))
                names.append(base.value)
        if names:
            self._aliases = tuple(names)
            self._sink = []

    def _leave_alias(self) -> None:
        if self._depth or not self._aliases or self._sink is None:
            return
        for name in self._aliases:
            self._alias_accesses.setdefault(name, []).extend(self._sink)
        self._aliases = ()
        self._sink = None

    def _enter_global(self, targets: list[cst.BaseExpression]) -> None:
        """Mentions in the value of ``X = ...`` go to ``X`` too, if ``global X``.

        The definition assigning still depends on them: its sink keeps them.
        """
        declared = self._globals[-1] if self._globals else frozenset()
        names: list[str] = []
        for target in targets:
            base = target.value if isinstance(target, cst.Subscript) else target
            if isinstance(base, cst.Name) and base.value in declared:
                names.append(base.value)
        if names:
            self._global_targets = tuple(names)
            self._global_sink = []

    def _leave_global(self) -> None:
        if self._global_sink is None:
            return
        for name in self._global_targets:
            self._alias_accesses.setdefault(name, []).extend(self._global_sink)
        self._global_targets = ()
        self._global_sink = None

    def visit_AugAssign(self, node: cst.AugAssign) -> None:
        """``__all__ += [...]``: more public names, if they can be read.

        Any other ``X |= ...`` / ``X += ...`` adds to what ``X`` holds, as an
        item assignment does.
        """
        if self._depth:
            self._enter_global([node.target])
            return
        if not _is_all(node.target):
            self._enter_alias([node.target])
            return
        if self._public is None:
            return
        more = _strings(node.value)
        self._public = None if more is None else self._public | frozenset(more)

    def leave_AugAssign(self, original_node: cst.AugAssign) -> None:
        self._leave_alias()
        self._leave_global()

    # --- definitions ------------------------------------------------------

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._enter(node)
        self._enter_type_parameters(node.type_parameters)

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self._leave_type_parameters(original_node.type_parameters)
        self._leave()

    def visit_ClassDef_body(self, node: cst.ClassDef) -> None:
        self._enter_body(node.body, "class body")

    def leave_ClassDef_body(self, node: cst.ClassDef) -> None:
        self._leave_body()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._enter(node)
        self._enter_type_parameters(node.type_parameters)

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self._leave_type_parameters(original_node.type_parameters)
        self._leave()

    def visit_FunctionDef_body(self, node: cst.FunctionDef) -> None:
        self._enter_body(node.body, "function body")

    def leave_FunctionDef_body(self, node: cst.FunctionDef) -> None:
        self._leave_body()

    def _enter_body(self, body: cst.BaseSuite, frame: _Frame) -> None:
        """A body's match captures are local to it, and only to it.

        Pushed for the body alone: a function's decorators, parameters and
        return annotation are read where it is defined, so a capture in its
        body does not shadow them.
        """
        names = _BodyNames()
        body.visit(names)
        self._locals.append((frozenset(names.captures), frame))
        self._globals.append(frozenset(names.globals))

    def _leave_body(self) -> None:
        self._globals.pop()
        self._locals.pop()

    def _enter(self, node: cst.ClassDef | cst.FunctionDef) -> None:
        self._definition_names.add(id(node.name))
        if self._depth == 0:
            owner = f"{self._module}.{node.name.value}"
            self._definitions[owner] = (
                NodeKind.CLASS if isinstance(node, cst.ClassDef) else NodeKind.FUNCTION
            )
            self._sink = self._accesses.setdefault(owner, [])
        self._depth += 1

    def _leave(self) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._sink = None

    def _enter_type_parameters(self, node: Optional[cst.TypeParameters]) -> None:
        """``[T: Foo = Bar]``: ``T`` is local, its bound and default are types.

        libcst resolves a type parameter to whatever the module binds by that
        name, so it is shadowed here.
        """
        if node is None:
            return
        names: set[str] = set()
        for parameter in node.params:
            self._mark(parameter.default, is_type=True)
            names.add(parameter.param.name.value)
            self._definition_names.add(id(parameter.param.name))
            if isinstance(parameter.param, cst.TypeVar):
                self._mark(parameter.param.bound, is_type=True)
        self._locals.append((frozenset(names), "type parameters"))

    def _leave_type_parameters(self, node: Optional[cst.TypeParameters]) -> None:
        if node is not None:
            self._locals.pop()

    # --- module-level imports ---------------------------------------------

    def _export(self, name: str, target: str) -> None:
        targets = self._exports.setdefault(name, [])
        if target not in targets:
            targets.append(target)

    def visit_Import(self, node: cst.Import) -> None:
        if self._depth:
            return
        for alias in node.names:
            name = alias.evaluated_name
            if alias.asname is not None:
                self._export(str(alias.evaluated_alias), name)
            else:
                top = name.split(".", 1)[0]  # `import a.b` binds `a`
                self._export(top, top)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if self._depth:
            return
        base = helpers.get_absolute_module_from_package_for_import(
            self._package or None,
            node,
        )
        if base is None:
            return
        if isinstance(node.names, cst.ImportStar):
            self._stars.append(base)
            return
        for alias in node.names:
            bound = alias.evaluated_alias or alias.evaluated_name
            self._export(bound, f"{base}.{alias.evaluated_name}")

    # --- references -------------------------------------------------------

    def visit_Name(self, node: cst.Name) -> None:
        self._reference(node)

    def visit_Attribute(self, node: cst.Attribute) -> None:
        self._reference(node)

    def _reference(self, node: cst.Name | cst.Attribute) -> None:
        if self._sink is None or id(node) in self._definition_names:
            return
        head = _dotted(node)
        if head is not None and self._is_local(head):
            return
        qualified = self.get_metadata(QualifiedNameProvider, node, set())
        if head is not None:
            outside = self._outside_class(node, head)
            if outside:
                self._emit(("", frozenset(outside)))
        if qualified:
            self._emit(("", frozenset(qualified)))
        elif isinstance(node, cst.Name) and self._is_unbound(node):
            self._emit((node.value, frozenset()))

    def _emit(self, access: _Access) -> None:
        """One mention, for the definition walked and any variable assigned."""
        if self._sink is not None:
            self._sink.append(access)
        if self._global_sink is not None:
            self._global_sink.append(access)

    def _outside_class(self, node: cst.CSTNode, dotted: str) -> set[QualifiedName]:
        """What ``dotted`` means around the class whose body binds its first part.

        libcst's scopes are not flow-sensitive: in ``class C: x: t.T; t = 0``
        the annotation reads the module's ``t`` — the attribute is bound only
        after it — yet libcst gives ``t`` the class-local meaning alone. Both
        meanings are kept, as for any name bound twice. Returned apart: the
        class-local meaning is rooted at a definition, which would otherwise
        shadow the import (``_meanings``).
        """
        scope = self.get_metadata(ScopeProvider, node, None)
        if not isinstance(scope, ClassScope):
            return set()
        if dotted.split(".", 1)[0] not in scope.assignments:
            return set()
        outer: Optional[Scope] = scope.parent
        while isinstance(outer, ClassScope):  # a class body sees no class around
            outer = outer.parent
        return set() if outer is None else set(outer.get_qualified_names_for(dotted))

    def _is_local(self, dotted: str) -> bool:
        """Whether a name's first part is a type parameter or match capture.

        A class body's captures are no local of the functions inside it.
        """
        first = dotted.split(".", 1)[0]
        in_function = False
        for names, frame in reversed(self._locals):
            if frame == "class body" and in_function:
                continue
            if first in names:
                return True
            in_function = in_function or frame == "function body"
        return False

    def _is_unbound(self, node: cst.Name) -> bool:
        """A name read with nothing in the module binding it: a star import's.

        Not an attribute's name (``obj.Widget``) nor a keyword's: those are
        not accesses of any scope.
        """
        scope = self.get_metadata(ScopeProvider, node, None)
        if scope is None:
            return False
        return any(access.node is node for access in scope.accesses[node.value])

    def _absolute(self, qualified: QualifiedName) -> Optional[str]:
        # `<locals>` (a parameter, a local variable), `<comprehension>`, ...
        if qualified.source is QualifiedNameSource.BUILTIN or "<" in qualified.name:
            return None
        if qualified.source is QualifiedNameSource.LOCAL:
            return f"{self._module}.{qualified.name}"
        return _absolute(qualified.name, self._package)

    # --- where a string is a type -----------------------------------------

    def visit_Annotation(self, node: cst.Annotation) -> None:
        self._mark(node, is_type=True)

    def visit_Subscript(self, node: cst.Subscript) -> None:
        if _named(node.value, "Literal"):
            self._mark(node, is_type=False)
        elif _named(node.value, "Annotated"):
            # Annotated[X, metadata...]: only the first element is a type.
            for position, element in enumerate(node.slice):
                self._mark(element, is_type=position == 0)
        elif self._is_generic(node.value):
            for element in node.slice:
                self._mark(element, is_type=True)

    def _is_generic(self, node: cst.BaseExpression) -> bool:
        """``Optional``, ``typing.List``, ``list``: a subscript of it is a type."""
        for name in self.get_metadata(QualifiedNameProvider, node, set()):
            if name.source is QualifiedNameSource.BUILTIN:
                if name.name in _GENERIC_BUILTINS:
                    return True
            elif name.name.startswith(_GENERIC_MODULES):
                return True
        return False

    def visit_Call(self, node: cst.Call) -> None:
        """``cast("Foo", x)``, ``TypeVar("T", "Foo", bound="Bar")``.

        Any other call's arguments are values, even inside an annotation:
        ``Annotated[int, Field(alias="E")]``.
        """
        if _named(node.func, "cast") or _named(node.func, "ForwardRef"):
            for position, arg in enumerate(node.args):
                self._mark(arg, is_type=position == 0 and arg.keyword is None)
        elif _named(node.func, "TypeVar"):
            for position, arg in enumerate(node.args):
                keyword = None if arg.keyword is None else arg.keyword.value
                constraint = keyword is None and position > 0
                self._mark(arg, is_type=constraint or keyword in {"bound", "default"})
        elif self._contexts:
            self._mark(node, is_type=False)

    def visit_SimpleString(self, node: cst.SimpleString) -> None:
        """A forward reference: libcst resolves no name inside a string."""
        if self._sink is None or not self._contexts or not self._contexts[-1]:
            return
        # Looked up in the scope the string sits in, as libcst looks up a name
        # written bare: a function-local import is seen, a parameter shadows.
        scope = self.get_metadata(ScopeProvider, node, None)
        for dotted in _string_names(node):
            if self._is_local(dotted):
                continue
            qualified = (
                scope.get_qualified_names_for(dotted) if scope is not None else set()
            )
            self._emit((dotted, frozenset(qualified)))
            outside = self._outside_class(node, dotted)
            if outside:
                self._emit((dotted, frozenset(outside)))


def _string_names(node: cst.SimpleString) -> list[str]:
    """The names a string holding a type mentions, strings inside it included."""
    value = node.evaluated_value
    if not isinstance(value, str):
        return []
    try:
        expression = cst.parse_expression(value.strip())
    except cst.ParserSyntaxError:
        return []  # not an expression: text, not a name
    names = _DottedNames()
    expression.visit(names)
    return names.found


class _DottedNames(cst.CSTVisitor):
    """Every ``a`` and ``a.b.c`` in a type expression, outermost chains only.

    Like the annotation it came from: a ``Literal``'s strings, ``Annotated``'s
    metadata and a call's arguments are values, a nested string is a type.
    """

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    def visit_Name(self, node: cst.Name) -> None:
        self.found.append(node.value)

    def visit_Attribute(self, node: cst.Attribute) -> bool:
        dotted = _dotted(node)
        if dotted is None:
            return True  # `f().x`: look for names inside the call
        self.found.append(dotted)
        return False

    def visit_Subscript(self, node: cst.Subscript) -> bool:
        node.value.visit(self)
        if _named(node.value, "Literal"):
            return False
        elements = node.slice[:1] if _named(node.value, "Annotated") else node.slice
        for element in elements:
            element.visit(self)
        return False

    def visit_Call(self, node: cst.Call) -> bool:
        node.func.visit(self)
        return False

    def visit_SimpleString(self, node: cst.SimpleString) -> None:
        self.found.extend(_string_names(node))


class _BodyNames(cst.CSTVisitor):
    """What a class or function body's own statements bind that libcst misses.

    ``captures``: the names its ``match`` statements capture, its locals —
    libcst binds no name in a pattern, so a capture named like an import would
    otherwise mean the import. ``globals``: the names it declares ``global``.
    A nested class's or function's are its own.
    """

    def __init__(self) -> None:
        super().__init__()
        self.captures: set[str] = set()
        self.globals: set[str] = set()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        return False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        return False

    def visit_Global(self, node: cst.Global) -> None:
        self.globals.update(item.name.value for item in node.names)

    def visit_MatchAs(self, node: cst.MatchAs) -> None:
        if node.name is not None:
            self.captures.add(node.name.value)

    def visit_MatchStar(self, node: cst.MatchStar) -> None:
        if node.name is not None:
            self.captures.add(node.name.value)

    def visit_MatchMapping(self, node: cst.MatchMapping) -> None:
        if node.rest is not None:
            self.captures.add(node.rest.value)


def _dotted(node: cst.BaseExpression) -> Optional[str]:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr.value}"
    return None


def _named(node: cst.BaseExpression, name: str) -> bool:
    """Whether ``node`` is ``name`` or ``something.name``: ``typing.Literal``."""
    dotted = _dotted(node)
    return dotted is not None and dotted.rpartition(".")[2] == name


def _is_all(node: cst.BaseExpression) -> bool:
    return isinstance(node, cst.Name) and node.value == "__all__"


def _strings(node: cst.BaseExpression) -> Optional[Collection[str]]:
    """The strings of a literal list or tuple of strings, else None."""
    if not isinstance(node, (cst.List, cst.Tuple)):
        return None
    values: list[str] = []
    for element in node.elements:
        if not isinstance(element, cst.Element):
            return None  # *unpacked
        if not isinstance(element.value, cst.SimpleString):
            return None
        value = element.value.evaluated_value
        if not isinstance(value, str):
            return None
        values.append(value)
    return values


def _absolute(name: str, package: str) -> str:
    """``.models.User`` as seen from ``package``, made absolute."""
    stripped = name.lstrip(".")
    dots = len(name) - len(stripped)
    if not dots:
        return name
    parts = package.split(".") if package else []
    parts = parts[: max(0, len(parts) - (dots - 1))]
    return ".".join(part for part in (*parts, stripped) if part)
