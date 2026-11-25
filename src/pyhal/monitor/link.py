"""
The HAL monitor's link to the HAL server, without Qt: the status poll, Close all, Stop and the
log tail. It only connects to a HAL; it never starts one (user decision 2026-11-24).

The link talks to the HAL over connections of its own and **never sends a parting request**:
close() closes its connection and sends nothing, so closing the monitor never touches the
bench (D36). `close_all` and `shutdown` go only from close_all() and stop(), which the window
calls when its user has pressed a button and confirmed.

**The poll.** status() keeps one connection, opened on first use: connect, read `hello`, then
`status` and its answer on each poll, every step bounded by POLL_TIMEOUT_S (the HAL answers
`status` at once, from its connection thread). Any failure closes it and the poll returns
None. A failure on a connection kept from an earlier poll is tried once more on a fresh one in
the same call: the HAL it belonged to may have gone and another taken the port, or the HAL may
have dropped it after CLIENT_SILENCE_S without a poll. A connection that polls every second
needs no beat. A connection that asks only `status` is not counted as a client by the HAL, so
a status's `clients` never includes the link's poll (and devices left open with no client using
them are still reported as such to the next client that connects, D40).

**The actions** each use a short connection of their own, so they never wait behind a poll and
a poll never waits behind them: close_all() sends `close_all` and waits for `closed_all` with no
deadline (a close ladder can take about 50 s per device, D57); stop() sends `close_all` and then
`shutdown`, as `python -m pyhal --stop` does. Call them from a worker thread, never from a GUI
thread.

**Locks.** One lock guards the kept connection and `hello`; status() holds it for its poll,
close() and log_tail() take it briefly. The actions do not take it.
"""

import contextlib
import logging
import socket
import threading
from collections.abc import Callable
from typing import BinaryIO

from pyhal import client
from pyhal.base_driver import DriverError
from pyhal.client import DEFAULT_PORT
from pyhal.protocol import codec, messages

log = logging.getLogger(__name__)

#: The longest each step of a poll may take: the connect, the `hello`, the `status` answer.
POLL_TIMEOUT_S = 2.0


class _NothingAnswers(DriverError):
    """Nothing accepted a connection on the port."""


class MonitorLink:
    """The monitor's connection to the HAL server on 127.0.0.1:<port>. Thread-safe."""

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        #: The HAL's port, on 127.0.0.1.
        self.port = port
        #: The `hello` of the last connection status() opened; None before the first.
        self.hello: messages.Hello | None = None
        self._lock = threading.Lock()
        #: The kept connection of status(); None when closed. Guarded by the lock.
        self._sock: socket.socket | None = None
        self._stream: BinaryIO | None = None

    def status(self) -> messages.StatusReport | None:
        """The HAL's status, or None when no HAL answers within the poll's bounds."""
        with self._lock:
            kept = self._sock is not None
            report = self._poll()
            if report is None and kept:
                report = self._poll()
            return report

    def close_all(self) -> list[str]:
        """
        Close every open device on the HAL, also those of other clients; the names of those
        not torn down. Waits as long as the close ladders take. Raises DriverError when no HAL
        answers, or when it refuses (it is shutting down).
        """
        sock, stream, _hello = _connect(self.port)
        try:
            sock.settimeout(None)
            return _close_all_on(sock, stream, self.port)
        finally:
            _close_quietly(sock, stream)

    def stop(self) -> list[str]:
        """
        Close every open device and stop the HAL (`close_all`, then `shutdown`, on one
        connection); the names of the devices not torn down. Raises DriverError when no HAL
        answers, or when it refuses either request; a refused `shutdown`'s text ends with what
        the `close_all` before it left (`Not torn down: ...` / `Every device was torn down.`).
        """
        sock, stream, _hello = _connect(self.port)
        try:
            sock.settimeout(None)
            not_torn_down = _close_all_on(sock, stream, self.port)
            answer = _exchange(sock, stream, messages.Shutdown(), self.port)
            match answer:
                case messages.Bye():
                    pass
                case messages.Error(message=text):
                    raise DriverError(
                        f"The HAL server did not stop: {text} "
                        f"{_not_torn_down_text(not_torn_down)}"
                    )
                case (
                    messages.Hello()
                    | messages.Opened()
                    | messages.Result()
                    | messages.Recovered()
                    | messages.DeviceInfo()
                    | messages.Closed()
                    | messages.ClosedAll()
                    | messages.StatusReport()
                ):
                    raise DriverError(
                        "HAL protocol error: the answer to 'shutdown' was "
                        f"'{messages.kind_of(answer)}'."
                    )
                case _:
                    messages.unhandled(answer)
            return not_torn_down
        finally:
            _close_quietly(sock, stream)

    def close(self) -> None:
        """Close the kept connection. Sends nothing. Idempotent."""
        with self._lock:
            self._drop()

    def log_tail(self, sink: Callable[[int, str], None]) -> client.LogTail | None:
        """
        A started client.LogTail on the log file the last `hello` names, passing each new
        record to sink(level, message); None before any `hello`, or when it names no log.
        The caller stops it.
        """
        with self._lock:
            hello = self.hello
        if hello is None or not hello.log:
            return None
        tail = client.LogTail(hello.log, sink)
        tail.start()
        return tail

    # --- the poll; the caller holds the lock ---------------------------------------

    def _poll(self) -> messages.StatusReport | None:
        if self._sock is None or self._stream is None:
            try:
                sock, stream, hello = _connect(self.port)
            except DriverError as exc:
                log.debug("The HAL monitor's poll of 127.0.0.1:%d: %s", self.port, exc)
                return None
            self._sock = sock
            self._stream = stream
            self.hello = hello
        else:
            sock = self._sock
            stream = self._stream
        try:
            sock.sendall(codec.encode(messages.Status()))
            line = codec.read_line(stream)
            answer: messages.HalToClient | None = None
            if line is not None:
                answer = codec.decode(line, messages.HAL_KINDS)
        except (OSError, codec.MalformedLine) as exc:
            log.debug("The HAL monitor's status on 127.0.0.1:%d failed: %s", self.port, exc)
            self._drop()
            return None
        match answer:
            case messages.StatusReport():
                return answer
            case None:
                log.debug(
                    "The HAL server on 127.0.0.1:%d closed the monitor's connection.", self.port
                )
            case messages.Error(message=text):
                log.debug("The HAL server on 127.0.0.1:%d answered the status: %s", self.port, text)
            case (
                messages.Hello()
                | messages.Opened()
                | messages.Result()
                | messages.Recovered()
                | messages.DeviceInfo()
                | messages.Closed()
                | messages.ClosedAll()
                | messages.Bye()
            ):
                log.debug(
                    "HAL protocol error: the answer to 'status' was '%s'.",
                    messages.kind_of(answer),
                )
            case _:
                messages.unhandled(answer)
        self._drop()
        return None

    def _drop(self) -> None:
        sock = self._sock
        stream = self._stream
        self._sock = None
        self._stream = None
        if sock is not None and stream is not None:
            _close_quietly(sock, stream)


