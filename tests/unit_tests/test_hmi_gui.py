# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the GUI HMI (src/pypts/hmi/gui/).

GUI tests need a display. On a headless machine (and on the GitLab runner) set
QT_QPA_PLATFORM=offscreen; adding that to CI is an existing TODO. pytest-qt is
already a test dependency.

The GUI holds a QWidget rather than inheriting from one. That is not a style
choice: PySide6's QWidget.__init__ cooperatively calls the next __init__ in the
MRO, so `class GUI(QWidget, HmiClient)` would call HmiClient.__init__ with no
arguments and fail at construction.

What is *not* tested here is the message handling, because the GUI does not
implement any: it inherits the whole protocol from HmiClient, and
test_messages.py asserts that both frontends leave it inherited. These tests
cover the presentation half only.
"""

import queue

import pytest

from pypts.messages import QueueWrapper
from pypts.messages.common import ErrorSeverity, ModuleError
from pypts.messages.core_hmi_link import (
    HmiStopped,
    ModuleErrorReported,
    ShutdownRequested,
    StatusChanged,
    StopHmi,
)

PLACEHOLDER = "placeholder - test not implemented yet"

pytest.importorskip("PySide6", reason="the GUI is an optional extra")


@pytest.fixture
def gui(qapp):
    """A constructed GUI with both channels wired to plain queues.

    `qapp` comes from pytest-qt and gives the widget the QApplication it needs.
    Yields (gui, outbox, inbox) where outbox holds what the GUI sent to CORE.
    """
    from pypts.hmi.gui.gui import GUI

    outbox: queue.Queue = queue.Queue()
    inbox: queue.Queue = queue.Queue()
    instance = GUI(QueueWrapper(outbox), QueueWrapper(inbox))
    yield instance, outbox, QueueWrapper(inbox)
    instance.timer.stop()
    instance.window.close()


def test_gui_starts_offscreen(gui):
    """Construction alone is worth asserting - it is where the MRO trap fires."""
    instance, _outbox, _inbox = gui
    instance.show()

    assert instance.window.isVisible()
    assert instance.status_label.text() == "Status: Idle"


def test_status_label_follows_update_status_events(gui):
    instance, _outbox, inbox = gui

    inbox.send(StatusChanged(text="Running Main"))
    instance.poll_core()

    assert instance.status_label.text() == "Status: Running Main"


def test_module_errors_are_shown_to_the_operator(gui):
    """Before ModuleErrorReported existed, an error could only reach the log file."""
    instance, _outbox, inbox = gui

    inbox.send(
        ModuleErrorReported(
            error=ModuleError(
                source="pypts.sequencer.sequencer",
                severity=ErrorSeverity.ERROR,
                message="instrument did not respond",
            )
        )
    )
    instance.poll_core()

    assert "instrument did not respond" in instance.status_label.text()


def test_stop_button_asks_core_to_shut_down(gui):
    """The button asks; it does not leave.

    A frontend that stopped itself would orphan the Sequencer and the Report,
    which is what used to happen when the window was simply closed.
    """
    instance, outbox, _inbox = gui

    instance.request_shutdown()

    assert isinstance(outbox.get_nowait(), ShutdownRequested)
    assert instance.running is True


def test_stop_from_core_closes_the_window_and_acknowledges(gui):
    """The GUI half of the shutdown handshake CORE waits for."""
    instance, outbox, inbox = gui
    instance.show()

    inbox.send(StopHmi())
    instance.poll_core()

    assert instance.running is False
    assert not instance.window.isVisible()
    assert isinstance(outbox.get_nowait(), HmiStopped)


@pytest.mark.skip(reason=PLACEHOLDER)
def test_gui_survives_an_engine_crash_and_reports_it():
    """The reason the GUI keeps its own process."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_widgets_are_resolved_by_step_or_stream_type():
    """"Widgets can be expanded, but the GUI implementation stays the same"."""
    ...


@pytest.mark.skip(reason=PLACEHOLDER)
def test_view_refreshes_on_every_event():
    """Known bug in TODO.txt: the GUI does not always refresh properly."""
    ...
