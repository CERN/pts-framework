# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Starts pypts through the launcher, exactly as `python -m pypts` does.

Every argument is passed straight through to the launcher:

    python run_pypts.py
    python run_pypts.py --mode cli
    python run_pypts.py --log-level DEBUG --no-debug-monitor

`src` is put on the path first, so this works from a checkout even where pypts
has not been installed into the interpreter running it.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pypts.launcher import startup  # noqa: E402 - needs the path set above

# The guard is load-bearing, not boilerplate: the launcher spawns its children,
# and a spawned child imports this file again as `__mp_main__`. Without the
# guard every child would start a whole new pypts.
if __name__ == "__main__":
    startup.main()
