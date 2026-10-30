"""The save helper the Recipe Creator and the Recipe Editor v2 share (rc_io)."""

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from pypts.helper_applications.recipe_creator.rc_io import save_recipe_text


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_save_writes_the_file_and_reports_success(qapp, tmp_path):
    path = tmp_path / "recipe.yml"
    assert save_recipe_text(None, str(path), "name: Saved\n") is True
    assert path.read_text(encoding="utf-8") == "name: Saved\n"


def test_a_failed_save_shows_the_dialog_and_reports_failure(qapp, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *args: seen.setdefault("dialog", args))
    )
    # The target is a directory, so the write itself fails.
    assert save_recipe_text(None, str(tmp_path), "name: Lost\n") is False
    assert "dialog" in seen
