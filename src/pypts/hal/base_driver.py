"""
The base every driver derives from, and the error the hardware layer raises.

Standard library only: this module is imported inside the driver's own process
(connection_driver.py) as well as in PyPTS.
"""

import inspect
from abc import ABC, abstractmethod
from typing import ClassVar

#: The three methods every driver has. The hardware layer calls them; they are
#: not offered to test code as operations of the device.
LIFECYCLE_METHODS = ("connect", "teardown", "recover")


class DriverError(Exception):
    """A device could not be reached, or an operation on it failed."""


class BaseDriver(ABC):
    """
    One instrument, or one remote connection, as a plain class.

    No IPC and no framework import: connection_driver.py wraps it. `connect()`
    receives the device's `[hardware.<name>]` keys as text, minus the keys the
    hardware layer reads itself (`driver`, `call_timeout_s`).

    Derive from a family in families.py, never from BaseDriver directly - a
    driver that belongs to no family is refused. Every public method becomes
    an operation test code can call; return values and arguments must be what
    pickle can carry.
    """

    #: The family this driver belongs to. Set by each family base.
    FAMILY: ClassVar[str] = ""

    @abstractmethod
    def connect(self, config: dict[str, str]) -> None:
        """Open the connection `config` describes."""

    @abstractmethod
    def teardown(self) -> None:
        """Close the connection. Must not raise when nothing is open."""

    def recover(self, config: dict[str, str]) -> None:
        """Bring a misbehaving device back: teardown, then connect again."""
        self.teardown()
        self.connect(config)


def operations_of(driver_class: type) -> list[str]:
    """
    The public methods test code may call on a device of this class, sorted.

    Read from the class rather than an instance, so a property is never
    evaluated just to find out what it is.
    """
    names = []
    for name, member in inspect.getmembers(driver_class):
        if name.startswith("_"):
            continue
        if name in LIFECYCLE_METHODS:
            continue
        if callable(member):
            names.append(name)
    return names
