<!--
SPDX-FileCopyrightText: 2025 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# quality_tests

`test_code_quality.py` runs the two code checkers as ordinary pytest tests:

- **ruff** (`ruff check src tests`): style and common mistakes; rules in `[tool.ruff]`.
- **mypy**: type checks; the files it covers are listed in `[tool.mypy]`.

Both settings live in `pyproject.toml`. A test fails when the tool reports a problem, with the
tool's output as the message, or when the tool is not installed (`pip install -e ".[test]"`).
CI has no separate lint or type-check job: its `pytest` run is the check.
