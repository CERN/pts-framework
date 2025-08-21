# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path
import sys
from importlib import util

"""Module that provides the utilities to the project.
    """
EXCLUDE_DIRS = {
    '.git',
    '.venv',
    '__pycache__',
    'archive',
    'backup',
    'old_tests',
    'results',
    'pts_reports',
    'dist',         
    'build',  
    '.eggs',         # eggs cache
    '.mypy_cache',   # mypy cache
    '.pytest_cache', # pytest cache
    '.tox',          # tox environment
    'node_modules',  # if you have JS deps
    '.idea',         # PyCharm config
    '.vscode',       # VSCode config
    '.cache',        # generic cache dirs
}

# def get_project_root() -> Path:
#     return Path(__file__).parent.parent.parent

def get_project_root() -> Path:
    current = Path(__file__).resolve()

    # Look for pyproject.toml up the tree. It should often be there
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    #trying other base settings
    for parent in current.parents:
        if (parent / "setup.py").exists() or (parent / "requirements.txt").exists():
            return parent

    #if in venv, return its parent
    if hasattr(sys, 'base_prefix') and sys.prefix != sys.base_prefix:
        return Path(sys.prefix).resolve().parent
    return current.parent.parent

def get_package_root(package_name: str) -> Path:
    spec = util.find_spec(package_name)
    if spec is None or spec.origin is None:
        raise ImportError(f"Cannot find package '{package_name}'")
    return Path(spec.origin).parent

def find_resource_path(module_name_str: str, root: Path) -> Path:
    for path in root.rglob(module_name_str):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.name == module_name_str:
            return path.relative_to(root)
    #raise FileNotFoundError(f"Module '{module_name_str}' not found under {root}")



if __name__ == "__main__":
    print(get_project_root())

