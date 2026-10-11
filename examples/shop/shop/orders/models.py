from shop.catalog.models import Product
from shop.shared.money import Money


class Order:
    """Products bought together."""

    def __init__(self, products: list[Product]) -> None:
        self.id = 1
        self.products = products
        self.total = Money(sum(product.price.cents for product in products))
