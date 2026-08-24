from __future__ import annotations

from shop.billing import Payment


class Customer:
    name: str


class Order:
    customer: Customer

    def pay(self, payment: Payment) -> None:
        self.payment = payment
