"""
Loopback - a device with nothing behind it.

Used by the hardware layer's own tests and by the hal demo recipe, and the
quickest way to see the layer work on a machine with no instrument:

    [hardware.loop1]
    driver = pypts.hal.drivers.loopback.LoopbackDriver
"""

import logging
import os
import time
from typing import Any

from pypts.hal.families import Other

logger = logging.getLogger(__name__)


class LoopbackDriver(Other):
    """Answers with what it was given; can also fail, stall and crash on request."""

    def __init__(self) -> None:
        self._settings: dict[str, str] = {}
        self._connected = False

    def connect(self, config: dict[str, str]) -> None:
        self._settings = dict(config)
        self._connected = True

    def teardown(self) -> None:
        self._connected = False

    def echo(self, value: Any) -> Any:
        """The value, back."""
        return value

    def settings(self) -> dict[str, str]:
        """
        The keys connect() was given, unmasked: this is a test/demo driver, and
        its return value appears in the DEBUG trace.
        """
        return dict(self._settings)

    def is_connected(self) -> bool:
        return self._connected

    def fail(self, message: str) -> None:
        """Raise, the way a driver does when its instrument refuses."""
        raise RuntimeError(message)

    def sleep(self, seconds: float) -> None:
        """Take this long to answer."""
        time.sleep(seconds)

    def log_message(self, message: str) -> None:
        """Write one INFO record from the driver's own logger."""
        logger.info("%s", message)

    def print_text(self, text: str) -> None:
        """Print, the way a careless vendor library does."""
        print(text, flush=True)

    def crash(self, exit_code: int) -> None:
        """End the driver process on the spot, as a crashing C library would."""
        os._exit(exit_code)

    def process_id(self) -> int:
        """The id of the driver process."""
        return os.getpid()
