from shop.billing.invoice import total
from shop.catalog.models import Product


def checkout(products: list[Product]) -> str:
    return total(products)
