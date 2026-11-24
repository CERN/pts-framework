"""
CORE's link to the HAL server (spec §6.1, §6.2, §6.4, §9): the connect at startup, the HAL's
log lines re-logged in PyPTS's log, and the close.

start() runs on the calling thread and never waits for the HAL. The switch first: with the
environment variable PYPTS_HAL set to `off` (the test suite sets it) no connect is made, and
get_device() raises HAL_OFF. Then the bench: a bench.ini that was discarded at startup means no
connect either, and get_device() raises the reason. Otherwise it announces the connect to the
client (connect_pending(), so a run's run_scope() waits for it) and starts the daemon thread
`HAL connect`, which calls pyhal.client.connect() on bench.ini's path: it connects to a HAL
that is running, or starts one - with `show_window`, the HAL monitor window that starts it. A
connect that fails is a WARNING; get_device() raises its reason. Every path of start() and of
the thread settles the pending connect, so run_scope() never waits out CONNECT_WAIT_S for
nothing.

The HAL's log lines come back through _sink(), logged here at their own level as `HAL: <text>`.

close() is the close of spec §6.4, on the calling thread: it waits for a connect still running
at most CLOSE_WAIT_S, then HalClient.close() ends the scope, closes the long connection and
sends `shutdown` to a HAL this link started, else `close_all`. A connect still running after
the wait closes its client itself, at once, when it returns. Idempotent; never raises.

finish() is for after CORE's loop, just before its process exits: the connect thread is a
daemon, so the exit would kill a connect that returns late (a slow window start, up to
HAL_WINDOW_START_TIMEOUT_S) before it closes its client, and a HAL it started would never be
shut down. finish() joins that thread for at most FINISH_WAIT_S, so its own close path sends
the parting request. Idempotent; never raises; nothing to do without a thread.
"""

import logging
import os
import threading
from pathlib import Path

from pyhal.base_driver import DriverError
from pyhal.client import DEFAULT_PORT, HalClient, connect, connect_pending, note_unavailable
from pypts.config_handler.bench_config import BenchOutcome, bench_config

log = logging.getLogger(__name__)

#: The environment variable that turns the HAL off for a process: the value `off` means no
#: connect. Read by start(), so a process that sets it before CORE starts is covered.
HAL_SWITCH_ENV = "PYPTS_HAL"

#: What get_device() raises with the HAL turned off.
HAL_OFF = "The HAL is turned off for this process (PYPTS_HAL=off)."

#: The longest close() waits for a startup connect still running: well below the 15 s the
#: frontend allows a silent CORE.
CLOSE_WAIT_S = 5.0

#: The longest finish() waits for a connect still running after close(): below the 30 s the
#: launcher gives CORE's process to end (CORE_SHUTDOWN_TIMEOUT_S).
FINISH_WAIT_S = 20.0


