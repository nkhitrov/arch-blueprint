from services import run


def handle() -> str:
    """Import the package facade, not the module behind it."""
    return run()
