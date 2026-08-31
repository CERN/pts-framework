# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Entry point: `python -m pypts.helper_applications.debug_monitor`.

With no argument it attaches to the newest run log in the configured log
directory, which is almost always the run you just started. Give it a path to
look at any other one, finished or not - the same code renders a live run and a
replay, because the only difference between them is whether the file is still
growing.

It never starts pypts. Attaching is a read of a file; there is nothing to
coordinate, nothing to shut down, and closing the Monitor mid-run cannot affect
the run.
"""

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from pypts.helper_applications.debug_monitor.log_source import (
    default_logs_dir,
    find_latest_log,
)
from pypts.helper_applications.debug_monitor.main_window import DebugMonitor

#: Returned when there is no log to attach to. Nothing was wrong with the
#: request, so it is not the same as a usage error.
NO_LOG_EXIT_CODE = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pypts.helper_applications.debug_monitor",
        description=(
            "Watch the messages, heartbeats and module liveness of a pypts run, "
            "by reading its run log. The run must have been started with "
            "--log-level DEBUG for the message trace to be in the log at all."
        ),
    )
    parser.add_argument(
        "log_file",
        nargs="?",
        default=None,
        help=(
            "Run log to read. Defaults to the most recently modified "
            "pypts_*.log in the configured log directory."
        ),
    )
    return parser


def resolve_log_file(argument: str | None) -> Path | None:
    """
    Which file to open: the one asked for, or the newest one there is.

    Returns None when nothing suitable exists, so the caller can say why rather
    than opening a window onto nothing.
    """
    if argument is not None:
        path = Path(argument)
        return path if path.is_file() else None

    return find_latest_log(default_logs_dir())


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    log_file = resolve_log_file(args.log_file)
    if log_file is None:
        if args.log_file is not None:
            print(f"No such log file: {args.log_file}", file=sys.stderr)
        else:
            print(
                f"No pypts_*.log found in {default_logs_dir()}.\n"
                "Start a run first:  python -m pypts --mode cli --log-level DEBUG",
                file=sys.stderr,
            )
        return NO_LOG_EXIT_CODE

    app = QApplication(sys.argv)
    monitor = DebugMonitor(log_file)
    monitor.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
