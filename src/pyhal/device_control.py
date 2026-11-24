"""
The value `device_info()` returns: a device as it stands.

What test code may do to a device beyond calling its operations is a function, not a
method, so that no name is taken away from drivers (every public name on a device goes to
the driver): `pyhal.recover_device(device)` and `pyhal.device_info(device)`, both in
`pyhal.client`.
"""

from dataclasses import dataclass


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
