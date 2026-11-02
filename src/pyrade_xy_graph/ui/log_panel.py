import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from pyrade_xy_graph.core.trace_level import TRACE
from pyrade_xy_graph.ui.style import SPACING

_LEVELS = [
    ('Trace', TRACE),
    ('Debug', logging.DEBUG),
    ('Info', logging.INFO),
    ('Warning', logging.WARNING),
    ('Error', logging.ERROR),
]


class _LogSignal(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    """
    logging.Handler that marshals records onto the GUI thread via a Qt
    signal - log calls can come from any thread (AcquisitionWorker,
    FileLoadWorker, or any other QThread in this app), and
    QPlainTextEdit isn't safe to touch off the GUI thread.
    """

    def __init__(self):
        super().__init__()
        self.signals = _LogSignal()

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.signals.message.emit(msg)


class LogPanel(QWidget):
    """
    Read-only, always-visible log view with a level selector
    (Trace/Debug/Info/Warning/Error). Trace is opt-in, not the default -
    it logs every sample as it arrives and would flood the panel during
    acquisition.
    """

    def __init__(self, parent=None, level=logging.DEBUG):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        # SPACING matches _titled()'s section header padding (ui/style.py)
        # so the "Log" title and "Level:" share a left edge.
        layout.setContentsMargins(SPACING, SPACING, SPACING, SPACING)
        layout.setSpacing(SPACING)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Level:"))
        self.level_combo = QComboBox()
        for name, value in _LEVELS:
            self.level_combo.addItem(name, value)
        self.level_combo.setCurrentIndex([v for _, v in _LEVELS].index(level))
        self.level_combo.currentIndexChanged.connect(self._on_level_changed)
        controls.addWidget(self.level_combo)
        controls.addStretch()
        layout.addLayout(controls)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumBlockCount(4000)
        layout.addWidget(self.text_edit)

        self.handler = QtLogHandler()
        self.handler.setLevel(level)
        self.handler.setFormatter(
            logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%H:%M:%S'))
        self.handler.signals.message.connect(self.text_edit.appendPlainText)

        self._attached_logger: logging.Logger | None = None

    def attach(self, logger: logging.Logger | None = None):
        """Adds the handler and raises the logger's effective level if
        needed - a logger left at a higher level would filter records
        out before the handler ever sees them."""
        logger = logger or logging.getLogger()
        self._attached_logger = logger
        if logger.level == logging.NOTSET or logger.level > self.handler.level:
            logger.setLevel(self.handler.level)
        logger.addHandler(self.handler)

    def _on_level_changed(self, index: int):
        level = self.level_combo.itemData(index)
        self.handler.setLevel(level)
        if self._attached_logger is not None and (
                self._attached_logger.level == logging.NOTSET or self._attached_logger.level > level):
            self._attached_logger.setLevel(level)
