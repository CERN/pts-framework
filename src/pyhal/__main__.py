"""
`python -m pyhal`: run a HAL server, or tell a running one to close its devices or to stop
(spec §11).

Serving (`--bench FILE`): start the log file, read the bench, install the exit handlers, bind
and serve until the server has exited. The port taken is exit code EXIT_PORT_IN_USE.

**The window** (`--window`, what `pyhal.connect(show_window=True)` and `run_hal.py` pass): once
the server is bound, the HAL opens its monitor window as a child process of its own,
`python -m pyhal.monitor --port N --exit-with-hal` (open_window()), and owns it: at the HAL's
exit, after the teardown, a window still open is ended (close_window()). The monitor never
starts or stops a HAL on its own (user decision 2026-11-24); closing the window leaves the HAL
running. The HAL never imports PySide6 and never waits for the window: a window that cannot be
started is a WARNING, and one that cannot open (no display) exits and says why in
MONITOR_STARTUP_FILE. `--exit-with-hal` is the net for a HAL killed without its exit (Windows
does not end a killed process's children): the window closes itself once the HAL has gone.

The client modes (`--close-all`, `--stop`) connect only, never start a HAL: `--close-all`
sends `close_all`, `--stop` sends `close_all` and then `shutdown` (`bye` carries no list, so
the `close_all` before it is what reports the devices not torn down). Each waits for its
answers, prints `Not torn down: <names>` or `Every device was torn down.`, and exits with
EXIT_OK, EXIT_NOT_TORN_DOWN, or EXIT_NO_HAL when no HAL answered.

**The exit handlers** (spec §6.5). Ctrl+C (SIGINT), Ctrl+Break (SIGBREAK), SIGTERM and SIGHUP,
where they exist, and on Windows the console's close, logoff and shutdown events, all call
`request_exit()` - the first one only; a second Ctrl+C does nothing, so it cannot cut the
teardown short. A signal handler does nothing else, as request_exit() is safe there. The
console handler runs on a thread Windows starts, and Windows ends the process as soon as it
returns, so it waits for the exit to finish (Windows still ends the process about 5 s after
a console close: a console closed by hand is only partly covered).

**What keeps the driver processes alive until their teardown.** They are `daemon=True`
(ConnectionDriver._start()), and multiprocessing terminates daemon children when the
interpreter exits, without teardown(). So the main thread leaves serve() only once the
server has exited, its teardown done: serve_until_stopped(), and on any other way out of it
(an exception) request_exit() and the same wait again, in a `finally`. The server's threads
are daemons too, so nothing else keeps the interpreter alive: the wait in the main thread is
what does.
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import Any

from pyhal.base_driver import DriverError
from pyhal.client import DEFAULT_PORT, EXIT_PORT_IN_USE, _open_connection
from pyhal.hal_log import default_log_dir, start_log_file
from pyhal.protocol import codec, messages
from pyhal.server import HalServer

log = logging.getLogger("pyhal")

EXIT_OK = 0
#: A client mode's close_all left a device not torn down.
EXIT_NOT_TORN_DOWN = 1
#: Serving: the bench file cannot be read.
EXIT_BAD_BENCH = 1
#: A client mode found no HAL to answer it.
EXIT_NO_HAL = 2

#: What open_window() runs with `python -m`.
MONITOR_MODULE = "pyhal.monitor"

#: The file in the log folder that takes the monitor window's stdout and stderr, appended to:
#: among them why a window could not open (no display).
MONITOR_STARTUP_FILE = "hal_monitor_startup.log"

#: How long close_window() waits for the window to end once it has been told to.
WINDOW_CLOSE_WAIT_S = 5.0

#: The signals that end the server, those of them this platform has.
EXIT_SIGNALS = ("SIGINT", "SIGBREAK", "SIGTERM", "SIGHUP")

#: Windows console control events (wincon.h).
CTRL_C_EVENT = 0
CTRL_BREAK_EVENT = 1
CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6

#: Every console callback ever installed, never freed: Windows may still be running one on
#: its own thread when restore() takes it off, and freeing it then would crash the process.
_CONSOLE_CALLBACKS: list[Any] = []

#: The console events the console handler takes; Ctrl+C and Ctrl+Break go to the signals.
CONSOLE_EXIT_EVENTS = {
    CTRL_CLOSE_EVENT: "the console is closing",
    CTRL_LOGOFF_EVENT: "the user is logging off",
    CTRL_SHUTDOWN_EVENT: "Windows is shutting down",
}


def parse_log_level(text: str) -> int:
    """A log level given as a number or as a name (`TRACE` included). Raises ValueError."""
    cleaned = text.strip()
    if cleaned.isdigit():
        return int(cleaned)
    level = logging.getLevelName(cleaned.upper())
    if isinstance(level, int):
        return level
    raise ValueError(f"'{text}' is not a log level")


def _log_level_argument(text: str) -> int:
    try:
        return parse_log_level(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def report_not_torn_down(names: list[str]) -> int:
    """Print what a close_all left; the exit code that goes with it."""
    if names:
        print("Not torn down: " + ", ".join(names))
        return EXIT_NOT_TORN_DOWN
    print("Every device was torn down.")
    return EXIT_OK


class ExitHandlers:
    """The handlers that turn a signal or a console event into the server's exit."""

    def __init__(self, hal: HalServer) -> None:
        self._hal = hal
        #: Set by the first signal or console event; the later ones do nothing more.
        self._exit_requested = False
        self._previous: dict[int, Any] = {}
        #: The ctypes callback while it is installed.
        self._console_callback: Any = None

    def install(self) -> None:
        """Install every handler this platform has. Call it from the main thread."""
        for name in EXIT_SIGNALS:
            signal_number = getattr(signal, name, None)
            if signal_number is None:
                continue
            self._previous[signal_number] = signal.signal(signal_number, self.on_signal)
        if sys.platform == "win32":
            import ctypes

            handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
            self._console_callback = handler_type(self.on_console_event)
            _CONSOLE_CALLBACKS.append(self._console_callback)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(self._console_callback, True)

    def restore(self) -> None:
        """Put back what install() replaced (for tests, and a server run in a process)."""
        for signal_number, previous in self._previous.items():
            signal.signal(signal_number, previous)
        self._previous = {}
        if sys.platform == "win32" and self._console_callback is not None:
            import ctypes

            ctypes.windll.kernel32.SetConsoleCtrlHandler(self._console_callback, False)
            self._console_callback = None

    def on_signal(self, signal_number: int, frame: FrameType | None) -> None:
        """A signal: the first one requests the exit; the others do nothing."""
        if self._exit_requested:
            return
        self._exit_requested = True
        self._hal.request_exit("signal " + signal.Signals(signal_number).name)

    def on_console_event(self, event: int) -> int:
        """
        A Windows console control event, on a thread Windows started. Close, logoff and
        shutdown request the exit (the first one only) and return 1 once it is done;
        anything else returns 0, so the next handler - Python's, for Ctrl+C - gets it.
        """
        reason = CONSOLE_EXIT_EVENTS.get(event)
        if reason is None:
            return 0
        if not self._exit_requested:
            self._exit_requested = True
            self._hal.request_exit(reason)
        # Windows ends the process when this returns: not before the teardown is done.
        self._hal.wait_until_exited(None)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pyhal",
        description=(
            "Run a HAL server for a bench file, or tell the one on the port to close every "
            "device (--close-all) or to stop (--stop)."
        ),
    )
    parser.add_argument("--bench", metavar="FILE", help="the bench file; required to serve")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"the port (default {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--log-dir", metavar="DIR", help=f"the log folder (default {default_log_dir()})"
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        type=_log_level_argument,
        default=logging.INFO,
        help="a number or a name, TRACE included (default INFO)",
    )
    parser.add_argument(
        "--nonce", metavar="TEXT", help="the start nonce hello echoes (set by a starting client)"
    )
    parser.add_argument(
        "--window",
        action="store_true",
        help="open the HAL monitor window on this HAL; the HAL ends it at its exit",
    )
    modes =parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--close-all",
        action="store_true",
        help="tell the HAL on the port to close every device; never starts one",
    )
    modes.add_argument(
        "--stop",
        action="store_true",
        help="tell the HAL on the port to close every device and exit; never starts one",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    if arguments.close_all:
        return ask(arguments.port, stop=False)
    if arguments.stop:
        return ask(arguments.port, stop=True)
    if arguments.bench is None:
        parser.error("--bench FILE is required to run a HAL server")
    if arguments.log_dir is None:
        log_dir = default_log_dir()
    else:
        log_dir = Path(arguments.log_dir)
    return serve(
        Path(arguments.bench),
        arguments.port,
        log_dir,
        arguments.log_level,
        arguments.nonce,
        window=arguments.window,
    )


def serve(
    bench: Path,
    port: int,
    log_dir: Path,
    level: int,
    nonce: str | None,
    *,
    window: bool = False,
) -> int:
    """Run a HAL server until it has exited, with its monitor window when `window`; the
    process's exit code."""
    log_path = start_log_file(log_dir, level)
    try:
        hal = HalServer(bench, port, nonce=nonce, log_path=str(log_path))
    except (OSError, ValueError, DriverError) as exc:
        # configparser's errors are ValueErrors; a driver of the old package a DriverError.
        text = f"The bench file '{bench}' could not be read: {exc}"
        log.error("%s", text)
        print(text, file=sys.stderr)
        return EXIT_BAD_BENCH
    # Installed before the threads start, so no signal can find the server without them.
    handlers = ExitHandlers(hal)
    handlers.install()
    try:
        try:
            hal.start()
        except OSError as exc:
            text = (
                f"Port {port} cannot be used: another HAL server or program has it, "
                "or the system reserves it. Choose another with --port."
            )
            log.error("%s (%s)", text, exc)
            print(text, file=sys.stderr)
            return EXIT_PORT_IN_USE
        log.info("The HAL server is running on 127.0.0.1:%d, bench '%s'.", hal.port, bench)
        print(f"The HAL server is running on 127.0.0.1:{hal.port}; its log is {log_path}.")
        print("Ctrl+C stops it, after tearing every open device down.", flush=True)
        monitor: subprocess.Popen[bytes] | None = None
        if window:
            monitor = open_window(hal.port, log_dir)
        try:
            hal.serve_until_stopped()
        finally:
            # Whatever ends the wait, this thread leaves only after the teardown (see above).
            if not hal.wait_until_exited(0):
                hal.request_exit("the main thread is ending")
                hal.serve_until_stopped()
            close_window(monitor)
        log.info("The HAL server on 127.0.0.1:%d has stopped.", hal.port)
        return EXIT_OK
    finally:
        # The teardown is done: a signal or a console event now may end the process at once.
        handlers.restore()


def open_window(port: int, log_dir: Path) -> subprocess.Popen[bytes] | None:
    """
    Start the HAL monitor window on the port as this HAL's child: `python -m pyhal.monitor
    --port N --exit-with-hal`, with this process's sys.path, its output appended to
    MONITOR_STARTUP_FILE in the log folder. Never waits for it. None, and a WARNING, when it
    cannot be started: the HAL runs on without a window.
    """
    folder = log_dir.resolve()
    startup_path = folder / MONITOR_STARTUP_FILE
    # -P and PYTHONPATH as the client starts the HAL: the window imports pyhal from where this
    # process does, whatever its working directory.
    command = [sys.executable, "-P", "-m", MONITOR_MODULE, "--port", str(port), "--exit-with-hal"]
    entries = [os.path.abspath(entry) for entry in sys.path if entry and os.path.exists(entry)]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with open(startup_path, "ab") as startup:
            if sys.platform == "win32":
                # A HAL a client started has no console, and a console program it starts
                # would get a console window of its own; the Qt window still shows.
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=startup,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    cwd=folder,
                    close_fds=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
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
                )
    except OSError as exc:
        log.warning("The HAL monitor window could not be started: %s", exc)
        return None
    log.debug(
        "Opened the HAL monitor window (pid %d); its output goes to '%s'.",
        process.pid,
        startup_path,
    )
    return process


