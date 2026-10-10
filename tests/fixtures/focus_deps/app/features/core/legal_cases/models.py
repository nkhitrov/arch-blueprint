from app.features.core.executory_processes.models import Process
from app.shared.clock import now


class LegalCase:
    opened = now()
    process: Process
