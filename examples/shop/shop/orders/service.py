from shop.catalog.models import Product
from shop.orders.models import Order
from shop.payments.gateway import charge
from shop.shared.events import publish


def place_order(products: list[Product]) -> Order:
    """Create an order, charge for it, announce it."""
    order = Order(products)
    charge(order)
    publish("order_placed", order.id)
    return order