def close_window(monitor: subprocess.Popen[bytes] | None) -> None:
    """
    End the HAL's monitor window, if it is still open: the HAL has exited, so there is nothing
    left for it to show. It is ended, not asked: the monitor sends nothing on its own, so
    there is nothing it could leave half done. Never raises.
    """
    if monitor is None or monitor.poll() is not None:
        return
    log.debug("Closing the HAL monitor window (pid %d).", monitor.pid)
    try:
        monitor.terminate()
        monitor.wait(WINDOW_CLOSE_WAIT_S)
    except subprocess.TimeoutExpired:
        monitor.kill()
    except OSError as exc:
        log.debug("The HAL monitor window could not be closed: %s", exc)


def ask(port: int, *, stop: bool) -> int:
    """--close-all and --stop: connect only, send, wait for the answers, report."""
    try:
        sock, stream, first = _open_connection(port)
    except DriverError as exc:
        print(exc, file=sys.stderr)
        return EXIT_NO_HAL
    try:
        match first:
            case messages.Hello():
                pass
            case messages.Error(message=text):
                print(f"The HAL server on 127.0.0.1:{port} answered: {text}", file=sys.stderr)
                return EXIT_NO_HAL
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
                print(f"What answered on 127.0.0.1:{port} is not a HAL server.", file=sys.stderr)
                return EXIT_NO_HAL
            case _:
                messages.unhandled(first)
        # No deadline on an answer (D57): a close ladder takes as long as it takes.
        sock.settimeout(None)
        answer = _exchange(sock, stream, messages.CloseAll())
        match answer:
            case messages.ClosedAll(not_torn_down=names):
                not_torn_down = list(names)
            case messages.Error(message=text):
                print(f"The HAL server answered: {text}", file=sys.stderr)
                return EXIT_NO_HAL
            case None:
                print(f"The HAL server on 127.0.0.1:{port} closed the connection.", file=sys.stderr)
                return EXIT_NO_HAL
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
                kind = messages.kind_of(answer)
                print(
                    f"HAL protocol error: the answer to 'close_all' was '{kind}'.",
                    file=sys.stderr,
                )
                return EXIT_NO_HAL
            case _:
                messages.unhandled(answer)
        if stop:
            _stop(sock, stream, port)
        return report_not_torn_down(not_torn_down)
    except (OSError, codec.MalformedLine) as exc:
        print(
            f"The connection to the HAL server on 127.0.0.1:{port} failed: {exc}", file=sys.stderr
        )
        return EXIT_NO_HAL
    finally:
        stream.close()
        sock.close()


def _stop(sock: Any, stream: Any, port: int) -> None:
    """Send `shutdown` and wait for `bye`; anything else is said on stderr."""
    answer = _exchange(sock, stream, messages.Shutdown())
    match answer:
        case messages.Bye():
            pass
        case messages.Error(message=text):
            print(f"The HAL server answered the shutdown: {text}", file=sys.stderr)
        case None:
            print(f"The HAL server on 127.0.0.1:{port} closed the connection.", file=sys.stderr)
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
            print(
                f"HAL protocol error: the answer to 'shutdown' was '{messages.kind_of(answer)}'.",
                file=sys.stderr,
            )
        case _:
            messages.unhandled(answer)


def _exchange(sock: Any, stream: Any, request: messages.ClientToHal) -> messages.HalToClient | None:
    """Send one request and read its answer; None when the connection closed first."""
    sock.sendall(codec.encode(request))
    line = codec.read_line(stream)
    if line is None:
        return None
    answer: messages.HalToClient = codec.decode(line, messages.HAL_KINDS)
    return answer


if __name__ == "__main__":
    sys.exit(main())
