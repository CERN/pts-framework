"""
The device families. A driver derives from exactly one of them.

A family names the verbs every driver of that family offers, so test code
written against "a PSU" runs against any PSU driver. The lists are short on
purpose; a driver may offer more operations than its family declares, and test
code that uses those is tied to that driver.

Standard library only, for the same reason as base_driver.py.
"""

from abc import abstractmethod
from typing import Any

from pypts.hal.base_driver import BaseDriver


class PSU(BaseDriver):
    """A programmable power supply. Channels are numbered from 1."""

    FAMILY = "PSU"

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
    """A digital multimeter. Each call takes one reading."""

    FAMILY = "DMM"

    @abstractmethod
    def measure_dc_voltage(self) -> float:
        """One DC voltage reading, in volts."""

    @abstractmethod
    def measure_ac_voltage(self) -> float:
        """One AC (RMS) voltage reading, in volts."""

    @abstractmethod
    def measure_dc_current(self) -> float:
        """One DC current reading, in amperes."""

    @abstractmethod
    def measure_resistance(self) -> float:
        """One resistance reading, in ohms."""


class Scope(BaseDriver):
    """An oscilloscope. Channels are numbered from 1."""

    FAMILY = "Scope"

    @abstractmethod
    def set_timebase(self, seconds_per_division: float) -> None:
        """Set the horizontal scale."""

    @abstractmethod
    def set_vertical_scale(self, channel: int, volts_per_division: float) -> None:
        """Set a channel's vertical scale."""

    @abstractmethod
    def arm_single(self) -> None:
        """Arm one single-shot acquisition."""

    @abstractmethod
    def read_waveform(self, channel: int) -> dict[str, Any]:
        """
        The last acquisition of a channel:
        {"x_origin": float, "x_increment": float, "samples": list[float]}.
        """


class SSH(BaseDriver):
    """A remote shell."""

    FAMILY = "SSH"

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

    FAMILY = "Load"

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

    FAMILY = "Other"


#: Every family, in the order the documentation lists them.
FAMILIES: tuple[type[BaseDriver], ...] = (PSU, DMM, Scope, SSH, Load, Other)

#: Their names - what a driver's FAMILY must be one of.
FAMILY_NAMES: tuple[str, ...] = tuple(family.FAMILY for family in FAMILIES)
