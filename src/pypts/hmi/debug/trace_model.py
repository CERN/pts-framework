# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The model behind the trace table, and the filter in front of it.

A Qt model rather than a growing list of table rows, because the trace is the
one part of this tool that has to keep up with a real run: the transport batches
64 messages per receive() per link, and rebuilding a widget tree at that rate would
make the console the slowest thing in the system it is supposed to be measuring.
"""

import time
from collections import deque

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor

from pypts.hmi.debug.icons import INJECTED, MESSAGE_ICONS
from pypts.messages.debug_link import TapRecord

#: Rows kept before the oldest are dropped. A long soak run would otherwise grow
#: the console's memory without bound, and nobody scrolls back past a few
#: thousand lines anyway.
MAX_ROWS = 5000

#: Types that say "still alive" and nothing else. They are the overwhelming
#: majority of traffic on an idle system - three modules beating steadily - so
#: the trace hides them unless asked.
NOISE_TYPES = frozenset({"Heartbeat"})

COLUMNS = ("Time", "Link", "Message", "Payload")

#: The "no parent" index a flat model is asked about. A module-level singleton
#: rather than a QModelIndex() default argument, which would be constructed once
#: at import and shared anyway - only less visibly.
NO_PARENT = QModelIndex()

# Rows are tinted rather than iconified: colour survives being skimmed at speed,
# which is how this table is actually read.
COLOUR_INJECTED = QColor(120, 90, 160)
COLOUR_ERROR = QColor(190, 60, 60)


class TraceModel(QAbstractTableModel):
    """A bounded, append-only table of TapRecords, newest last."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._records: deque[TapRecord] = deque(maxlen=MAX_ROWS)
        #: Counted separately from len(_records) so the header can report the
        #: true total after old rows have been dropped.
        self.total_seen = 0

    # --- Qt model interface ---------------------------------------------------

    def rowCount(self, parent=NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent=NO_PARENT) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        record = self._records[index.row()]

        if role == Qt.DisplayRole:
            match index.column():
                case 0:
                    # Wall-clock with milliseconds. Ordering two messages a
                    # millisecond apart is the usual reason to look at this
                    # column at all.
                    stamp = time.strftime("%H:%M:%S", time.localtime(record.timestamp))
                    return f"{stamp}.{int(record.timestamp % 1 * 1000):03d}"
                case 1:
                    return record.link
                case 2:
                    # Glyph first, so the column reads as a stripe of shapes
                    # when it is scrolling too fast to read the names.
                    marker = INJECTED if record.injected else ""
                    icon = MESSAGE_ICONS.get(record.message_type, "")
                    return " ".join(p for p in (marker, icon, record.message_type) if p)
                case 3:
                    return record.payload
        elif role == Qt.ForegroundRole:
            if record.message_type == "ModuleError":
                return QBrush(COLOUR_ERROR)
            if record.injected:
                return QBrush(COLOUR_INJECTED)
        elif role == Qt.ToolTipRole:
            return record.payload
        elif role == Qt.UserRole:
            return record
        return None

    # --- Appending -------------------------------------------------------------

    def append(self, records: list[TapRecord]) -> None:
        """
        Add a batch in one signal pair.

        Batched because the console drains its tap queue on a timer and normally
        gets several records at once; emitting per record would put the cost of
        a full view update on every message.
        """
        if not records:
            return
        self.total_seen += len(records)

        # A bounded deque drops silently on append, but a view told only about
        # the insertions would keep stale indices, so the drops are announced.
        overflow = max(0, len(self._records) + len(records) - MAX_ROWS)
        if overflow:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            for _ in range(overflow):
                self._records.popleft()
            self.endRemoveRows()

        first = len(self._records)
        self.beginInsertRows(QModelIndex(), first, first + len(records) - 1)
        self._records.extend(records)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._records.clear()
        self.total_seen = 0
        self.endResetModel()


class TraceFilter(QSortFilterProxyModel):
    """
    Link, type and free-text filtering over the trace.

    All three are combined with AND, which is what makes the table usable during
    a run: "sequencer->core, hide heartbeats, containing FAIL" is the question a
    developer actually has.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: None means "every link"; a set restricts to those links.
        self.links: set[str] | None = None
        self.hide_noise = True
        self.text = ""

    def set_links(self, links: set[str] | None) -> None:
        self.links = links
        self.invalidateFilter()

    def set_hide_noise(self, hide: bool) -> None:
        self.hide_noise = hide
        self.invalidateFilter()

    def set_text(self, text: str) -> None:
        self.text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        record = model.data(model.index(source_row, 0, source_parent), Qt.UserRole)
        if record is None:
            return True

        if self.hide_noise and record.message_type in NOISE_TYPES:
            return False
        if self.links is not None and record.link not in self.links:
            return False
        if self.text:
            haystack = f"{record.link} {record.message_type} {record.payload}".lower()
            if self.text not in haystack:
                return False
        return True