class HalLink:
    """CORE's connection to the HAL server: started once, closed once."""

    def __init__(self, log_level: int, *, show_window: bool, port: int = DEFAULT_PORT) -> None:
        """
        Args:
            log_level: the log level of a HAL this link starts (one found running keeps its own).
            show_window: when no HAL is running, start the HAL monitor window, which starts it.
            port: the HAL's port.
        """
        self._log_level = log_level
        self._show_window = show_window
        self._port = port
        #: Guards _client and _closed, shared by the connect thread and close().
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        #: The connected client; None before the connect has returned, and after the close.
        self._client: HalClient | None = None
        #: Set by close(): a connect that returns afterwards closes its client at once.
        self._closed = False

    def start(self) -> None:
        """Start the connect on the thread `HAL connect`, or say why there is none."""
        with self._lock:
            closed = self._closed
        if closed or self._thread is not None:
            log.debug("The HAL link is already started or closed; no new connect.")
            return
        switch = os.environ.get(HAL_SWITCH_ENV, "")
        if switch.strip().lower() == "off":
            log.debug("%s=%s: no connect to the HAL server.", HAL_SWITCH_ENV, switch)
            note_unavailable(HAL_OFF)
            return
        bench = bench_config()
        if bench.outcome is BenchOutcome.DISCARDED:
            log.debug("bench.ini was discarded at startup: no connect to the HAL server.")
            note_unavailable(
                f"bench.ini was discarded at startup, so this start has no devices: {bench.problem}"
            )
            return
        log.debug(
            "Connecting to the HAL server on port %d, bench '%s', window %s.",
            self._port,
            bench.path,
            self._show_window,
        )
        connect_pending()
        thread = threading.Thread(
            target=self._connect, args=(bench.path,), name="HAL connect", daemon=True
        )
        try:
            thread.start()
        except RuntimeError as exc:
            # No thread, so nothing would settle the pending connect.
            log.warning("The HAL server could not be reached: %s", exc)
            note_unavailable(str(exc))
            return
        self._thread = thread

    def close(self) -> None:
        """The close (spec §6.4), on the calling thread. Idempotent; never raises."""
        try:
            with self._lock:
                if self._closed:
                    return
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(CLOSE_WAIT_S)
            with self._lock:
                self._closed = True
                hal_client = self._client
                self._client = None
            if hal_client is not None:
                hal_client.close()
            elif thread is not None and thread.is_alive():
                log.debug(
                    "The HAL connect was still running after %g s; it closes its connection "
                    "itself when it returns.",
                    CLOSE_WAIT_S,
                )
        except Exception as exc:  # noqa: BLE001 - the close runs in CORE's shutdown; never raises
            log.warning("The connection to the HAL server could not be closed: %s", exc)

    def finish(self) -> None:
        """
        Once CORE's loop is over: wait at most FINISH_WAIT_S for a connect still running, so
        that it closes its client before the process exits (module docstring). Idempotent;
        never raises.
        """
        try:
            thread = self._thread
            if thread is None or thread is threading.current_thread() or not thread.is_alive():
                return
            log.debug(
                "Waiting at most %g s for the HAL connect, so it closes its connection.",
                FINISH_WAIT_S,
            )
            thread.join(FINISH_WAIT_S)
            if thread.is_alive():
                log.debug(
                    "The HAL connect was still running after %g s; the process exits without it.",
                    FINISH_WAIT_S,
                )
        except Exception as exc:  # noqa: BLE001 - runs as CORE's process ends; never raises
            log.warning("The HAL connect could not be waited for: %s", exc)

    def _connect(self, bench_path: Path) -> None:
        """The thread `HAL connect`: connect, or start the HAL. Never raises."""
        try:
            hal_client = connect(
                bench_path,
                self._port,
                scope=False,
                log_sink=self._sink,
                log_level=self._log_level,
                show_window=self._show_window,
            )
        except DriverError as exc:
            log.warning("The HAL server could not be reached: %s", exc)
            # connect() has noted the reason and settled the pending connect already; this
            # makes it so for any connect that raises.
            note_unavailable(str(exc))
            return
        except Exception as exc:
            # Whatever went wrong, the pending connect must be settled.
            reason = f"{type(exc).__name__}: {exc}"
            log.warning("The HAL server could not be reached: %s", reason)
            log.debug("The HAL connect failed unexpectedly.", exc_info=True)
            note_unavailable(reason)
            return
        if hal_client.started_hal:
            log.info("Started the HAL server.")
        else:
            log.info("Connected to the HAL server.")
        log.debug(
            "The HAL server: pid %d, port %d, bench '%s', its log '%s', window %s.",
            hal_client.hello.pid,
            hal_client.port,
            hal_client.hello.bench,
            hal_client.hello.log,
            self._show_window and hal_client.started_hal,
        )
        with self._lock:
            closed = self._closed
            if not closed:
                self._client = hal_client
        if closed:
            log.debug("The HAL link was closed during the connect; closing the connection now.")
            hal_client.close()

    def _sink(self, level: int, message: str) -> None:
        """A record of the HAL's log, logged here at its own level."""
        log.log(level, "HAL: %s", message)
