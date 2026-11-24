"""
The hardware layer: devices on the bench, reached by logical name.

    from pyhal import get_device

    def read_kernel():
        result = get_device("ssh1").execute("uname -r")
        return {"kernel": result["stdout"].strip()}

Every device runs its driver in a process of its own. How it works, the
configuration format and how to write a driver: pyhal.md beside this file.

Import-light on purpose: a driver's `from pyhal import PSU` runs in every driver
process. Only the driver contract, the device types and the dispatch functions
are imported here; every other public name is imported on first use, by the
module `__getattr__` below - the client (and with it `socket`) included.
"""

import importlib
from typing import TYPE_CHECKING, Any

from pyhal.base_driver import BaseDriver, DriverError
from pyhal.device_types import DMM, PSU, SSH, Load, Other, Scope
from pyhal.dispatch import device_info, get_device, recover_device

if TYPE_CHECKING:
    from pyhal.client import DEFAULT_PORT, HalClient, close_device, connect, run_scope
    from pyhal.connection_driver import ConnectionDriver
    from pyhal.device_control import DeviceInfo

#: The names imported on first use, and the module each comes from.
_LAZY_NAMES = {
    "DEFAULT_PORT": "pyhal.client",
    "HalClient": "pyhal.client",
    "close_device": "pyhal.client",
    "connect": "pyhal.client",
    "run_scope": "pyhal.client",
    "ConnectionDriver": "pyhal.connection_driver",
    "DeviceInfo": "pyhal.device_control",
}


def __getattr__(name: str) -> Any:
    """A lazy name, imported now and kept; any other name is not pyhal's."""
    module_name = _LAZY_NAMES.get(name)
    if module_name is None:
        raise AttributeError(f"module 'pyhal' has no attribute '{name}'")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


__all__ = [
    "DEFAULT_PORT",
    "DMM",
    "PSU",
    "SSH",
    "BaseDriver",
    "ConnectionDriver",
    "DeviceInfo",
    "DriverError",
    "HalClient",
    "Load",
    "Other",
    "Scope",
    "close_device",
    "connect",
    "device_info",
    "get_device",
    "recover_device",
    "run_scope",
]
