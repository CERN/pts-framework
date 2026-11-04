"""
ConnectionDriver - one device as test code sees it: a local object whose
methods run in the driver's own process.

**Every public name belongs to the driver.** ConnectionDriver's own members
are all `_private`, so any public name - `close`, `open`, `name`, ... - reaches
the driver's operation of that name through __getattr__, and no name is
reserved. LocalSetup, in this package, calls the private lifecycle below; test
code controls a device through device_control.py (recover_device(),
device_info()).

_open() starts the driver process (multiprocessing, spawn) with a Pipe between
the two, waits for the driver to say hello, and calls its connect(). After that
every operation of the driver is a method of this object. _close() calls
teardown() and ends the process. Every failure is a DriverError that names the
device, so it reads well on the operator's ERROR line.

teardown() is where a driver leaves its instrument safe, so it must run however
the device ends. _close() is one serialized ladder: teardown() on the live
process; failing that - the process hung, crashed or was stopped - a fresh
process connects and tears down instead (the rescue); failing that too, the
ERROR line says the device may still be energised, and that is where the
framework stops: the driver's stability is the driver's own job. _abandon()
runs the same ladder for a run that will not end, without waiting for the
device's lock, and is final: _open() and _recover() refuse an abandoned device.
_recover() is for test code that wants to retry (through recover_device()): it
escalates from the driver's own recover() to a fresh process, and only raises
when even that fresh process cannot connect.

What crosses the Pipe is pickled: arguments and return values must be
picklable. Calls are one at a time: a lock makes a second thread wait.

The bottom half of this file is what runs inside the driver process.
"""

import contextlib
import importlib
import importlib.util
import io
import logging
import multiprocessing
import pickle
import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from multiprocessing.process import BaseProcess
from multiprocessing.reduction import ForkingPickler
from pathlib import Path
from types import ModuleType
from typing import Any, TextIO, cast

from pypts.hal.base_driver import LIFECYCLE_METHODS, BaseDriver, DriverError, operations_of
from pypts.hal.device_types import DEVICE_TYPE_NAMES
from pypts.logger.log import log

# The type of one end of a Pipe differs by platform; mypy follows the check.
if sys.platform == "win32":
    from multiprocessing.connection import PipeConnection as PipeEnd
else:
    from multiprocessing.connection import Connection as PipeEnd

#: How long _open() waits for the driver process to say hello.
#: Generous: importing a vendor library can take seconds on a cold machine.
STARTUP_TIMEOUT_S = 30.0

#: The longest one call to a driver - connect() included - may take before its
#: driver process is stopped. The same for every device; bench.ini does not set it.
CALL_TIMEOUT_S = 30.0

#: How long _close() waits for the driver process to end before killing it.
EXIT_TIMEOUT_S = 5.0

#: The longest a rescue - a fresh driver process, connect(), teardown() - may take.
RESCUE_TIMEOUT_S = 10.0

#: How long _abandon() gives an idle device's teardown() before the driver
#: process is killed and the ladder moves on to the rescue. Short on purpose:
#: shutdown is waiting.
ABANDON_TEARDOWN_TIMEOUT_S = 5.0

#: How often a wait for the driver process looks whether it is still alive.
LIVENESS_POLL_S = 0.2

#: The longest a call argument or return value gets in the DEBUG trace.
TRACE_MAX_CHARS = 300

#: What a driver file (`driver = C:/bench/acme_psu.py:AcmePsuDriver`) is called
#: as a module in its driver process, before the file's stem - and so what the
#: driver's `logging.getLogger(__name__)` is named.
DRIVER_FILE_MODULE_PREFIX = "pypts_driver_file_"

# What the driver process sends back. The first item of every message is its kind.
#: ("hello", device_type, operations) - once, first: the driver is built.
HELLO = "hello"
#: ("fatal", reason) - instead of hello: the driver could not be built.
FATAL = "fatal"
#: ("log", level, logger name, message) - at any time.
LOG = "log"
#: ("printed", line) - at any time: one line the driver printed.
PRINTED = "printed"
#: ("result", value) - the answer to a call.
RESULT = "result"
#: ("error", type name, message, traceback) - the call raised.
ERROR = "error"


def _left_until(deadline: float) -> float:
    """The seconds left until a time.monotonic() deadline, never less than a tenth."""
    left = deadline - time.monotonic()
    if left < 0.1:
        return 0.1
    return left


