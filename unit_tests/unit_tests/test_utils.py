# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path
from pypts import get_project_root  # Replace 'your_module' with the actual module name

def test_get_project_root():
    expected_root = Path(__file__).resolve().parents[2]
    assert get_project_root().resolve() == expected_root
