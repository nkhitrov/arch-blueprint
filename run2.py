import libcst as cst


class DecoratorCollector(cst.CSTVisitor):
    def __init__(self):
        super().__init__()
        self.objects: dict[str, list[str]] = {}

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        decorators = []
        for dec in node.decorators:
            decorators.append(self._as_source_code(dec.decorator))

        if not decorators:
            return True

        annotations = []

        all_params = list(node.params.params) + \
                     list(node.params.posonly_params) + \
                     list(node.params.kwonly_params)

        if node.params.star_arg and isinstance(node.params.star_arg, cst.Param):
            all_params.append(node.params.star_arg)
        if node.params.star_kwarg:
            all_params.append(node.params.star_kwarg)

        for param in all_params:
            if param.annotation:
                # Извлекаем текст аннотации
                ann_text = self._as_source_code(param.annotation.annotation)
                annotations.append(ann_text)

        for d_name in decorators:
            if d_name not in self.objects:
                self.objects[d_name] = []
            self.objects[d_name].extend(annotations)

        return True

    def _as_source_code(self, node: cst.CSTNode) -> str:
        # Используем пустой модуль как контекст для генерации кода
        return cst.Module([]).code_for_node(node).strip()


# Тестовый сценарий
source_code = """
@app.route("/home")
@login_required
def home_page(request: Request, ID: int):
    pass
    
@login_required(path="123")
def home_page2(request: Request, ID: dict):
    pass
"""

module = cst.parse_module(source_code)
visitor = DecoratorCollector()
module.visit(visitor)

print(f"Found deps: {visitor.objects}")


# Ожидаемый вывод:
# Found deps: {
#   'app.route("/home")': ['Request', 'int'],
#   'login_required': ['Request', 'int'],
#   'check(foo=1)': ['dict']
# }
