"""
The hardware layer: devices on the bench, reached by logical name.

    from pypts.hal import get_device

    def read_kernel():
        result = get_device("ssh1").execute("uname -r")
        return {"kernel": result["stdout"].strip()}

Every device runs its driver in a process of its own. How it works, the
configuration format and how to write a driver: hal.md beside this file.
"""

from pypts.hal.base_driver import BaseDriver, DriverError
from pypts.hal.connection_driver import ConnectionDriver
from pypts.hal.families import DMM, PSU, SSH, Load, Other, Scope
from pypts.hal.local_setup import LocalSetup, get_device

__all__ = [
    "DMM",
    "PSU",
    "SSH",
    "BaseDriver",
    "ConnectionDriver",
    "DriverError",
    "Load",
    "LocalSetup",
    "Other",
    "Scope",
    "get_device",
]
