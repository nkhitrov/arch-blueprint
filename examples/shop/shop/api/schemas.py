from shop.orders.models import Order


class OrderOut:
    """What the API returns for an order."""

    def __init__(self, order: Order) -> None:
        self.id = order.id
