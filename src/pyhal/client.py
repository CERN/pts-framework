"""
The HAL client: what test code and scripts use to reach the HAL server (spec §6.1, §6.3, §7.5).

One client per process, the process's client: connect() makes it, starting a HAL when none
answers (connect_only() never starts one). It holds the **long connection** test code uses and
a beat thread (`HAL beat`) that sends `beat` every CLIENT_BEAT_S, so the HAL does not take an
idle client for a frozen one (D53).

**Connect or start** (§6.2): connect() tries the port. A `hello` → the client compares the
version and the bench (path and SHA-256) and warns on a difference. An `error` instead (a HAL
shutting down) → it retries every CONNECT_RETRY_S until nothing listens, for at most
HAL_SHUTDOWN_WAIT_S. Nothing listens → it starts `python -m pyhal` detached, with a one-time
start nonce, and retries until HAL_START_TIMEOUT_S; `started_hal` is whether the `hello` that
answered echoes that nonce, which also settles two starters at once (the second HAL cannot
bind and exits; both connect to the first). The HAL's stdout and stderr go to STARTUP_FILE in
the log folder; a start that times out quotes the tail of what it wrote there. start_hal() is
the same start without a client (the HAL monitor's Start button): it waits for a `hello` with
its own nonce, closes that connection without a parting request and returns the HAL's pid.

**The close** (§6.4, HalClient.close(); also `with` and the `atexit` connect() registers):
end the scope and raise the scope counter, close the long connection, then send one request
on a short connection - `shutdown` if this client started the HAL, else `close_all` - and
half-close it without reading the answer. All on the calling thread. A connect that replaces
an unclosed client whose close sent `shutdown` first waits for that HAL to exit.

Two locks on the long connection (§7.5). The **request lock** is held by whoever sends a
request until its answer arrives (D18: one request outstanding, threads take turns); the
thread that sent a request reads its answer itself, since the HAL sends nothing unprompted.
The **write lock** is held for one line only: by a request's send, and by the beat thread,
which never takes the request lock, so beats go on during a long call. Lock order: request
lock, then the module lock (the fence), then the write lock; nothing takes them the other way.
There is no client-side deadline on an answer (D57): a wait ends with the answer or with the
connection closing. A send or a wait ended by anything else (KeyboardInterrupt) closes the
connection: its answer, unread, would be taken by the next request.

**The scope and the fence** (§6.3). run_scope() fills the process's one active-scope slot and
raises the scope counter on entry and again on exit; get_device() works only inside a scope.
A device handle (`Device`) remembers the counter it was made under, and every request it
makes compares that with the counter in the same step as the send, under the request lock:
a handle of a scope that has ended is refused here, never by the HAL. The scope's exit takes
only the module lock to end the scope, then sends `close` for each device the scope asked
for, newest first; those closes take the request lock like any request, so a request that
passed the fence is answered before them, and one that did not pass it never reaches the HAL.

Not fenced (gap): the slot is one per process. A thread test code started in one run that
calls get_device() again during the next run gets a valid handle of the next run.
"""

import atexit
import contextlib
import hashlib
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO

from pyhal.base_driver import DriverError
from pyhal.device_control import DeviceInfo
from pyhal.hal_log import RECORD_START, TRACE, default_log_dir
from pyhal.protocol import codec, messages

log = logging.getLogger(__name__)

#: The port every client and the HAL use unless told otherwise (D56). Below 32768, so it is
#: outside the ranges Linux (32768-60999) and Windows (49152-65535) hand out as temporary
#: ports and Windows reserves in blocks for Hyper-V/WSL; above 1024, so no admin rights.
DEFAULT_PORT = 29555

#: How often the beat thread sends `beat` on the long connection (D53).
CLIENT_BEAT_S = 1.0

#: The longest wait for the long connection's `hello` (and, with connect(), for a HAL to start).
HAL_START_TIMEOUT_S = 15.0

#: A short connection's connect, and its `hello`; also each connect while connect() retries.
SHORT_CONNECT_TIMEOUT_S = 1.0

#: How long connect() waits for a HAL that is shutting down to free the port: above a few
#: close ladders (about 50 s each, spec §7.6).
HAL_SHUTDOWN_WAIT_S = 120.0

#: How often connect() tries the port again, while a HAL starts or shuts down.
CONNECT_RETRY_S = 0.2

#: The file in the log folder that takes a started HAL's stdout and stderr, appended to.
STARTUP_FILE = "hal_startup.log"

#: How many of the startup file's last lines the error of a failed start quotes.
STARTUP_TAIL_LINES = 20

#: `python -m pyhal`'s exit code when the port is taken: a starter that lost the race.
EXIT_PORT_IN_USE = 3

#: How long a hang-up waits for a line being written before it closes the socket anyway.
HANG_UP_WAIT_S = 1.0

#: How often the log tail thread reads the HAL log's new bytes.
LOG_TAIL_POLL_S = 0.2

#: How long close() waits for the log tail thread to end.
LOG_TAIL_STOP_WAIT_S = 2.0

#: The longest a TRACE line quotes of one line on the wire.
TRACE_MAX_CHARS = 300

NOT_CONNECTED = "Not connected to a HAL server."

NO_SCOPE = (
    "No HAL scope is active. get_device() works in test code PyPTS is running, or inside "
    "'with pyhal.connect(...)' in a script of your own."
)

#: A request on a long connection that has been closed, by either side, or one cut off by
#: the client's own close().
CONNECTION_CLOSED = "The connection to the HAL server is closed."

NESTED_SCOPE = (
    "A HAL scope is already active; run_scope() does not nest. "
    "Connect with scope=False to manage scopes yourself."
)


