import datetime

from app.features.core.executory_processes.models import Process
from app.features.core.legal_cases import LegalCase
from app.features.core.legal_cases.usecases import RemoveOldCustomerUseCase
from billing.invoices import Invoice


async def run_delete_old_customer(context) -> None:
    use_case = context.state.container.resolve(RemoveOldCustomerUseCase)
    await use_case(datetime.date.today())


class Tracker:
    process: Process
    case: LegalCase

    def bill(self) -> Invoice:
        return Invoice()
