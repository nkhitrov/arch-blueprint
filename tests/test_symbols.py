"""Definitions and the names they reference, read with libcst — in-process.

Every project here is a few files in ``tmp_path``: small enough that each test
shows the one construct it is about. A dependency is asserted through
``SymbolIndex.resolve``, the way the extractor sees it: a referenced name ends
on a definition, or on nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arch_blueprint.domain.node import NodeKind
from arch_blueprint.extract.source import GrimpSource
from arch_blueprint.extract.symbols import ModuleSymbols, SymbolIndex

_MODELS = """\
class User:
    @classmethod
    def create(cls) -> "User":
        return cls()


class Meta(type):
    pass


def tracked(cls):
    return cls


class Order:
    pass
"""


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def _index(root: Path, files: dict[str, str], *patterns: str) -> SymbolIndex:
    _write(root, {"shop/__init__.py": "", "shop/models.py": _MODELS, **files})
    return SymbolIndex(GrimpSource(str(root), list(patterns or ["shop.**"])))


def _deps(index: SymbolIndex, definition: str) -> set[str]:
    """What ``definition`` depends on: its references, resolved, itself left out."""
    module = definition.rsplit(".", 1)[0]
    symbols = index.symbols(module)
    assert symbols is not None
    resolved = {
        target
        for name in symbols.references[definition]
        for target in index.resolve(name)
    }
    return resolved - {definition}


# --- definitions ----------------------------------------------------------


def test_definitions_are_top_level_classes_and_functions(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "class Service:\n"
                "    class Inner:\n"
                "        pass\n"
                "    def run(self):\n"
                "        def helper():\n"
                "            pass\n"
                "def build():\n"
                "    pass\n"
                "async def fetch():\n"
                "    pass\n"
                "LIMIT = 3\n"
            ),
        },
    )
    symbols = index.symbols("shop.service")
    assert symbols is not None
    assert symbols.definitions == {
        "shop.service.Service": NodeKind.CLASS,
        "shop.service.build": NodeKind.FUNCTION,
        "shop.service.fetch": NodeKind.FUNCTION,
    }
    assert list(symbols.definitions) == [
        "shop.service.Service",
        "shop.service.build",
        "shop.service.fetch",
    ], "source order: renderers draw in node order"


def test_nested_definitions_count_for_their_outer_one(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from shop.models import User, Order\n"
                "class Service:\n"
                "    class Inner(User):\n"
                "        pass\n"
                "    def run(self):\n"
                "        def helper():\n"
                "            return Order()\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {
        "shop.models.User",
        "shop.models.Order",
    }


# --- the four places a class references another ----------------------------


def test_declarative_typing(tmp_path: Path) -> None:
    """Bases, metaclass, decorators, class-level annotations and values."""
    index = _index(
        tmp_path,
        {
            "shop/other.py": "class Base:\n    pass\nclass Default:\n    pass\n",
            "shop/service.py": (
                "from shop.models import User, Meta, tracked, Order\n"
                "from shop.other import Base, Default\n"
                "@tracked\n"
                "class Service(Base, metaclass=Meta):\n"
                "    owner: User\n"
                "    fallback = Default\n"
                "    orders: list[Order] = []\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {
        "shop.models.tracked",
        "shop.other.Base",
        "shop.models.Meta",
        "shop.models.User",
        "shop.other.Default",
        "shop.models.Order",
    }


def test_constructor(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from shop.models import User, Order\n"
                "class Service:\n"
                "    def __init__(self, user: User) -> None:\n"
                "        self.order = Order()\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {
        "shop.models.User",
        "shop.models.Order",
    }


def test_method_signatures(tmp_path: Path) -> None:
    """Parameter annotations, defaults and the return annotation."""
    index = _index(
        tmp_path,
        {
            "shop/other.py": "class Base:\n    pass\n",
            "shop/service.py": (
                "from shop import models\n"
                "from shop.other import Base\n"
                "class Service:\n"
                "    def get(self, user: models.User, kind=Base) -> models.Order:\n"
                "        pass\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {
        "shop.models.User",
        "shop.models.Order",
        "shop.other.Base",
    }


def test_method_bodies(tmp_path: Path) -> None:
    """A call through a class — ``User.create()`` — depends on the class."""
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "import shop.models\n"
                "class Service:\n"
                "    def run(self):\n"
                "        user = shop.models.User.create()\n"
                "        return [shop.models.Order() for _ in range(3)]\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {
        "shop.models.User",
        "shop.models.Order",
    }


# --- how names are written -------------------------------------------------


def test_string_annotations(tmp_path: Path) -> None:
    """Forward references under ``TYPE_CHECKING``; a ``Literal`` is not one."""
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from typing import TYPE_CHECKING, Literal, Optional\n"
                "if TYPE_CHECKING:\n"
                "    from shop import models\n"
                "    from shop.models import User\n"
                "class Service:\n"
                "    owner: 'User'\n"
                "    def get(self, mode: Literal['Helper']) -> 'list[models.Order]':\n"
                "        pass\n"
                "    def peer(self) -> Optional['Service']:\n"
                "        pass\n"
                "class Helper:\n"
                "    pass\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {
        "shop.models.User",
        "shop.models.Order",
    }


def test_unparsable_string_annotation_is_ignored(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from typing import Annotated\n"
                "from shop.models import User\n"
                "class Service:\n"
                "    owner: Annotated[User, 'not a name!']\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {"shop.models.User"}


def test_relative_and_aliased_imports(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/sales/__init__.py": "",
            "shop/sales/cart.py": "class Cart:\n    pass\n",
            "shop/sales/service.py": (
                "from ..models import User as Customer\n"
                "from . import cart\n"
                "import shop.models as m\n"
                "class Service:\n"
                "    def run(self, who: Customer) -> cart.Cart:\n"
                "        return m.Order()\n"
            ),
        },
    )
    assert _deps(index, "shop.sales.service.Service") == {
        "shop.models.User",
        "shop.sales.cart.Cart",
        "shop.models.Order",
    }


def test_relative_import_in_a_package_facade(tmp_path: Path) -> None:
    """In ``__init__.py`` a single dot is the package itself, not its parent."""
    index = _index(
        tmp_path,
        {
            "shop/sales/__init__.py": (
                "from .cart import Cart\ndef checkout(cart: Cart):\n    pass\n"
            ),
            "shop/sales/cart.py": "class Cart:\n    pass\n",
        },
    )
    assert _deps(index, "shop.sales.checkout") == {"shop.sales.cart.Cart"}


def test_function_local_import(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "class Service:\n"
                "    def run(self):\n"
                "        from shop.models import User\n"
                "        return User()\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {"shop.models.User"}


def test_shadowing_parameter_is_not_the_import(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from shop.models import User, Order\n"
                "class Service:\n"
                "    def run(self, User: int) -> None:\n"
                "        User.bit_length()\n"
                "        Order = 3\n"
                "        return Order\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == set()
    symbols = index.symbols("shop.service")
    assert symbols is not None
    assert all("<" not in name for name in symbols.references["shop.service.Service"])


def test_builtins_and_outside_names_resolve_to_nothing(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "import typing\n"
                "from collections import OrderedDict\n"
                "class Service:\n"
                "    def run(self) -> typing.Any:\n"
                "        return OrderedDict(), len([]), print\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == set()
    assert index.resolve("typing.Any") == set()
    assert index.resolve("shop.no_such_module.Thing") == set()


def test_functions_and_classes_reference_each_other(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from shop.models import User\n"
                "def make() -> User:\n"
                "    return User()\n"
                "class Service:\n"
                "    def run(self):\n"
                "        return make()\n"
            ),
        },
    )
    assert _deps(index, "shop.service.make") == {"shop.models.User"}
    assert _deps(index, "shop.service.Service") == {"shop.service.make"}


def test_self_reference_resolves_to_itself(tmp_path: Path) -> None:
    index = _index(tmp_path, {})
    symbols = index.symbols("shop.models")
    assert symbols is not None
    resolved = {
        target
        for name in symbols.references["shop.models.User"]
        for target in index.resolve(name)
    }
    assert resolved == {"shop.models.User"}


# --- resolution ------------------------------------------------------------


def test_reexport_through_a_package_facade(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/__init__.py": "from shop.api import User\n",
            "shop/api/__init__.py": "from ..models import User\n",
            "shop/service.py": (
                "import shop\n"
                "from shop import User\n"
                "class Service(User):\n"
                "    def run(self):\n"
                "        return shop.User.create()\n"
            ),
        },
    )
    assert index.resolve("shop.User") == {"shop.models.User"}
    assert index.resolve("shop.api.User.create") == {"shop.models.User"}
    assert _deps(index, "shop.service.Service") == {"shop.models.User"}


def test_circular_reexports_end(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/a/__init__.py": "from shop.b import Thing\n",
            "shop/b/__init__.py": "from shop.a import Thing\n",
        },
    )
    assert index.resolve("shop.a.Thing") == set()


def test_reexported_submodule(tmp_path: Path) -> None:
    index = _index(tmp_path, {"shop/__init__.py": "from . import models as m\n"})
    assert index.resolve("shop.m.User") == {"shop.models.User"}


def test_symbols_of_a_module_outside_the_graph_is_none(tmp_path: Path) -> None:
    index = _index(tmp_path, {})
    assert index.symbols("typing") is None
    assert index.symbols("shop.missing") is None


# --- locating files without running them -----------------------------------


def test_modules_under(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/models.py": "",
            "shop/sales/__init__.py": "",
            "shop/sales/cart.py": "",
            "shopping/__init__.py": "",
        },
    )
    source = GrimpSource(str(tmp_path), ["shop.**", "shopping"])
    assert source.modules_under("shop.sales") == ["shop.sales", "shop.sales.cart"]
    assert source.modules_under("shop") == [
        "shop",
        "shop.models",
        "shop.sales",
        "shop.sales.cart",
    ]


def test_module_file(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/models.py": "",
            "shop/sales/__init__.py": "",
            "ns/plugins/__init__.py": "",
            "ns/plugins/auth.py": "",
        },
    )
    source = GrimpSource(str(tmp_path), ["shop.**", "ns.**"])
    assert source.module_file("shop") == tmp_path / "shop" / "__init__.py"
    assert source.module_file("shop.models") == tmp_path / "shop" / "models.py"
    assert source.module_file("shop.sales") == tmp_path / "shop/sales/__init__.py"
    assert source.module_file("ns.plugins.auth") == tmp_path / "ns/plugins/auth.py"
    assert source.module_file("ns") is None, "a namespace package has no file"
    assert source.module_file("shop.missing") is None
    assert source.module_file("typing") is None, "outside the analysed packages"


def test_nothing_is_imported_or_executed(tmp_path: Path) -> None:
    """``find_spec("a.b")`` imports ``a`` — running the project. Nothing may."""
    before_modules = set(sys.modules)
    before_path = list(sys.path)
    boom = "raise RuntimeError('project code ran')\n"
    index = _index(
        tmp_path,
        {
            "shop/__init__.py": boom,
            "shop/sales/__init__.py": boom,
            "shop/sales/cart.py": (
                "from shop.models import User\nclass Cart(User):\n    pass\n"
            ),
        },
    )
    assert _deps(index, "shop.sales.cart.Cart") == {"shop.models.User"}
    assert index.resolve("shop.sales.cart.Cart") == {"shop.sales.cart.Cart"}
    assert set(sys.modules) - before_modules == set()
    assert sys.path == before_path


def test_parse_reads_one_file(tmp_path: Path) -> None:
    path = tmp_path / "cart.py"
    path.write_text("from .models import User\nclass Cart(User):\n    pass\n")
    symbols = ModuleSymbols.parse("shop.sales.cart", path, is_package=False)
    assert symbols.module == "shop.sales.cart"
    assert symbols.exports == {"User": ("shop.sales.models.User",)}
    assert "shop.sales.models.User" in symbols.references["shop.sales.cart.Cart"]


@pytest.mark.parametrize(
    ("statement", "exports"),
    [
        pytest.param("import a.b", {"a": ("a",)}, id="import_binds_top"),
        pytest.param("import a.b as c", {"c": ("a.b",)}, id="import_as"),
        pytest.param("from a import b as c", {"c": ("a.b",)}, id="from_as"),
        pytest.param("from . import x", {"x": ("shop.x",)}, id="relative"),
        pytest.param("from a import *", {}, id="star"),
        pytest.param(
            "try:\n    from a import b\nexcept ImportError:\n    b = None",
            {"b": ("a.b",)},
            id="try_block",
        ),
        pytest.param("def f():\n    from a import b", {}, id="local_not_exported"),
    ],
)
def test_exports(
    tmp_path: Path,
    statement: str,
    exports: dict[str, tuple[str, ...]],
) -> None:
    path = tmp_path / "__init__.py"
    path.write_text(statement + "\n")
    assert ModuleSymbols.parse("shop", path, is_package=True).exports == exports


# --- star imports, rebinding, strings in scope ------------------------------


def test_star_import_in_a_facade_is_followed(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/star/__init__.py": "from .impl import *\n",
            "shop/star/impl.py": "class Starred:\n    pass\nclass _Hidden:\n    pass\n",
            "shop/service.py": (
                "from shop.star import Starred\n"
                "import shop.star\n"
                "class Service:\n"
                "    def run(self):\n"
                "        return Starred(), shop.star._Hidden()\n"
            ),
        },
    )
    assert index.resolve("shop.star.Starred") == {"shop.star.impl.Starred"}
    assert index.resolve("shop.star._Hidden") == set(), "private: not star-exported"
    assert _deps(index, "shop.service.Service") == {"shop.star.impl.Starred"}


def test_star_import_honours_a_static_all(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/star/__init__.py": "from .impl import *\n",
            "shop/star/impl.py": (
                "__all__ = ['Listed']\n"
                "__all__ += ['Added']\n"
                "class Listed:\n    pass\n"
                "class Added:\n    pass\n"
                "class Unlisted:\n    pass\n"
            ),
        },
    )
    assert index.resolve("shop.star.Listed") == {"shop.star.impl.Listed"}
    assert index.resolve("shop.star.Added") == {"shop.star.impl.Added"}
    assert index.resolve("shop.star.Unlisted") == set()


def test_star_import_in_a_consumer(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from shop.models import *\n"
                "LIMIT = 3\n"
                "class Service:\n"
                "    def run(self, user: 'Order') -> None:\n"
                "        return User(), LIMIT, user.Meta\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {
        "shop.models.User",
        "shop.models.Order",
    }


def test_star_imports_of_each_other_end(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/a/__init__.py": "from shop.b import *\n",
            "shop/b/__init__.py": "from shop.a import *\n",
        },
    )
    assert index.resolve("shop.a.Thing") == set()


def test_a_definition_rebinding_an_import_is_the_one_used(tmp_path: Path) -> None:
    """Scope-based names give ``F`` both meanings; the definition stands."""
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from shop.models import User, tracked\n"
                "def tracked():\n"
                "    pass\n"
                "class User:\n"
                "    pass\n"
                "class Service:\n"
                "    def run(self) -> 'User':\n"
                "        return tracked()\n"
            ),
        },
    )
    assert _deps(index, "shop.service.tracked") == set(), "not its own name"
    assert _deps(index, "shop.service.User") == set()
    assert _deps(index, "shop.service.Service") == {
        "shop.service.tracked",
        "shop.service.User",
    }


def test_string_annotation_sees_a_function_local_import(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "class Service:\n"
                "    def run(self):\n"
                "        from shop.models import User\n"
                "        def check(user: 'User') -> None:\n"
                "            pass\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {"shop.models.User"}


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param("Annotated[int, 'Order']", id="metadata_string"),
        pytest.param("Annotated[int, Field(alias='Order')]", id="call_argument"),
        pytest.param("typing.Literal['Order']", id="literal"),
    ],
)
def test_strings_that_are_values_are_no_forward_reference(
    tmp_path: Path,
    annotation: str,
) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "import typing\n"
                "from typing import Annotated\n"
                "from shop.models import Order\n"
                "def Field(alias):\n"
                "    pass\n"
                "class Service:\n"
                f"    x: {annotation}\n"
            ),
        },
    )
    assert "shop.models.Order" not in _deps(index, "shop.service.Service")


def test_annotated_type_in_quotes_is_a_forward_reference(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from typing import Annotated\n"
                "from shop.models import Order\n"
                "class Service:\n"
                "    x: Annotated['Order', 'Order is metadata here']\n"
            ),
        },
    )
    assert _deps(index, "shop.service.Service") == {"shop.models.Order"}


# --- what cannot be read ends in a warning, not a traceback ------------------


def test_deep_expression_is_left_out_with_a_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    chain = " + ".join(["'s'"] * 1000)
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from shop.models import User\n"
                "class Service:\n"
                f"    def run(self):\n        return {chain} + User()\n"
            ),
        },
    )
    symbols = index.symbols("shop.service")
    assert symbols is not None
    assert symbols.definitions == {}
    assert "cannot parse" in capsys.readouterr().err


def test_reexport_from_a_path_that_is_no_module_ends(tmp_path: Path) -> None:
    """Each hop rewrites the name longer — a.x.Q, a.x.x.Q — so it never repeats."""
    _write(
        tmp_path,
        {
            "a/__init__.py": "from a.x import x\n",
            "a/c.py": "import a\nclass C:\n    def f(self):\n        return a.x.Q\n",
        },
    )
    index = SymbolIndex(GrimpSource(str(tmp_path), ["a.**"]))
    assert index.resolve("a.x.Q") == set()
    assert _deps(index, "a.c.C") == set()


# --- every way a definition refers to another ------------------------------
#
# One case per syntactic form in the catalogue of dependency forms: the source
# of ``shop/service.py`` (``shop.models`` holds User, Order, Meta, tracked;
# ``shop.extra`` holds Extra and helper), the definition asked about, and what
# it depends on. Where a form is deliberately no dependency, the expected set
# says so and the case's id starts with ``not_``.

_EXTRA = """\
class Extra:
    pass


