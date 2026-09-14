<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Migration instructions

How to run an existing recipe against the new architecture.

## Entry point

**Old:** User package had its own `__main__.py` calling `run_pts()` +
`create_and_start_gui()`. Recipe ran inside the same process.

**New:** Delete your `__main__.py`. Run the framework directly:

```bash
python -m pypts          # GUI
python -m pypts --mode cli
```

Load your recipe from the GUI file picker, or (CLI) type `load <path>` then `run`.

## Step-type names

The `steptype` field values changed — the `Step` suffix was dropped:

| Old | New |
|-----|-----|
| `PythonModuleStep` | `PythonModule` |
| `UserInteractionStep` | `UserInteraction` |
| `WaitStep` | `Wait` |
| `UserWriteStep` | `UserWrite` |
| `IndexedStep` | handled at load time — wrap steps in an indexed input |

Rename every `steptype:` value in your recipe YAML accordingly.

## Step types that no longer exist

| Old steptype | What to do |
|---|---|
| `SequenceStep` | Dropped. Inline the steps or restructure the recipe. |
| `UserRunMethodStep` | Deprecated. Replace with a `UserInteraction` step (for the prompt) followed by a `PythonModule` step (for the method call). |
| `SSHConnectStep` / `SSHCloseStep` | Not yet available (Phase 3 HAL). Keep using the old engine for recipes that need SSH. |
| `UserLoadingStep` | Not yet ported. Keep using the old engine for recipes that need file-load dialogs. |

## PythonModuleStep — action_type

`read_attribute` and `write_attribute` are dropped. If your step uses these,
replace them with a `PythonModule` step that calls a wrapper method instead.

## UserWriteStep — serial-port mode

The `ID` option (serial-port picker) is dropped. The `wrt` text-entry mode is
available as `UserWrite`. If you relied on `ID`, implement the serial-port dialog
in a `PythonModule` step.

## Module loading

Both file-based (path relative to recipe) and package-based (`test_package` in
the header) loading still work. The `test_package` package must be installed.

## Reports

Reports are now written to a per-run subfolder under `reports_dir` (configured in
`config.ini`). The path is shown in the GUI after the run, and sent to the log.
There is no longer a single overwritten `report.csv`.

## Globals used as magic keys

The old engine read certain globals by convention (e.g. `cancel_key`, `ssh_client`,
`ID_key`, `wrt_key`). The new engine does not. You can remove those from your recipe.

## Config file

The new framework writes a config on first run:

- Windows: `%LOCALAPPDATA%\pypts\config.ini`
- Linux: `~/.config/pypts/config.ini`

Edit it to set `[paths] reports_dir` if you want reports somewhere specific.
