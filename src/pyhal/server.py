"""
The HAL server: a localhost TCP service that owns the bench's devices (spec §6.5, §7.2-§7.5).

Threads:

- `HAL accept` accepts connections. While the server is shutting down (a `shutdown` queued or
  running, or the exit requested) it answers a new connection with SHUTTING_DOWN instead of
  `hello` and closes it; the listener stays open until the very end, so no second HAL can
  bind the port while this one tears down.
- `HAL client <n>`, one per connection: sends `hello`, then reads lines. Any line resets the
  client's silence clock; `beat` does nothing else; `status` is answered at once from the
  last snapshot; every other request goes on the one queue with its connection. A malformed
  or oversized line is answered with an `Error("protocol", ...)` and ends the connection.
- `HAL requests` takes the queue first in first out and runs each request on `Devices`, which
  no other thread touches while it lives. It writes the answer to the request's connection
  only, and only while that client is still connected. It also runs the exit teardown.
- `HAL watchdog` looks every WATCHDOG_TICK_S and drops a client silent for CLIENT_SILENCE_S
  that has nothing queued or running, and a client whose answer has been on its way for
  WRITE_STALL_S (it does not read, so the write would block the request thread for ever).

Locks: `_lock` guards the queue, the client list, the status snapshot and the exit state
(`_clients_changed` is a condition on it). Each connection has a write lock, held for one
line; a write holds it and then `_lock` briefly, never the other way round. request_exit()
takes neither: it sets state and wakes the request thread through a `queue.SimpleQueue`, so
it is safe from any thread and from a signal handler.

A client that is gone (end of stream, reset, write failure, dropped): its queued `open`,
`call`, `recover` and `info` are removed, its `close`, `close_all` and `shutdown` stay and
run; a request of its that is running finishes and the answer is discarded. A line its
connection thread read just before the drop is treated the same way. The bench is left as it
is (D36).

The exit (request_exit): stop welcoming new clients; let the running request finish; answer
every queued request but a `close_all` / `shutdown` with SHUTTING_DOWN; run every queued
`close_all` and `shutdown` - all of them, not only the one that caused the exit; then the
teardown (`Devices.close_all()`, whose ladder logs the ERROR "may still be energised" line for
each device it could not tear down); wait up to EXIT_GRACE_S for clients to close their end,
then close the rest; stop the accept and watchdog threads; close the listener last. The
request thread runs all of it, from its `finally` - also when it is the thread that died.
serve_until_stopped() takes it over only if the request thread ended without running it.
"""

import contextlib
import logging
import os
import queue
import re
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyhal.base_driver import DriverError
from pyhal.bench import read_bench
from pyhal.connection_driver import CALL_TIMEOUT_S
from pyhal.devices import Devices
from pyhal.hal_log import DATE_FORMAT
from pyhal.protocol import codec, messages

log = logging.getLogger(__name__)

#: A client that sends nothing for this long, with nothing queued or running, is dropped (D53).
CLIENT_SILENCE_S = 5.0

#: How often the watchdog looks for silent clients.
WATCHDOG_TICK_S = 0.5

#: How often the accept thread looks whether the server is exiting.
ACCEPT_POLL_S = 0.5

#: How long the exit waits for clients to close their end first (spec §6.5, the port).
EXIT_GRACE_S = 1.0

#: A write to a client that has not finished in this long is a client that does not read.
WRITE_STALL_S = 30.0

#: How long a hang-up waits for a write in progress before it closes the socket under it.
HANG_UP_WAIT_S = 1.0

#: How long the accept thread waits after accept() failed before it tries again.
ACCEPT_RETRY_S = 0.1

#: How long the exit waits for each server thread to end.
THREAD_JOIN_S = 5.0

#: What a new client, or a request that can no longer run, gets while the server exits.
SHUTTING_DOWN = "The HAL server is shutting down."

#: A DriverError text the driver produced, by raising: `Device 'x': 'op' failed: ...`.
_DRIVER_RAISED = re.compile(r"^Device '[^']*': '[^']*' failed: ")

#: The requests that go on the queue; `status` and `beat` never do.
QueuedRequest = (
    messages.Open
    | messages.Call
    | messages.Recover
    | messages.Info
    | messages.Close
    | messages.CloseAll
    | messages.Shutdown
)

