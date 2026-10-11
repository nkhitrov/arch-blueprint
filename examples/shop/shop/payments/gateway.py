from shop.orders.models import Order
from shop.shared.money import Money


def charge(order: Order) -> Money:
    """Charge the order total (a cycle: orders imports payments, and back)."""
    return order.total
