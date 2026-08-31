# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Runs the pypts test suite: unit tests first, then functional tests.

Any extra argument is passed straight through to pytest, so this still works:

    python run_tests.py -k logger
    python run_tests.py --lf -x
"""

import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent
TEST_PATHS = [
    REPO_ROOT / "tests" / "unit_tests",
    REPO_ROOT / "tests" / "functional_tests",
]

if __name__ == "__main__":
<<<<<<< HEAD
    exit_code = pytest.main([
        "-s",
        "-v",
        "--color=yes",
        "unit_tests/unit_tests",
        "unit_tests/functional_tests"
    ])
    exit(exit_code)
=======
    missing = [path for path in TEST_PATHS if not path.is_dir()]
    if missing:
        print("Test directories not found:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        sys.exit(1)

    # Paths are resolved from this file rather than the working directory, so the
    # suite runs the same way from anywhere.
    args = ["-s", "-v", "--color=yes", *(str(path) for path in TEST_PATHS), *sys.argv[1:]]
    sys.exit(pytest.main(args))
>>>>>>> 04a05cd756975e2dc007fe919cc630e4191643db
