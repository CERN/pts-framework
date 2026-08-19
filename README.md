<!--
SPDX-FileCopyrightText: 2025 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# pypts

Hardware-oriented testing framework developed by BE-CEM-MTA.

## Key Features

*   **YAML-based Recipes:** Define test sequences, steps, parameters, and variables using structured YAML files.
*   **Modular Steps:** Supports various step types including Python function calls, sub-sequence execution, user interaction prompts, wait times, and indexed steps for running tasks multiple times with varying inputs.
    **Reliable order execution:** Unlike pytest-order, the reliably follows the specified order.
*   **Variable Scopes:** Manages global variables for the recipe and local variables within sequences.
*   **Threaded Execution:** Runs recipes in a separate thread using `pts.run_pts`.
*   **Incremental Reporting:** Generates a detailed CSV report (`report.csv`) in real-time as steps complete.
*   **Contextual Reports:** Includes run context (Recipe Name, File Name, Serial Number) and step context (Sequence Name) in reports.
*   **HTML Reports:** Provides a utility to convert the CSV report into a styled HTML file (`report.html`) for easy viewing, similar to `pytest-html`.
*   **Event System:** Uses queues for inter-thread communication and event reporting (e.g., step start/end).

## Running

Plain Python — no IDE, no launch configuration, no wrapper script:

```bash
.venv\Scripts\python.exe -m pypts                     # GUI, plus the Debug Monitor
.venv\Scripts\python.exe -m pypts --mode cli          # CLI, plus the Debug Monitor
.venv\Scripts\python.exe -m pypts --no-debug-monitor  # without the Monitor
.venv\Scripts\python.exe -m pytest tests              # the test suite
```

`src\pypts\launcher\startup.py` may be run directly instead of `-m pypts`; it is the same
entry point. With the virtual environment activated, `python` replaces
`.venv\Scripts\python.exe`. The Debug Monitor opens beside the run by default during the
refactor and is deliberately left open when the run ends.

For full documentation, please visit [PTS Framework Documentation](https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/stable/).
