"""
ConnectionDriver - one device as test code sees it: a local object whose
methods run in the driver's own process.

open() starts the driver process (multiprocessing, spawn) with a Pipe between
the two, waits for the driver to say hello, and calls its connect(). After that
every operation of the driver is a method of this object. close() calls
teardown() and ends the process. Every failure is a DriverError that names the
device, so it reads well on the operator's ERROR line.

What crosses the Pipe is pickled: arguments and return values must be
picklable. Calls are one at a time: a lock makes a second thread wait.

The bottom half of this file is what runs inside the driver process.
"""

import contextlib
import importlib
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
from typing import Any, TextIO, cast

from pypts.hal.base_driver import LIFECYCLE_METHODS, BaseDriver, DriverError, operations_of
from pypts.hal.families import FAMILY_NAMES
from pypts.logger.log import log
from pypts.utilities.common import masked

# The type of one end of a Pipe differs by platform; mypy follows the check.
if sys.platform == "win32":
    from multiprocessing.connection import PipeConnection as PipeEnd
else:
    from multiprocessing.connection import Connection as PipeEnd

#: How long open() waits for the driver process to say hello.
#: Generous: importing a vendor library can take seconds on a cold machine.
STARTUP_TIMEOUT_S = 30.0

#: How long close() waits for the driver process to end before killing it.
EXIT_TIMEOUT_S = 5.0

#: How often a wait for the driver process looks whether it is still alive.
LIVENESS_POLL_S = 0.2

#: Names ConnectionDriver itself uses. A driver operation with one of these
#: names cannot be reached - do not give a driver method these names.
RESERVED_NAMES = ("name", "family", "operations", "open", "close", "recover", "is_open")

#: The longest a call argument or return value gets in the DEBUG trace.
TRACE_MAX_CHARS = 300

