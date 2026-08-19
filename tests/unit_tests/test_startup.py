# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the launcher's configuration notice (src/pypts/launcher/startup.py).

Only the notice plumbing is tested here - which of popup and banner is chosen,
and that a failing popup falls back instead of stopping the run. No test opens
a real QMessageBox: the box is behind `_open_message_box`, which exists exactly
so these tests can replace it.
"""

from pypts.launcher import startup


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
