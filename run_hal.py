# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Opens the HAL monitor window on this machine's bench, owning its HAL server.

    python run_hal.py

It takes no arguments. It serves the bench file PyPTS uses - `bench.ini` beside `config.ini` -
created from the template when there is none yet, exactly as a PyPTS start does
(`pypts.config_handler.bench_config`), on the default port. The window starts a HAL when none
answers and attaches to one that does; closing the window stops the HAL
(`python -m pyhal.monitor --serve`, `pyhal/pyhal.md` -> *The monitor*). A HAL without a
window is `python -m pyhal --bench FILE`.

`src` is put on the path first, so this works from a checkout even where the package has not
been installed into the interpreter running it. This launcher may import `pypts`; the `pyhal`
package itself never does.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pyhal.__main__ import EXIT_BAD_BENCH  # noqa: E402 - needs the path set above

#: The exit code for arguments given: the launcher takes none (argparse's usage-error code).
EXIT_USAGE = 2


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
    from pyhal.monitor.__main__ import main as monitor_main

    return monitor_main(["--bench", bench, "--serve"])


# The HAL runs in a process of its own (`python -m pyhal`, started by client.start_hal()), so
# its driver processes never import this file; the guard keeps an import (the tests) silent.
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