class HalClient:
    """
    The process's connection to the HAL server: the long connection and its beat thread.
    Made by connect() or connect_only(); not meant to be built directly.
    """

    def __init__(
        self,
        sock: socket.socket,
        stream: BinaryIO,
        hello: messages.Hello,
        port: int,
        *,
        started_hal: bool = False,
    ) -> None:
        #: What the HAL said when this client connected.
        self.hello = hello
        #: Whether this client started the HAL it is connected to (D38).
        self.started_hal = started_hal
        #: The port of the HAL, on 127.0.0.1.
        self.port = port
        #: The long connection. Set to None, under the write lock, when it is closed.
        self._sock: socket.socket | None = sock
        #: Read only by the holder of the request lock.
        self._stream: BinaryIO | None = stream
        self._request_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stop_beats = threading.Event()
        self._beat_thread: threading.Thread | None = None
        self._close_lock = threading.Lock()
        self._closed = False
        #: Set first thing by close(): a request it cuts off is told the client closed.
        self._closing = False
        #: Passes the HAL log's records to connect()'s log_sink; None without a sink.
        self._log_tail: LogTail | None = None
        #: Whether the close sent `shutdown`: the next connect waits for that HAL to exit.
        self._sent_shutdown = False

    # --- the public surface ---------------------------------------------------------

    def send(self, kind: str, /, **fields: Any) -> messages.HalToClient:
        """
        One request and its answer, in plain Python (D30): `send("close_all")`,
        `send("call", device="psu1", operation="output_off", args=[], kwargs={})`.

        A misspelt kind or field, or a field of the wrong type, raises ValueError before
        anything is sent. An `error` answer raises DriverError: a driver's or the HAL's text
        verbatim, a protocol error as `HAL protocol error: ...`. The connection closing
        before the answer arrives raises DriverError. `beat` has no answer: the beat thread
        sends it.
        """
        if kind == "beat":
            raise ValueError("beat has no answer; the beat thread sends it")
        message = messages.build(messages.CLIENT_KINDS, kind, **fields)
        return self._request(message, None)

    def close(self) -> None:
        """
        The close (spec §6.4), the same for `with`, an explicit call and the `atexit`:
        (1) end the scope - the counter raised, no per-device closes - and close the long
        connection; (2) on a short connection, send `shutdown` if this client started the
        HAL, else `close_all`, half-close and close without reading the answer. Nothing
        answering is a DEBUG line; something that accepts the short connection but whose
        `hello` or the send fails is a WARNING that says how to close the devices by hand.
        On the calling thread; idempotent; never raises.
        """
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        atexit.unregister(self.close)
        self._closing = True
        with _state_lock:
            is_the_process_client = _client is self
        if is_the_process_client:
            # A scope=True client's scope, or a run_scope() cut short: that run_scope()'s
            # exit then finds no devices to close.
            _end_scope()
        self._close_long_connection()
        _forget_client(self)
        self._send_parting_request()
        tail = self._log_tail
        if tail is not None:
            tail.stop()

    def __enter__(self) -> "HalClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # --- what the module functions call ---------------------------------------------

    def _call(
        self, device: "Device", operation: str, args: list[Any], kwargs: dict[str, Any]
    ) -> Any:
        """One operation of a device, through its handle (fenced)."""
        message = messages.Call(device._name, operation, args, kwargs)
        answer = self._request(message, _Fence(device._name, device._scope, record=False))
        match answer:
            case messages.Result(value=value):
                return value
            case (
                messages.Hello()
                | messages.Opened()
                | messages.Recovered()
                | messages.DeviceInfo()
                | messages.Closed()
                | messages.ClosedAll()
                | messages.Bye()
                | messages.StatusReport()
                | messages.Error()
            ):
                raise _unexpected(answer, operation)
            case _:
                messages.unhandled(answer)

    def _drain_log(self) -> None:
        """Pass the HAL log's new records to the log sink before a scope returns (§9)."""
        tail = self._log_tail
        if tail is not None:
            tail.drain()

    # --- the long connection --------------------------------------------------------

    def _request(
        self, message: messages.ClientToHal, fence: "_Fence | None"
    ) -> messages.HalToClient:
        """
        Send one request and read its answer, under the request lock. With a fence, the
        handle's scope is checked in the same step. An `error` answer raises DriverError.

        Anything else that ends the send or the wait (KeyboardInterrupt: Ctrl+C interrupts
        the recv on Linux) closes the connection before it is passed on: the answer may still
        be on its way, and with no request ids (D18) the next request would take it as its own.
        """
        what = _what(message)
        data = _encode_request(message, what)
        with self._request_lock:
            if fence is not None:
                _pass_fence(fence)
            try:
                if not self._write(data):
                    if self._stream is None:
                        raise DriverError(CONNECTION_CLOSED)
                    self._lose()
                    raise self._closed_while(what)
                if log.isEnabledFor(TRACE):
                    log.log(TRACE, "To the HAL: %s", _cut(data))
                return self._read_answer(what)
            except DriverError:
                # Already handled: the connection was lost where that was needed.
                raise
            except BaseException:
                self._lose()
                raise

    def _read_answer(self, what: str) -> messages.HalToClient:
        """
        The answer: the next line, decoded. An `error` answer raises DriverError: a driver's
        or the HAL's text verbatim, a protocol error logged and as `HAL protocol error: ...`.
        The caller holds the request lock.
        """
        stream = self._stream
        if stream is None:
            raise DriverError(CONNECTION_CLOSED)
        try:
            line = codec.read_line(stream)
            if line is None:
                self._lose()
                raise self._closed_while(what)
            answer: messages.HalToClient = codec.decode(line, messages.HAL_KINDS)
        except codec.MalformedLine as exc:
            # The rest of a bad line may still be in the stream: the connection is unusable.
            self._lose()
            log.error("HAL protocol error: %s", exc.reason)
            raise DriverError(f"HAL protocol error: {exc.reason}") from exc
        except OSError:
            self._lose()
            raise self._closed_while(what) from None
        if log.isEnabledFor(TRACE):
            log.log(TRACE, "From the HAL: %s", _cut(line))
        match answer:
            case messages.Error(origin=origin, message=text):
                if origin == "protocol":
                    # The HAL ends a connection after a protocol error.
                    self._lose()
                    log.error("HAL protocol error: %s", text)
                    raise DriverError(f"HAL protocol error: {text}")
                raise DriverError(text)
            case (
                messages.Hello()
                | messages.Opened()
                | messages.Result()
                | messages.Recovered()
                | messages.DeviceInfo()
                | messages.Closed()
                | messages.ClosedAll()
                | messages.Bye()
                | messages.StatusReport()
            ):
                return answer
            case _:
                messages.unhandled(answer)

    def _write(self, data: bytes) -> bool:
        """Write one line under the write lock; False when the connection is closed or fails."""
        with self._write_lock:
            sock = self._sock
            if sock is None:
                return False
            try:
                sock.sendall(data)
            except OSError as exc:
                log.debug("A write to the HAL server failed: %s", exc)
                return False
        return True

    def _start_beats(self) -> None:
        thread = threading.Thread(target=self._beat_loop, name="HAL beat", daemon=True)
        self._beat_thread = thread
        thread.start()

    def _beat_loop(self) -> None:
        beat = codec.encode(messages.Beat())
        while not self._stop_beats.wait(CLIENT_BEAT_S):
            if not self._write(beat):
                return

    def _hang_up(self) -> None:
        """
        Close the socket, under the write lock so never in the middle of a line. A thread
        blocked reading on it is woken: shutdown() wakes it on Linux, closing the handle
        does on Windows (the server's _hang_up() has the details). A write that has not
        finished within HANG_UP_WAIT_S is a stalled one: the socket is closed under it.
        """
        locked = self._write_lock.acquire(timeout=HANG_UP_WAIT_S)
        try:
            sock = self._sock
            # Without the lock (the timeout path) this is still safe: _write() reads the
            # attribute once, and a write that took the old socket fails on the closed handle.
            self._sock = None
            if sock is None:
                return
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                socket.close(sock.detach())
        finally:
            if locked:
                self._write_lock.release()

    def _lose(self) -> None:
        """The connection has ended. The caller holds the request lock."""
        self._stop_beats.set()
        self._hang_up()
        stream = self._stream
        self._stream = None
        if stream is not None:
            with contextlib.suppress(OSError):
                stream.close()

    def _closed_while(self, what: str) -> DriverError:
        """The error for a request whose connection ended under it."""
        if self._closing:
            return DriverError(CONNECTION_CLOSED)
        return DriverError(f"The HAL server closed the connection while {what} was running.")

    def _send_parting_request(self) -> None:
        """
        The close's step (2): one request on a short connection, not waited for. The HAL
        finishes a `close_all` it has read even after the client has gone (D47); `hello` is
        read before sending, and the half-close keeps the request from being lost to a reset.

        `shutdown` goes only to the HAL this client started: the short connection's `hello`
        must echo the start nonce the long connection's did. A HAL that took the port since
        (the one it started crashed or was stopped, another was started) gets `close_all`.
        """
        kind = "close_all"
        try:
            sock = socket.create_connection(
                ("127.0.0.1", self.port), timeout=SHORT_CONNECT_TIMEOUT_S
            )
        except OSError as exc:
            log.debug(
                "No HAL server answered on 127.0.0.1:%d for the close (%s); nothing was sent.",
                self.port,
                exc,
            )
            return
        stream = sock.makefile("rb")
        try:
            line = codec.read_line(stream)
            first: messages.HalToClient | None = None
            if line is not None:
                first = codec.decode(line, messages.HAL_KINDS)
            match first:
                case messages.Hello(nonce=nonce):
                    request: messages.ClientToHal = messages.CloseAll()
                    if self.started_hal and nonce == self.hello.nonce:
                        request = messages.Shutdown()
                    kind = messages.kind_of(request)
                    sock.sendall(codec.encode(request))
                    sock.shutdown(socket.SHUT_WR)
                    if isinstance(request, messages.Shutdown):
                        self._sent_shutdown = True
                    log.debug(
                        "Sent '%s' to the HAL server on 127.0.0.1:%d for the close.",
                        kind,
                        self.port,
                    )
                case messages.Error(message=text):
                    log.debug(
                        "The HAL server on 127.0.0.1:%d answered the close with: %s; "
                        "nothing was sent.",
                        self.port,
                        text,
                    )
                case None:
                    log.debug(
                        "What answered on 127.0.0.1:%d for the close closed without a hello; "
                        "nothing was sent.",
                        self.port,
                    )
                    self._warn_close_not_taken(kind)
                case (
                    messages.Opened()
                    | messages.Result()
                    | messages.Recovered()
                    | messages.DeviceInfo()
                    | messages.Closed()
                    | messages.ClosedAll()
                    | messages.Bye()
                    | messages.StatusReport()
                ):
                    log.debug(
                        "What answered on 127.0.0.1:%d for the close is not a HAL server; "
                        "nothing was sent.",
                        self.port,
                    )
                case _:
                    messages.unhandled(first)
        except (OSError, codec.MalformedLine) as exc:
            log.debug("The close's '%s' to 127.0.0.1:%d failed: %s", kind, self.port, exc)
            self._warn_close_not_taken(kind)
        finally:
            with contextlib.suppress(OSError):
                stream.close()
            with contextlib.suppress(OSError):
                sock.close()

    def _warn_close_not_taken(self, kind: str) -> None:
        """
        Something accepted the short connection, but its `hello` or the send failed: the
        technician is told how to close the devices by hand.
        """
        if kind == "shutdown":
            command = "python -m pyhal --stop"
        else:
            command = "python -m pyhal --close-all"
        if self.port != DEFAULT_PORT:
            command = f"{command} --port {self.port}"
        log.warning(
            "The HAL server did not take the %s; devices may still be open. "
            "Run '%s' to close them.",
            kind,
            command,
        )

    def _close_long_connection(self) -> None:
        """Stop the beats and close the long connection; a request waiting on it fails."""
        self._stop_beats.set()
        self._hang_up()
        with self._request_lock:
            self._lose()
        thread = self._beat_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()


