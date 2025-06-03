# SPDX-FileCopyrightText: 2025 CERN
#
# SPDX-License-Identifier: LGPL-2.1-or-lateer

from pathlib import Path

"""Module that provides the utilities to the project.
    """

def get_project_root() -> Path:
    return Path(__file__).parent.parent.parent

if __name__ == "__main__":
    print(get_project_root())

