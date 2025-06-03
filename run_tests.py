# SPDX-FileCopyrightText: 2025 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import pytest

if __name__ == "__main__":
    exit_code = pytest.main([
        "-s",
        "-v",
        "--color=yes",
        "tests/unit_tests",
        "tests/functional_tests"
    ])
    exit(exit_code)