class LogTail:
    """
    Follows the HAL's log file and passes each new record to `sink(levelno, message)` (spec
    §9): the level from the record's level name (`TRACE` = 5 included; a name logging does not
    know is INFO), the message as written after `time;level;name;`, its continuation lines
    joined by "\n".

    start() notes the file's size: only what is written after it is passed. The thread
    `HAL log tail` reads every LOG_TAIL_POLL_S. A line counts once its `\n` is written. The
    thread holds the last record back until the next record's header or a quiet poll shows it
    is whole; drain() passes it at once. The drain and the thread share one lock, so no record
    is passed twice or out of order, and each calls the sink itself. A sink that raises is
    logged once at DEBUG and the tail goes on; a file that is missing or unreadable is
    retried quietly (logged once at DEBUG until a read works again). A file missing at start()
    is tailed from its beginning once it appears. A file that becomes shorter than what was
    read is read again from its start.

    The sink runs on the tail's thread and on the thread that calls drain(). It must not call
    drain() or stop() (they take the tail's lock or wait for its thread), and it must not log
    into the HAL's own log file: that record would be read back and passed to the sink again.
    """

    def __init__(self, path: str, sink: Callable[[int, str], None]) -> None:
        self._path = path
        self._sink = sink
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        #: How far into the file has been read.
        self._offset = 0
        #: The bytes after the last newline read: a line not complete yet.
        self._partial = b""
        #: The record being read: its level and its lines; passed on at the next header.
        self._level = 0
        self._lines: list[str] = []
        self._complained_read = False
        self._complained_sink = False

    def start(self) -> None:
        """Note the file's size and start the thread."""
        try:
            self._offset = os.path.getsize(self._path)
        except OSError:
            self._offset = 0
        thread = threading.Thread(target=self._run, name="HAL log tail", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        """End the thread (waited for, at most LOG_TAIL_STOP_WAIT_S). Idempotent."""
        self._stopped.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(LOG_TAIL_STOP_WAIT_S)

    def drain(self) -> None:
        """
        Read to the end of the file and pass every complete record, the last one included,
        before returning, on the calling thread.
        """
        with self._lock:
            self._read_new()
            self._flush()

    def _run(self) -> None:
        while not self._stopped.wait(LOG_TAIL_POLL_S):
            with self._lock:
                if not self._read_new():
                    # Nothing new since the last poll: the held record is whole.
                    self._flush()

    def _read_new(self) -> bool:
        """Read the new bytes and pass the records they finish; whether there were any."""
        try:
            with open(self._path, "rb") as file:
                if os.fstat(file.fileno()).st_size < self._offset:
                    # The file is shorter than what was read: it was replaced or truncated.
                    self._offset = 0
                    self._partial = b""
                file.seek(self._offset)
                data = file.read()
        except OSError as exc:
            if not self._complained_read:
                self._complained_read = True
                log.debug("The HAL log '%s' cannot be read yet: %s", self._path, exc)
            return False
        self._complained_read = False
        if not data:
            return False
        self._offset = self._offset + len(data)
        data = self._partial + data
        end = data.rfind(b"\n")
        if end < 0:
            self._partial = data
            return True
        self._partial = data[end + 1 :]
        for raw in data[: end + 1].split(b"\n")[:-1]:
            self._take_line(raw.decode("utf-8", errors="replace").rstrip("\r"))
        return True

    def _take_line(self, line: str) -> None:
        if RECORD_START.match(line):
            self._flush()
            parts = line.split(";", 3)
            known = logging.getLevelName(parts[1])
            if isinstance(known, int):
                self._level = known
            else:
                self._level = logging.INFO
            self._lines = [parts[3] if len(parts) == 4 else ""]
        elif self._lines:
            self._lines.append(line)
        # else: a continuation line whose record began before the tail did; dropped.

    def _flush(self) -> None:
        """Pass the record being read to the sink."""
        if not self._lines:
            return
        message = "\n".join(self._lines)
        level = self._level
        self._lines = []
        try:
            self._sink(level, message)
        except Exception as exc:  # noqa: BLE001 - a sink must not kill the tail
            if not self._complained_sink:
                self._complained_sink = True
                log.debug("The HAL log sink raised: %r; the tail goes on.", exc)


class Device:
    """
    One device as test code sees it, from get_device(): every public name on it is the
    driver's operation (its own members are all `_private`, so no name is reserved), and a
    call is a request on the long connection.
    """

    def __init__(
        self,
        hal_client: HalClient,
        name: str,
        device_type: str,
        operations: tuple[str, ...],
        scope: int,
    ) -> None:
        self._client = hal_client
        self._name = name
        self._device_type = device_type
        self._operations = operations
        #: The scope counter this handle was made under: the fence.
        self._scope = scope

    def __getattr__(self, name: str) -> Callable[..., Any]:
        """
        An operation of the driver, as a method. Only called for names this class lacks,
        and it has no public ones, so every public name lands here. A name that is not an
        operation raises AttributeError without a round trip.
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
            return self._client._call(self, name, list(args), dict(kwargs))

        operation.__name__ = name
        return operation

    def __repr__(self) -> str:
        return f"<pyhal device '{self._name}' ({self._device_type})>"


class _Fence:
    """What a request checks under the request lock: its handle's scope."""

    def __init__(self, name: str, scope: int, *, record: bool) -> None:
        self.name = name
        self.scope = scope
        #: get_device()'s `open`: note the device in the scope, so its exit closes it.
        self.record = record


# --- the process's client and its scope ----------------------------------------------
#
# One per process. Not thread-local on purpose: test code may start threads of its own,
# and they belong to the same run. All of it is guarded by _state_lock.

_state_lock = threading.Lock()
_client: HalClient | None = None
#: Why the last connect failed: what get_device() reports when there is no client (D21).
_connect_problem: str | None = None
_scope_counter = 0
_scope_active = False
#: The devices the active scope asked for, in the order it first asked.
_scope_devices: list[str] = []


class _NothingListens(DriverError):
    """Nothing accepted a connection on the port."""


class _Refused(DriverError):
    """The HAL answered with an `error` instead of `hello`: it is shutting down."""


def _open_connection(
    port: int, connect_timeout_s: float = HAL_START_TIMEOUT_S
) -> tuple[socket.socket, BinaryIO, messages.HalToClient]:
    """
    Connect to 127.0.0.1:<port> within `connect_timeout_s` and read the first message within
    HAL_START_TIMEOUT_S. The first message is `hello`, or an `error` from a HAL that is
    shutting down. Raises _NothingListens (a DriverError) when nothing listens, DriverError
    when what answers is not a HAL; nothing is left open.

    A listener on loopback accepts at once, so a short connect timeout only cuts the wait
    for a port nobody listens on (Windows retries a refused connect for about 2 s).
    """
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=connect_timeout_s)
    except OSError as exc:
        log.debug("Connecting to 127.0.0.1:%d failed: %s", port, exc)
        raise _NothingListens(f"No HAL server answered on 127.0.0.1:{port}.") from None
    stream = sock.makefile("rb")
    try:
        sock.settimeout(HAL_START_TIMEOUT_S)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        line = codec.read_line(stream)
        if line is None:
            raise DriverError(f"What answered on 127.0.0.1:{port} closed without a hello.")
        first = codec.decode(line, messages.HAL_KINDS)
        # No client-side deadline after the handshake (D57).
        sock.settimeout(None)
    except (OSError, codec.MalformedLine) as exc:
        stream.close()
        sock.close()
        raise DriverError(f"What answered on 127.0.0.1:{port} is not a HAL server: {exc}") from None
    except DriverError:
        stream.close()
        sock.close()
        raise
    return sock, stream, first


