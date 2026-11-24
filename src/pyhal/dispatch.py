"""
The top-level `pyhal.get_device()`, `pyhal.recover_device()` and `pyhal.device_info()`.

Recipes and test code import `from pyhal import get_device`; the devices are the HAL
server's, reached through the client (`pyhal.client`). These three functions forward to
the client's own, imported at call time.

Import-light on purpose, as `pyhal/__init__.py` is: it imports neither `socket` nor
`pyhal.client` at module level, so a driver's `from pyhal import PSU` stays cheap.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyhal.client import Device
    from pyhal.device_control import DeviceInfo


def get_device(name: str) -> "Device":
    """
    The device called `name` on the HAL server - what test code calls. Raises DriverError
    outside a scope (`pyhal.client.run_scope()`, which PyPTS enters for every run).
    """
    from pyhal import client

    return client.get_device(name)


def recover_device(device: "Device") -> None:
    """Bring a device back after a failure. Raises DriverError (see `pyhal.client`)."""
    from pyhal import client

    client.recover_device(device)


def device_info(device: "Device") -> "DeviceInfo":
    """The device's name, device type, operations and whether it is open."""
    from pyhal import client

    return client.device_info(device)
