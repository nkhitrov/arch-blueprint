from app.features.core.executory_processes import Tracker, run_delete_old_customer
from billing.invoices import Invoice


async def handle(context) -> Invoice:
    await run_delete_old_customer(context)
    return Tracker().bill()


class Health:
    status = "ok"