def _open_client(port: int, connect_timeout_s: float = HAL_START_TIMEOUT_S) -> HalClient:
    """
    A connected HalClient with its beat thread running. Raises DriverError: _NothingListens
    when nothing listens, _Refused when the HAL is shutting down.
    """
    sock, stream, first = _open_connection(port, connect_timeout_s)
    match first:
        case messages.Hello():
            hal_client = HalClient(sock, stream, first, port)
            hal_client._start_beats()
            log.debug(
                "Connected to the HAL server on 127.0.0.1:%d: pid %d, version %s, bench '%s'.",
                port,
                first.pid,
                first.version,
                first.bench,
            )
            return hal_client
        case messages.Error(message=text):
            stream.close()
            sock.close()
            raise _Refused(text)
        case (
            messages.Opened()
            | messages.Result()
            | messages.Recovered()
            | messages.DeviceInfo()
            | messages.Closed()
            | messages.ClosedAll()
            | messages.Bye()
            | messages.StatusReport()
        ):
            stream.close()
            sock.close()
            raise DriverError(
                f"What answered on 127.0.0.1:{port} is not a HAL server: it began with "
                f"'{messages.kind_of(first)}', not 'hello'."
            )
        case _:
            messages.unhandled(first)


def connect_only(port: int = DEFAULT_PORT, *, scope: bool = True) -> HalClient:
    """
    Connect to a HAL server already running on 127.0.0.1:<port>, never start one, and make
    the client the process's client. With `scope` (a script) a scope is opened too; PyPTS
    passes scope=False, its Sequencer's run_scope() being its scope.

    Raises DriverError("No HAL server answered on 127.0.0.1:<port>.") when nothing listens;
    the reason is also what get_device() reports from then on.
    """
    _close_previous_client()
    try:
        hal_client = _open_client(port)
    except DriverError as exc:
        _note_connect_problem(str(exc))
        raise
    _install(hal_client, scope)
    return hal_client


