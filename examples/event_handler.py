from typing import Generic, TypeVar


class DomainEvent: ...
T = TypeVar("T", bound=DomainEvent)
class EventHandler(Generic[T]): ...
class UseCase(Generic[T]): ...


class CustomerUpdatedEvent(DomainEvent):
    customer_id: int


class UpdateCustomerUseCase(UseCase[CustomerUpdatedEvent]): ...
class CheckCustomerUseCase(UseCase): ...


class CustomerUpdatedEventEventHandler(EventHandler[CustomerUpdatedEvent]):
    _check_customer_use_case: CheckCustomerUseCase
