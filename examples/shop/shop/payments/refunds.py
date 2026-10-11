from shop.orders.models import Order
from shop.shared.events import publish


def refund(order: Order) -> None:
    """Refund an order and announce it."""
    publish("refunded", order.id)