def _shortened(value: Any) -> str:
    """repr(value), cut to TRACE_MAX_CHARS with '...' appended when it was longer."""
    text = repr(value)
    if len(text) > TRACE_MAX_CHARS:
        return text[:TRACE_MAX_CHARS] + "..."
    return text


class ConnectionDriver:
    """One device, its driver running in a process of its own."""

    def __init__(
        self,
        name: str,
        driver_path: str,
        settings: Mapping[str, str],
        *,
        call_timeout_s: float = CALL_TIMEOUT_S,
    ) -> None:
        self._name = name
        #: The driver's device type and operations, as its hello said. Empty until _open().
        self._device_type = ""
        self._operations: tuple[str, ...] = ()
        self._driver_path = driver_path
        self._driver_module = driver_module_name(driver_path)
        self._settings = dict(settings)
        self._call_timeout_s = call_timeout_s
        self._process: BaseProcess | None = None
        self._conn: PipeEnd | None = None
        self._lock = threading.Lock()
        #: Set by _abandon(), never cleared: _close(), _open() and _recover()
        #: refuse - the device stays down.
        self._abandoned = False
        #: Set once connect() has returned: before that there is nothing to tear down.
        self._connected = False

    # --- what test code calls ----------------------------------------------------

    def __getattr__(self, name: str) -> Callable[..., Any]:
        """
        An operation of the driver, as a method. Only called for names this
        class lacks - and it has no public ones, so every public name lands here.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._operations:
            known = ", ".join(self._operations) or "none"
            device_type = self._device_type or "not open"
            raise AttributeError(
                f"Device '{self._name}' ({device_type}) has no operation '{name}'. It has: {known}."
            )

        def operation(*args: Any, **kwargs: Any) -> Any:
            return self._call(name, list(args), kwargs)

        operation.__name__ = name
        return operation

    # --- what device_control.py calls for test code -------------------------------

    def _is_open(self) -> bool:
        return self._conn is not None

    def _recover(self) -> None:
        """
        Bring the device back, escalating: the driver's own recover() while its
        process is alive; when that fails or the process is gone, teardown and
        a fresh process with connect(). Only when the fresh process cannot
        connect does the DriverError reach the caller. An abandoned device is
        refused: it stays down. The hardware layer never calls this by itself -
        test code decides.
        """
        if self._abandoned:
            raise DriverError(
                f"Device '{self._name}' cannot be recovered: its run was abandoned "
                f"and the device was torn down."
            )
        log.info("Recovering device '%s'.", self._name)
        alive = self._process is not None and self._process.is_alive()
        if self._conn is not None and alive:
            log.debug("Device '%s': calling recover(%r).", self._name, self._settings)
            try:
                self._call("recover", [self._settings], {}, trace=False)
                log.info("Device '%s' recovered.", self._name)
                return
            except DriverError as exc:
                log.warning(
                    "Device '%s' did not recover and is being connected again: %s",
                    self._name,
                    exc,
                )
        self._close()
        self._open()
        log.info("Device '%s' recovered.", self._name)

    # --- what LocalSetup calls ---------------------------------------------------

    def _open(self) -> None:
        """
        Start the driver process and connect the device. Leaves nothing running
        on failure. An abandoned device is refused: its run will not end, so
        nothing would ever tear a new process down.
        """
        if self._abandoned:
            raise DriverError(
                f"Device '{self._name}' cannot be opened: its run was abandoned "
                f"and the device was torn down."
            )
        self._start(STARTUP_TIMEOUT_S, self._call_timeout_s)
        log.info("Device '%s' connected.", self._name)

    def _close(self) -> None:
        """
        The teardown ladder, in one serialized escalation. Never raises.

        teardown() on the live process; failing that - it hung, crashed or was
        already stopped - teardown on a fresh process (the rescue); failing
        that too, the rescue's ERROR line has said the device may still be
        energised, and the ladder stops there. An abandoned device is refused:
        _abandon() already ran the ladder, and the device stays down.
        """
        if self._abandoned:
            return
        if self._conn is None and self._process is None and not self._connected:
            return
        torn_down = False
        if self._conn is not None:
            try:
                self._call("teardown", [], {})
                torn_down = True
            except DriverError as exc:
                log.warning("Device '%s' did not disconnect cleanly: %s", self._name, exc)
        self._discard()
        if not torn_down and self._connected:
            torn_down = self._rescue()
        self._connected = False
        if torn_down:
            log.info("Device '%s' disconnected.", self._name)

    def _abandon(self, time_limit_s: float | None = None) -> bool:
        """
        Tear the device down for a run that will not end. Never raises.

        The same ladder as _close(), on one shared time budget, except that the
        lock is never waited for - the stuck run may hold it. An idle device
        gets one teardown() within ABANDON_TEARDOWN_TIMEOUT_S; a busy device's
        driver process is killed at once (the call then fails as a crash in
        the stuck thread). A device that is not down after that is torn down
        on a fresh process (_rescue) with whatever budget is left. Nothing
        reconnects afterwards: abandonment is final - _open() and _recover()
        refuse - and a device that could not be torn down is the caller's
        CRITICAL to report, not this layer's problem to fix.

        Returns:
            True if teardown ran, or nothing was open to tear down.
        """
        self._abandoned = True
        if time_limit_s is None:
            # The full ladder: one teardown attempt, then the rescue.
            time_limit_s = ABANDON_TEARDOWN_TIMEOUT_S + RESCUE_TIMEOUT_S
        deadline = time.monotonic() + max(time_limit_s, 0.0)
        if not self._lock.acquire(blocking=False):
            log.debug("Device '%s' is in a call; killing its driver process.", self._name)
            process = self._process
            if process is not None and process.is_alive():
                process.kill()
        else:
            try:
                if self._conn is not None:
                    try:
                        budget = min(ABANDON_TEARDOWN_TIMEOUT_S, _left_until(deadline))
                        self._exchange("teardown", [], {}, budget, trace=True)
                        return True
                    except DriverError as exc:
                        # A teardown that timed out was killed by
                        # _read_message(), one that crashed is gone, and one
                        # the driver refused did not run: in every case
                        # teardown did not happen, so the ladder goes on.
                        log.warning(
                            "Device '%s' did not disconnect cleanly: %s", self._name, exc
                        )
            finally:
                self._discard()
                self._lock.release()
        if not self._connected:
            return True
        return self._rescue(min(RESCUE_TIMEOUT_S, _left_until(deadline)))

    # --- the process ------------------------------------------------------------

    def _start(self, hello_timeout_s: float, connect_timeout_s: float) -> None:
        """Start the driver process and call connect(). Leaves nothing running on failure."""
        if self._is_open():
            raise DriverError(f"Device '{self._name}' is already open.")
        log.debug("Starting the driver process of device '%s': %s.", self._name, self._driver_path)
        # Spawn on every platform: a fork of a process with threads (CORE) is unsafe.
        context = multiprocessing.get_context("spawn")
        parent_end, child_end = context.Pipe()
        process = context.Process(
            target=driver_process_main,
            args=(child_end, self._driver_path, logging.getLogger().getEffectiveLevel()),
            name=f"Device {self._name}",
            # A daemon is ended when PyPTS exits, so it can never outlive it.
            daemon=True,
        )
        try:
            process.start()
        except Exception as exc:
            parent_end.close()
            child_end.close()
            raise DriverError(
                f"Device '{self._name}': its driver process could not be started: {exc}"
            ) from exc
        # Only the driver process holds this end now: when it ends, recv() here sees EOF.
        child_end.close()
        self._process = process
        self._conn = parent_end
        try:
            self._receive_hello(hello_timeout_s)
            log.debug("Device '%s': calling connect(%r).", self._name, self._settings)
            self._call("connect", [self._settings], {}, trace=False, timeout_s=connect_timeout_s)
        except BaseException:
            self._kill()
            raise
        self._connected = True

    def _rescue(self, time_limit_s: float | None = None) -> bool:
        """
        Tear the device down on a fresh connection, its own process being gone.

        The kill freed the instrument, so a new driver process can connect and
        run teardown(), which is where a driver leaves its instrument safe.
        The last rung of the ladder: a rescue that fails is an ERROR, and
        nothing tries again. Never raises.

        Returns:
            True if teardown ran.
        """
        log.warning("Device '%s' is being connected again, to tear it down.", self._name)
        if time_limit_s is None:
            time_limit_s = RESCUE_TIMEOUT_S
        deadline = time.monotonic() + time_limit_s
        rescuer = ConnectionDriver(
            self._name, self._driver_path, self._settings, call_timeout_s=time_limit_s
        )
        try:
            rescuer._start(_left_until(deadline), _left_until(deadline))
            rescuer._call("teardown", [], {}, timeout_s=_left_until(deadline))
        except DriverError as exc:
            log.error(
                "Device '%s' could not be torn down and may still be energised: %s",
                self._name,
                exc,
            )
            return False
        finally:
            rescuer._discard()
        log.info("Device '%s' was torn down on a fresh connection.", self._name)
        return True

    def _receive_hello(self, timeout_s: float) -> None:
        message = self._read_message(timeout_s, "at start-up")
        kind = message[0]
        if kind == FATAL:
            raise DriverError(f"Device '{self._name}' could not be opened: {message[1]}")
        if kind != HELLO:
            raise DriverError(
                f"Device '{self._name}' could not be opened: it began with {kind!r}, not hello."
            )
        self._device_type = str(message[1])
        self._operations = tuple(message[2])
        log.debug(
            "Device '%s' is a %s with operations %s.",
            self._name,
            self._device_type,
            self._operations,
        )

    def _discard(self) -> None:
        """Close the Pipe - the driver process then exits - and wait for the process."""
        if self._conn is not None:
            with contextlib.suppress(OSError):
                self._conn.close()
            self._conn = None
        if self._process is not None:
            self._process.join(EXIT_TIMEOUT_S)
            if self._process.is_alive():
                log.debug("The driver process of device '%s' did not exit; killing it.", self._name)
                self._process.kill()
                self._process.join()
            self._process = None

    def _kill(self) -> None:
        if self._process is not None and self._process.is_alive():
            self._process.kill()
        self._discard()

    def _exit_code(self) -> str:
        if self._process is None:
            return "unknown"
        self._process.join(1.0)
        if self._process.exitcode is None:
            return "unknown"
        return str(self._process.exitcode)

    def _stopped_unexpectedly(self) -> DriverError:
        code = self._exit_code()
        self._discard()
        return DriverError(f"Device '{self._name}' stopped unexpectedly (exit code {code}).")

    # --- one call -----------------------------------------------------------------

    def _call(
        self,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
        trace: bool = True,
        timeout_s: float | None = None,
    ) -> Any:
        if timeout_s is None:
            timeout_s = self._call_timeout_s
        with self._lock:
            return self._exchange(method, args, kwargs, timeout_s, trace)

    def _exchange(
        self,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
        timeout_s: float,
        trace: bool,
    ) -> Any:
        """One call and its answer. The caller holds the lock."""
        if self._conn is None:
            raise DriverError(f"Device '{self._name}' is not open.")
        # Pickled whole before anything is written, so a refusal leaves the Pipe clean.
        # Any exception: pickle refuses with PicklingError, TypeError, ValueError, ...
        try:
            data = ForkingPickler.dumps((method, args, kwargs))
        except Exception as exc:
            raise DriverError(
                f"Device '{self._name}': the arguments of '{method}' cannot be sent: {exc}"
            ) from exc
        try:
            self._conn.send_bytes(data)
        except OSError:
            raise self._stopped_unexpectedly() from None
        if trace:
            log.debug(
                "Device '%s': calling %s(*%s, **%s).",
                self._name,
                method,
                _shortened(args),
                _shortened(kwargs),
            )
        reply = self._read_message(timeout_s, f"'{method}'")

        if reply[0] == RESULT:
            value = reply[1]
            if trace:
                log.debug("Device '%s': %s returned %s.", self._name, method, _shortened(value))
            return value
        type_name = reply[1]
        message = reply[2]
        trace_text = reply[3]
        if trace_text:
            log.debug("Traceback in device '%s' for '%s':\n%s", self._name, method, trace_text)
        raise DriverError(f"Device '{self._name}': '{method}' failed: {type_name}: {message}")

    def _read_message(self, timeout_s: float, waiting_for: str) -> tuple[Any, ...]:
        """The next message that is not a log record or a printed line, logging those."""
        if self._conn is None:
            raise DriverError(f"Device '{self._name}' is not open.")
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = max(deadline - time.monotonic(), 0.0)
            try:
                # Waits in short slices: a process that died before it took over
                # its end of the Pipe closes nothing this side can see (Windows).
                ready = self._conn.poll(min(remaining, LIVENESS_POLL_S))
                if not ready:
                    if self._process is None or not self._process.is_alive():
                        raise self._stopped_unexpectedly()
                    if time.monotonic() < deadline:
                        continue
                    self._kill()
                    # The stuck process could not tear down. Nothing rescues
                    # here: the device is torn down on a fresh process when it
                    # is closed - _close() and _abandon() own that ladder.
                    raise DriverError(
                        f"Device '{self._name}' did not answer {waiting_for} within "
                        f"{timeout_s:.1f} s; its driver process was stopped."
                    )
                data = self._conn.recv_bytes()
            except (EOFError, OSError):
                raise self._stopped_unexpectedly() from None
            # The message was read whole, so the Pipe stays usable when it cannot be unpickled.
            try:
                message = pickle.loads(data)
            except Exception as exc:
                raise DriverError(
                    f"Device '{self._name}': the answer {waiting_for} could not be read: {exc}"
                ) from exc
            kind = message[0]
            if kind == LOG:
                self._relog(message)
                continue
            if kind == PRINTED:
                log.debug("Device '%s' printed: %s", self._name, message[1])
                continue
            return message

    def _relog(self, message: tuple[Any, ...]) -> None:
        """
        One forwarded record, into the run log. The driver's own records keep
        their level; another library's (paramiko's INFO chatter) is DEBUG unless
        it is a WARNING or worse - the technician's panel shows INFO.
        """
        level = message[1]
        logger_name = message[2]
        text = message[3]
        own = bool(self._driver_module) and (
            logger_name == self._driver_module
            or logger_name.startswith(self._driver_module + ".")
        )
        if level < logging.WARNING and not own:
            level = logging.DEBUG
        log.log(level, "Device '%s': %s", self._name, text)


# --- inside the driver process ------------------------------------------------------
#
# Everything below runs in the driver's own process, started by
# ConnectionDriver._open(). Nothing here is called in PyPTS's own process except
# by the tests.


class _Channel:
    """The driver process's end of the Pipe. send() is locked: a driver thread may log."""

    def __init__(self, conn: PipeEnd) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    def send(self, message: tuple[Any, ...]) -> None:
        with self._lock:
            self._conn.send(message)

    def receive_bytes(self) -> bytes:
        return self._conn.recv_bytes()