def helper():
    pass
"""

_IMPORTS = (
    "import typing\n"
    "from typing import TYPE_CHECKING, Annotated, Any, Optional, TypeVar, cast\n"
    "import shop.models\n"
    "from shop import models\n"
    "from shop.models import User, Order, Meta, tracked\n"
    "from shop.extra import Extra, helper\n"
)

_U = {"shop.models.User"}
_UO = {"shop.models.User", "shop.models.Order"}

_FORMS = [
    # declaration of a function
    pytest.param(
        "@tracked\ndef f(): pass\n",
        "f",
        {"shop.models.tracked"},
        id="fn_decorator",
    ),
    pytest.param(
        "@helper(User, key=Order)\ndef f(): pass\n",
        "f",
        {"shop.extra.helper", *_UO},
        id="fn_decorator_call_args",
    ),
    pytest.param(
        "@models.tracked\ndef f(): pass\n",
        "f",
        {"shop.models.tracked"},
        id="fn_decorator_dotted",
    ),
    pytest.param(
        "def f(a: User, /, b: Order): pass\n",
        "f",
        _UO,
        id="fn_posonly_and_plain",
    ),
    pytest.param(
        "def f(*, a: User, b: Order = None): pass\n",
        "f",
        _UO,
        id="fn_kwonly",
    ),
    pytest.param(
        "def f(*args: User, **kwargs: Order): pass\n",
        "f",
        _UO,
        id="fn_star_args",
    ),
    pytest.param(
        "from typing_extensions import Unpack\ndef f(**kw: Unpack[User]): pass\n",
        "f",
        _U,
        id="fn_unpack_kwargs",
    ),
    pytest.param("def f(a=User, *, b=Order()): pass\n", "f", _UO, id="fn_defaults"),
    pytest.param(
        "def f(a=helper): pass\n",
        "f",
        {"shop.extra.helper"},
        id="fn_default_function",
    ),
    pytest.param(
        "def f(a: Annotated[User, helper(Order)]): pass\n",
        "f",
        {"shop.extra.helper", *_UO},
        id="fn_annotated_depends",
    ),
    pytest.param(
        "def f(a: Annotated[Any, helper()] = helper(Order)): pass\n",
        "f",
        {"shop.extra.helper", "shop.models.Order"},
        id="fn_depends_default",
    ),
    pytest.param("def f() -> User: pass\n", "f", _U, id="fn_return"),
    pytest.param("async def f() -> User: pass\n", "f", _U, id="fn_async"),
    pytest.param("def f() -> 'User': pass\n", "f", _U, id="fn_string_return"),
    pytest.param(
        "def f(a: Optional['User']): pass\n",
        "f",
        _U,
        id="fn_string_in_optional",
    ),
    pytest.param("def f(a: 'Optional[User]'): pass\n", "f", _U, id="fn_string_whole"),
    pytest.param(
        "def f(a: 'list[shop.models.User]'): pass\n",
        "f",
        _U,
        id="fn_string_dotted_path",
    ),
    pytest.param(
        "def f(a: \"Optional['User']\"): pass\n",
        "f",
        _U,
        id="fn_string_in_string",
    ),
    pytest.param(
        (
            "if TYPE_CHECKING:\n"
            "    from shop.extra import Extra as E\n"
            "def f(a: 'E'): pass\n"
        ),
        "f",
        {"shop.extra.Extra"},
        id="fn_type_checking_import",
    ),
    pytest.param("def f[T: User](a: T) -> T: pass\n", "f", _U, id="fn_pep695_bound"),
    pytest.param(
        "def f[T: (User, Order)](a: T): pass\n",
        "f",
        _UO,
        id="fn_pep695_constraints",
    ),
    pytest.param(
        "def f[T: 'User'](a: T): pass\n",
        "f",
        _U,
        id="fn_pep695_string_bound",
    ),
    pytest.param(
        "def f[T = User](a: T): pass\n",
        "f",
        _U,
        id="fn_pep696_default",
    ),
    # declaration of a class
    pytest.param(
        "@tracked\nclass C: pass\n",
        "C",
        {"shop.models.tracked"},
        id="cls_decorator",
    ),
    pytest.param(
        "@helper(Order)\nclass C: pass\n",
        "C",
        {"shop.extra.helper", "shop.models.Order"},
        id="cls_decorator_call_args",
    ),
    pytest.param("class C(User, models.Order): pass\n", "C", _UO, id="cls_bases"),
    pytest.param(
        "class C(metaclass=Meta): pass\n",
        "C",
        {"shop.models.Meta"},
        id="cls_metaclass",
    ),
    pytest.param("class C(User, flag=Order): pass\n", "C", _UO, id="cls_keyword"),
    pytest.param(
        "from typing import Generic\nclass C(Generic[User]): pass\n",
        "C",
        _U,
        id="cls_generic_arg",
    ),
    pytest.param(
        "class C(list['User']): pass\n",
        "C",
        _U,
        id="cls_string_generic_base",
    ),
    pytest.param("class C[T: User]: pass\n", "C", _U, id="cls_pep695_bound"),
    pytest.param(
        "class C[T](list[T], Order): pass\n",
        "C",
        {"shop.models.Order"},
        id="cls_pep695_base",
    ),
    pytest.param(
        "class C:\n    x: User\n    y: 'Order'\n",
        "C",
        _UO,
        id="cls_annotations",
    ),
    pytest.param(
        "from typing import ClassVar\nclass C:\n    x: ClassVar['User']\n",
        "C",
        _U,
        id="cls_classvar_string",
    ),
    pytest.param(
        "class C:\n    x = User\n    y = helper()\n",
        "C",
        {"shop.extra.helper", *_U},
        id="cls_values",
    ),
    pytest.param(
        "from dataclasses import dataclass, field\n"
        "@dataclass\nclass C:\n    x: list = field(default_factory=User)\n",
        "C",
        _U,
        id="cls_default_factory",
    ),
    pytest.param(
        "class C:\n    def m(self, a: User) -> Order: pass\n",
        "C",
        _UO,
        id="cls_method_signature",
    ),
    pytest.param(
        "class C:\n    @tracked\n    def m(self): pass\n",
        "C",
        {"shop.models.tracked"},
        id="cls_method_decorator",
    ),
    pytest.param(
        "class C:\n    @property\n    def m(self) -> 'User': pass\n",
        "C",
        _U,
        id="cls_property_string",
    ),
    pytest.param(
        "class C:\n    m = staticmethod(helper)\n",
        "C",
        {"shop.extra.helper"},
        id="cls_attr_from_function",
    ),
    pytest.param(
        "class C:\n    def __init__(self):\n        self.u: User = None\n",
        "C",
        _U,
        id="cls_attr_annotation_in_init",
    ),
    # body
    pytest.param(
        "def f():\n    User()\n    helper()\n",
        "f",
        {"shop.extra.helper", *_U},
        id="body_calls",
    ),
    pytest.param(
        "def f():\n    return User.create()\n",
        "f",
        _U,
        id="body_classmethod_call",
    ),
    pytest.param("def f():\n    return models.User\n", "f", _U, id="body_module_attr"),
    pytest.param(
        "def f():\n    return shop.models.User.create\n",
        "f",
        _U,
        id="body_package_path",
    ),
    pytest.param(
        "def f(x):\n    return isinstance(x, (User, Order))\n",
        "f",
        _UO,
        id="body_isinstance",
    ),
    pytest.param(
        "def f(x):\n    return issubclass(x, User)\n",
        "f",
        _U,
        id="body_issubclass",
    ),
    pytest.param(
        (
            "def f():\n"
            "    try:\n"
            "        pass\n"
            "    except (User, models.Order) as e:\n"
            "        pass\n"
        ),
        "f",
        _UO,
        id="body_except",
    ),
    pytest.param(
        "def f():\n    try:\n        pass\n    except* User:\n        pass\n",
        "f",
        _U,
        id="body_except_star",
    ),
    pytest.param(
        "def f():\n    raise User() from Order()\n",
        "f",
        _UO,
        id="body_raise",
    ),
    pytest.param(
        "def f():\n    with User() as u, Order():\n        pass\n",
        "f",
        _UO,
        id="body_with",
    ),
    pytest.param(
        (
            "async def f():\n"
            "    async with User():\n"
            "        async for _ in Order():\n"
            "            await helper()\n"
        ),
        "f",
        {"shop.extra.helper", *_UO},
        id="body_async",
    ),
    pytest.param(
        "def f():\n    return [User(x) for x in Order()], {k: Extra for k in ()}\n",
        "f",
        {"shop.extra.Extra", *_UO},
        id="body_comprehensions",
    ),
    pytest.param(
        "def f():\n    return (User() for _ in ())\n",
        "f",
        _U,
        id="body_generator",
    ),
    pytest.param(
        "def f():\n    return lambda a=User: Order()\n",
        "f",
        _UO,
        id="body_lambda",
    ),
    pytest.param(
        (
            "def f():\n"
            "    def g(a: User) -> Order:\n"
            "        return Extra()\n"
            "    return g\n"
        ),
        "f",
        {"shop.extra.Extra", *_UO},
        id="body_nested_function",
    ),
    pytest.param(
        "def f():\n    class L(User):\n        x: Order\n    return L\n",
        "f",
        _UO,
        id="body_nested_class",
    ),
    pytest.param(
        "def f():\n    @tracked\n    def g(): pass\n",
        "f",
        {"shop.models.tracked"},
        id="body_nested_decorator",
    ),
    pytest.param(
        "def f():\n    if (u := User()):\n        return u\n",
        "f",
        _U,
        id="body_walrus",
    ),
    pytest.param(
        "def f(x):\n    match x:\n        case User(name='a'):\n            pass\n"
        "        case models.Order():\n            pass\n",
        "f",
        _UO,
        id="body_match_class",
    ),
    pytest.param(
        "def f(x):\n    match x:\n        case Extra.value:\n            pass\n",
        "f",
        {"shop.extra.Extra"},
        id="body_match_value",
    ),
    pytest.param(
        "def f():\n    return f'{User.name} {helper()!r}'\n",
        "f",
        {"shop.extra.helper", *_U},
        id="body_fstring",
    ),
    pytest.param(
        "def f():\n    from shop.models import User as U\n    return U()\n",
        "f",
        _U,
        id="body_local_import_aliased",
    ),
    pytest.param(
        "def f():\n    from .models import Order\n    return Order()\n",
        "f",
        {"shop.models.Order"},
        id="body_local_relative_import",
    ),
    pytest.param(
        "def f():\n    import shop.extra\n    return shop.extra.Extra()\n",
        "f",
        {"shop.extra.Extra"},
        id="body_local_import_module",
    ),
    pytest.param(
        "def f():\n    import shop.extra as e\n    return e.helper()\n",
        "f",
        {"shop.extra.helper"},
        id="body_local_import_module_alias",
    ),
    pytest.param(
        "def f():\n    x: User = None\n    y: 'Order'\n",
        "f",
        _UO,
        id="body_var_annotations",
    ),
    pytest.param("def f(x):\n    return cast(User, x)\n", "f", _U, id="body_cast"),
    pytest.param(
        "def f(x):\n    return cast('User', x)\n",
        "f",
        _U,
        id="body_cast_string",
    ),
    pytest.param(
        "def f(x):\n    return typing.cast('Optional[User]', x)\n",
        "f",
        _U,
        id="body_cast_string_dotted",
    ),
    pytest.param(
        "def f():\n    return {'a': User, 'b': [Order, helper]}\n",
        "f",
        {"shop.extra.helper", *_UO},
        id="body_literals_of_definitions",
    ),
    pytest.param(
        "def f():\n    global Extra\n    return Extra()\n",
        "f",
        {"shop.extra.Extra"},
        id="body_global",
    ),
    pytest.param(
        (
            "def f():\n"
            "    Order = 1\n"
            "    def g():\n"
            "        nonlocal Order\n"
            "        return Order\n"
            "    return User\n"
        ),
        "f",
        _U,
        id="body_nonlocal_is_local",
    ),
    pytest.param(
        "def f(x):\n    return x or User\n",
        "f",
        _U,
        id="body_boolean_operand",
    ),
    pytest.param(
        "def f():\n    return [*User.all(), *Order]\n",
        "f",
        _UO,
        id="body_starred",
    ),
    pytest.param("def f():\n    del User.cache\n", "f", _U, id="body_del_attr"),
    pytest.param(
        "def f():\n    assert isinstance(1, User), Order\n",
        "f",
        _UO,
        id="body_assert",
    ),
    pytest.param("def f():\n    yield User\n", "f", _U, id="body_yield"),
    pytest.param(
        "def f():\n    return User.create().save()\n",
        "f",
        _U,
        id="body_call_chain",
    ),
    pytest.param(
        "def f():\n    return getattr(User, 'x')\n",
        "f",
        _U,
        id="body_getattr_object",
    ),
    # deliberately no dependency
    pytest.param(
        "def f(User):\n    return User()\n",
        "f",
        set(),
        id="not_parameter_shadows",
    ),
    pytest.param(
        "def f(User: User):\n    return User\n",
        "f",
        _U,
        id="parameter_annotation_is_outer",
    ),
    pytest.param(
        "def f(User=User):\n    return User\n",
        "f",
        _U,
        id="parameter_default_is_outer",
    ),
    pytest.param(
        "def f():\n    User = 1\n    return User\n",
        "f",
        set(),
        id="not_local_shadows",
    ),
    pytest.param(
        "def f():\n    return [User for User in ()]\n",
        "f",
        set(),
        id="not_comprehension_variable",
    ),
    pytest.param(
        (
            "def f():\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError as User:\n"
            "        return User\n"
        ),
        "f",
        set(),
        id="not_except_as_name",
    ),
    pytest.param(
        "def f():\n    return lambda User: User\n",
        "f",
        set(),
        id="not_lambda_parameter",
    ),
    pytest.param(
        "def f():\n    for User in ():\n        return User\n",
        "f",
        set(),
        id="not_loop_variable",
    ),
    pytest.param(
        "def f(x):\n    match x:\n        case [User]:\n            return User\n",
        "f",
        set(),
        id="not_match_capture",
    ),
    pytest.param("def f[User](a: User): pass\n", "f", set(), id="not_type_parameter"),
    pytest.param(
        (
            "def f(x: User):\n"
            "    match x:\n"
            "        case [User]:\n"
            "            return User\n"
        ),
        "f",
        _U,
        id="match_capture_leaves_signature",
    ),
    pytest.param(
        "@tracked\ndef f(x):\n    match x:\n        case tracked:\n            pass\n",
        "f",
        {"shop.models.tracked"},
        id="match_capture_leaves_decorator",
    ),
    pytest.param(
        "class C:\n    match 1:\n        case User:\n            pass\n",
        "C",
        set(),
        id="not_class_body_match_capture",
    ),
    pytest.param(
        (
            "class C:\n"
            "    match 1:\n"
            "        case User:\n"
            "            pass\n"
            "    def m(self):\n"
            "        return User\n"
        ),
        "C",
        _U,
        id="class_capture_is_no_method_local",
    ),
    pytest.param(
        "class C:\n    x: models.User\n    models: int = 0\n",
        "C",
        _U,
        id="class_attribute_named_like_import",
    ),
    pytest.param(
        "class C:\n    x: 'models.User'\n    models = 0\n",
        "C",
        _U,
        id="class_attribute_named_like_import_string",
    ),
    pytest.param(
        "G = None\ndef f():\n    global G\n    G = User()\n",
        "f",
        _U,
        id="global_assignment_still_counts_for_function",
    ),
    pytest.param(
        "def f(x):\n    return x.User\n",
        "f",
        set(),
        id="not_attribute_of_other",
    ),
    pytest.param(
        "def f():\n    '''Returns a User.'''\n    return 'Order'\n",
        "f",
        set(),
        id="not_plain_strings",
    ),
    pytest.param(
        "def f(x):\n    return getattr(x, 'User'), x['Order']\n",
        "f",
        set(),
        id="not_dynamic_strings",
    ),
    pytest.param(
        "from typing import Literal\ndef f(a: Literal['User']): pass\n",
        "f",
        set(),
        id="not_literal",
    ),
    pytest.param(
        "def f(x):\n    return cast(int, 'User')\n",
        "f",
        set(),
        id="not_cast_value",
    ),
    pytest.param(
        "def f():\n    return {'User': 1}['User']\n",
        "f",
        set(),
        id="not_subscript_key",
    ),
]


@pytest.mark.parametrize(("code", "definition", "expected"), _FORMS)
def test_dependency_forms(
    tmp_path: Path,
    code: str,
    definition: str,
    expected: set[str],
) -> None:
    index = _index(
        tmp_path,
        {"shop/extra.py": _EXTRA, "shop/service.py": _IMPORTS + code},
    )
    assert _deps(index, f"shop.service.{definition}") == expected


# --- through a module-level name --------------------------------------------
#
# A module-level variable is no definition and no node: a definition using it
# depends on whatever its value names, wherever the variable is reached from.

_ALIASES = [
    pytest.param(
        "from typing import NewType\n"
        "Order = 1\n"
        "UserId = NewType('Order', User)\n"
        "def f(a: UserId): pass\n",
        _U,
        id="newtype_name_is_no_reference",
    ),
    pytest.param("Alias = User\ndef f() -> Alias: pass\n", _U, id="alias"),
    pytest.param(
        "Alias = A2 = User\ndef f(): return A2\n",
        _U,
        id="alias_chained_targets",
    ),
    pytest.param(
        (
            "from typing import TypeAlias\n"
            "Alias: TypeAlias = User\n"
            "def f(a: Alias): pass\n"
        ),
        _U,
        id="typealias_annotation",
    ),
    pytest.param(
        (
            "from typing import TypeAlias\n"
            "Alias: TypeAlias = 'Optional[User]'\n"
            "def f(a: Alias): pass\n"
        ),
        _U,
        id="typealias_string",
    ),
    pytest.param(
        "Alias = User | Order\ndef f(a: Alias): pass\n",
        _UO,
        id="alias_union",
    ),
    pytest.param(
        "Alias = Optional['User']\ndef f(a: Alias): pass\n",
        _U,
        id="alias_string_in_generic",
    ),
    pytest.param(
        "type Alias = User | Order\ndef f(a: Alias): pass\n",
        _UO,
        id="pep695_type_alias",
    ),
    pytest.param(
        "type Alias[T] = dict[T, 'User']\ndef f(a: Alias[int]): pass\n",
        _U,
        id="pep695_generic_alias",
    ),
    pytest.param(
        "T = TypeVar('T', bound=User)\ndef f(a: T) -> T: pass\n",
        _U,
        id="typevar_bound",
    ),
    pytest.param(
        "T = TypeVar('T', bound='User')\ndef f(a: T): pass\n",
        _U,
        id="typevar_string_bound",
    ),
    pytest.param(
        "T = TypeVar('T', 'User', Order)\ndef f(a: T): pass\n",
        _UO,
        id="typevar_constraints",
    ),
    pytest.param(
        "from typing import Generic\nT = TypeVar('T', bound=User)\n"
        "class C(Generic[T]): pass\ndef f(c: C): pass\n",
        {"shop.service.C"},
        id="generic_typevar_bound",
    ),
    pytest.param(
        "HANDLERS = {'a': User, 'b': helper}\ndef f(k): return HANDLERS[k]()\n",
        {"shop.extra.helper", *_U},
        id="registry_dict",
    ),
    pytest.param(
        "HANDLERS = {}\nHANDLERS['a'] = Order\ndef f(k): return HANDLERS[k]\n",
        {"shop.models.Order"},
        id="registry_item_assignment",
    ),
    pytest.param(
        "HANDLERS = {'a': 1}\nHANDLERS |= {'b': User}\ndef f(): return HANDLERS\n",
        _U,
        id="registry_augmented_union",
    ),
    pytest.param(
        "ITEMS = [1]\nITEMS += [Order]\ndef f(): return ITEMS\n",
        {"shop.models.Order"},
        id="registry_augmented_add",
    ),
    pytest.param(
        (
            "settings = None\n"
            "def setup():\n"
            "    global settings\n"
            "    settings = User()\n"
            "def f(): return settings\n"
        ),
        _U,
        id="module_variable_assigned_through_global",
    ),
    pytest.param(
        (
            "settings = None\n"
            "def setup():\n"
            "    settings = User()\n"
            "def f(): return settings\n"
        ),
        set(),
        id="not_function_local_named_like_module_variable",
    ),
    pytest.param(
        "settings = User()\ndef f(): return settings.name\n",
        _U,
        id="module_instance",
    ),
    pytest.param(
        "settings: User\ndef f(): return settings\n",
        _U,
        id="module_annotated_only",
    ),
    pytest.param(
        "make = lambda: Order()\ndef f(): return make()\n",
        {"shop.models.Order"},
        id="module_lambda",
    ),
    pytest.param(
        "import functools\nrun = functools.partial(helper, 1)\ndef f(): return run()\n",
        {"shop.extra.helper"},
        id="module_partial",
    ),
    pytest.param(
        "m = models\ndef f(): return m.Order()\n",
        {"shop.models.Order"},
        id="module_alias_of_module",
    ),
    pytest.param(
        "A = B = None\nA = B\nB = A\ndef f(): return A\n",
        set(),
        id="alias_cycle_ends",
    ),
    pytest.param(
        (
            "try:\n"
            "    Impl = User\n"
            "except ImportError:\n"
            "    Impl = Order\n"
            "def f(): return Impl\n"
        ),
        _UO,
        id="alias_every_branch",
    ),
    pytest.param(
        "def f(): return LIMIT\nLIMIT = 3\n",
        set(),
        id="not_alias_of_nothing",
    ),
    pytest.param(
        "__all__ = ['User']\ndef f(): return __all__\n",
        set(),
        id="not_all_strings",
    ),
]


@pytest.mark.parametrize(("code", "expected"), _ALIASES)
def test_dependency_through_a_module_level_name(
    tmp_path: Path,
    code: str,
    expected: set[str],
) -> None:
    index = _index(
        tmp_path,
        {"shop/extra.py": _EXTRA, "shop/service.py": _IMPORTS + code},
    )
    assert _deps(index, "shop.service.f") == expected


def test_generic_base_bound_by_a_typevar(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/service.py": (
                "from typing import Generic, TypeVar\n"
                "from shop.models import User\n"
                "T = TypeVar('T', bound=User)\n"
                "class C(Generic[T]):\n"
                "    pass\n"
            ),
        },
    )
    assert _deps(index, "shop.service.C") == _U


def test_alias_reached_from_another_module(tmp_path: Path) -> None:
    """Imported, star-imported or re-exported by a facade: still its value."""
    index = _index(
        tmp_path,
        {
            "shop/types.py": (
                "from shop.models import User, Order\n"
                "Customer = User\n"
                "Either = User | Order\n"
            ),
            "shop/facade/__init__.py": "from shop.types import *\n",
            "shop/service.py": (
                "from shop.types import Customer\n"
                "import shop.facade\n"
                "def f(a: Customer): pass\n"
                "def g(): return shop.facade.Either\n"
            ),
        },
    )
    assert index.resolve("shop.types.Customer") == {"shop.models.User"}
    assert _deps(index, "shop.service.f") == _U
    assert _deps(index, "shop.service.g") == _UO


def test_conditional_import_in_a_facade_keeps_every_branch(tmp_path: Path) -> None:
    index = _index(
        tmp_path,
        {
            "shop/pick/__init__.py": (
                "import sys\n"
                "if sys.version_info >= (3, 11):\n"
                "    from shop.models import User as Impl\n"
                "else:\n"
                "    from shop.models import Order as Impl\n"
            ),
            "shop/service.py": "from shop.pick import Impl\ndef f(): return Impl\n",
        },
    )
    assert _deps(index, "shop.service.f") == _UO
