# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path
import sys
from importlib import util
import logging


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
    """
    Resolve a module path under `root` from either:
      - 'example_test'   (no suffix)
      - 'example_test.py'
      - 'subdir/example_test' or 'subdir/example_test.py'

    Returns a path *relative to* root.
    Raises FileNotFoundError if not found.
    """
    module_name = Path(module_name_str)
    search_root = root / module_name.parent if str(module_name.parent) not in ("", ".") else root

    # Try both with and without ".py" when no suffix was provided
    names_to_try = (
        [module_name.name] if module_name.suffix == ".py" else [module_name.name, f"{module_name.name}.py"]
    )

    for name in names_to_try:
        for path in search_root.rglob(name):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if path.name == name:
                return path.relative_to(root)

    raise FileNotFoundError(f"Module '{module_name_str}' not found under {root}")


def setup_logging():
    """
    Configures the root logger with:
      - Console output with timestamp + milliseconds
      - Reduces noisy libraries
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()  # remove old handlers

    # Console handler
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s.%(msecs)03d : %(levelname)s : %(name)s : %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Reduce verbosity of noisy libraries
    logging.getLogger("paramiko.transport").setLevel(logging.WARN)

    return root_logger


def setup_status_logger():
    """
    Creates a dedicated logger for status updates.
    Optionally connects it to an existing QTextEdit handler.
    """
    status_logger = logging.getLogger("status")
    status_logger.setLevel(logging.DEBUG)
    status_logger.handlers.clear()  # remove old handlers

    # Avoid duplicate handlers
    if not status_logger.handlers:
        # Console handler (optional, you can skip if you only want GUI)
        status_handler = logging.StreamHandler()
        formatter = logging.Formatter('%(message)s')
        status_handler.setFormatter(formatter)
        status_logger.addHandler(status_handler)

    return status_logger


if __name__ == "__main__":
    print(get_project_root())

