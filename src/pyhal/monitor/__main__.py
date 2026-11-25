"""
Starts the HAL monitor window.

    python -m pyhal.monitor                      # the HAL on the default port
    python -m pyhal.monitor --port 29600
    python -m pyhal.monitor --exit-with-hal      # what `python -m pyhal --window` opens

The window only connects to a HAL on the port: it never starts one (user decision
2026-11-24). With no HAL answering it shows *not reachable* and keeps polling. A HAL with its
window is `python -m pyhal --bench FILE --window`, or `python run_hal.py` from a checkout.
`--exit-with-hal` closes the window once the HAL it has seen is gone (`window.py`, *Exit with
the HAL*). The window is always light, whatever the system's colour scheme.
"""

import argparse
import logging
import sys
from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

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
        "--exit-with-hal",
        action="store_true",
        help="close the window once the HAL it has seen is gone",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
    # Light, also when Windows is in dark mode (user decision 2026-11-23).
    QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)
    window = MonitorWindow(arguments.port, exit_with_hal=arguments.exit_with_hal)
    window.show()
    exit_code = app.exec()
    # The window is gone: a Close all or Stop still running is carried out to its end, then
    # the closing worker ends the log tail and the link. The HAL is left as it is.
    window.wait_before_exit()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
