from deep.api.v1.schemas import dump
from deep.core.services import load


def handle() -> str:
    return dump(load())
