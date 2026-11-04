"""
Ruff and mypy as pytest tests, so `pytest tests` is the one command that checks a change,
on a developer's machine and in CI alike.

Both tools read their settings from pyproject.toml ([tool.ruff], [tool.mypy]); these tests add
no rules of their own. A missing tool is a failure, not a skip: a quality gate that quietly
does not run looks exactly like one that passed.
"""

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def run_tool(module_name: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Run `python -m <module_name> <arguments>` from the repository root."""
    if importlib.util.find_spec(module_name) is None:
        pytest.fail(
            module_name + ' is not installed. Install the test extra: pip install -e ".[test]"'
        )
    command = [sys.executable, "-m", module_name, *arguments]
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def test_ruff_finds_no_problems() -> None:
    result = run_tool("ruff", ["check", "src", "tests"])
    assert result.returncode == 0, result.stdout + result.stderr


def test_mypy_finds_no_problems() -> None:
    # No paths given: the files to check are listed in [tool.mypy].
    result = run_tool("mypy", [])
    assert result.returncode == 0, result.stdout + result.stderr