#: The queued requests of a gone client that are removed (the others still run).
_DROPPED_WHEN_GONE = (messages.Open, messages.Call, messages.Recover, messages.Info)

#: The queued requests that still run once the exit is requested.
_KEPT_ON_EXIT = (messages.CloseAll, messages.Shutdown)


@dataclass(eq=False)
class _Connection:
    """
    One client's connection. `connected`, `last_heard` and `writing_since` are guarded by the
    server lock.
    """

    number: int
    sock: socket.socket
    last_heard: float
    connected: bool = True
    #: When the write in progress started (time.monotonic()); None when nothing is written.
    writing_since: float | None = None
    write_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(eq=False)
class _Item:
    connection: _Connection
    request: QueuedRequest


class HalServer:
    """The HAL server on one port, its devices those of one bench file."""

    def __init__(
        self,
        bench_path: Path,
        port: int,
        *,
        nonce: str | None = None,
        log_path: str = "",
        call_timeout_s: float = CALL_TIMEOUT_S,
    ) -> None:
        """
        Read the bench file; nothing listens before start().

        Args:
            bench_path: the bench INI file, read once here (D25).
            port: the port to listen on, on 127.0.0.1; 0 picks a free one (see `port`).
            nonce: the start nonce `hello` echoes, so a starter knows it started this HAL.
            log_path: the HAL's log file, as `hello` and `status` name it.
            call_timeout_s: the longest one driver call may take.
        """
        self._bench_path = Path(bench_path).resolve()
        sections, self._bench_sha256 = read_bench(self._bench_path)
        self._devices = Devices(sections, call_timeout_s=call_timeout_s)
        self._nonce = nonce
        self._log_path = log_path
        self._version = messages.hal_version()
        #: The bound port, once start() has bound it.
        self.port = port
        #: How many requests the request thread has run.
        self.requests_run = 0

        self._lock = threading.Lock()
        self._clients_changed = threading.Condition(self._lock)
        self._queue: deque[_Item] = deque()
        self._connections: list[_Connection] = []
        self._next_number = 1
        self._busy: dict[str, Any] | None = None
        self._running: _Connection | None = None
        self._open_names = self._devices.open_names()
        self._device_rows = self._devices.snapshot()

        # The exit state. Plain attributes, set without a lock by request_exit().
        self._exit_reason: str | None = None
        self._refusing = False
        self._wakeups: queue.SimpleQueue[None] = queue.SimpleQueue()
        self._exit_lock = threading.Lock()
        self._exit_claimed = False
        self._stopping = threading.Event()
        self._exited = threading.Event()

        self._listener: socket.socket | None = None
        #: Every connection thread started, so the exit can wait for them.
        self._connection_threads: list[threading.Thread] = []
        self._accept_thread: threading.Thread | None = None
        self._request_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None

    # --- the public surface ---------------------------------------------------------

    def start(self) -> None:
        """Bind and start the threads. The port taken raises OSError; nothing is left open."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.port))
            listener.listen()
            listener.settimeout(ACCEPT_POLL_S)
        except OSError:
            listener.close()
            raise
        self._listener = listener
        self.port = listener.getsockname()[1]
        log.debug(
            "The HAL server is listening on 127.0.0.1:%d, bench '%s'.",
            self.port,
            self._bench_path,
        )
        self._accept_thread = self._thread("HAL accept", self._accept_loop)
        request_thread = self._thread("HAL requests", self._request_thread_main)
        self._watchdog_thread = self._thread("HAL watchdog", self._watchdog_loop)
        self._accept_thread.start()
        request_thread.start()
        # Only once it runs: serve_until_stopped() takes a thread that is not alive for dead.
        self._request_thread = request_thread
        self._watchdog_thread.start()

    def serve_until_stopped(self) -> None:
        """
        Block until the server has exited, its teardown done. Call it after start(). A safety
        net: should the request thread end without running the exit, this thread runs it.
        """
        while not self._exited.wait(WATCHDOG_TICK_S):
            self._take_over_exit_if_request_thread_died()

    def wait_until_exited(self, timeout_s: float | None = None) -> bool:
        """
        Wait until the server has exited, its teardown done, for at most `timeout_s` (None:
        no bound). True when it has. Unlike serve_until_stopped() it never runs the exit.
        """
        return self._exited.wait(timeout_s)

    def request_exit(self, reason: str) -> None:
        """
        The one way out: tear every device down, then exit (spec §6.5). Thread-safe,
        idempotent and safe in a signal handler: it sets state and wakes the request thread,
        which runs the exit; it takes no lock and logs nothing.
        """
        if self._exit_reason is None:
            self._exit_reason = reason
        self._refusing = True
        self._wakeups.put(None)

    # --- threads --------------------------------------------------------------------

    def _thread(self, name: str, target: Callable[[], None]) -> threading.Thread:
        def run() -> None:
            try:
                target()
            except BaseException:
                # The death of any server thread is fatal: teardown, then exit (spec §6.5).
                log.exception("The HAL server thread '%s' failed.", name)
                self.request_exit("thread died")

        return threading.Thread(target=run, name=name, daemon=True)

    def _take_over_exit_if_request_thread_died(self) -> None:
        thread = self._request_thread
        if thread is None or thread.is_alive():
            return
        if self._exit_reason is None:
            self._exit_reason = "thread died"
        self._exit_sequence()

    # --- accepting ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        failing = False
        while not self._stopping.is_set():
            listener = self._listener
            assert listener is not None
            try:
                sock, address = listener.accept()
            except TimeoutError:
                continue
            except OSError as exc:
                # Transient (a connection aborted before it was taken, no handle free): one
                # client lost, not a reason to tear the bench down. The first failure of a
                # row is a WARNING; the repeats are DEBUG, until an accept succeeds again.
                if self._stopping.is_set():
                    return
                if failing:
                    log.debug("The HAL server could not accept a connection: %s", exc)
                else:
                    log.warning("The HAL server could not accept a connection: %s", exc)
                    failing = True
                self._stopping.wait(ACCEPT_RETRY_S)
                continue
            failing = False
            self._welcome(sock, address)

    def _welcome(self, sock: socket.socket, address: Any) -> None:
        if self._refusing:
            log.debug("A client connected from %s while the server is shutting down.", address)
            self._refuse(sock)
            return
        with self._lock:
            number = self._next_number
            self._next_number = number + 1
            connection = _Connection(number, sock, time.monotonic())
            others = len(self._connections)
            self._connections.append(connection)
            self._clients_changed.notify_all()
        log.debug("Client %d connected from %s; %d other client(s).", number, address, others)

        def serve() -> None:
            self._connection_main(connection, others)

        thread = self._thread(f"HAL client {number}", serve)
        with self._lock:
            self._connection_threads = [
                started for started in self._connection_threads if started.is_alive()
            ]
            self._connection_threads.append(thread)
        thread.start()

    def _refuse(self, sock: socket.socket) -> None:
        try:
            sock.sendall(codec.encode(messages.Error("hal", SHUTTING_DOWN)))
            sock.shutdown(socket.SHUT_WR)
        except OSError as exc:
            log.debug("The refusal could not be sent: %s", exc)
        sock.close()

    # --- one connection -------------------------------------------------------------

    def _connection_main(self, connection: _Connection, others: int) -> None:
        why = "it closed the connection"
        stream = connection.sock.makefile("rb")
        try:
            with self._lock:
                open_names = list(self._open_names)
            hello = messages.Hello(
                pid=os.getpid(),
                nonce=self._nonce,
                version=self._version,
                bench=str(self._bench_path),
                bench_sha256=self._bench_sha256,
                log=self._log_path,
                open=open_names,
                clients=others,
            )
            if not self._send(connection, codec.encode(hello)):
                return
            while True:
                try:
                    line = codec.read_line(stream)
                    if line is None:
                        break
                    request = codec.decode(line, messages.CLIENT_KINDS)
                except codec.MalformedLine as exc:
                    why = "it sent a line that is not a request: " + exc.reason
                    error = messages.Error("protocol", exc.reason)
                    self._send(connection, codec.encode(error))
                    break
                except OSError as exc:
                    why = "its connection failed: " + str(exc)
                    break
                self._take(connection, request)
        finally:
            self._client_gone(connection, why)
            with connection.write_lock:
                stream.close()
                connection.sock.close()

    def _take(self, connection: _Connection, request: messages.ClientToHal) -> None:
        """One request read from the connection: any line resets the client's silence clock."""
        with self._lock:
            connection.last_heard = time.monotonic()
        match request:
            case messages.Beat():
                pass
            case messages.Status():
                self._send(connection, codec.encode(self._status_report()))
            case (
                messages.Open()
                | messages.Call()
                | messages.Recover()
                | messages.Info()
                | messages.Close()
                | messages.CloseAll()
                | messages.Shutdown()
            ):
                refused = False
                discarded = False
                with self._lock:
                    if self._exit_reason is not None:
                        refused = True
                    elif not connection.connected and isinstance(request, _DROPPED_WHEN_GONE):
                        # Read just before the client was dropped: what its queue would lose.
                        discarded = True
                    else:
                        self._queue.append(_Item(connection, request))
                        if isinstance(request, messages.Shutdown):
                            self._refusing = True
                if refused:
                    self._send(connection, codec.encode(messages.Error("hal", SHUTTING_DOWN)))
                elif discarded:
                    log.debug(
                        "Client %d is gone; its '%s' read after that is dropped.",
                        connection.number,
                        _operation_of(request),
                    )
                else:
                    self._wakeups.put(None)
            case _:
                messages.unhandled(request)

    def _status_report(self) -> messages.StatusReport:
        with self._lock:
            busy = None
            if self._busy is not None:
                busy = dict(self._busy)
            devices = [dict(row) for row in self._device_rows]
            return messages.StatusReport(
                pid=os.getpid(),
                version=self._version,
                bench=str(self._bench_path),
                log=self._log_path,
                clients=len(self._connections),
                busy=busy,
                queued=len(self._queue),
                devices=devices,
            )

    def _send(self, connection: _Connection, data: bytes) -> bool:
        """Write one line to the connection; a failure makes the client gone."""
        failure = ""
        with connection.write_lock:
            with self._lock:
                connection.writing_since = time.monotonic()
            try:
                connection.sock.sendall(data)
            except OSError as exc:
                failure = str(exc)
            finally:
                with self._lock:
                    connection.writing_since = None
        if not failure:
            return True
        self._drop(connection, "a write to it failed: " + failure)
        return False

    def _client_gone(self, connection: _Connection, why: str) -> None:
        with self._lock:
            if not connection.connected:
                return
            connection.connected = False
            self._connections.remove(connection)
            kept: deque[_Item] = deque()
            dropped = 0
            for item in self._queue:
                if item.connection is connection and isinstance(item.request, _DROPPED_WHEN_GONE):
                    dropped = dropped + 1
                else:
                    kept.append(item)
            self._queue = kept
            self._clients_changed.notify_all()
        log.debug(
            "Client %d is gone: %s; %d queued request(s) of its dropped.",
            connection.number,
            why,
            dropped,
        )

    def _drop(self, connection: _Connection, why: str) -> None:
        """Make the client gone and wake its connection thread, which then closes the socket."""
        self._client_gone(connection, why)
        _hang_up(connection)

    # --- the watchdog ---------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        while not self._stopping.wait(WATCHDOG_TICK_S):
            silence_s = CLIENT_SILENCE_S
            stall_s = WRITE_STALL_S
            now = time.monotonic()
            dropped: list[tuple[_Connection, str]] = []
            with self._lock:
                waiting = {item.connection for item in self._queue}
                if self._running is not None:
                    waiting.add(self._running)
                for connection in self._connections:
                    if connection.writing_since is not None:
                        if now - connection.writing_since >= stall_s:
                            why = f"an answer to it has not been taken in {stall_s} s"
                            dropped.append((connection, why))
                        continue
                    if connection in waiting:
                        continue
                    if now - connection.last_heard >= silence_s:
                        dropped.append((connection, f"it was silent for {silence_s} s"))
            for connection, why in dropped:
                self._drop(connection, why)

    # --- the request thread ---------------------------------------------------------

    def _request_thread_main(self) -> None:
        try:
            self._request_loop()
        except BaseException:
            # The death of any server thread is fatal: teardown, then exit (spec §6.5).
            log.exception("The HAL server thread 'HAL requests' failed.")
            if self._exit_reason is None:
                self._exit_reason = "thread died"
        finally:
            self._exit_sequence()

    def _request_loop(self) -> None:
        """Run the queue until the exit is requested and only nothing is left to run."""
        while True:
            item, refused = self._next_item()
            self._refuse_requests(refused)
            if item is None:
                if self._exit_reason is not None:
                    return
                self._wakeups.get()
                continue
            self._run(item)

    def _next_item(self) -> tuple[_Item | None, list[_Item]]:
        """The next request to run, and the requests the exit refuses."""
        refused: list[_Item] = []
        with self._lock:
            if self._exit_reason is not None:
                kept: deque[_Item] = deque()
                for item in self._queue:
                    if isinstance(item.request, _KEPT_ON_EXIT):
                        kept.append(item)
                    else:
                        refused.append(item)
                self._queue = kept
            if not self._queue:
                return None, refused
            item = self._queue.popleft()
            self._running = item.connection
            self._busy = {
                "device": getattr(item.request, "device", None),
                "operation": _operation_of(item.request),
                "since": time.strftime(DATE_FORMAT),
            }
        return item, refused

    def _refuse_requests(self, items: list[_Item]) -> None:
        for item in items:
            if item.connection.connected:
                error = messages.Error("hal", SHUTTING_DOWN)
                self._send(item.connection, codec.encode(error))

    def _run(self, item: _Item) -> None:
        operation = _operation_of(item.request)
        log.debug("Client %d: running '%s'.", item.connection.number, operation)
        answer = self._handle(item.request)
        open_names = self._devices.open_names()
        device_rows = self._devices.snapshot()
        with self._lock:
            self.requests_run = self.requests_run + 1
            self._running = None
            self._busy = None
            self._open_names = open_names
            self._device_rows = device_rows
            connected = item.connection.connected
            if connected:
                item.connection.last_heard = time.monotonic()
        if connected:
            self._send(item.connection, _encode_answer(answer, operation))
        else:
            log.debug(
                "The answer to client %d's '%s' is discarded: the client is gone.",
                item.connection.number,
                operation,
            )
        if isinstance(item.request, messages.Shutdown):
            self.request_exit("shutdown")

    def _handle(self, request: QueuedRequest) -> messages.HalToClient:
        """Run one request on the devices; its answer, an Error for a DriverError."""
        try:
            match request:
                case messages.Open(device=name):
                    device_type, operations = self._devices.open(name)
                    return messages.Opened(name, device_type, operations)
                case messages.Call(device=name, operation=operation, args=args, kwargs=kwargs):
                    value = self._devices.call(name, operation, args, kwargs)
                    return messages.Result(value)
                case messages.Recover(device=name):
                    self._devices.recover(name)
                    return messages.Recovered(name)
                case messages.Info(device=name):
                    device_type, operations, is_open = self._devices.info(name)
                    return messages.DeviceInfo(name, device_type, operations, is_open)
                case messages.Close(device=name):
                    self._devices.close(name)
                    return messages.Closed(name)
                case messages.CloseAll():
                    return messages.ClosedAll(self._devices.close_all())
                case messages.Shutdown():
                    self._devices.close_all()
                    return messages.Bye()
                case _:
                    messages.unhandled(request)
        except DriverError as exc:
            text = str(exc)
            if _DRIVER_RAISED.match(text):
                return messages.Error("driver", text)
            return messages.Error("hal", text)

    # --- the exit -------------------------------------------------------------------

    def _exit_sequence(self) -> None:
        """The teardown and the rest of the exit; runs once, on whichever thread claims it."""
        with self._exit_lock:
            if self._exit_claimed:
                return
            self._exit_claimed = True
        try:
            if self._exit_reason is None:
                self._exit_reason = "the request thread ended"
            self._refusing = True
            log.debug("The HAL server is exiting: %s.", self._exit_reason)
            # Empty, unless the request thread died before it got to them, or one was
            # queued in the moment after its last look: the teardown answers what it covers.
            with self._lock:
                kept = [item for item in self._queue if isinstance(item.request, _KEPT_ON_EXIT)]
                refused = [item for item in self._queue if item not in kept]
                self._queue.clear()
            self._refuse_requests(refused)
            not_torn_down = self._devices.close_all()
            open_names = self._devices.open_names()
            device_rows = self._devices.snapshot()
            with self._lock:
                self._open_names = open_names
                self._device_rows = device_rows
            log.debug("The exit teardown is done; not torn down: %s.", not_torn_down)
            for item in kept:
                self._answer_after_teardown(item, not_torn_down)
            self._close_connections()
        finally:
            self._stopping.set()
            self._join_server_threads()
            if self._listener is not None:
                self._listener.close()
            log.debug("The HAL server has exited.")
            self._exited.set()

    def _answer_after_teardown(self, item: _Item, not_torn_down: list[str]) -> None:
        """A close_all / shutdown left over at the exit: the teardown did its work."""
        answer: messages.HalToClient
        match item.request:
            case messages.CloseAll():
                answer = messages.ClosedAll(list(not_torn_down))
            case messages.Shutdown():
                answer = messages.Bye()
            case (
                messages.Open()
                | messages.Call()
                | messages.Recover()
                | messages.Info()
                | messages.Close()
            ):
                answer = messages.Error("hal", SHUTTING_DOWN)
            case _:
                messages.unhandled(item.request)
        if item.connection.connected:
            self._send(item.connection, codec.encode(answer))

    def _close_connections(self) -> None:
        """Let clients close their end first (EXIT_GRACE_S), then close what is left."""
        with self._lock:
            self._clients_changed.wait_for(lambda: not self._connections, EXIT_GRACE_S)
            left = list(self._connections)
        for connection in left:
            self._drop(connection, "the HAL server is exiting")

    def _join_server_threads(self) -> None:
        current = threading.current_thread()
        threads: list[threading.Thread] = []
        with self._lock:
            for connection_thread in self._connection_threads:
                if connection_thread is not current:
                    threads.append(connection_thread)
        for server_thread in (self._accept_thread, self._watchdog_thread):
            if server_thread is not None and server_thread is not current:
                threads.append(server_thread)
        for thread in threads:
            if thread.is_alive():
                thread.join(THREAD_JOIN_S)
                if thread.is_alive():
                    log.debug("The thread '%s' did not end.", thread.name)


