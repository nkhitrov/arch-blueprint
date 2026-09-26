"""A facade: importing it runs this, and this imports the engine."""

from services.engine import run

__all__ = ["run"]
