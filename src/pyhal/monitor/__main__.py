"""
Starts the HAL monitor window.

    python -m pyhal.monitor                      # the HAL on the default port
    python -m pyhal.monitor --port 29600
    python -m pyhal.monitor --bench bench.ini    # Start HAL serves this bench file
    python -m pyhal.monitor --bench bench.ini --log-dir logs --log-level TRACE
    python -m pyhal.monitor --bench bench.ini --serve   # start or attach; closing stops the HAL
    python -m pyhal.monitor --bench bench.ini --serve --exit-with-hal --nonce N   # connect()'s

Without `--bench` the window works the same, but Start HAL stays disabled. `--log-dir` and
`--log-level` (as `python -m pyhal` parses it: a number or a name, TRACE included) are those of
a HAL that Start HAL starts. `--serve` (needs `--bench`) makes the window own the HAL: it
starts one when none answers, and closing the window stops it (`window.py`, *Serve mode*).
`--nonce` (needs `--serve`) is the start nonce of the HAL the window starts, and
`--exit-with-hal` (needs `--serve`) closes the window once the HAL it has seen is gone, with no
Stop: what `pyhal.connect(show_window=True)` starts. The window is always light, whatever the
system's colour scheme.
"""

import argparse
import logging
import sys
from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from pyhal.__main__ import _log_level_argument
from pyhal.client import DEFAULT_PORT
from pyhal.monitor.window import MonitorWindow


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pyhal.monitor",
        description="A window that shows a running HAL server's status.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"the HAL's port (default {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--bench", metavar="FILE", help="the bench file Start HAL serves; without it, no Start"
    )
    parser.add_argument(
        "--log-dir", metavar="DIR", help="the log folder of a HAL that Start HAL starts"
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        type=_log_level_argument,
        default=None,
        help="the log level of a HAL that Start HAL starts: a number or a name, TRACE included",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="start a HAL on --bench when none answers; closing the window stops the HAL",
    )
    parser.add_argument(
        "--nonce",
        metavar="TEXT",
        help="with --serve: the start nonce of the HAL the window starts (set by a client)",
    )
    parser.add_argument(
        "--exit-with-hal",
        action="store_true",
        help="with --serve: close the window, stopping nothing, once the HAL has gone",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    if arguments.serve and not arguments.bench:
        parser.error("--serve needs --bench")
    if arguments.nonce is not None and not arguments.serve:
        parser.error("--nonce needs --serve")
    if arguments.exit_with_hal and not arguments.serve:
        parser.error("--exit-with-hal needs --serve")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
    # Light, also when Windows is in dark mode (user decision 2026-11-23).
    QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)
    window = MonitorWindow(
        arguments.port,
        bench=arguments.bench,
        log_dir=arguments.log_dir,
        serve=arguments.serve,
        log_level=arguments.log_level,
        nonce=arguments.nonce,
        exit_with_hal=arguments.exit_with_hal,
    )
    window.show()
    exit_code = app.exec()
    # The window is gone: a Close all or Stop still running is carried out to its end, then
    # the closing worker ends the log tail and the link; in serve mode the HAL is stopped,
    # unless the window closed because the HAL had gone (--exit-with-hal).
    window.wait_before_exit()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
