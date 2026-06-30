from arch_blueprint.objects.parsers import BlueprintObjectParser
from arch_blueprint.objects.renderers import (
    PlantUmlUseCaseRenderer,
)

if __name__ == "__main__":
    try:

        # TODO подгружать остальные модули, от которых зависит таргет
        # привести к единому интерфейсу cli через модули а не подпуть
        # подсвечивать транзитивные связи, т.к. в идеале их быть не должно по аналогии с циклами
        # packages = BlueprintObjectParser(
        #     "<path>", "features/",
        #     parent_classes=(
        #             "BaseUseCase", "BaseService",
        #            "ResponseHandler", "EventHandler",
        #             "BaseEventHandler",
        #            # "BaseRepo", "BaseGateway"
        #     )
        # ).run()
        packages = BlueprintObjectParser(
            ".", "./examples",
            parent_classes=(
                "UseCase", "DomainEvent", "EventHandler",
            )
        ).run()
        text = PlantUmlUseCaseRenderer().render(packages)
        print(text)
    except KeyboardInterrupt:
        exit(1)
