# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the launcher (src/pypts/launcher/startup.py).

Two groups. The first is the configuration notice - which of popup and banner
is chosen, and that a failing popup falls back instead of stopping the run. No
test opens a real QMessageBox: the box is behind `_open_message_box`, which
exists exactly so these tests can replace it.

The second is the shutdown, which is the ordering guarantee the whole exit
design rests on: CORE is *asked* before it is killed. `stop_core()` only calls
send/join/is_alive/terminate, so a stub with scripted `is_alive` answers
exercises both of its branches with no process anywhere near the test. Every
real timeout is monkeypatched small - the launcher's five seconds are for a
bench, not for a test suite.
"""

import logging
import queue
import sys

import pytest

from pypts.launcher import startup
from pypts.messages import QueueWrapper
from pypts.messages.core_hmi_communication import HmiStopped, ShutdownRequested


def test_cli_mode_prints_a_banner_instead_of_a_popup(capsys, monkeypatch):
    def fail_if_called(title, text, *, warning):
        raise AssertionError("CLI mode must not open a message box")

    monkeypatch.setattr(startup, "_open_message_box", fail_if_called)

    startup.show_config_popup("cli", "pypts configuration created", "the details", warning=False)

    printed = capsys.readouterr().out
    assert "PYPTS CONFIGURATION CREATED" in printed
    assert "the details" in printed


def test_a_failing_popup_falls_back_to_the_banner(capsys, monkeypatch):
    """A headless bench or CI has no display; the notice must not stop the run."""

    def broken_box(title, text, *, warning):
        raise RuntimeError("no display")

    monkeypatch.setattr(startup, "_open_message_box", broken_box)

    startup.show_config_popup("gui", "pypts configuration discarded", "the reason", warning=True)

    printed = capsys.readouterr().out
    assert "PYPTS CONFIGURATION DISCARDED" in printed
    assert "the reason" in printed


def test_gui_mode_uses_the_popup_and_skips_the_banner(capsys, monkeypatch):
    shown = []

    def record_box(title, text, *, warning):
        shown.append((title, text, warning))

    monkeypatch.setattr(startup, "_open_message_box", record_box)

    startup.show_config_popup("gui", "pypts configuration discarded", "the reason", warning=True)

    assert shown == [("pypts configuration discarded", "the reason", True)]
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------
# The multiprocessing start method
# --------------------------------------------------------------------------


class Abort(Exception):
    """Sentinel: stops main() the moment the pin and argparse are behind it."""


def test_main_pins_the_spawn_start_method_before_building_anything(monkeypatch):
    """
    Children are spawned on every platform, and the pin happens before the
    first Queue() - queues take the start method from the default context at
    call time, so a later pin would be too late. Bootstrap is replaced with a
    raise, which is how main() is stopped before it spawns anything real.
    """
    pinned = []

    def abort():
        raise Abort

    monkeypatch.setattr(sys, "argv", ["pypts"])
    monkeypatch.setattr(startup.ConfigHandler, "bootstrap", abort)
    monkeypatch.setattr(startup, "set_start_method", pinned.append)
    monkeypatch.setattr(startup, "get_start_method", lambda allow_none=False: "fork")

    with pytest.raises(Abort):
        startup.main()

    assert pinned == ["spawn"]

    # And again with spawn already in place: pinning twice is a RuntimeError,
    # so the guard - not force=True - is what makes a second call harmless.
    pinned.clear()
    monkeypatch.setattr(startup, "get_start_method", lambda allow_none=False: "spawn")

    with pytest.raises(Abort):
        startup.main()

    assert pinned == []


# --------------------------------------------------------------------------
# Shutdown
# --------------------------------------------------------------------------


class FakeProcess:
    """
    Everything stop_core() uses of a Process, and nothing else.

    `alive_answers` is the script for is_alive(), so a test says which branch it
    is exercising by whether CORE is still there when it is asked.
    """

    def __init__(self, alive_answers):
        self.alive_answers = list(alive_answers)
        self.joined = []
        self.terminated = False

    def join(self, timeout=None):
        self.joined.append(timeout)

    def is_alive(self):
        return self.alive_answers.pop(0)

    def terminate(self):
        self.terminated = True


def a_link_to_core():
    """The launcher's outbox to CORE, plus the queue behind it."""
    outbox: queue.Queue = queue.Queue()
    return QueueWrapper(outbox), outbox


def drain(a_queue):
    """Everything waiting on a queue right now, as a list."""
    messages = []
    while True:
        try:
            messages.append(a_queue.get_nowait())
        except queue.Empty:
            return messages


def test_stop_core_asks_before_terminating():
    """
    The order is the whole point: HmiStopped so CORE stops waiting for a
    frontend that has already gone, then ShutdownRequested, and only then a
    join. A CORE that leaves on its own is never terminated, which is what lets
    it finish writing the report and close the log.
    """
    to_core, sent = a_link_to_core()
    core_process = FakeProcess(alive_answers=[False])

    startup.stop_core(core_process, to_core)

    assert drain(sent) == [HmiStopped(), ShutdownRequested()]
    assert core_process.terminated is False
    assert len(core_process.joined) == 1


def test_stop_core_terminates_a_wedged_core(monkeypatch, caplog):
    """
    The other branch, and the reason the timeout exists: a CORE still alive
    after its budget is killed rather than left holding the launcher open.
    """
    monkeypatch.setattr(startup, "CORE_SHUTDOWN_TIMEOUT_S", 0.01)

    to_core, _sent = a_link_to_core()
    core_process = FakeProcess(alive_answers=[True])

    with caplog.at_level(logging.WARNING):
        startup.stop_core(core_process, to_core)

    assert core_process.terminated is True
    # Once waiting for the clean exit, once for the terminated process to go.
    assert len(core_process.joined) == 2
    assert [r for r in caplog.records if "terminating it" in r.getMessage()]


def test_stop_core_with_no_process_is_a_no_op():
    """
    CORE may never have been started - the config bootstrap can fail first - and
    the launcher's `finally` runs regardless. Sending into a queue nobody reads
    would be harmless; asking a None to join would not be.
    """
    to_core, sent = a_link_to_core()

    startup.stop_core(None, to_core)

    assert drain(sent) == []


def test_start_debug_monitor_gives_up_when_the_log_never_appears(
    tmp_path, monkeypatch, caplog
):
    """
    The Monitor exits on a path that is not yet a file, so the launcher waits
    for the Logger to create it - bounded, because the Monitor is a developer
    convenience and must never be able to hold up a run.
    """
    monkeypatch.setattr(startup, "MONITOR_LOG_WAIT_S", 0.1)

    def must_not_spawn(*args, **kwargs):
        raise AssertionError("the Monitor must not be started without its log")

    monkeypatch.setattr(startup.subprocess, "Popen", must_not_spawn)

    missing_log = tmp_path / "never_created.log"

    with caplog.at_level(logging.WARNING):
        monitor_process = startup.start_debug_monitor(str(missing_log), logging.DEBUG)

    assert monitor_process is None
    assert [r for r in caplog.records if "Debug Monitor not started" in r.getMessage()]
