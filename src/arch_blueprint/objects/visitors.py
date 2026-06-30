from dataclasses import dataclass
from typing import Set, List, TypedDict

import libcst as cst
from libcst import SimpleStatementLine, Assign
from libcst.matchers import matches

from arch_blueprint.objects.models import BlueprintObject


class ClassInfoCollector(cst.CSTVisitor):
    """Collect classes with parents from module."""

    def __init__(self):
        self.class_bases: dict[str, list[str]] = {}  # {class_name: [base_classes]}

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        base_classes = []
        if node.bases:
            for base in node.bases:
                base_name = self._extract_base_name(base)
                if base_name:
                    base_classes.append(base_name)

        self.class_bases[node.name.value] = base_classes

    # TODO use module path to class instead of class name
    def _extract_base_name(self, base: cst.Arg) -> str:
        value = base.value
        if isinstance(value, cst.Name):
            return value.value
        elif isinstance(value, cst.Attribute):
            return value.attr.value
        return ""


class BlueprintClassCollector(cst.CSTVisitor):
    def __init__(self, classes: Set[str], module: str, methods: set[str] | None = None, decorators: set[str] | None = None):
        """
        :param classes: Module paths to classes that can be dependencies for classes in target module. Example: `myapp.mymodule.MyClass`
        :param methods: Methods that should be parsing to collect class dependencies from typing annotations
        """
        super().__init__()
        self.module = module
        self.function_names = (methods or set()) | {"__init__"}
        self.class_names = classes
        self.decorator_names = decorators or set()

        self.current_class = None
        self.current_dependencies = []

        self.objects: List[BlueprintObject] = []


    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        if node.name.value in self.class_names:
            self.current_class = node.name.value
            self.current_dependencies = []

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        """
        Collect dependencies from class annotations (field1: MyField1)
        """
        if self.current_class:
            if isinstance(node.target, cst.Name):
                annotation = self._get_annotation_string(node.annotation)
                self.current_dependencies.append(annotation)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """
        Collect dependencies from method's arguments like `__init__`
        """
        if self.current_class and node.name.value in self.function_names:
            for param in node.params.params:
                if param.annotation:
                    dep_name = self._extract_type_name(param.annotation)
                    if dep_name and dep_name not in self.current_dependencies:
                        self.current_dependencies.append(dep_name)

            return

        if not node.decorators:
            return

        deps = set()
        all_params = list(node.params.params) + \
                     list(node.params.posonly_params) + \
                     list(node.params.kwonly_params)

        if node.params.star_arg and isinstance(node.params.star_arg, cst.Param):
            all_params.append(node.params.star_arg)
        if node.params.star_kwarg:
            all_params.append(node.params.star_kwarg)

        for param in all_params:
            if param.annotation:
                ann_text = param.annotation.annotation
                deps.add(ann_text)

        deps = [BlueprintObject(name=dep) for dep in deps if dep in self.class_names]

        for dec in node.decorators:
            # Если это вызов декоратора @login_required(path="123")
            expr = dec.decorator
            if isinstance(expr, cst.Call):
                expr = expr.func

            # Сборка полного имени (обработка Name и Attribute)
            name = self.get_full_name(expr)

            if name not in self.decorator_names:
                continue

            title = self._as_source_code(dec)
            usecase = BlueprintObject(
                name=name, title=title, dependencies=deps
            )
            self.objects.append(usecase)

    def get_full_name(self, node: cst.CSTNode) -> str:
        """Рекурсивно собирает имя для Name и Attribute (например, a.b.c)"""
        if isinstance(node, cst.Name):
            return node.value
        elif isinstance(node, cst.Attribute):
            return f"{self.get_full_name(node.value)}.{node.attr.value}"
        return ""

    def _as_source_code(self, node: cst.CSTNode) -> str:
        # Используем пустой модуль как контекст для генерации кода
        return cst.Module([]).code_for_node(node).strip()


    def leave_ClassDef(self, node: cst.ClassDef) -> None:
        if self.current_class:
            filtered_deps = [
                BlueprintObject(name=dep)
                for dep in self.current_dependencies
                if dep in self.class_names
            ]

            usecase = BlueprintObject(
                name=self.current_class, dependencies=filtered_deps
            )
            self.objects.append(usecase)
            self.current_class = None

    def _extract_type_name(self, annotation: cst.Annotation) -> str:
        node = annotation.annotation
        if isinstance(node, cst.Name):
            return node.value
        elif isinstance(node, cst.Subscript) and isinstance(node.value, cst.Name):
            return node.value.value
        elif isinstance(node, cst.Attribute):
            return node.attr.value
        return ""

    def _get_annotation_string(self, annotation: cst.Annotation) -> str:
        if isinstance(annotation.annotation, cst.Name):
            return annotation.annotation.value

        if isinstance(annotation.annotation, cst.Subscript):
            # TODO handle containers
            return "list"  # self._get_subscript_string(annotation.annotation)

        if isinstance(annotation.annotation, cst.Attribute):
            return self._get_attribute_string(annotation.annotation)

        return cst.Module([]).code_for_node(annotation.annotation)

    def _get_subscript_string(self, node: cst.Subscript) -> str:
        # Handle generic types like List[int], Dict[str, int], etc.
        base = node.value.value
        slice_str = self._get_slice_string(node.slice)
        return f"{base}[{slice_str}]"

    def _get_slice_string(self, slice_node: cst.SubscriptElement) -> str:
        if isinstance(slice_node.slice, cst.Index):
            return self._get_value_string(slice_node.slice.value)
        elif isinstance(slice_node.slice, cst.Slice):
            return "..."
        return ""

    def _get_value_string(self, value_node: cst.BaseExpression) -> str:
        if isinstance(value_node, cst.Name):
            return value_node.value
        elif isinstance(value_node, cst.Subscript):
            return self._get_subscript_string(value_node)
        elif isinstance(value_node, cst.Tuple):
            elements = [self._get_value_string(el.value) for el in value_node.elements]
            return ", ".join(elements)
        return "..."

    def _get_attribute_string(self, node: cst.Attribute) -> str:
        if isinstance(node.value, cst.Name):
            return f"{node.value.value}.{node.attr.value}"
        return node.attr.value

