from shop.catalog.queries import find_products
from shop.orders.service import place_order


def checkout(product_ids: list[int]) -> int:
    """Place an order for the products found."""
    return place_order(find_products(product_ids)).id
