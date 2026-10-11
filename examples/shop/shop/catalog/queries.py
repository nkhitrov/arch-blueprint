from shop.catalog.models import Product
from shop.shared.money import Money


def find_products(ids: list[int]) -> list[Product]:
    """Look the products up."""
    return [Product(f"product {i}", Money(100 * i)) for i in ids]