class _ForwardingHandler(logging.Handler):
    """Sends every log record of the driver process to PyPTS, for the run log."""

    def __init__(self, channel: _Channel) -> None:
        super().__init__()
        self._channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        # A log record must never take the driver down, and nothing is left to report to.
        with contextlib.suppress(Exception):
            self._channel.send((LOG, record.levelno, record.name, record.getMessage()))


class _PrintForwarder(io.TextIOBase):
    """Stands in for sys.stdout and sys.stderr: every printed line goes to PyPTS's run log."""

    def __init__(self, channel: _Channel) -> None:
        super().__init__()
        self._channel = channel
        self._pending = ""
        self._lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        with self._lock:
            self._pending += text
            lines = self._pending.split("\n")
            self._pending = lines.pop()
        for line in lines:
            self._send(line)
        return len(text)

    def flush(self) -> None:
        with self._lock:
            line = self._pending
            self._pending = ""
        self._send(line)

    def _send(self, line: str) -> None:
        text = line.rstrip()
        if not text:
            return
        with contextlib.suppress(Exception):
            self._channel.send((PRINTED, text))


def split_driver_file(driver_path: str) -> tuple[str, str] | None:
    """
    (file, class name) when `driver_path` names a driver file and its class -
    `C:/bench/acme_psu.py:AcmePsuDriver` - or None for a dotted import path.

    Split at the last colon, so a Windows drive letter stays in the file part.
    """
    file_name, separator, class_name = driver_path.rpartition(":")
    if separator and file_name.endswith(".py"):
        return file_name, class_name
    return None


