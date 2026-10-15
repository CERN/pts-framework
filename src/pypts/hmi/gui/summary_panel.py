"""
SummaryPanel: the last run summed up, on the left pane's Summary tab (gui.md §14).

The step card and the Result tooltip already show every step's values, so this
page is about the run as a whole, in four cards:

  - Result: the run's verdict on its chip, the recipe and its version, the
    sequence, when it started and how long it took, the pypts version - and,
    for an engineering retest, that it wrote no report
  - Metrics: the verdict counts, the pass rate, the slowest steps
  - Failures: every FAIL and ERROR step with its reason; a click on one shows
    it on the Run tab, in the step card (`failure_clicked`)
  - Unit & report: the run's metadata (serial number, ...) and its files -
    the report, the CSV, the run log, the folder - each with an Open button
    (`open_requested`; the window opens it)

Before the first run it says so, with the loaded recipe. The state is a
RunRecord; this is only the view, redrawn by refresh().
"""

import html
import time
from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.gui.palette import UNKNOWN_VERDICT, get_palette
from pypts.hmi.gui.run_display import COUNT_ORDER
from pypts.hmi.gui.run_header import RUNNING_TEXT, elapsed_text
from pypts.hmi.gui.run_record import RunRecord
from pypts.messages.run_events import RecipeLoaded

NO_RUN_TEXT = "No run yet."
NO_RECIPE_TEXT = "Open a recipe and start a run: its summary appears here."
NO_FAILURES_TEXT = "No failures."
NO_TIMES_TEXT = "No step has finished yet."
NO_REPORT_TEXT = "Engineering retest: no report and no run folder were written."
REPORT_PENDING_TEXT = "The report is written when the run ends."

#: The run's files, in the order they are listed.
FILE_REPORT = "Report"
FILE_CSV = "Results (CSV)"
FILE_RUN_LOG = "Run log"
FILE_FOLDER = "Run folder"
FILES = (FILE_REPORT, FILE_CSV, FILE_RUN_LOG, FILE_FOLDER)

_RUNNING_CHIP = "RUNNING"
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class SummaryBadge(QLabel):
    """One count - `3  PASS` - on its verdict's colours."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = label
        self._bg = ""
        self._fg = ""
        self.update_count(0)

    def update_count(self, count: int) -> None:
        self.setText(f"<b style='font-size:16px'>{count}</b>&nbsp;&nbsp;{self._label}")

    def set_colors(self, bg: str, fg: str) -> None:
        self._bg = bg
        self._fg = fg
        self.setStyleSheet(
            f"background:{self._bg}; color:{self._fg}; border-radius:6px;"
            f" padding:6px 16px; font-size:11px; font-weight:600;"
        )


class _Card(QFrame):
    """A titled box on the page."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("summaryCard")
        self.title_label = QLabel(title)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(14, 12, 14, 12)
        self.column.setSpacing(6)
        self.column.addWidget(self.title_label)


class _FileRow:
    """One of the run's files: what it is, its name, and Open."""

    def __init__(self, grid: QGridLayout, row: int, name: str, on_open) -> None:
        self.name_label = QLabel(name)
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_button = QPushButton("Open")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(lambda _checked=False: on_open(self.path))
        self.path = ""
        grid.addWidget(self.name_label, row, 0)
        grid.addWidget(self.path_label, row, 1)
        grid.addWidget(self.open_button, row, 2)

    def set_path(self, path: str) -> None:
        """Shown by its last part, the whole path on hover; "" hides the row."""
        self.path = path
        shown = bool(path)
        self.name_label.setVisible(shown)
        self.path_label.setVisible(shown)
        self.open_button.setVisible(shown)
        if not shown:
            return
        # The last part, whichever separator the path uses.
        last = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        self.path_label.setText(last)
        self.path_label.setToolTip(path)
        self.open_button.setToolTip(f"Open {path}")


