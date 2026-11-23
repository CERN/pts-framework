"""
Drivers that are broken on purpose, for test_hal_connection.py.

They run in a driver process of their own, and are importable there as
`hal_test_drivers` because pytest puts this folder on sys.path (the default
`prepend` import mode) and spawn hands this process's sys.path on to the
driver process.
"""

import ctypes
import os
import threading
import time

from pyhal.base_driver import BaseDriver
from pyhal.device_types import Other


class NoDeviceTypeDriver(BaseDriver):
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


class CommonNamesDriver(Other):
    """
    Operations named like ConnectionDriver's own lifecycle once was - close,
    open, name - which test code must reach, since no name is reserved.
    """

    def connect(self, config):
        self._relay = "open"

    def teardown(self):
        pass

    def close(self):
        self._relay = "closed"
        return "relay closed"

    def open(self):
        self._relay = "open"
        return "relay open"

    def name(self):
        return "ACME relay"

    def relay(self):
        return self._relay


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


class FailingRecoverDriver(Other):
    """connect() works; recover() always raises, so a recovery must escalate."""

    def connect(self, config):
        pass

    def teardown(self):
        pass

    def recover(self, config):
        raise RuntimeError("reset line is stuck")

    def process_id(self):
        return os.getpid()

    def ping(self):
        return "pong"


class MarkingDriver(Other):
    """
    Writes each connect() and teardown() into the file its `marks` key names,
    so a teardown in a fresh driver process can be seen from the test. Its
    connect() hangs while a file named like that one plus `.hang` exists, and
    its teardown() hangs while one named plus `.tdhang` exists - or once,
    deleting the file first, when one named plus `.tdhang_once` exists.

    A `tag` key tells devices that share one marks file apart: every mark is
    followed by it (`teardown m2`), and the teardown hangs on `.tdhang.<tag>`.
    A `slow_teardown_s` key makes every teardown take that many seconds first.
    """

    def __init__(self):
        self._marks = ""
        self._tag = ""
        self._slow_teardown_s = 0.0

    def connect(self, config):
        self._marks = config["marks"]
        self._tag = config.get("tag", "")
        self._slow_teardown_s = float(config.get("slow_teardown_s", "0"))
        if os.path.exists(self._marks + ".hang"):
            time.sleep(60)
        self._mark("connect")

    def teardown(self):
        if self._marks:
            once = self._marks + ".tdhang_once"
            if os.path.exists(once):
                os.remove(once)
                time.sleep(60)
            if self._tag:
                tagged = self._marks + ".tdhang." + self._tag
                if os.path.exists(tagged):
                    time.sleep(60)
            if os.path.exists(self._marks + ".tdhang"):
                time.sleep(60)
            if self._slow_teardown_s > 0:
                time.sleep(self._slow_teardown_s)
            self._mark("teardown")

    def hang(self, seconds):
        time.sleep(seconds)

    def hang_marked(self, seconds):
        """Like hang(), then a mark `hang done`: the file shows it ended before a teardown."""
        time.sleep(seconds)
        self._mark("hang done")

    def _mark(self, word):
        with open(self._marks, "a", encoding="utf-8") as handle:
            if self._tag:
                word = word + " " + self._tag
            handle.write(word + "\n")


class CrashingMarkingDriver(MarkingDriver):
    """A MarkingDriver whose crash() ends its process on the spot."""

    def crash(self, exit_code):
        os._exit(exit_code)


class FlakyConnectDriver(Other):
    """
    connect() fails while the file its `fail_connect_file` key names exists;
    recover() always fails; crash() ends the process.
    """

    def connect(self, config):
        if os.path.exists(config["fail_connect_file"]):
            raise ConnectionError("instrument is switched off")

    def teardown(self):
        pass

    def recover(self, config):
        raise RuntimeError("reset line is stuck")

    def crash(self, exit_code):
        os._exit(exit_code)

    def ping(self):
        return "pong"


class BigResultDriver(Other):
    """Returns a string as large as asked, to pass the protocol's message limit."""

    def connect(self, config):
        pass

    def teardown(self):
        pass

    def big(self, megabytes):
        return "x" * (megabytes * 1024 * 1024)