# --- one connection --------------------------------------------------------------------


def _connect(port: int) -> tuple[socket.socket, BinaryIO, messages.Hello]:
    """
    Connect to 127.0.0.1:<port> and read `hello`, each within POLL_TIMEOUT_S; the socket keeps
    that timeout. Raises _NothingAnswers when nothing listens, DriverError when the HAL refuses
    (it is shutting down) or what answers is not a HAL; nothing is left open.
    """
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=POLL_TIMEOUT_S)
    except OSError as exc:
        log.debug("Connecting to 127.0.0.1:%d failed: %s", port, exc)
        raise _NothingAnswers(f"No HAL server answered on 127.0.0.1:{port}.") from None
    stream = sock.makefile("rb")
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        line = codec.read_line(stream)
        first: messages.HalToClient | None = None
        if line is not None:
            first = codec.decode(line, messages.HAL_KINDS)
    except (OSError, codec.MalformedLine) as exc:
        _close_quietly(sock, stream)
        raise DriverError(f"What answered on 127.0.0.1:{port} is not a HAL server: {exc}") from None
    match first:
        case messages.Hello():
            return sock, stream, first
        case messages.Error(message=text):
            _close_quietly(sock, stream)
            raise DriverError(f"The HAL server on 127.0.0.1:{port} answered: {text}")
        case None:
            _close_quietly(sock, stream)
            raise DriverError(f"What answered on 127.0.0.1:{port} closed without a hello.")
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
            _close_quietly(sock, stream)
            raise DriverError(
                f"What answered on 127.0.0.1:{port} is not a HAL server: it began with "
                f"'{messages.kind_of(first)}', not 'hello'."
            )
        case _:
            messages.unhandled(first)


def _exchange(
    sock: socket.socket, stream: BinaryIO, request: messages.ClientToHal, port: int
) -> messages.HalToClient:
    """Send one request and read its answer. Raises DriverError when the connection ends first."""
    try:
        sock.sendall(codec.encode(request))
        line = codec.read_line(stream)
        if line is None:
            raise DriverError(f"The HAL server on 127.0.0.1:{port} closed the connection.")
        answer: messages.HalToClient = codec.decode(line, messages.HAL_KINDS)
    except (OSError, codec.MalformedLine) as exc:
        raise DriverError(
            f"The connection to the HAL server on 127.0.0.1:{port} failed: {exc}"
        ) from None
    return answer


def _close_all_on(sock: socket.socket, stream: BinaryIO, port: int) -> list[str]:
    """`close_all` and its answer on the connection; the names not torn down."""
    answer = _exchange(sock, stream, messages.CloseAll(), port)
    match answer:
        case messages.ClosedAll(not_torn_down=names):
            return list(names)
        case messages.Error(message=text):
            raise DriverError(f"The HAL server did not close the devices: {text}")
        case (
            messages.Hello()
            | messages.Opened()
            | messages.Result()
            | messages.Recovered()
            | messages.DeviceInfo()
            | messages.Closed()
            | messages.Bye()
            | messages.StatusReport()
        ):
            raise DriverError(
                f"HAL protocol error: the answer to 'close_all' was '{messages.kind_of(answer)}'."
            )
        case _:
            messages.unhandled(answer)


def _not_torn_down_text(names: list[str]) -> str:
    """What a close_all left, as `python -m pyhal` prints it."""
    if names:
        return "Not torn down: " + ", ".join(names)
    return "Every device was torn down."


def _close_quietly(sock: socket.socket, stream: BinaryIO) -> None:
    with contextlib.suppress(OSError):
        stream.close()
    with contextlib.suppress(OSError):
        sock.close()
