from shop.shared.money import Money


class Product:
    """Something to buy."""

    def __init__(self, name: str, price: Money) -> None:
        self.name = name
        self.price = price
