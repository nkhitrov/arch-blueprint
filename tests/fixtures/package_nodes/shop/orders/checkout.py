from shop.billing.tax import rate


def summary() -> str:
    return rate()
