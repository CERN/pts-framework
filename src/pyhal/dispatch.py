"""
The transition dispatch until phase 3: `pyhal.get_device()`, `pyhal.recover_device()` and
`pyhal.device_info()` for both ways a device is reached today.

PyPTS still runs its devices in-process (the Sequencer's `LocalSetup`), and recipes and test
code import `from pyhal import get_device`. A script connected to a HAL server gets its
devices through the client (`pyhal.client`). These functions pick the one in use:

- get_device() uses the active local setup when there is one (`pyhal.local_setup.get_device`,
  today's texts): during a PyPTS run test code always gets the run's in-process devices, even
  when a client scope is active in the same process. Else it uses the client's scope when the
  client module is loaded and a client scope is active; else the local setup's function,
  which raises its `No local setup is active. ...`;
- recover_device() and device_info() go by the handle's type: a `ConnectionDriver` goes to
  `pyhal.device_control`, a `pyhal.client.Device` to the client (both are imported then, at
  call time, when one of their objects already exists).

Import-light on purpose, as `pyhal/__init__.py` is: it imports neither `socket` nor
`pyhal.client` at module level, so a driver's `from pyhal import PSU` stays cheap. A module
that has never been imported cannot have a setup or a scope active, which is why looking in
`sys.modules` is enough.

Phase 3 moves PyPTS onto the HAL server and removes the in-process branch.
"""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyhal.client import Device
    from pyhal.connection_driver import ConnectionDriver
    from pyhal.device_control import DeviceInfo


def get_device(name: str) -> "Device | ConnectionDriver":
    """
    The device called `name` - what test code calls: on the active local setup when there is
    one, else on the HAL server inside a client scope. Raises DriverError.
    """
    local = sys.modules.get("pyhal.local_setup")
    if local is not None and local._setup_is_active():
        return local.get_device(name)
    client = sys.modules.get("pyhal.client")
    if client is not None and client._scope_is_active():
        return client.get_device(name)
    from pyhal import local_setup

    return local_setup.get_device(name)


def recover_device(device: "Device | ConnectionDriver") -> None:
    """Bring a device back after a failure. Raises DriverError (see the two modules)."""
    from pyhal.connection_driver import ConnectionDriver

    if isinstance(device, ConnectionDriver):
        from pyhal import device_control

        device_control.recover_device(device)
        return
    from pyhal import client

    client.recover_device(device)


def device_info(device: "Device | ConnectionDriver") -> "DeviceInfo":
    """The device's name, device type, operations and whether it is open."""
    from pyhal.connection_driver import ConnectionDriver

    if isinstance(device, ConnectionDriver):
        from pyhal import device_control

        return device_control.device_info(device)
    from pyhal import client

    return client.device_info(device)
