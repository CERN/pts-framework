"""
What test code may do to a device beyond calling its operations.

A device (`get_device("psu1")`) offers only its driver's operations: every
public name on it goes to the driver, so a driver may call an operation
`close`, `open` or `name` and test code reaches it. Controlling the device
itself therefore lives here, as functions, rather than as methods that would
take those names away from drivers:

    from pypts.hal import device_info, get_device, recover_device

    psu = get_device("psu1")
    recover_device(psu)                  # bring it back after a failure
    device_info(psu).operations          # what it can do
"""

from dataclasses import dataclass

from pypts.hal.connection_driver import ConnectionDriver


@dataclass(frozen=True)
class DeviceInfo:
    """A device as it stands: what device_info() returns."""

    #: The logical name - the bench.ini section.
    name: str
    #: The driver's device type ("PSU", "DMM", ...), empty until the device is open.
    device_type: str
    #: The operations test code can call, empty until the device is open.
    operations: tuple[str, ...]
    #: Whether its driver process is running and connected.
    is_open: bool


def recover_device(device: ConnectionDriver) -> None:
    """
    Bring a device back after a failure, escalating: the driver's own
    recover() while its process is alive; when that fails or the process is
    gone, teardown and a fresh process with connect(). Raises DriverError only
    when even the fresh process cannot connect, or when the device's run was
    abandoned. Nothing recovers on its own: test code decides.
    """
    device._recover()


def device_info(device: ConnectionDriver) -> DeviceInfo:
    """The device's name, device type, operations and whether it is open."""
    return DeviceInfo(
        name=device._name,
        device_type=device._device_type,
        operations=device._operations,
        is_open=device._is_open(),
    )
