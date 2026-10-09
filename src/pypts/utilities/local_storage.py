# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Naming the files pypts writes.

This module used to decide *where* they went as well, by building a path under
`tempfile.gettempdir()`. It no longer does: the directory comes from the
configuration, and the caller passes it in. What is left here is the naming
convention and the mkdir, which is all this ever should have been.

The log file name still carries a timestamp taken when the function is called.
The launcher calls get_log_file_path() once at startup, in the reports folder,
and hands the result to every process; the GUI calls next_log_file_path() when
the operator unloads the recipe and the session log carries on in a new file.
The Sequencer calls make_run_folder() and get_log_file_path() at the start of
every run, for the run's own folder and the run log inside it.
"""

import os
import time
from datetime import datetime
from pathlib import Path

#: Prefix of the run log file name. The rest is the timestamp.
LOG_FILE_PREFIX = "pypts"


def ensure_folder_exists(folder_path) -> None:
    """Create the folder, and its parents, if they are not there already."""
    os.makedirs(folder_path, exist_ok=True)


def get_log_file_path(folder) -> str:
    """
    Full path of the log file for this run, creating its directory.

    Args:
        folder: where the log goes - `paths.reports_dir` for the session log,
            a run folder for a run log.
            Passed in rather than looked up here, so that this module stays
            free of the configuration and remains usable by a standalone tool.

    Returns:
        The path, as a string, because that is what `logging.FileHandler` takes
        and what the launcher hands to the Logger process.
    """
    ensure_folder_exists(folder)

    # Naive local time, deliberately: the Logger writes local time with no offset,
    # so a UTC file name would be the one timestamp in the system that did not
    # match the others.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
    return str(Path(folder) / f"{LOG_FILE_PREFIX}_{timestamp}.log")


def safe_name_part(value: str) -> str:
    """One folder-name component: alphanumerics kept, everything else an underscore."""
    return "".join(c if c.isalnum() else "_" for c in value)[:60]


def make_run_folder(reports_dir, recipe_name: str) -> Path:
    """
    Create one run's folder: <reports_dir>/<YYYYmmdd_HHMMSS>_<recipe name>.

    A second run in the same second gets `_2`, `_3`... The folder holds the
    run's report.csv, report.html and run log, and keeps this name.

    Raises:
        OSError: the folder cannot be created.
    """
    safe_name = safe_name_part(recipe_name)
    if not safe_name:
        safe_name = "recipe"
    base = time.strftime("%Y%m%d_%H%M%S", time.localtime()) + "_" + safe_name
    run_dir = Path(reports_dir) / base
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = Path(reports_dir) / f"{base}_{suffix}"
    run_dir.mkdir(parents=True)
    return run_dir


def next_log_file_path(current_log_file_path) -> str:
    """
    A new run log beside the current one, for the run log to carry on in.

    The name is get_log_file_path()'s. Within the same second as the current
    file, or as any file already there, `_2`, `_3`... is added: the new file
    must be a new file, or the Logger would simply append to the old one.
    """
    current = Path(current_log_file_path)
    base = Path(get_log_file_path(current.parent))
    candidate = base
    counter = 2
    while candidate == current or candidate.exists():
        candidate = base.with_name(f"{base.stem}_{counter}{base.suffix}")
        counter += 1
    return str(candidate)