def connect(
    bench: str | os.PathLike[str],
    port: int = DEFAULT_PORT,
    *,
    scope: bool = True,
    log_sink: Callable[[int, str], None] | None = None,
    log_level: int | None = None,
    log_dir: str | None = None,
) -> HalClient:
    """
    Connect to the HAL server on 127.0.0.1:<port>, or start one for the bench file `bench`
    (spec §6.2), and make the client the process's client. With `scope` (a script) a scope
    is opened too; PyPTS passes scope=False. The close is registered with `atexit`, so a
    script that never closes still runs it; close() unregisters it.

    Args:
        bench: the bench INI file the HAL serves; a running HAL's own bench is compared
            with it (a difference is a WARNING, and the HAL is used anyway).
        port: the HAL's port.
        log_sink: where the HAL log's records go, as (level number, message).
        log_level: the log level of a HAL this call starts (a HAL found running keeps its
            own); None: the HAL's default.
        log_dir: the log folder of a HAL this call starts, and where its startup file goes;
            None: pyhal's default folder.

    Raises:
        DriverError: no HAL could be reached or started; the reason is also what
            get_device() reports from then on.
    """
    bench_path = os.path.realpath(os.fspath(bench))
    _close_previous_client()
    try:
        hal_client = _connect_or_start(bench_path, port, log_level, log_dir)
    except DriverError as exc:
        _note_connect_problem(str(exc))
        raise
    if log_sink is not None and hal_client.hello.log:
        hal_client._log_tail = LogTail(hal_client.hello.log, log_sink)
        hal_client._log_tail.start()
    _compare_hello(hal_client.hello, bench_path, port)
    _install(hal_client, scope)
    atexit.register(hal_client.close)
    return hal_client


def _close_previous_client() -> None:
    """
    A client of this process that was never closed gets its close before a new one connects:
    after, its `shutdown` would stop the HAL the new one has just connected to. When that
    close sent `shutdown`, the new connect first waits for that HAL to exit, or it could be
    welcomed by a HAL that has not read the `shutdown` yet.
    """
    with _state_lock:
        previous = _client
    if previous is not None:
        log.debug("A new HAL client replaces one that was never closed.")
        previous.close()
        if previous._sent_shutdown:
            _wait_for_exit(previous.port, previous.hello.pid)


