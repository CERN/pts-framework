<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# launcher — the thin supervisor

`startup.py` is the only file. Entry point: `python -m pypts`.

## What it owns

- **Process tree** — starts the Logger, CORE, and (in GUI mode) the GUI as separate
  processes. In CLI mode the CLI runs in the launcher's own process.
- **Queue construction** — builds the HMI↔CORE link (the only cross-process pair) and
  the Logger queue. Passes them into child processes as constructor arguments.
- **Config bootstrap** — runs `ConfigHandler.bootstrap()` before spawning anything.
  Shows a popup (GUI) or console banner (CLI) if the config was discarded.
- **Spawn pinning** — pins `multiprocessing.set_start_method("spawn")` as the first
  statement of `main()`, before the first `Queue()`. This makes Linux behave like Windows
  and avoids the Qt fork hazard (plan 005).
- **Debug Monitor** — starts `pypts.helper_applications.debug_monitor` via
  `subprocess.Popen` (never as an import). On by default during the refactor;
  `--no-debug-monitor` turns it off.
- **Shutdown** — `stop_core()` sends `HmiStopped` + `ShutdownRequested` to CORE, joins
  up to `CORE_SHUTDOWN_TIMEOUT_S` (5.0 s), and terminates if CORE does not stop in time.

## The engine half, shared with `pypts.api`

`main()` is argument parsing plus three functions, which `pypts.api` calls too - so the API
starts exactly what `python -m pypts` starts:

| Function | Does |
|----------|------|
| `start_engine(mode, log_level_name, debug_monitor)` | pins spawn, bootstraps config, starts the Logger, `init_logging()`, starts CORE; returns an `Engine` (the processes and both HMI links). Stops what it started if it fails. `mode` is `gui` / `cli` / `api`. |
| `run_gui(engine, recipe_path, start, sequence_name)` | spawns the GUI process and joins it. The last three are for `pypts.api.open_gui()`. |
| `stop_engine(engine)` | `stop_core()`, then `StopLogger` and the Logger join. |

## Process topology

```
launcher (main process)
  ├── Logger process    (logger_main)
  ├── CORE process      (core_main)
  │     ├── Sequencer thread
  │     └── Report thread
  └── GUI process       (gui_main)     — GUI mode only
      (CLI runs in launcher process)   — CLI mode
```

## Key constants

| Name | Value | Meaning |
|------|-------|---------|
| `CORE_SHUTDOWN_TIMEOUT_S` | 5.0 s | Join timeout before CORE is terminated |
| `LOGGER_SHUTDOWN_TIMEOUT_S` | 5.0 s | Logger drain budget |
| `MONITOR_LOG_WAIT_S` | 5.0 s | How long to wait for the log file before giving up on the Monitor |

## Rules

- Must stay **the simplest component**. If something can be done in a child, do it there.
- Never import `helper_applications/debug_monitor/`. The dependency runs one way only.
- `stop_core()` is a pure function of its two arguments — no global state.

## Arguments

`--mode gui|cli|headless`, `--log-level`, `--debug-monitor/--no-debug-monitor`, and for
headless mode only `--recipe` (required) and `--sequence`. The parser is `ArgumentParser`,
which exits with `USAGE_EXIT_CODE` (3) on a bad command line instead of argparse's 2, because
headless mode uses 2 for a run that ended in ERROR/STOP. `--debug-monitor` defaults to on in
gui/cli and off in headless.

## Headless mode

`main()` hands over to `pypts.api.headless.headless_main()` and exits with its return code.
The launcher starts no engine itself in this mode - `Pts` does. The import is inside the
branch because `pypts.api` imports this module. Context: `api/api.md`.

## CLI mode

The CLI (`hmi/cli/cli.py`) runs in the launcher process, not as a subprocess. It calls
`wait_until_stopped()` after the user types `exit`, which polls until CORE confirms
shutdown or the grace period expires.
