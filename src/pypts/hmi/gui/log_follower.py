"""
What the LOG OUTPUT panel follows: the session log and, during a run, the
run's own log.

The whole lifecycle lives here - opening the session log, picking up a run
log the Logger has yet to create, reading the two files in the order the
Logger wrote them, and waiting for the new session log an unload switched to.
Only this class touches its tails and deadlines; the GUI appends what poll()
returns and owns the timer that calls it. No Qt in this module, so the
ordering rules are testable with two plain files.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path

from pypts.hmi.gui.log_tail import LogTail

log = logging.getLogger(__name__)

#: How long poll() waits for the Logger to create a log file it was told
#: about - a run's own log, or the new session log after an unload - before
#: the panel says it could not be opened.
NEW_LOG_WAIT_S = 5.0


class LogFollower:
    """
    Hands back new log lines in the order the Logger wrote them.

    The Logger writes one file at a time, so the session log and the run log
    never interleave: into a run it is session then run, out of it run then
    session. What needs care is a switch between the two reads of one tick -
    lines of the first file written after it was read. Seeing the second file
    grow proves the switch happened, so the first is read once more, to its
    end, before the second's lines are handed back.

    Which way the switch goes is decided by the files, not by RunFinished:
    the Logger is back in the session log before RunFinished reaches this
    process, so once the run log has had a line, it is read first.
    """

    def __init__(
        self,
        get_session_log_path: Callable[[], str | None],
        report_open_failure: Callable[[OSError, str], None],
    ) -> None:
        """
        Args:
            get_session_log_path: the current session log's path, read per
                call - an unload switches it. None when this process was
                never told one.
            report_open_failure: called with the exception and the failing
                operation's name when a log file cannot be opened. The
                failure is survivable - the run is fine, the panel is not -
                so the follower carries on either way.
        """
        self._get_session_log_path = get_session_log_path
        self._report_open_failure = report_open_failure
        #: The session log on follow, None before and after.
        self.session_tail: LogTail | None = None
        #: The run's own log, followed beside the session log during a run.
        self.run_tail: LogTail | None = None
        #: A run log announced but not created by the Logger yet, and how long
        #: poll() waits for it.
        self._run_log_pending: str | None = None
        self._run_log_deadline: float | None = None
        #: True from run_finished() until the run log has been read to its end.
        self._run_log_finished = False
        #: True once the run log has shown a line: from then on the Logger can
        #: only go back to the session log, so the run log is read first.
        self._run_log_written = False
        #: Set while poll() waits for the Logger to create the session log an
        #: unload switched to; None the rest of the time.
        self._new_log_deadline: float | None = None

    def follow_session_log(self, path: str) -> list[str]:
        """
        Follow the session log at `path`. Returns the panel's notice lines -
        empty when the file opened, one `Could not open...` line when not.
        """
        tail = LogTail(path)
        try:
            tail.open()
        except OSError as exc:
            self._report_open_failure(exc, "GUI.start_log_tail")
            return [f"Could not open the run log: {path}"]
        log.debug("The log panel is following the run log at %s.", path)
        self.session_tail = tail
        return []

    def follow_run_log(self, run_log_path: str) -> list[str]:
        """
        RunStarted: the run is logged in its own file. Follow it as well.

        The Logger creates the file a moment after the switch was queued, so
        it is opened by poll() once it exists. Returns the lines still unread
        in a previous run's log, when one never saw its session lines.
        """
        lines: list[str] = []
        if self.run_tail is not None:
            lines = self._new_lines(self.run_tail)
            self._close_run_log()
        self._run_log_finished = False
        self._run_log_pending = run_log_path
        self._run_log_deadline = time.monotonic() + NEW_LOG_WAIT_S
        return lines

    def run_finished(self) -> None:
        """RunFinished: what follows the run log's last line is in the session log."""
        if self.run_tail is None and self._run_log_pending is None:
            # No run log was ever followed, so there is nothing to finish reading.
            return
        self._run_log_finished = True

    def expect_new_session_log(self) -> None:
        """
        The Logger was asked to switch to a new session log (an unload): wait
        for the file and follow it once it exists. Called after stop().
        """
        self._new_log_deadline = time.monotonic() + NEW_LOG_WAIT_S

    def is_active(self) -> bool:
        """Whether anything is followed or waited for - whether poll() needs a timer."""
        return (
            self.session_tail is not None
            or self.run_tail is not None
            or self._run_log_pending is not None
            or self._new_log_deadline is not None
        )

    def poll(self) -> list[str]:
        """
        This tick's lines for the panel: whatever the Logger has written since
        the last tick, plus a notice when a waited-for file never appeared.
        A read that fails raises OSError for the caller to report; it will
        fail every tick, so the caller should stop() rather than leave the
        failure to repeat forever.
        """
        lines: list[str] = []
        if self._run_log_pending is not None:
            lines += self._open_run_log()
        if self.session_tail is None and self.run_tail is None:
            if self._new_log_deadline is not None:
                lines += self._wait_for_new_log()
            return lines
        return lines + self._read_in_order()

    def stop(self) -> None:
        """Stop following and release the files. Safe to call twice."""
        if self.session_tail is not None:
            self.session_tail.close()
            self.session_tail = None
        self._close_run_log()
        self._run_log_pending = None
        self._run_log_deadline = None
        self._new_log_deadline = None

    def _read_in_order(self) -> list[str]:
        """This tick's new lines from the session log and the run log - the
        ordering rules are the class docstring's."""
        if self._run_log_finished or self._run_log_written:
            lines = self._new_lines(self.run_tail)
            session_lines = self._new_lines(self.session_tail)
            if session_lines:
                # Back in the session log, so the run log is complete - and
                # exists, even when a short run ended before it was opened.
                if self._run_log_pending is not None:
                    lines += self._open_run_log()
                lines += self._new_lines(self.run_tail)
                self._close_run_log()
                self._run_log_pending = None
                self._run_log_deadline = None
            return lines + session_lines
        lines = self._new_lines(self.session_tail)
        run_lines = self._new_lines(self.run_tail)
        if run_lines:
            lines += self._new_lines(self.session_tail)
            self._run_log_written = True
        return lines + run_lines

    @staticmethod
    def _new_lines(tail: LogTail | None) -> list[str]:
        if tail is None:
            return []
        return tail.new_lines()

    def _open_run_log(self) -> list[str]:
        """One tick of waiting for the Logger to create the run log."""
        path = self._run_log_pending
        if path is None:
            return []
        if Path(path).exists():
            self._run_log_pending = None
            self._run_log_deadline = None
            tail = LogTail(path)
            try:
                tail.open()
            except OSError as exc:
                self._report_open_failure(exc, "GUI.follow_run_log")
                return [f"Could not open the run log: {path}"]
            log.debug("The log panel is following the run log at %s.", path)
            self.run_tail = tail
            return []
        if self._run_log_deadline is not None and time.monotonic() > self._run_log_deadline:
            self._run_log_pending = None
            self._run_log_deadline = None
            log.warning("The log panel could not find the run's log.")
            log.debug("No file appeared at %s within %.1f s.", path, NEW_LOG_WAIT_S)
            return [f"Could not open the run log: {path}"]
        return []

    def _wait_for_new_log(self) -> list[str]:
        """
        One tick of waiting for the Logger to create the new session log.

        The switch is queued behind whatever the Logger has still to write, so
        the file appears a moment after expect_new_session_log(). If it never
        does - the Logger could not open it, and kept writing to the old one -
        the panel says so instead of waiting forever.
        """
        log_path = self._get_session_log_path()
        if log_path is not None and Path(log_path).exists():
            self._new_log_deadline = None
            return self.follow_session_log(log_path)
        if self._new_log_deadline is not None and time.monotonic() > self._new_log_deadline:
            self._new_log_deadline = None
            log.warning("The log panel could not find the new run log.")
            log.debug("No file appeared at %s within %.1f s.", log_path, NEW_LOG_WAIT_S)
            return [f"Could not open the run log: {log_path}"]
        return []

    def _close_run_log(self) -> None:
        if self.run_tail is not None:
            self.run_tail.close()
            self.run_tail = None
        self._run_log_finished = False
        self._run_log_written = False