class SummaryPanel(QWidget):
    """The Summary tab. set_record() and refresh() draw it; it never changes the record."""

    #: A failure was clicked: the step's UUID.
    failure_clicked = Signal(object)
    #: An Open button was clicked: the file or folder's path.
    open_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._dark = False
        self._record: RunRecord | None = None
        self._recipe: RecipeLoaded | None = None

        # --- Before the first run
        self.empty_label = QLabel(NO_RUN_TEXT)
        self.empty_hint_label = QLabel(NO_RECIPE_TEXT)
        self.empty_hint_label.setWordWrap(True)

        # --- Result
        self.result_card = _Card("RESULT")
        self.verdict_label = QLabel()
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.no_report_label = QLabel(NO_REPORT_TEXT)
        self.no_report_label.setWordWrap(True)
        self.result_card.column.addWidget(self.verdict_label, alignment=Qt.AlignmentFlag.AlignLeft)
        self.result_card.column.addWidget(self.title_label)
        self.result_card.column.addWidget(self.details_label)
        self.result_card.column.addWidget(self.no_report_label)

        # --- Metrics
        self.metrics_card = _Card("METRICS")
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(8)
        self.badges = {}
        for result_type in COUNT_ORDER:
            badge = SummaryBadge(result_type.name)
            self.badges[result_type] = badge
            badge_row.addWidget(badge)
        self.total_badge = SummaryBadge("TOTAL")
        badge_row.addWidget(self.total_badge)
        badge_row.addStretch()
        self.metrics_card.column.addLayout(badge_row)
        self.pass_rate_label = QLabel()
        self.slowest_heading_label = QLabel("Slowest steps")
        self.slowest_label = QLabel()
        self.slowest_label.setTextFormat(Qt.TextFormat.RichText)
        self.metrics_card.column.addWidget(self.pass_rate_label)
        self.metrics_card.column.addWidget(self.slowest_heading_label)
        self.metrics_card.column.addWidget(self.slowest_label)

        # --- Failures
        self.failures_card = _Card("FAILURES")
        self.failures_label = QLabel()
        self.failures_label.setTextFormat(Qt.TextFormat.RichText)
        self.failures_label.setWordWrap(True)
        self.failures_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.failures_label.setToolTip("Click a step to show it on the Run tab.")
        self.failures_label.linkActivated.connect(self._failure_link)
        self.failures_card.column.addWidget(self.failures_label)

        # --- Unit & report
        self.report_card = _Card("UNIT & REPORT")
        self.metadata_label = QLabel()
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.report_pending_label = QLabel(REPORT_PENDING_TEXT)
        self.report_card.column.addWidget(self.metadata_label)
        files_grid = QGridLayout()
        files_grid.setContentsMargins(0, 0, 0, 0)
        files_grid.setHorizontalSpacing(12)
        files_grid.setColumnStretch(1, 1)
        self.files = {}
        for row, name in enumerate(FILES):
            self.files[name] = _FileRow(files_grid, row, name, self.open_requested.emit)
        self.report_card.column.addLayout(files_grid)
        self.report_card.column.addWidget(self.report_pending_label)

        page = QWidget()
        page_column = QVBoxLayout(page)
        page_column.setContentsMargins(0, 0, 8, 0)
        page_column.setSpacing(10)
        page_column.addWidget(self.empty_label)
        page_column.addWidget(self.empty_hint_label)
        for card in self._cards():
            page_column.addWidget(card)
        page_column.addStretch()

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(page)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.scroll_area)

        self.set_dark(False)

    def _cards(self) -> tuple[_Card, ...]:
        return (self.result_card, self.metrics_card, self.failures_card, self.report_card)

    # --- What it is given --------------------------------------------------------

    def set_recipe(self, recipe: RecipeLoaded | None) -> None:
        """The loaded recipe, named on the page before its first run."""
        self._recipe = recipe
        self.refresh()

    def set_record(self, record: RunRecord | None) -> None:
        """The run to sum up; None for no run."""
        self._record = record
        self.refresh()

    def record(self) -> RunRecord | None:
        return self._record

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        palette = get_palette(dark)
        for card in self._cards():
            card.setStyleSheet(
                f"QFrame#summaryCard {{ background:{palette.panel_background};"
                f" border:1px solid {palette.border}; border-radius:6px; }}"
                # The card's own background shows through its text.
                " QFrame#summaryCard QLabel { background:transparent; }"
            )
            card.title_label.setStyleSheet(
                f"font-size:11px; font-weight:600; color:{palette.section_label};"
            )
        self.empty_label.setStyleSheet(f"font-size:16px; font-weight:600; color:{palette.text};")
        self.empty_hint_label.setStyleSheet(f"font-size:12px; color:{palette.text_muted};")
        self.title_label.setStyleSheet(f"font-size:16px; font-weight:600; color:{palette.text};")
        for label in (self.details_label, self.pass_rate_label, self.metadata_label):
            label.setStyleSheet(f"font-size:12px; color:{palette.text};")
        for label in (self.slowest_heading_label, self.report_pending_label):
            label.setStyleSheet(f"font-size:11px; color:{palette.text_muted};")
        self.no_report_label.setStyleSheet(f"font-size:12px; color:{palette.text_muted};")
        for row in self.files.values():
            row.name_label.setStyleSheet(f"font-size:12px; color:{palette.text_muted};")
            row.path_label.setStyleSheet(f"font-size:12px; color:{palette.text};")
        for result_type, badge in self.badges.items():
            chip = palette.verdicts.get(result_type.name, UNKNOWN_VERDICT)
            badge.set_colors(chip.background, chip.text)
        # TOTAL is not a verdict, so it wears the highlight rather than a chip.
        self.total_badge.set_colors(palette.menu_highlight, palette.menu_highlight_text)
        # The chip, the slowest steps and the failures carry colours in their text.
        self.refresh()

    # --- Drawing -------------------------------------------------------------------

    def refresh(self) -> None:
        record = self._record
        has_run = record is not None
        self.empty_label.setVisible(not has_run)
        self.empty_hint_label.setVisible(not has_run)
        for card in self._cards():
            card.setVisible(has_run)
        if record is None:
            self.empty_hint_label.setText(self._recipe_text())
            return
        self._draw_result(record)
        self._draw_metrics(record)
        self._draw_failures(record)
        self._draw_report(record)

    def _recipe_text(self) -> str:
        recipe = self._recipe
        if recipe is None:
            return NO_RECIPE_TEXT
        title = recipe.recipe_name
        if recipe.recipe_version:
            title = f"{title} v{recipe.recipe_version}"
        count = len(recipe.sequences)
        if count == 1:
            sequences = "1 sequence"
        else:
            sequences = f"{count} sequences"
        return (
            f"Loaded {title} - {sequences}, main sequence {recipe.main_sequence}. "
            "Start a run: its summary appears here."
        )

    def _draw_result(self, record: RunRecord) -> None:
        palette = get_palette(self._dark)
        if record.result is None:
            text = RUNNING_TEXT
            key = _RUNNING_CHIP
        else:
            text = record.result.name
            key = record.result.name
        chip = palette.verdicts.get(key, UNKNOWN_VERDICT)
        self.verdict_label.setText(text)
        self.verdict_label.setStyleSheet(
            f"font-size:18px; font-weight:700; color:{chip.text};"
            f"background-color:{chip.background}; border-radius:6px; padding:4px 16px;"
        )
        title = record.recipe_name
        if record.recipe_version:
            title = f"{title} v{record.recipe_version}"
        self.title_label.setText(title)

        lines = []
        if record.sequence_name:
            lines.append(f"Sequence: {record.sequence_name}")
        started = record.started_wall.strftime(_TIME_FORMAT)
        if record.result is None:
            lines.append(f"Started {started} · still running")
        else:
            took = elapsed_text(record.duration(time.monotonic()))
            lines.append(f"Started {started} · took {took}")
        if record.pypts_version:
            lines.append(f"pypts {record.pypts_version}")
        self.details_label.setText("\n".join(lines))
        self.no_report_label.setVisible(not record.write_report)

    def _draw_metrics(self, record: RunRecord) -> None:
        counts = record.counts()
        for result_type, badge in self.badges.items():
            count = counts.get(result_type, 0)
            badge.update_count(count)
            badge.setVisible(count > 0)
        self.total_badge.update_count(len(record.outcomes))

        rate = record.pass_rate_text()
        self.pass_rate_label.setText(rate)
        self.pass_rate_label.setVisible(bool(rate))

        palette = get_palette(self._dark)
        slowest = record.slowest()
        if not slowest:
            self.slowest_label.setText(
                f'<span style="color:{palette.text_muted};">{NO_TIMES_TEXT}</span>'
            )
            return
        rows = []
        for step_time in slowest:
            rows.append(
                "<tr>"
                f'<td style="color:{palette.text};">{html.escape(step_time.step_name)}</td>'
                f'<td style="color:{palette.text_muted};" align="right">'
                f"&nbsp;&nbsp;{elapsed_text(step_time.seconds)}</td>"
                "</tr>"
            )
        self.slowest_label.setText(
            '<table cellspacing="0" cellpadding="2">' + "".join(rows) + "</table>"
        )

    def _draw_failures(self, record: RunRecord) -> None:
        palette = get_palette(self._dark)
        failures = record.failures()
        if not failures:
            self.failures_label.setText(
                f'<span style="color:{palette.text_muted};">{NO_FAILURES_TEXT}</span>'
            )
            return
        lines = []
        for outcome in failures:
            chip = palette.verdicts.get(outcome.result.name, UNKNOWN_VERDICT)
            line = (
                f'<span style="background-color:{chip.background}; color:{chip.text};'
                f' font-weight:600;">&nbsp;{outcome.result.name}&nbsp;</span> '
                f'<a href="{outcome.step_id}" style="color:{palette.accent_text};">'
                f"{html.escape(outcome.step_name)}</a>"
            )
            if outcome.error_info:
                reason = html.escape(outcome.error_info).replace("\n", "<br>")
                line += f'<br><span style="color:{palette.danger};">{reason}</span>'
            lines.append(line)
        self.failures_label.setText("<br><br>".join(lines))

    def _draw_report(self, record: RunRecord) -> None:
        if record.metadata:
            lines = [f"{name}: {value}" for name, value in record.metadata.items()]
            self.metadata_label.setText("\n".join(lines))
        self.metadata_label.setVisible(bool(record.metadata))

        self.files[FILE_REPORT].set_path(record.report_path)
        self.files[FILE_CSV].set_path(record.csv_path())
        self.files[FILE_RUN_LOG].set_path(record.run_log_path)
        self.files[FILE_FOLDER].set_path(record.run_folder())
        waiting = record.write_report and not record.report_path
        self.report_pending_label.setVisible(waiting)
        # An engineering retest with no metadata has nothing to show here.
        has_content = bool(record.metadata) or record.write_report or bool(record.run_log_path)
        self.report_card.setVisible(has_content)

    def _failure_link(self, link: str) -> None:
        self.failure_clicked.emit(UUID(link))
