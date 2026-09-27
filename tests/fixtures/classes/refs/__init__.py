"""The package facade: what it defines is drawn, like any module's definitions.

``exported`` is named like the ``refs.exported`` package, so its node id is
``refs.__init__.exported``: ``refs.exported`` is the frame of that package's
own classes.
"""

from refs.cycles import Chicken


class Farm:
    def raise_one(self) -> Chicken:
        return Chicken()


def exported() -> Farm:
    return Farm()
