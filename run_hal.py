# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Starts the HAL server with its monitor window on this machine's bench.

    python run_hal.py

It takes no arguments. It uses the bench file PyPTS uses - `bench.ini` beside `config.ini` -
created from the template when there is none yet, exactly as a PyPTS start does
(`pypts.config_handler.bench_config`), on the default port.

- No HAL answers: it starts one, detached, with its window (`python -m pyhal --bench FILE
  --window`, through `pyhal.start_hal(show_window=True)`), and returns. The HAL owns the window
  and keeps running when the window is closed; `python -m pyhal --stop` (or the window's Stop
  HAL) stops it.
- A HAL answers already: it only opens the monitor on it (`python -m pyhal.monitor`), in this
  process; closing the window leaves that HAL running.

The monitor never starts a HAL (user decision 2026-11-24; `pyhal/pyhal.md` -> *The monitor*).
A HAL without a window is `python -m pyhal --bench FILE`.

`src` is put on the path first, so this works from a checkout even where the package has not
been installed into the interpreter running it. This launcher may import `pypts`; the `pyhal`
package itself never does.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pyhal.__main__ import EXIT_BAD_BENCH, EXIT_OK  # noqa: E402 - needs the path set above
from pyhal.base_driver import DriverError  # noqa: E402 - needs the path set above
from pyhal.client import DEFAULT_PORT  # noqa: E402 - needs the path set above

#: The exit code for arguments given: the launcher takes none (argparse's usage-error code).
EXIT_USAGE = 2

#: The exit code when the HAL could not be started.
EXIT_START_FAILED = 1


def pypts_bench_path() -> str | None:
    """
    The path of PyPTS's bench.ini, created from the template when missing; None when it
    cannot be used (the reason has been printed).
    """
    from pypts.config_handler.bench_config import BenchOutcome, bench_config

    bench = bench_config()
    if bench.outcome is BenchOutcome.DISCARDED:
        print(f"The bench file cannot be used: {bench.problem}", file=sys.stderr)
        return None
    if bench.outcome is BenchOutcome.CREATED:
        print(f"No bench file was found; one was created from the template at {bench.path}.")
    devices = ", ".join(sorted(bench.devices)) or "none"
    print(f"Bench file {bench.path}, devices: {devices}.")
    return str(bench.path)


def running_hal_pid() -> int | None:
    """The pid of the HAL that answers on the default port; None when none answers."""
    from pyhal.monitor.link import MonitorLink

    link = MonitorLink(DEFAULT_PORT)
    try:
        report = link.status()
    finally:
        link.close()
    if report is None:
        return None
    return report.pid


def main(arguments: list[str]) -> int:
    if arguments:
        print(
            "run_hal.py takes no arguments; for a HAL without a window use "
            "python -m pyhal --bench FILE.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    bench = pypts_bench_path()
    if bench is None:
        return EXIT_BAD_BENCH
    pid = running_hal_pid()
    if pid is not None:
        print(
            f"A HAL server is already running on port {DEFAULT_PORT} (pid {pid}); "
            "opening its monitor."
        )
        from pyhal.monitor.__main__ import main as monitor_main

        return monitor_main([])
    from pyhal.client import start_hal

    try:
        pid = start_hal(bench, DEFAULT_PORT, show_window=True)
    except DriverError as exc:
        print(exc, file=sys.stderr)
        return EXIT_START_FAILED
    print(
        f"Started the HAL server on port {DEFAULT_PORT} (pid {pid}) with its window. "
        "It keeps running when the window is closed; stop it with python -m pyhal --stop."
    )
    return EXIT_OK


# The HAL runs in a process of its own (`python -m pyhal`, started by client.start_hal()), so
# its driver processes never import this file; the guard keeps an import (the tests) silent.
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
