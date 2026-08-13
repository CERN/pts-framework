# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The table behind the Trace tab.

A model over a bounded deque, plus a filter proxy over that. Both are ordinary
Qt classes; what is worth reading here is the two decisions that keep a table
fed from a 1 kHz log honest and responsive.

**Appending is batched, and overflow is announced.** A `deque(maxlen=...)` drops
from the front silently when it is full, which is exactly what a model must not
do: a view that was told about the insertions but not the drops keeps indices
pointing at rows that have moved, and the table starts showing the wrong payload
against the wrong timestamp. So `append()` computes the overflow first, wraps it
in `beginRemoveRows()`, and only then inserts - one pair of signals per poll
rather than one per message.

**The count is kept separately from the rows.** `total_seen` counts everything
that ever arrived; `rowCount()` is what is still in the buffer. Reporting the
second as the first would quietly under-report a busy run by however much was
trimmed, and under-reporting is the one thing a message trace may not do.
"""

from collections import deque

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from pypts.helper_applications.debug_monitor.trace_parser import SEND, TraceEvent

#: Rows kept in memory. An 8-hour run at DEBUG produces far more than this; the
#: buffer is a window on the tail, and the file remains the whole record.
MAX_ROWS = 5000

COLUMNS = ("Time", "Process", "", "Link", "Message", "Payload")

#: Column indices, so the code does not count commas.
COL_TIME = 0
COL_PROCESS = 1
COL_DIRECTION = 2
COL_LINK = 3
COL_TYPE = 4
COL_PAYLOAD = 5

#: Message types that say something went wrong, tinted so they are findable
#: while scrolling rather than only by filtering.
ERROR_TYPES = frozenset({"ModuleError", "ModuleErrorReported"})

#: Hidden by default. Three modules at 1 Hz in two directions is about six rows a
#: second of pure noise - and also the liveness signal, which is why they are
#: filtered rather than dropped.
NOISE_TYPES = frozenset({"Heartbeat"})

COLOUR_ERROR = QColor(190, 60, 60)
COLOUR_SEND = QColor(120, 120, 120)

#: Arrows rather than the words. The direction column is read at a glance, and
#: `send`/`recv` are the same width and shape.
DIRECTION_GLYPH = {SEND: "→", "recv": "←"}


class TraceModel(QAbstractTableModel):
    """
    Every message the Monitor has read, newest last.

    Rows are `TraceEvent`s and are handed back whole under `Qt.UserRole`, which
    is how the filter proxy below can ask about a field the table does not show.
    """

    def __init__(self, max_rows: int = MAX_ROWS) -> None:
        super().__init__()
        self._rows: deque[TraceEvent] = deque(maxlen=max_rows)

        #: Messages seen since the Monitor started, including those since
        #: trimmed. Not the same number as rowCount(), deliberately.
        self.total_seen = 0

    # --- Qt model interface ---

    # The camelCase names and the QModelIndex() defaults below are Qt's, not a
    # choice: these override virtuals and have to match their signatures.
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008 - Qt's signature
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008 - Qt's signature
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return COLUMNS[section]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        event = self._rows[index.row()]

        if role == Qt.UserRole:
            # The whole event, for the filter proxy. Nothing else uses it.
            return event

        if role == Qt.DisplayRole:
            return self._text(event, index.column())

        if role == Qt.ToolTipRole:
            # The payload column is elided at any sane width, and the payload is
            # the thing worth reading.
            return event.payload

        if role == Qt.ForegroundRole:
            if event.message_type in ERROR_TYPES:
                return COLOUR_ERROR
            if event.direction == SEND:
                # Sends dimmed, so a scan down the column reads as arrivals.
                return COLOUR_SEND

        return None

    # --- Feeding it ---

    def append(self, events) -> None:
        """
        Add a batch of events, trimming the front if the buffer is full.

        One `beginInsertRows`/`endInsertRows` pair for the whole batch, and one
        `beginRemoveRows` pair for whatever the batch pushes out. See the module
        docstring for why the removal cannot be left implicit.
        """
        events = list(events)
        if not events:
            return

        self.total_seen += len(events)

        # A single batch larger than the whole buffer would otherwise report
        # more insertions than there are rows. Only the tail can survive anyway.
        maximum = self._rows.maxlen
        if maximum is not None and len(events) > maximum:
            events = events[-maximum:]

        if maximum is not None:
            overflow = max(0, len(self._rows) + len(events) - maximum)
            if overflow:
                self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
                for _ in range(overflow):
                    self._rows.popleft()
                self.endRemoveRows()

        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(events) - 1)
        self._rows.extend(events)
        self.endInsertRows()

    def clear(self) -> None:
        """
        Empty the table. `total_seen` is reset with it - after a clear, the
        count means "since you cleared", which is what the button implies.
        """
        self.beginResetModel()
        self._rows.clear()
        self.total_seen = 0
        self.endResetModel()

    # --- Rendering ---

    @staticmethod
    def _text(event: TraceEvent, column: int) -> str:
        """One cell, as text."""
        if column == COL_TIME:
            if event.timestamp is None:
                return ""
            # Milliseconds matter here: the interesting question is usually how
            # long a message spent between its send and its recv. %f gives
            # microseconds, so the last three digits are dropped.
            return event.timestamp.strftime("%H:%M:%S.%f")[:-3]
        if column == COL_PROCESS:
            return event.process
        if column == COL_DIRECTION:
            return DIRECTION_GLYPH.get(event.direction, event.direction)
        if column == COL_LINK:
            return event.link
        if column == COL_TYPE:
            return event.message_type
        return event.payload


class TraceFilter(QSortFilterProxyModel):
    """
    Link, noise and free-text filters, ANDed.

    All three are asked of the `TraceEvent` itself rather than of the rendered
    cells, so the text search matches the whole payload even though the column
    showing it is elided, and hiding heartbeats does not depend on how the type
    column happens to be formatted.
    """

    def __init__(self) -> None:
        super().__init__()
        #: Links to show. None means "all", which is not the same as the set of
        #: every link the Monitor knows: a link nobody thought of - an anonymous
        #: QueueWrapper tracing as "?" - must still appear.
        self._hidden_links: set[str] = set()
        self._hide_noise = True
        self._text = ""

    def set_hidden_links(self, links) -> None:
        """Hide these links. Everything not named stays visible."""
        self._hidden_links = set(links)
        self.invalidateFilter()

    def set_hide_noise(self, hide: bool) -> None:
        """Hide heartbeats, which is most of the traffic and none of the news."""
        self._hide_noise = hide
        self.invalidateFilter()

    def set_text(self, text: str) -> None:
        """Case-insensitive substring, matched against link, type and payload."""
        self._text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        index = self.sourceModel().index(source_row, 0, source_parent)
        event = self.sourceModel().data(index, Qt.UserRole)
        if event is None:
            return True

        if event.link in self._hidden_links:
            return False

        if self._hide_noise and event.message_type in NOISE_TYPES:
            return False

        if self._text:
            haystack = f"{event.link} {event.message_type} {event.payload} {event.process}".lower()
            if self._text not in haystack:
                return False

        return True
