from __future__ import annotations

from shop.models import Order


class Payment:
    def __init__(self, order: Order) -> None:
        self.order = order
