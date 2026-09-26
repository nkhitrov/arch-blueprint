from shop.catalog.constants import CURRENCY
from shop.catalog.models import Product


def total(products: list[Product]) -> str:
    return f"{len(products)} {CURRENCY}"
