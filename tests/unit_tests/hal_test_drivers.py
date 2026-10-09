"""
Drivers that are broken on purpose, for test_hal_connection.py.

They run in a driver process of their own, and are importable there as
`hal_test_drivers` because pytest puts this folder on sys.path (the default
`prepend` import mode) and spawn hands this process's sys.path on to the
driver process.
"""

import ctypes
import threading

from pypts.hal.base_driver import BaseDriver
from pypts.hal.families import Other


class NoFamilyDriver(BaseDriver):
    def connect(self, config):
        pass

    def teardown(self):
        pass


class BrokenConstructorDriver(Other):
    def __init__(self):
        raise RuntimeError("constructor exploded")

    def connect(self, config):
        pass

    def teardown(self):
        pass


class FailingConnectDriver(Other):
    def connect(self, config):
        raise ConnectionError("instrument is switched off")

    def teardown(self):
        pass


class UnsendableResultDriver(Other):
    """Returns a value pickle cannot carry back."""

    def connect(self, config):
        pass

    def teardown(self):
        pass

    def lock(self):
        return threading.Lock()

    def ping(self):
        return "pong"


class TwoArgumentError(Exception):
    """Pickles, but cannot be unpickled: the classic two-argument exception."""

    def __init__(self, first, second):
        super().__init__(f"{first} and {second}")


class OddValuesDriver(Other):
    """Returns values that pickle refuses or that cannot be read back."""

    def connect(self, config):
        pass

    def teardown(self):
        pass

    def pointer(self):
        return ctypes.pointer(ctypes.c_int(1))

    def two_argument_error(self):
        return TwoArgumentError(1, 2)

    def ping(self):
        return "pong"
