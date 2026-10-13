"""The Recipe Creator's own log file and its handler for uncaught errors."""

import faulthandler
import logging
import subprocess
import sys
import textwrap

import pytest

from pypts.helper_applications.recipe_creator import rc_logging


@pytest.fixture
def creator_logging(tmp_path, monkeypatch):
    """start_logging() into tmp_path, undone afterwards: handlers, hooks, open file."""
    monkeypatch.setattr(rc_logging, "_reports_dir", lambda: tmp_path)
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    excepthook = sys.excepthook

    path = rc_logging.start_logging()
    yield path

    faulthandler.disable()
    if rc_logging._fault_file is not None:
        rc_logging._fault_file.close()
        rc_logging._fault_file = None
    sys.excepthook = excepthook
    for handler in list(root.handlers):
        root.removeHandler(handler)
        if handler not in handlers:
            handler.close()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


def _raise(error: Exception):
    """An exception with a real traceback, as excepthook receives it."""
    try:
        raise error
    except type(error):
        return sys.exc_info()


def test_the_log_file_is_named_after_the_creator(creator_logging, tmp_path):
    name = creator_logging.replace("\\", "/").rsplit("/", 1)[-1]
    assert name.startswith("recipe_creator_")
    assert name.endswith(".log")
    assert creator_logging.startswith(str(tmp_path))


def test_an_uncaught_error_is_logged_with_its_traceback(creator_logging, monkeypatch):
    shown = []
    monkeypatch.setattr(rc_logging.QMessageBox, "critical", lambda *args: shown.append(args))

    sys.excepthook(*_raise(TypeError("unhashable type: 'dict'")))

    for handler in logging.getLogger().handlers:
        handler.flush()
    with open(creator_logging, encoding="utf-8") as file:
        text = file.read()
    assert ";ERROR;" in text
    assert "unexpected error: unhashable type: 'dict'" in text
    assert "Traceback (most recent call last)" in text


def test_the_dialog_says_where_the_log_is(creator_logging, monkeypatch, qapp_for_dialog):
    shown = []
    monkeypatch.setattr(rc_logging.QMessageBox, "critical", lambda *args: shown.append(args))

    sys.excepthook(*_raise(ValueError("boom")))

    assert len(shown) == 1
    message = shown[0][2]
    assert "ValueError: boom" in message
    assert creator_logging in message


@pytest.fixture
def qapp_for_dialog():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_a_hard_crash_lands_in_the_log_file(tmp_path):
    # A real crash takes the interpreter with it, so it runs in its own process.
    script = textwrap.dedent(
        f"""
        import faulthandler
        from pathlib import Path
        from pypts.helper_applications.recipe_creator import rc_logging
        rc_logging._reports_dir = lambda: Path({str(tmp_path)!r})
        print(rc_logging.start_logging(), flush=True)
        faulthandler._sigsegv()
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode != 0, result.stderr
    log_path = result.stdout.strip().splitlines()[0]
    with open(log_path, encoding="utf-8") as file:
        text = file.read()
    assert "Fatal Python error" in text