def driver_module_name(driver_path: str) -> str:
    """The module the driver class lives in: what its own logger is named after."""
    driver_file = split_driver_file(driver_path)
    if driver_file is None:
        return driver_path.rpartition(".")[0]
    return DRIVER_FILE_MODULE_PREFIX + Path(driver_file[0]).stem


def load_driver_file(file_name: str) -> ModuleType:
    """
    A driver file, loaded as a module of its own. Only the file: its folder is
    not put on sys.path, so a driver file imports what is installed, nothing
    that merely sits beside it.

    Registered in sys.modules, unlike a recipe's module: a driver process holds
    this one driver and nothing else, and code that looks its own module up
    there (dataclasses, pickle) then works as it does for an imported driver.
    """
    path = Path(file_name)
    if not path.is_file():
        raise ValueError(f"Driver file '{path}' does not exist.")
    module_name = DRIVER_FILE_MODULE_PREFIX + path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Driver file '{path}' cannot be loaded as a Python module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[module_name]
        raise
    return module


def load_driver_class(driver_path: str) -> type[BaseDriver]:
    """
    The class `driver_path` names, checked to be a driver of a known device type.

    Two spellings: a dotted import path (`bench_drivers.acme_psu.AcmePsuDriver`),
    or a driver file and its class (`C:/bench/acme_psu.py:AcmePsuDriver`). A
    relative file is relative to the current directory here; LocalSetup makes
    it relative to the INI file that declares it before it gets this far.
    """
    driver_file = split_driver_file(driver_path)
    if driver_file is not None:
        module_name, class_name = driver_file
        module = load_driver_file(module_name)
    else:
        if driver_path.endswith(".py"):
            raise ValueError(
                f"'{driver_path}' names a file but no class; "
                f"write it as '{driver_path}:ClassName'."
            )
        module_name, _, class_name = driver_path.rpartition(".")
        if not module_name:
            raise ValueError(f"'{driver_path}' is not a dotted path to a class.")
        module = importlib.import_module(module_name)
    found = getattr(module, class_name, None)
    if found is None:
        raise ValueError(f"Module '{module_name}' has no class '{class_name}'.")
    if not isinstance(found, type) or not issubclass(found, BaseDriver):
        raise ValueError(f"'{driver_path}' is not a driver: it does not derive from BaseDriver.")
    if found.DEVICE_TYPE not in DEVICE_TYPE_NAMES:
        raise ValueError(
            f"'{driver_path}' belongs to no device type; derive it from one of "
            f"{', '.join(DEVICE_TYPE_NAMES)}."
        )
    return found