# What the driver process sends back. The first item of every message is its kind.
#: ("hello", family, operations) - once, first: the driver is built.
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
        call_timeout_s: float = 60.0,
    ) -> None:
        self.name = name
        #: The driver's family and operations, as its hello said. Empty until open().
        self.family = ""
        self.operations: tuple[str, ...] = ()
        self._driver_path = driver_path
        self._driver_module = driver_path.rpartition(".")[0]
        self._settings = dict(settings)
        self._call_timeout_s = call_timeout_s
        self._process: BaseProcess | None = None
        self._conn: PipeEnd | None = None
        self._lock = threading.Lock()

    # --- what test code calls ----------------------------------------------------

    def __getattr__(self, name: str) -> Callable[..., Any]:
        """An operation of the driver, as a method. Only called for names this class lacks."""
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self.operations:
            known = ", ".join(self.operations) or "none"
            family = self.family or "not open"
            raise AttributeError(
                f"Device '{self.name}' ({family}) has no operation '{name}'. It has: {known}."
            )

        def operation(*args: Any, **kwargs: Any) -> Any:
            return self._call(name, list(args), kwargs)

        operation.__name__ = name
        return operation

    def is_open(self) -> bool:
        return self._conn is not None

    def recover(self) -> None:
        """
        Bring the device back: the driver's own recover() while its process is
        alive, a fresh process and connect() when it is not. The hardware layer
        never calls this by itself - test code decides.
        """
        log.info("Recovering device '%s'.", self.name)
        alive = self._process is not None and self._process.is_alive()
        if self._conn is not None and alive:
            log.debug("Device '%s': calling recover(%r).", self.name, masked(self._settings))
            self._call("recover", [self._settings], {}, trace=False)
        else:
            self._discard()
            self.open()
        log.info("Device '%s' recovered.", self.name)

    # --- what LocalSetup calls ---------------------------------------------------

    def open(self) -> None:
        """Start the driver process and connect the device. Leaves nothing running on failure."""
        if self.is_open():
            raise DriverError(f"Device '{self.name}' is already open.")
        log.debug("Starting the driver process of device '%s': %s.", self.name, self._driver_path)
        # Spawn on every platform: a fork of a process with threads (CORE) is unsafe.
        context = multiprocessing.get_context("spawn")
        parent_end, child_end = context.Pipe()
        process = context.Process(
            target=driver_process_main,
            args=(child_end, self._driver_path, logging.getLogger().getEffectiveLevel()),
            name=f"Device {self.name}",
            # A daemon is ended when PyPTS exits, so it can never outlive it.
            daemon=True,
        )
        try:
            process.start()
        except Exception as exc:
            parent_end.close()
            child_end.close()
            raise DriverError(
                f"Device '{self.name}': its driver process could not be started: {exc}"
            ) from exc
        # Only the driver process holds this end now: when it ends, recv() here sees EOF.
        child_end.close()
        self._process = process
        self._conn = parent_end
        try:
            self._receive_hello()
            log.debug("Device '%s': calling connect(%r).", self.name, masked(self._settings))
            self._call("connect", [self._settings], {}, trace=False)
        except BaseException:
            self._kill()
            raise
        log.info("Device '%s' connected.", self.name)

    def close(self) -> None:
        """teardown(), then end the process. Never raises: a failure is a WARNING."""
        if self._conn is None and self._process is None:
            return
        try:
            if self._conn is not None:
                self._call("teardown", [], {})
        except DriverError as exc:
            log.warning("Device '%s' did not disconnect cleanly: %s", self.name, exc)
        finally:
            self._discard()
        log.info("Device '%s' disconnected.", self.name)

    # --- the process ------------------------------------------------------------

    def _receive_hello(self) -> None:
        message = self._read_message(STARTUP_TIMEOUT_S, "at start-up")
        kind = message[0]
        if kind == FATAL:
            raise DriverError(f"Device '{self.name}' could not be opened: {message[1]}")
        if kind != HELLO:
            raise DriverError(
                f"Device '{self.name}' could not be opened: it began with {kind!r}, not hello."
            )
        self.family = str(message[1])
        self.operations = tuple(message[2])
        log.debug(
            "Device '%s' is a %s with operations %s.", self.name, self.family, self.operations
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
                log.debug("The driver process of device '%s' did not exit; killing it.", self.name)
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
        return DriverError(f"Device '{self.name}' stopped unexpectedly (exit code {code}).")

    # --- one call -----------------------------------------------------------------

    def _call(
        self, method: str, args: list[Any], kwargs: dict[str, Any], trace: bool = True
    ) -> Any:
        with self._lock:
            if self._conn is None:
                raise DriverError(f"Device '{self.name}' is not open.")
            # Pickled whole before anything is written, so a refusal leaves the Pipe clean.
            # Any exception: pickle refuses with PicklingError, TypeError, ValueError, ...
            try:
                data = ForkingPickler.dumps((method, args, kwargs))
            except Exception as exc:
                raise DriverError(
                    f"Device '{self.name}': the arguments of '{method}' cannot be sent: {exc}"
                ) from exc
            try:
                self._conn.send_bytes(data)
            except OSError:
                raise self._stopped_unexpectedly() from None
            if trace:
                log.debug(
                    "Device '%s': calling %s(*%s, **%s).",
                    self.name,
                    method,
                    _shortened(args),
                    _shortened(kwargs),
                )
            reply = self._read_message(self._call_timeout_s, f"'{method}'")

        if reply[0] == RESULT:
            value = reply[1]
            if trace:
                log.debug("Device '%s': %s returned %s.", self.name, method, _shortened(value))
            return value
        type_name = reply[1]
        message = reply[2]
        trace_text = reply[3]
        if trace_text:
            log.debug("Traceback in device '%s' for '%s':\n%s", self.name, method, trace_text)
        raise DriverError(f"Device '{self.name}': '{method}' failed: {type_name}: {message}")

    def _read_message(self, timeout_s: float, waiting_for: str) -> tuple[Any, ...]:
        """The next message that is not a log record or a printed line, logging those."""
        if self._conn is None:
            raise DriverError(f"Device '{self.name}' is not open.")
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
                    raise DriverError(
                        f"Device '{self.name}' did not answer {waiting_for} within "
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
                    f"Device '{self.name}': the answer {waiting_for} could not be read: {exc}"
                ) from exc
            kind = message[0]
            if kind == LOG:
                self._relog(message)
                continue
            if kind == PRINTED:
                log.debug("Device '%s' printed: %s", self.name, message[1])
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
        log.log(level, "Device '%s': %s", self.name, text)


# --- inside the driver process ------------------------------------------------------
#
# Everything below runs in the driver's own process, started by
# ConnectionDriver.open(). Nothing here is called in PyPTS's own process except
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


def load_driver_class(dotted: str) -> type[BaseDriver]:
    """The class `dotted` names, checked to be a driver of a known family."""
    module_name, _, class_name = dotted.rpartition(".")
    if not module_name:
        raise ValueError(f"'{dotted}' is not a dotted path to a class.")
    module = importlib.import_module(module_name)
    found = getattr(module, class_name, None)
    if found is None:
        raise ValueError(f"Module '{module_name}' has no class '{class_name}'.")
    if not isinstance(found, type) or not issubclass(found, BaseDriver):
        raise ValueError(f"'{dotted}' is not a driver: it does not derive from BaseDriver.")
    if found.FAMILY not in FAMILY_NAMES:
        raise ValueError(
            f"'{dotted}' belongs to no device family; derive it from one of "
            f"{', '.join(FAMILY_NAMES)}."
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

    PyPTS's end closes after close(), or because PyPTS died. Either way the
    driver's teardown() runs: the last chance to release the instrument, and
    harmless when nothing is open.
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
    channel.send((HELLO, driver_class.FAMILY, operations))
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
        with contextlib.suppress(Exception):
            driver.teardown()
        conn.close()
