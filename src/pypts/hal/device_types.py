"""
The device types. A driver derives from exactly one of them.

A device type names the verbs every driver of that type offers, so test code
written against "a PSU" runs against any PSU driver. The lists are short on
purpose; a driver may offer more operations than its device type declares, and test
code that uses those is tied to that driver.

Standard library only, for the same reason as base_driver.py.
"""

from abc import abstractmethod
from typing import Any

from pypts.hal.base_driver import BaseDriver


class PSU(BaseDriver):
    """A programmable power supply. Channels are numbered from 1."""

    DEVICE_TYPE = "PSU"

    @abstractmethod
    def set_voltage(self, channel: int, volts: float) -> None:
        """Set the output voltage of a channel."""

    @abstractmethod
    def set_current_limit(self, channel: int, amps: float) -> None:
        """Set the current limit of a channel."""

    @abstractmethod
    def output_on(self, channel: int) -> None:
        """Switch a channel's output on."""

    @abstractmethod
    def output_off(self, channel: int) -> None:
        """Switch a channel's output off."""

    @abstractmethod
    def measure_voltage(self, channel: int) -> float:
        """The voltage a channel is delivering, in volts."""

    @abstractmethod
    def measure_current(self, channel: int) -> float:
        """The current a channel is delivering, in amperes."""


class DMM(BaseDriver):
    """
    A digital multimeter. Configure it once, then take readings: a waveform
    (read_waveform) or a single value (measure_point), both in whatever the
    last configure_waveform_acquisition() set up.
    """

    DEVICE_TYPE = "DMM"

    @abstractmethod
    def configure_waveform_acquisition(
        self, function: str, range: float, sample_rate_hz: float, points: int
    ) -> None:
        """
        Set what is measured and how a waveform is taken. `function` is one of
        "DC_VOLTS", "AC_VOLTS", "DC_CURRENT", "AC_CURRENT", "RESISTANCE";
        `range` is in the unit of the function (V, A or ohm).
        """

    @abstractmethod
    def read_waveform(self) -> dict[str, Any]:
        """
        One acquisition as configured:
        {"x_origin": float, "x_increment": float, "samples": list[float]}.
        """

    @abstractmethod
    def measure_point(self) -> float:
        """One reading, however the meter is configured."""

    @abstractmethod
    def get_frequency(self) -> float:
        """The frequency of the signal at the input, in hertz."""


class Scope(BaseDriver):
    """
    An oscilloscope. Channels are numbered from 1. Configure a channel once,
    then take readings: a waveform (read_waveform) or a single value
    (measure_point), both in whatever configure_waveform_acquisition() set up.
    """

    DEVICE_TYPE = "Scope"

    @abstractmethod
    def configure_waveform_acquisition(
        self, channel: int, volts_per_division: float, seconds_per_division: float, points: int
    ) -> None:
        """Set a channel's vertical scale, the timebase and how many points a waveform has."""

    @abstractmethod
    def read_waveform(self, channel: int) -> dict[str, Any]:
        """
        One acquisition of a channel, as configured:
        {"x_origin": float, "x_increment": float, "samples": list[float]}.
        """

    @abstractmethod
    def measure_point(self, channel: int) -> float:
        """One reading of a channel, however it is configured, in volts."""


class SSH(BaseDriver):
    """A remote shell."""

    DEVICE_TYPE = "SSH"

    @abstractmethod
    def execute(self, command: str, timeout_s: float | None = None) -> dict[str, Any]:
        """Run one command: {"stdout": str, "stderr": str, "exit_code": int}."""

    @abstractmethod
    def put_file(self, local_path: str, remote_path: str) -> None:
        """Copy a file from this machine to the remote one."""

    @abstractmethod
    def get_file(self, remote_path: str, local_path: str) -> None:
        """Copy a file from the remote machine to this one."""


class Load(BaseDriver):
    """An electronic load."""

    DEVICE_TYPE = "Load"

    @abstractmethod
    def set_mode(self, mode: str) -> None:
        """Constant current, voltage, resistance or power: "CC", "CV", "CR" or "CP"."""

    @abstractmethod
    def set_level(self, value: float) -> None:
        """The set point, in the unit of the mode: A, V, ohm or W."""

    @abstractmethod
    def input_on(self) -> None:
        """Start sinking."""

    @abstractmethod
    def input_off(self) -> None:
        """Stop sinking."""

    @abstractmethod
    def measure_voltage(self) -> float:
        """The voltage at the input, in volts."""

    @abstractmethod
    def measure_current(self) -> float:
        """The current through the input, in amperes."""


class Other(BaseDriver):
    """Anything that is none of the above. No verbs of its own."""

    DEVICE_TYPE = "Other"


#: Every device type, in the order the documentation lists them.
DEVICE_TYPES: tuple[type[BaseDriver], ...] = (PSU, DMM, Scope, SSH, Load, Other)

#: Their names - what a driver's DEVICE_TYPE must be one of.
DEVICE_TYPE_NAMES: tuple[str, ...] = tuple(device_type.DEVICE_TYPE for device_type in DEVICE_TYPES)
