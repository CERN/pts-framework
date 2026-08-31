# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Naming the files pypts writes.

This module used to decide *where* they went as well, by building a path under
`tempfile.gettempdir()`. It no longer does: the directory comes from the
configuration, and the caller passes it in. What is left here is the naming
convention and the mkdir, which is all this ever should have been.

The log file name still carries a timestamp taken when the function is called,
so it must be called exactly once per run - the launcher does that, and every
process is then given the resulting path.
"""

import os
from datetime import datetime
from pathlib import Path

#: Prefix of the run log file name. The rest is the timestamp.
LOG_FILE_PREFIX = "pypts"


def ensure_folder_exists(folder_path) -> None:
    """Create the folder, and its parents, if they are not there already."""
    os.makedirs(folder_path, exist_ok=True)


def get_log_file_path(logs_dir) -> str:
    """
    Full path of the log file for this run, creating its directory.

    Args:
        logs_dir: where run logs go - `paths.logs_dir` from the configuration.
            Passed in rather than looked up here, so that this module stays
            free of the configuration and remains usable by a standalone tool.

    Returns:
        The path, as a string, because that is what `logging.FileHandler` takes
        and what the launcher hands to the Logger process.
    """
    ensure_folder_exists(logs_dir)

    # Naive local time, deliberately: the Logger writes local time with no offset
    # and the Debug Monitor parses it back the same way, so a UTC file name would
    # be the one timestamp in the system that did not match the others.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
    return str(Path(logs_dir) / f"{LOG_FILE_PREFIX}_{timestamp}.log")