def _wait_for_exit(port: int, pid: int) -> None:
    """
    Wait until the HAL with this pid no longer answers on the port: nothing listens, or what
    answers is another HAL or not a HAL. At most HAL_SHUTDOWN_WAIT_S; after that the connect
    goes on, and meets that HAL as any connect would.
    """
    deadline = time.monotonic() + HAL_SHUTDOWN_WAIT_S
    while True:
        try:
            sock, stream, first = _open_connection(port, SHORT_CONNECT_TIMEOUT_S)
        except DriverError:
            # _NothingListens, or what answers is not a HAL: the one shut down has gone.
            return
        stream.close()
        sock.close()
        match first:
            case messages.Hello(pid=answering_pid):
                if answering_pid != pid:
                    return
            case messages.Error():
                pass
            case (
                messages.Opened()
                | messages.Result()
                | messages.Recovered()
                | messages.DeviceInfo()
                | messages.Closed()
                | messages.ClosedAll()
                | messages.Bye()
                | messages.StatusReport()
            ):
                return
            case _:
                messages.unhandled(first)
        if time.monotonic() >= deadline:
            log.debug(
                "The HAL server on 127.0.0.1:%d (pid %d) was sent 'shutdown' but still answers "
                "after %g s.",
                port,
                pid,
                HAL_SHUTDOWN_WAIT_S,
            )
            return
        time.sleep(CONNECT_RETRY_S)


def _note_connect_problem(problem: str) -> None:
    global _connect_problem
    with _state_lock:
        _connect_problem = problem


def _install(hal_client: HalClient, scope: bool) -> None:
    """Make `hal_client` the process's client, and open its scope with `scope`."""
    global _client, _connect_problem
    with _state_lock:
        _client = hal_client
        _connect_problem = None
    if scope:
        _begin_scope(nest_refused=False)


def _connect_or_start(
    bench_path: str, port: int, log_level: int | None, log_dir: str | None
) -> HalClient:
    """The HAL on the port, waited for while it shuts down, or started. Raises DriverError."""
    deadline = time.monotonic() + HAL_SHUTDOWN_WAIT_S
    waiting = False
    while True:
        try:
            return _open_client(port, SHORT_CONNECT_TIMEOUT_S)
        except _NothingListens:
            break
        except _Refused:
            if not waiting:
                log.debug(
                    "The HAL server on 127.0.0.1:%d is shutting down; waiting for it to exit.",
                    port,
                )
                waiting = True
            if time.monotonic() >= deadline:
                raise DriverError(
                    f"The HAL server on 127.0.0.1:{port} was still shutting down after "
                    f"{HAL_SHUTDOWN_WAIT_S:g} s."
                ) from None
            time.sleep(CONNECT_RETRY_S)
    return _start_hal(bench_path, port, log_level, log_dir)


#: The HALs this process started, kept so their Popen objects are never collected (a
#: collected Popen whose process still runs warns about it). Nothing waits for them.
_started_processes: list[subprocess.Popen[bytes]] = []


class _AnotherHal(DriverError):
    """start_hal(): a HAL that another starter started answered on the port first."""


class _Launched:
    """A HAL process _launch() started, and what waiting for it needs."""

    def __init__(
        self, process: subprocess.Popen[bytes], nonce: str, startup_path: Path, start_offset: int
    ) -> None:
        self.process = process
        #: The start nonce handed to the HAL as --nonce; its `hello` echoes it.
        self.nonce = nonce
        self.startup_path = startup_path
        #: Where this start's output begins in the startup file.
        self.start_offset = start_offset


def _start_hal(bench_path: str, port: int, log_level: int | None, log_dir: str | None) -> HalClient:
    """
    Start a HAL and connect to it. `started_hal` is whether the connection's `hello` echoes
    this start's nonce: a HAL another starter started first answers with its own (D38).
    Raises DriverError.
    """
    hal_client, nonce = _start_and_connect(bench_path, port, log_level, log_dir)
    hal_client.started_hal = hal_client.hello.nonce == nonce
    if not hal_client.started_hal:
        log.debug("Another starter's HAL server took port %d first; using it.", port)
    return hal_client


def start_hal(
    bench: str | os.PathLike[str],
    port: int = DEFAULT_PORT,
    *,
    log_level: int | None = None,
    log_dir: str | None = None,
) -> int:
    """
    Start `python -m pyhal` detached on the port for the bench file `bench`, and return as
    soon as the HAL answers `hello` with this start's nonce, within HAL_START_TIMEOUT_S. It
    makes no client: its connection is closed again, without a parting request, so nothing of
    this process stays connected to the HAL.

    Args:
        bench: the bench INI file the HAL serves.
        port: the HAL's port.
        log_level: the HAL's log level; None: the HAL's default.
        log_dir: the HAL's log folder, and where its startup file goes; None: pyhal's default.

    Returns:
        The pid the HAL's `hello` names, its own. (On Windows, in a venv, the process Popen
        starts is the venv's launcher, whose pid is another.)

    Raises:
        DriverError: the HAL could not be started (with the tail of what it wrote to its
            startup file), or what answers on the port is not a HAL. `_AnotherHal`, a
            DriverError, when a HAL another starter started answered first: the one started
            here cannot bind the port and exits.
    """
    bench_path = os.path.realpath(os.fspath(bench))
    hal_client, nonce = _start_and_connect(bench_path, port, log_level, log_dir)
    hello = hal_client.hello
    hal_client._close_long_connection()
    if hello.nonce != nonce:
        raise _AnotherHal(
            f"Another HAL server (pid {hello.pid}) answered on port {port} first; "
            "the one started here exits."
        )
    return hello.pid


