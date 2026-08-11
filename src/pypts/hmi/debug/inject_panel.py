# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Building messages and putting them on the wire.

Two halves, because the two things a developer does here are different in kind.
The curated buttons are the handful of moves worth one click - above all
"simulate a run", which is the only way to see a run at all until the engine is
ported. The generic form below them reaches every other message that exists,
without anybody having to maintain a list.

Nothing here draws results. An injected message is sent and then observed in the
Trace tab like any other, which is deliberate: if a simulated StepFinished did
not come back through CORE and the console's own HmiClient handler, it would
prove nothing about either.
"""

from typing import get_args
from uuid import uuid4

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pypts.hmi.debug import icons
from pypts.hmi.debug.icons import label
from pypts.hmi.debug.message_forms import MessageForm
from pypts.messages.common import ErrorSeverity, ModuleError, ResultType, StepOutcome
from pypts.messages.debug_link import (
    CORE_TO_HMI,
    CORE_TO_REPORT,
    CORE_TO_SEQUENCER,
    HMI_TO_CORE,
    REPORT_TO_CORE,
    SEQUENCER_TO_CORE,
    InjectTarget,
)
from pypts.messages.hmi_link import CoreToHmi, HmiToCore
from pypts.messages.report_link import CoreToReport, ReportGenerated, ReportToCore
from pypts.messages.run_events import (
    RunFinished,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    SerialNumberRequest,
    StepFinished,
    StepStarted,
    UserPromptRequest,
)
from pypts.messages.sequencer_link import CoreToSequencer, SequencerToCore, StopSequence

#: Every link, with the union it carries and how the console reaches it. A link
#: whose target is None is the console's own outbox: it *is* the HMI, so it
#: sends those itself rather than asking CORE to do it.
LINKS = {
    HMI_TO_CORE: (HmiToCore, None),
    CORE_TO_HMI: (CoreToHmi, InjectTarget.TO_HMI),
    CORE_TO_SEQUENCER: (CoreToSequencer, InjectTarget.TO_SEQUENCER),
    SEQUENCER_TO_CORE: (SequencerToCore, InjectTarget.FROM_SEQUENCER),
    CORE_TO_REPORT: (CoreToReport, InjectTarget.TO_REPORT),
    REPORT_TO_CORE: (ReportToCore, InjectTarget.FROM_REPORT),
}

#: The steps a simulated run walks through. Named after real bench operations so
#: that a screenshot of the console looks like the thing being built.
SIMULATED_STEPS = ("Power on", "Measure Vout", "Measure Iout", "Thermal soak", "Power off")

#: Milliseconds between the events of a simulated run. Fast enough not to wait,
#: slow enough that the trace scrolls the way a real run would rather than
#: arriving as one indistinguishable block.
SIMULATION_INTERVAL_MS = 300


class InjectPanel(QWidget):
    """
    Attributes:
        client: the DebugConsole. Used for send_as_hmi() and inject(), which are
            the only two ways anything leaves this panel.
    """

    def __init__(self, client, parent=None) -> None:
        super().__init__(parent)
        self.client = client

        #: Queued events of a running simulation, drained by _timer. Held as a
        #: list rather than fired in a loop so that a simulated run unfolds over
        #: time - the whole point is to watch it arrive.
        self._pending: list[tuple[InjectTarget, object]] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fire_next)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_curated())
        layout.addWidget(self._build_generic(), stretch=1)

    # --- Curated -------------------------------------------------------------

    def _build_curated(self) -> QWidget:
        box = QGroupBox("Common actions")
        grid = QGridLayout(box)

        self.recipe_path = QLineEdit("resources/recipes/example.yaml")
        self.sequence_name = QLineEdit("main")

        grid.addWidget(QLabel("Recipe path"), 0, 0)
        grid.addWidget(self.recipe_path, 0, 1, 1, 2)
        grid.addWidget(self._button("Load recipe", self._load_recipe), 0, 3)

        grid.addWidget(QLabel("Sequence"), 1, 0)
        grid.addWidget(self.sequence_name, 1, 1, 1, 2)
        grid.addWidget(self._button("Start sequence", self._start_sequence), 1, 3)

        # Labelled with the outcome each one produces, so the palette can be
        # scanned for "the one that breaks something" without reading it.
        buttons = [
            (label(icons.OK, "Simulate passing run"), self._simulate_pass),
            (label(icons.ERROR, "Simulate failing run"), self._simulate_fail),
            (label(icons.OK, "Step PASS"), lambda: self._one_step(ResultType.PASS)),
            (label(icons.ERROR, "Step FAIL"), lambda: self._one_step(ResultType.FAIL)),
            (label("❓", "Ask serial number"), self._ask_serial),
            (label("❓", "Ask user prompt"), self._ask_prompt),
            (label(icons.WARNING, "WARNING error"), lambda: self._error(ErrorSeverity.WARNING)),
            (label("🛑", "CRITICAL error"), lambda: self._error(ErrorSeverity.CRITICAL)),
            (label("📄", "Report generated"), self._report_generated),
            (label(icons.STOPPED, "Stop sequence"), self._stop_sequence),
            (label(icons.STOPPED, "Request shutdown"), self.client.request_shutdown),
        ]
        for offset, (text, slot) in enumerate(buttons):
            grid.addWidget(self._button(text, slot), 2 + offset // 4, offset % 4)
        return box

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    # --- Curated actions -----------------------------------------------------

    def _load_recipe(self) -> None:
        self.client.load_recipe(self.recipe_path.text().strip())

    def _start_sequence(self) -> None:
        self.client.start_sequence(self.sequence_name.text().strip())

    def _one_step(self, result: ResultType) -> None:
        """One StepStarted/StepFinished pair, as the Sequencer would send them."""
        step_id = uuid4()
        name = "Ad-hoc step"
        self._enqueue(
            [
                (InjectTarget.FROM_SEQUENCER, StepStarted(step_id=step_id, step_name=name)),
                (
                    InjectTarget.FROM_SEQUENCER,
                    StepFinished(
                        outcome=StepOutcome(
                            step_id=step_id,
                            step_name=name,
                            result=result,
                            error_info="simulated failure" if result is ResultType.FAIL else "",
                        )
                    ),
                ),
            ]
        )

    def _simulate_pass(self) -> None:
        self._enqueue(self._run_events(failing_step=None))

    def _simulate_fail(self) -> None:
        # The third step, so that the run has both a history behind the failure
        # and steps after it - which is where result aggregation gets decided.
        self._enqueue(self._run_events(failing_step=2))

    def _run_events(self, failing_step: int | None) -> list[tuple[InjectTarget, object]]:
        """
        A whole run, as the Sequencer will emit it once Phase 1 lands.

        The aggregate result follows the rule ResultType's integer order encodes
        and old_code aggregated by: the worst outcome wins.
        """
        events: list[tuple[InjectTarget, object]] = [
            (
                InjectTarget.FROM_SEQUENCER,
                RunStarted(recipe_name="simulated_recipe", recipe_description="Injected by the debug console"),
            ),
            (InjectTarget.FROM_SEQUENCER, SequenceStarted(sequence_name="main")),
        ]

        outcomes = []
        for position, name in enumerate(SIMULATED_STEPS):
            step_id = uuid4()
            result = ResultType.FAIL if position == failing_step else ResultType.PASS
            outcome = StepOutcome(
                step_id=step_id,
                step_name=name,
                result=result,
                error_info="measured 4.31 V, limit 4.50-5.50 V" if result is ResultType.FAIL else "",
            )
            outcomes.append(outcome)
            events.append((InjectTarget.FROM_SEQUENCER, StepStarted(step_id=step_id, step_name=name)))
            events.append((InjectTarget.FROM_SEQUENCER, StepFinished(outcome=outcome)))

        overall = max(outcome.result for outcome in outcomes)
        events.append((InjectTarget.FROM_SEQUENCER, SequenceFinished(sequence_name="main", result=overall)))
        events.append((InjectTarget.FROM_SEQUENCER, RunFinished(result=overall, outcomes=tuple(outcomes))))
        return events

    def _ask_serial(self) -> None:
        self._enqueue([(InjectTarget.FROM_SEQUENCER, SerialNumberRequest(request_id=uuid4()))])

    def _ask_prompt(self) -> None:
        self._enqueue(
            [
                (
                    InjectTarget.FROM_SEQUENCER,
                    UserPromptRequest(
                        request_id=uuid4(),
                        message="Connect the load and confirm.",
                        options=("Connected", "Skip", "Abort"),
                    ),
                )
            ]
        )

    def _error(self, severity: ErrorSeverity) -> None:
        self._enqueue(
            [
                (
                    InjectTarget.FROM_SEQUENCER,
                    ModuleError(
                        source="pypts.sequencer.sequencer",
                        severity=severity,
                        message=f"Simulated {severity.name.lower()} from the debug console",
                        exception="RuntimeError('simulated')",
                        traceback=None,
                    ),
                )
            ]
        )

    def _report_generated(self) -> None:
        self._enqueue(
            [(InjectTarget.FROM_REPORT, ReportGenerated(report_path="C:/tmp/simulated_report.html"))]
        )

    def _stop_sequence(self) -> None:
        self._enqueue([(InjectTarget.TO_SEQUENCER, StopSequence())])

    # --- Firing --------------------------------------------------------------

    def _enqueue(self, events: list[tuple[InjectTarget, object]]) -> None:
        """
        Queue events and start firing.

        Appending rather than replacing means pressing a button twice runs the
        second batch after the first instead of losing it - which also makes
        "simulate two runs back to back" possible without any extra machinery.
        """
        self._pending.extend(events)
        if not self._timer.isActive():
            # Fire the first immediately; a button that does nothing for a third
            # of a second feels broken.
            self._fire_next()
            self._timer.start(SIMULATION_INTERVAL_MS)

    def _fire_next(self) -> None:
        if not self._pending:
            self._timer.stop()
            return
        target, message = self._pending.pop(0)
        self.client.inject(target, message)

    # --- Generic form --------------------------------------------------------

    def _build_generic(self) -> QWidget:
        box = QGroupBox("Any message")
        outer = QVBoxLayout(box)

        chooser = QHBoxLayout()
        self.link_choice = QComboBox()
        self.link_choice.addItems(LINKS)
        self.message_choice = QComboBox()
        chooser.addWidget(QLabel("Link"))
        chooser.addWidget(self.link_choice, stretch=1)
        chooser.addWidget(QLabel("Message"))
        chooser.addWidget(self.message_choice, stretch=1)
        outer.addLayout(chooser)

        # The form is rebuilt on every choice, so it lives alone in a container
        # whose contents can be thrown away wholesale.
        self._form_host = QWidget()
        self._form_layout = QVBoxLayout(self._form_host)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._form_host)
        outer.addWidget(scroll, stretch=1)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._send_generic)
        outer.addWidget(self.send_button)

        self.link_choice.currentTextChanged.connect(self._rebuild_message_choices)
        self.message_choice.currentIndexChanged.connect(self._rebuild_form)
        self._rebuild_message_choices(self.link_choice.currentText())
        return box

    def _rebuild_message_choices(self, link: str) -> None:
        union, _ = LINKS[link]
        self._message_types = list(get_args(union))
        self.message_choice.clear()
        self.message_choice.addItems(t.__name__ for t in self._message_types)

    def _rebuild_form(self) -> None:
        while self._form_layout.count():
            item = self._form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        index = self.message_choice.currentIndex()
        if index < 0:
            return

        self._form = MessageForm(self._message_types[index])
        self._form_layout.addWidget(self._form.widget)
        self._form_layout.addStretch(1)

        # A form that cannot build every required field must not offer to send:
        # a message built from a partial form would misrepresent what was sent.
        blocked = bool(self._form.problems)
        self.send_button.setEnabled(not blocked)
        self.send_button.setText("Send" if not blocked else "; ".join(self._form.problems))

    def _send_generic(self) -> None:
        link = self.link_choice.currentText()
        _, target = LINKS[link]
        message = self._form.build()
        if target is None:
            self.client.send_as_hmi(message)
        else:
            self.client.inject(target, message)
