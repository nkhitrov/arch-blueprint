from app.features.core.executory_processes.models import Process


def report(process: Process) -> str:
    return str(process)