def answer(
    driver: Any, operations: list[str], request: tuple[str, list[Any], dict[str, Any]]
) -> tuple[Any, ...]:
    """Run one call against the driver and build the reply. Never raises."""
    method_name, args, kwargs = request
    if method_name not in operations and method_name not in LIFECYCLE_METHODS:
        return (ERROR, "AttributeError", f"No operation '{method_name}'.", "")
    try:
        value = getattr(driver, method_name)(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - every failure goes back to the caller
        return (ERROR, type(exc).__name__, str(exc), traceback.format_exc())
    return (RESULT, value)


def driver_process_main(conn: PipeEnd, driver_path: str, log_level: int) -> None:
    """
    The driver process: build the driver, say hello, answer calls until the Pipe closes.

    PyPTS's end closes after _close(), or because PyPTS died. Either way the
    driver's teardown() has run by then, exactly once: _close() sends it as a
    call, and the net in the finally covers every other end of the Pipe - a
    teardown run twice sends its "output off" commands twice.
    """
    channel = _Channel(conn)
    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(_ForwardingHandler(channel))
    forwarder = _PrintForwarder(channel)
    sys.stdout = cast(TextIO, forwarder)
    sys.stderr = cast(TextIO, forwarder)

    try:
        driver_class = load_driver_class(driver_path)
        driver = driver_class()
    except Exception as exc:  # noqa: BLE001 - reported to ConnectionDriver, which raises it
        channel.send((FATAL, f"{type(exc).__name__}: {exc}"))
        conn.close()
        return

    operations = operations_of(driver_class)
    channel.send((HELLO, driver_class.DEVICE_TYPE, operations))
    # True while a teardown call is the driver's last lifecycle call: the
    # finally below must not run teardown() a second time.
    torn_down = False
    try:
        while True:
            try:
                data = channel.receive_bytes()
            except (EOFError, OSError):
                return
            try:
                request = pickle.loads(data)
            except Exception as exc:  # noqa: BLE001 - the caller learns why, the driver lives on
                reply: tuple[Any, ...] = (
                    ERROR,
                    type(exc).__name__,
                    f"the call could not be read in the driver process: {exc}",
                    "",
                )
                method_name = "the call"
            else:
                reply = answer(driver, operations, request)
                method_name = f"'{request[0]}'"
                if reply[0] == RESULT:
                    if request[0] == "teardown":
                        torn_down = True
                    elif request[0] in ("connect", "recover"):
                        torn_down = False
            try:
                channel.send(reply)
            except OSError:
                return
            except Exception as exc:  # noqa: BLE001 - pickle refuses with many types
                refusal = (
                    ERROR,
                    "TypeError",
                    f"{method_name} returned a value that cannot be sent: {exc}",
                    "",
                )
                try:
                    channel.send(refusal)
                except OSError:
                    return
    finally:
        if not torn_down:
            with contextlib.suppress(Exception):
                driver.teardown()
        conn.close()
