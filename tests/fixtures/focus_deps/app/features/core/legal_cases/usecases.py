from app.features.core.executory_processes.models import Process
from app.features.core.legal_cases.models import LegalCase


class RemoveOldCustomerUseCase:
    case: LegalCase
    process: Process
