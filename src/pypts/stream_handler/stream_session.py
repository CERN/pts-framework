"""
The streams of one run, and the one session that is active in this process.

A StreamSession is to streams what hal.local_setup.LocalSetup is to devices:
the Sequencer enters one per run, test code asks the active one through
register_stream(), and a script outside PyPTS does the same with
`with StreamSession(folder):`.
"""

import logging
import os
import threading
from types import TracebackType

from pypts.stream_handler.stream_file import Stream, stream_csv_path

logger = logging.getLogger(__name__)


class StreamError(RuntimeError):
    """No stream can be registered: no session is active, or its run was abandoned."""


class StreamSession:
    """
    The streams of one run. Thread-safe.

    `folder` is the run folder; None means streams are off for this run, and
    registered streams then write nothing.
    """

    def __init__(self, folder: str | os.PathLike[str] | None) -> None:
        self._folder = folder
        self._lock = threading.Lock()
        self._by_name: dict[str, Stream] = {}
        self._all: list[Stream] = []
        self._abandoned = False
        self._closed = False
        self._warned_no_folder = False

    @property
    def records_streams(self) -> bool:
        return self._folder is not None

    def has_stream(self, name: str) -> bool:
        safe = stream_csv_path("", name).name
        with self._lock:
            return any(stream_csv_path("", known).name == safe for known in self._by_name)

    def register(self, name: str, unit: str | None = None) -> Stream:
        """
        Open the stream `name`. Registering a name again opens a new Stream on
        the same file, which appends.

        Raises:
            StreamError: the run was abandoned.
        """
        with self._lock:
            if self._abandoned:
                raise StreamError("This run was abandoned; its streams are closed.")
            if self._closed:
                logger.debug("Stream '%s' registered after the session closed; not recorded.", name)
                stream = Stream(name, None, unit)
            elif self._folder is None:
                stream = Stream(name, None, unit)
                if not self._warned_no_folder:
                    self._warned_no_folder = True
                    logger.warning("Stream '%s' is not recorded: this run has no run folder.", name)
            else:
                stream = Stream(name, stream_csv_path(self._folder, name), unit)
            self._by_name[name] = stream
            self._all.append(stream)
            return stream

    def close(self) -> None:
        """Close every stream of this session. Never raises."""
        with self._lock:
            self._closed = True
            streams = list(self._all)
        for stream in streams:
            try:
                stream.close()
            except Exception as exc:  # noqa: BLE001 - one stream must not keep the others open
                logger.warning("Stream '%s' did not close: %s", stream.name, exc)

    def abandon(self) -> None:
        """Close the streams of a run that will not end, and refuse new ones. Never raises."""
        with self._lock:
            self._abandoned = True
        self.close()

    def __enter__(self) -> "StreamSession":
        _activate(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        finally:
            _deactivate(self)


# --- the active stream session ----------------------------------------------------
#
# One per process, not thread-local: test code may push from threads of its own.
# The same shape as the active local setup in hal/local_setup.py.

_active_session: StreamSession | None = None
_active_lock = threading.Lock()


def _activate(session: StreamSession) -> None:
    global _active_session
    with _active_lock:
        if _active_session is not None and _active_session is not session:
            # Only an abandoned run leaves a session active behind it.
            logger.debug("A new stream session replaces one that was never closed.")
        _active_session = session


def _deactivate(session: StreamSession) -> None:
    global _active_session
    with _active_lock:
        if _active_session is session:
            _active_session = None


def register_stream(name: str, unit: str | None = None) -> Stream:
    """
    Open the stream `name` on the active session - what test code calls.

    Raises:
        StreamError: no session is active.
    """
    with _active_lock:
        session = _active_session
    if session is None:
        raise StreamError(
            "No stream session is active. register_stream() works in test code PyPTS is "
            "running, or inside 'with StreamSession(folder):' in a script of your own."
        )
    return session.register(name, unit)


def abandon_active_session() -> None:
    """Take the active session from a run that will not end and close its streams. Never raises."""
    global _active_session
    with _active_lock:
        session = _active_session
        _active_session = None
    if session is not None:
        session.abandon()