def _start_and_connect(
    bench_path: str, port: int, log_level: int | None, log_dir: str | None
) -> tuple[HalClient, str]:
    """
    Start a HAL (_launch()) and connect to the port within HAL_START_TIMEOUT_S; the connected
    HalClient (not installed as the process's client, `started_hal` not set) and this start's
    nonce. The HAL that answers may be another starter's. Raises DriverError.
    """
    launched = _launch(bench_path, port, log_level, log_dir)
    deadline = time.monotonic() + HAL_START_TIMEOUT_S
    while True:
        try:
            return _open_client(port, SHORT_CONNECT_TIMEOUT_S), launched.nonce
        except (_NothingListens, _Refused):
            pass
        # A HAL that has exited will not answer - unless it lost the port to another
        # starter's, which is the one to wait for.
        exit_code = launched.process.poll()
        exited_for_good = exit_code is not None and exit_code != EXIT_PORT_IN_USE
        if exited_for_good or time.monotonic() >= deadline:
            tail = _startup_tail(launched.startup_path, launched.start_offset)
            raise DriverError(f"The HAL server could not be started: {tail}")
        time.sleep(CONNECT_RETRY_S)


def _launch(bench_path: str, port: int, log_level: int | None, log_dir: str | None) -> _Launched:
    """Start `python -m pyhal` detached on the port, with a new start nonce. Raises DriverError."""
    nonce = secrets.token_hex(16)
    if log_dir is None:
        folder = default_log_dir()
    else:
        folder = Path(log_dir).resolve()
    # -P: the starter's working directory is not put on the HAL's sys.path; the entries that
    # matter come through PYTHONPATH, absolute.
    command = [
        sys.executable,
        "-P",
        "-m",
        "pyhal",
        "--bench",
        bench_path,
        "--port",
        str(port),
        "--nonce",
        nonce,
    ]
    if log_level is not None:
        command.extend(["--log-level", str(log_level)])
    if log_dir is not None:
        command.extend(["--log-dir", str(folder)])
    # The driver classes resolve in the HAL as they do here: on this process's sys.path.
    # Every path the HAL gets is absolute, so its working directory - the log folder, which
    # keeps it from holding the starter's folder open - changes nothing.
    entries = [os.path.abspath(entry) for entry in sys.path if entry and os.path.exists(entry)]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    startup_path = folder / STARTUP_FILE
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with open(startup_path, "ab") as startup:
            start_offset = startup.tell()
            if sys.platform == "win32":
                # Not DETACHED_PROCESS: the driver processes would open console windows.
                flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=startup,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    cwd=folder,
                    close_fds=True,
                    creationflags=flags,
                )
            else:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=startup,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    cwd=folder,
                    close_fds=True,
                    start_new_session=True,
                )
    except OSError as exc:
        raise DriverError(f"The HAL server could not be started: {exc}") from None
    _started_processes.append(process)
    log.debug(
        "Started a HAL server on 127.0.0.1:%d (pid %d), bench '%s'; its output goes to '%s'.",
        port,
        process.pid,
        bench_path,
        startup_path,
    )
    return _Launched(process, nonce, startup_path, start_offset)


def _startup_tail(path: Path, offset: int) -> str:
    """The last STARTUP_TAIL_LINES lines this start wrote to the startup file."""
    try:
        with open(path, "rb") as startup:
            startup.seek(offset)
            text = startup.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"its startup file '{path}' could not be read: {exc}"
    lines = text.splitlines()[-STARTUP_TAIL_LINES:]
    if not lines:
        return f"it wrote nothing to '{path}'."
    return "\n".join(lines)


def _compare_hello(hello: messages.Hello, bench_path: str, port: int) -> None:
    """Warn when the HAL is not what this client expects (spec §6.2 step 2)."""
    own_version = messages.hal_version()
    if hello.version != own_version:
        log.warning(
            "The HAL server on port %d is version %s, this client %s; using it anyway.",
            port,
            hello.version,
            own_version,
        )
    ours = os.path.normcase(os.path.realpath(bench_path))
    theirs = os.path.normcase(os.path.realpath(hello.bench))
    if ours != theirs:
        log.warning(
            "The HAL server on port %d serves the bench '%s', not '%s'; using it anyway.",
            port,
            hello.bench,
            bench_path,
        )
    elif _file_sha256(bench_path) != hello.bench_sha256:
        log.warning(
            "The bench '%s' has changed since the HAL server on port %d read it; using it anyway.",
            bench_path,
            port,
        )
    if hello.open:
        names = ", ".join(hello.open)
        if hello.clients == 0:
            log.warning(
                "The HAL server on port %d has devices open that no client is using: %s.",
                port,
                names,
            )
        else:
            log.debug(
                "The HAL server on port %d has devices open, %d other client(s) connected: %s.",
                port,
                hello.clients,
                names,
            )


