"""
The recipe-file save layer the Recipe Creator and the Recipe Editor v2 share.

One rule lives here: a save that fails changes nothing for the caller. The
helper reports the failure itself (log and dialog) and returns False, so the
window keeps its current file, clean mark and title exactly as they were —
only on True may it adopt the path it just wrote.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

log = logging.getLogger(__name__)


def save_recipe_text(parent: QWidget | None, path: str, text: str) -> bool:
    """Write a recipe's YAML to path; on failure show a dialog and return False."""
    try:
        Path(path).write_text(text, encoding="utf-8")
    except OSError as error:
        log.error("Recipe '%s' could not be saved: %s", path, error)
        log.debug("Traceback for the failed save:", exc_info=True)
        QMessageBox.critical(parent, "Save failed", str(error))
        return False
    return True
