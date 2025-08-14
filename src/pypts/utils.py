# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

"""Module that provides the utilities to the project.
    """

def get_project_root(marker: str = 'pyproject.toml') -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / marker).exists():
            return parent
    raise FileNotFoundError(f"Project root not found using marker: {marker}")


if __name__ == "__main__":
    print(get_project_root())

