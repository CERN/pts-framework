# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the CLI HMI (src/pypts/hmi/cli/).

The CLI runs in the launcher process; only the GUI keeps a process boundary.
"""

import queue
import threading
import time

from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_communication import LoadRecipe, ShutdownRequested, StartSequence
from pypts.messages.run_events import StopSequence


def test_known_commands_are_dispatched_to_core(monkeypatch):
    """Each shell verb sends its message; `stop_sequence` aborts the run while
    plain `stop` stays an exit alias."""
    from pypts.hmi.cli.cli import CLI

    outbox: queue.Queue = queue.Queue()
    inbox: queue.Queue = queue.Queue()
    cli = CLI(QueueWrapper(outbox), QueueWrapper(inbox))

    lines = iter(
        [
            "load_recipe recipes/wait_recipe.yml",
            "start_sequence Main",
            "stop_sequence",
            "exit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(lines))
    cli._command_loop()

    sent = []
    while True:
        try:
            sent.append(outbox.get_nowait())
        except queue.Empty:
            break
    assert sent == [
        LoadRecipe(recipe_path="recipes/wait_recipe.yml"),
        StartSequence(sequence_name="Main"),
        StopSequence(),
        ShutdownRequested(),
    ]


def test_stop_from_core_ends_the_cli_without_waiting_for_input(monkeypatch):
    """
    The operator is at the prompt and types nothing. CORE sends StopHmi - the
    application is shutting down, or the engine went quiet - and the shell must
    end on its own. It used to sit in input() until the next Enter.
    """
    from pypts.hmi.cli.cli import CLI
    from pypts.messages.core_hmi_communication import HmiStopped, StopHmi

    outbox: queue.Queue = queue.Queue()
    inbox: queue.Queue = queue.Queue()
    cli = CLI(QueueWrapper(outbox), QueueWrapper(inbox))

    never_typed = threading.Event()
    monkeypatch.setattr("builtins.input", lambda prompt: never_typed.wait() or "")

    inbox.put(StopHmi())
    # What the polling thread does, a moment after the prompt is up.
    threading.Timer(0.2, cli.poll_core).start()

    started = time.monotonic()
    cli._command_loop()
    elapsed = time.monotonic() - started
    never_typed.set()

    assert cli.running is False
    assert elapsed < 2.0
    assert HmiStopped() in [outbox.get_nowait() for _ in range(outbox.qsize())]


def test_nothing_is_read_after_exit(monkeypatch):
    """The reader asks for a line only when the shell is ready for one."""
    from pypts.hmi.cli.cli import CLI

    cli = CLI(QueueWrapper(queue.Queue()), QueueWrapper(queue.Queue()))
    asked = []

    def typed(prompt):
        asked.append(prompt)
        return "exit"

    monkeypatch.setattr("builtins.input", typed)

    cli._command_loop()
    time.sleep(0.3)

    assert asked == ["pypts> "]


def test_report_ready_is_printed_with_its_path(capsys):
    """The CLI has no button; the path on the console is its whole feature."""
    from pypts.hmi.cli.cli import CLI
    from pypts.messages.core_hmi_communication import ReportReady

    cli = CLI(QueueWrapper(queue.Queue()), QueueWrapper(queue.Queue()))

    cli.handle_core_message(
        ReportReady(report_path="/runs/run_1/report.html", report_dir="/runs/run_1")
    )

    printed = capsys.readouterr().out
    assert "/runs/run_1/report.html" in printed


def test_a_finished_step_prints_its_inputs_and_outputs(capsys):
    """A PASS says what was measured too, not only a FAIL (M-3)."""
    from uuid import uuid4

    from pypts.hmi.cli.cli import CLI
    from pypts.messages.common_messages import ResultType, StepOutcome
    from pypts.messages.run_events import StepFinished

    cli = CLI(QueueWrapper(queue.Queue()), QueueWrapper(queue.Queue()))

    cli.handle_core_message(
        StepFinished(
            outcome=StepOutcome(
                step_id=uuid4(),
                step_name="Measure voltage",
                result=ResultType.PASS,
                inputs=(("channel", "1"),),
                outputs=(("voltage", "12.1"),),
                expectations=(("voltage", "range 11 .. 13"),),
            )
        )
    )

    printed = capsys.readouterr().out
    assert "Measure voltage: PASS" in printed
    assert "inputs: channel = 1" in printed
    assert "outputs: voltage = 12.1 (range 11 .. 13)" in printed