def _hang_up(connection: _Connection) -> None:
    """
    End a connection whose threads may be blocked on it: its connection thread reading, the
    request thread writing an answer. shutdown() wakes both on Linux. On Windows it wakes
    neither (checked: a blocked recv() and a blocked sendall() both stay blocked); only
    closing the handle does, and sock.close() waits for the connection thread's makefile to
    close first, so the handle is detached and closed. That close waits for the write lock,
    so it never lands in the middle of a write that is going on - except a write that has
    not finished within HANG_UP_WAIT_S, which is the stalled write being hung up on.
    A socket closed already raises OSError, which is ignored: there is nothing left to wake.
    """
    with contextlib.suppress(OSError):
        connection.sock.shutdown(socket.SHUT_RDWR)
    if sys.platform != "win32":
        return
    locked = connection.write_lock.acquire(timeout=HANG_UP_WAIT_S)
    try:
        with contextlib.suppress(OSError):
            socket.close(connection.sock.detach())
    finally:
        if locked:
            connection.write_lock.release()


def _operation_of(request: QueuedRequest) -> str:
    """The name the status and the errors give a request: a call's operation, else its kind."""
    if isinstance(request, messages.Call):
        return request.operation
    return messages.kind_of(request)


def _encode_answer(answer: messages.HalToClient, operation: str) -> bytes:
    """The answer's line; a result the codec refuses becomes an Error saying so."""
    try:
        return codec.encode(answer)
    except codec.MessageTooLarge as exc:
        text = f"'{operation}' ran, but its result is too large to send: {exc.size} bytes."
    except ValueError as exc:
        text = f"'{operation}' ran, but its result cannot be sent: {exc}"
    return codec.encode(messages.Error("hal", text))