def _file_sha256(path: str) -> str:
    """The SHA-256 hex digest of the file's bytes; empty when it cannot be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _forget_client(hal_client: HalClient) -> None:
    global _client
    with _state_lock:
        if _client is hal_client:
            _client = None


def _begin_scope(*, nest_refused: bool) -> None:
    """
    Open the scope. With `nest_refused` (run_scope()) an active scope raises DriverError and
    nothing changes; without it (a reconnect) the new scope replaces the old one.
    """
    global _scope_counter, _scope_active, _scope_devices
    with _state_lock:
        if _scope_active:
            if nest_refused:
                raise DriverError(NESTED_SCOPE)
            log.debug("A new HAL scope replaces one that never ended.")
        _scope_counter = _scope_counter + 1
        _scope_active = True
        _scope_devices = []


def _end_scope() -> list[str]:
    """End the active scope; the devices it asked for, newest first. Only the module lock."""
    global _scope_counter, _scope_active, _scope_devices
    with _state_lock:
        _scope_counter = _scope_counter + 1
        _scope_active = False
        names = list(_scope_devices)
        _scope_devices = []
    names.reverse()
    return names


def _scope_is_active() -> bool:
    with _state_lock:
        return _scope_active


def _pass_fence(fence: _Fence) -> None:
    """Refuse a request of a scope that has ended. The caller holds the request lock."""
    with _state_lock:
        current = _scope_counter
        if fence.record and fence.scope == current and fence.name not in _scope_devices:
            _scope_devices.append(fence.name)
    if fence.scope != current:
        raise DriverError(
            f"Device '{fence.name}' belongs to a run that has ended; "
            f"call get_device('{fence.name}') again."
        )


@contextlib.contextmanager
def run_scope() -> Iterator[None]:
    """
    A run's devices (D42): get_device() works inside it, and on exit each device it asked
    for is closed, newest first, each close waiting for its answer. The exit never raises;
    a close that fails is logged as a WARNING. It does not nest: inside an active scope (a
    script's connect() scope, or another run_scope()) it raises DriverError and changes nothing.
    """
    _begin_scope(nest_refused=True)
    try:
        yield
    finally:
        _close_scope_devices(_end_scope())


def _close_scope_devices(names: list[str]) -> None:
    with _state_lock:
        hal_client = _client
    for name in names:
        try:
            if hal_client is None:
                raise DriverError(NOT_CONNECTED)
            answer = hal_client._request(messages.Close(name), None)
            match answer:
                case messages.Closed():
                    pass
                case (
                    messages.Hello()
                    | messages.Opened()
                    | messages.Result()
                    | messages.Recovered()
                    | messages.DeviceInfo()
                    | messages.ClosedAll()
                    | messages.Bye()
                    | messages.StatusReport()
                    | messages.Error()
                ):
                    raise _unexpected(answer, "close")
                case _:
                    messages.unhandled(answer)
        except Exception as exc:  # noqa: BLE001 - one device must not keep the others open
            log.warning("Device '%s' did not close: %s", name, exc)
    if hal_client is not None:
        try:
            hal_client._drain_log()
        except Exception as exc:  # noqa: BLE001 - the scope's exit never raises
            log.warning("The HAL log could not be read to its end: %s", exc)


def get_device(name: str) -> Device:
    """
    The device called `name`, opened on the HAL (or reused) - what test code calls. Raises
    DriverError outside a scope, without a client, or when the HAL cannot open the device.
    """
    with _state_lock:
        active = _scope_active
        counter = _scope_counter
        hal_client = _client
        problem = _connect_problem
    if not active:
        raise DriverError(NO_SCOPE)
    if hal_client is None:
        if problem is None:
            problem = NOT_CONNECTED
        raise DriverError(problem)
    message = messages.Open(name)
    answer = hal_client._request(message, _Fence(name, counter, record=True))
    match answer:
        case messages.Opened(device_type=device_type, operations=operations):
            return Device(hal_client, name, device_type, tuple(operations), counter)
        case (
            messages.Hello()
            | messages.Result()
            | messages.Recovered()
            | messages.DeviceInfo()
            | messages.Closed()
            | messages.ClosedAll()
            | messages.Bye()
            | messages.StatusReport()
            | messages.Error()
        ):
            raise _unexpected(answer, "open")
        case _:
            messages.unhandled(answer)


def recover_device(device: Device) -> None:
    """
    Bring a device back after a failure (the HAL escalates: the driver's own recover(), then
    a fresh process). Raises DriverError only when even the fresh process cannot connect.
    """
    answer = device._client._request(
        messages.Recover(device._name), _Fence(device._name, device._scope, record=False)
    )
    match answer:
        case messages.Recovered():
            pass
        case (
            messages.Hello()
            | messages.Opened()
            | messages.Result()
            | messages.DeviceInfo()
            | messages.Closed()
            | messages.ClosedAll()
            | messages.Bye()
            | messages.StatusReport()
            | messages.Error()
        ):
            raise _unexpected(answer, "recover")
        case _:
            messages.unhandled(answer)


def device_info(device: Device) -> DeviceInfo:
    """The device's name, device type, operations and whether it is open: a round trip."""
    answer = device._client._request(
        messages.Info(device._name), _Fence(device._name, device._scope, record=False)
    )
    match answer:
        case messages.DeviceInfo(device_type=device_type, operations=operations, is_open=is_open):
            return DeviceInfo(
                name=device._name,
                device_type=device_type,
                operations=tuple(operations),
                is_open=is_open,
            )
        case (
            messages.Hello()
            | messages.Opened()
            | messages.Result()
            | messages.Recovered()
            | messages.Closed()
            | messages.ClosedAll()
            | messages.Bye()
            | messages.StatusReport()
            | messages.Error()
        ):
            raise _unexpected(answer, "info")
        case _:
            messages.unhandled(answer)


def close_device(device: Device) -> None:
    """Close one device on the HAL (D55). Its next request opens it again (D44)."""
    answer = device._client._request(
        messages.Close(device._name), _Fence(device._name, device._scope, record=False)
    )
    match answer:
        case messages.Closed():
            pass
        case (
            messages.Hello()
            | messages.Opened()
            | messages.Result()
            | messages.Recovered()
            | messages.DeviceInfo()
            | messages.ClosedAll()
            | messages.Bye()
            | messages.StatusReport()
            | messages.Error()
        ):
            raise _unexpected(answer, "close")
        case _:
            messages.unhandled(answer)


# --- helpers ---------------------------------------------------------------------------


def _what(message: messages.ClientToHal) -> str:
    """What the errors call a request: `'op' on device 'x'` for a call, else its kind."""
    if isinstance(message, messages.Call):
        return f"'{message.operation}' on device '{message.device}'"
    return messages.kind_of(message)


def _encode_request(message: messages.ClientToHal, what: str) -> bytes:
    """The request's line; a value the codec refuses raises DriverError before anything is sent."""
    try:
        return codec.encode(message)
    except (ValueError, codec.MessageTooLarge) as exc:
        if isinstance(message, messages.Call):
            raise DriverError(
                f"Device '{message.device}': the arguments of '{message.operation}' "
                f"cannot be sent: {exc}"
            ) from exc
        raise DriverError(f"The '{what}' request cannot be sent: {exc}") from exc


def _unexpected(answer: messages.HalToClient, what: str) -> DriverError:
    text = f"HAL protocol error: the answer to '{what}' was '{messages.kind_of(answer)}'."
    log.error("%s", text)
    return DriverError(text)


def _cut(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace").rstrip("\n")
    if len(text) > TRACE_MAX_CHARS:
        return text[:TRACE_MAX_CHARS] + "..."
    return text
