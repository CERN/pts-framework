<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Design: split the bench's devices out of config.ini into bench.ini

**Date:** 2026-10-15 · **Status:** approved · **Origin:** codebase review finding #11
(a discarded config.ini wipes every `[hardware.*]` section, and the device error blames
the user).

## Problem

Typed application settings and untyped `[hardware.*]` device sections share one file,
`config.ini`, and the bootstrap discard decision is whole-file. One bad application value
therefore drops every device definition for the run, and the first `get_device()` then says
"Add a `[hardware.x]` section to config.ini" even though the section is sitting in the file.
"Restore default settings" has the same blast radius: recreating config.ini deletes the
bench's devices as a side effect.

## Decision

Device sections move to their own file, **`bench.ini`**, read by a small dedicated reader.
The two files cannot take each other down. Decisions made with the user:

- **File name:** `bench.ini`, beside `config.ini` (same `platformdirs` config directory).
- **Section names:** bare — `[ssh1]`, not `[hardware.ssh1]`. The prefix is redundant in a
  dedicated file.
- **Migration:** clean break. A leftover `[hardware.*]` section in config.ini is warned
  about and ignored; pypts never auto-migrates (it never modifies an existing user file).
- **Broken bench.ini:** discarded, mirroring config.ini — operator notice at start, the run
  continues with zero devices, and the first `get_device()` names the real reason.
- **Architecture:** approach A — a small reader beside ConfigHandler, not inside it and not
  in `hal/`. Device sections are verbatim text by design; they need none of ConfigHandler's
  schema/version/roles/writer machinery, and the startup notice belongs to the launcher,
  which `hal/` never meets.

## The new file

```ini
[ssh1]
driver = pypts.hal.drivers.ssh.SshDriver    ; required: the driver class, dotted
call_timeout_s = 120                         ; optional: longest one call may take, default 60
host = 192.168.0.10                          ; everything else goes to the driver's connect()
```

No version, no schema, nothing mandatory; every value stays text for the driver, exactly as
hardware sections behave today. Parsing uses the same file-format rules as config.ini:
`utf-8-sig` on read (Notepad writes a BOM), `interpolation=None` (a path or password may
contain `%`).

## Components

### `config_handler/file_locations.py`

- `BENCH_FILE_NAME = "bench.ini"`.
- `bench_file_path() -> Path` — `config_dir() / BENCH_FILE_NAME`. Same monkeypatch seam
  pattern as `config_file_path()`; callers go through the module
  (`file_locations.bench_file_path()`), never `from … import`.

### `config_handler/bench_template.ini` (new)

The commented device example that today ends `config_template.ini`, moved here and
de-prefixed. Comments only — a freshly created bench.ini declares zero devices and documents
the format (driver key, `call_timeout_s`, plain-text warning: prefer `key_filename` to
`password`).

### `config_handler/bench_config.py` (new)

One public entry point plus a result type:

- `BenchOutcome` enum: `CREATED` / `LOADED` / `DISCARDED`.
- `BenchConfig` (frozen dataclass): `devices: dict[str, dict[str, str]]` (by logical name,
  values as text, keys lower-cased by configparser), `outcome: BenchOutcome`,
  `problem: str | None`, `path: Path`.
- `bench_config() -> BenchConfig` — cached per process (computed once, module-level):
  - File missing → written from `bench_template.ini` (comments only), outcome `CREATED`,
    one INFO line. **No popup**: a first start shows only the existing config.ini notice.
    If creation itself fails (unwritable directory), outcome `DISCARDED` with the reason;
    the run continues with zero devices.
  - File present and parses as INI → outcome `LOADED`, every section a device, verbatim.
  - File present but unreadable or not INI → outcome `DISCARDED`: `devices` empty, the
    reason in `problem` and logged at ERROR. The "exists but cannot be opened" case is its
    own reason, as in `_load_or_discard()` (the file is opened explicitly, not handed to
    `ConfigParser.read()`, which swallows `OSError`).
  - Runs after `init_logging()`, so no buffered-log machinery (`_note()`-style) is needed.
- No writer, no roles, no `set_parameter` path: nothing in pypts ever writes a device
  section. The file is the user's; a hand edit applies from the next start (the result is
  cached per process), same rule as config.ini.
- A test seam mirroring `ConfigHandler.reset_for_testing()`: `reset_for_testing()` clears
  the cached result.

### `launcher/startup.py`

After `init_logging()` / `replay_bootstrap_log()`: call `bench_config()` once. Outcome
`DISCARDED` → the existing `show_config_popup()` (popup in GUI mode, banner otherwise)
naming `bench.ini` and the reason, and saying the run continues without devices. `CREATED`
and `LOADED` show nothing. Both files broken → two independent notices.

### `hal/local_setup.py`

- The Sequencer's default sections-provider (today `hardware_sections_from_config()`)
  becomes `bench_sections()`: returns `bench_config().devices`, but raises
  `DriverError("bench.ini was discarded: <problem> No devices are available for this
  run.")` when the outcome is `DISCARDED`. A run that asks for no device never calls it,
  so device-free runs are untouched; the first `get_device()` on a broken file states the
  real cause. (Lazy import of `pypts.config_handler`, as the module already does.)
- The unknown-device message becomes: `No device 'x' is configured. Add a [x] section to
  bench.ini. Configured devices: …`.
- `ini_hardware_sections()` and `LocalSetup.from_ini()` switch to the bench.ini format:
  **every section of the given file is a device, bare name**. `hardware_sections()`'s
  prefix-stripping goes away. This is a deliberate breaking change for external callers of
  `from_ini()`; the docstring says the file has bench.ini's format.
- Secret-key masking (`utilities/common.py` → `is_secret_key()`) keeps applying wherever
  bench values are logged (connect/recover trace, dumps).

### `config_handler/config_handler.py` + `configuration_schema.py`

- The hardware branch in the unknown-section walk (DEBUG note instead of WARNING,
  `config_handler.py:590`) becomes a tailored one-time WARNING: device sections have moved
  to `bench.ini`; move this section there and drop the `hardware.` prefix; the section is
  ignored.
- `HARDWARE_PREFIX` / `is_hardware_section()` survive in `configuration_schema.py` solely
  to produce that warning.
- A leftover section is otherwise an ordinary unknown section (kept as text in
  `get_whole_config()`, never used). `CONFIG_VERSION` is **unchanged** — nothing new is
  mandatory.

### `config_handler/config_template.ini`

The trailing commented `[hardware.ssh1]` example block is removed (it lives in
`bench_template.ini` now, de-prefixed). In its place, one comment line says devices are
declared in bench.ini.

### `hmi/gui/settings_dialog.py` + `hmi/gui/gui.py`

- The "Restore default settings" confirmation no longer claims the `[hardware.*]` devices
  are removed — bench.ini is never touched; the text says so instead.
- `_restore_default_settings()` is unchanged in behaviour (deletes only config.ini); only
  wording and comments referencing `[hardware.*]` in config.ini are updated
  (`gui.py:452`, dialog text at `settings_dialog.py:809`).

## Error-handling summary

| Situation | Behaviour |
|---|---|
| config.ini broken | Discarded as today; **devices unaffected** |
| bench.ini missing | Created from template (zero devices), INFO only |
| bench.ini broken / unreadable | Discarded: notice at start, run continues, first `get_device()` raises `DriverError` with the reason |
| bench.ini cannot be created | Same as discarded, with the creation failure as the reason |
| Unknown device name | `DriverError` naming bench.ini and the configured names |
| Leftover `[hardware.*]` in config.ini | One WARNING pointing at bench.ini; section ignored |

## Testing

- New `tests/unit_tests/test_bench_config.py`: creation from template when missing,
  loading, bare-section devices as text, discard on not-INI and on unreadable file,
  creation failure, per-process caching + `reset_for_testing()`, the
  `bench_file_path` monkeypatch seam, BOM (`utf-8-sig`) and `%` in values.
- `test_config_handler.py`: the hardware-section tests become leftover-section-warning
  tests (WARNING once, section ignored, text kept in `get_whole_config()`).
- HAL tests (`local_setup`): bare sections via `from_ini()`, the discarded-bench
  `DriverError`, the new unknown-device message.
- Quality gates: `pytest tests`, `ruff check src tests`, `mypy`, documentation check.

## Documents to update in the same change

`config_handler/config_handler.md` (new module, file table, lifecycle, hardware section
rules move out), `hal/hal.md` (Configuration section: bench.ini, `from_ini` format, error
table), `sequencer/sequencer.md` (`read_hardware_sections` default), `hmi/gui/gui.md`
(restore-default and restart wording), `usage_manual.html` (file locations, settings,
restore-default, startup notices), `pypts_implementation_status.html` (roadmap entry),
`CLAUDE.md` (config line mentions both files), and the review HTML's #11 once implemented.
`reuse.toml` already covers new `.py` files under `src/pypts/**` and `tests/**` and —
deliberately, no inline header, because templates are copied verbatim into the user's own
file — `src/pypts/**/*.ini`, so `bench_template.ini` needs nothing extra.

## Out of scope

Live propagation of config changes, typing/validating driver keys, any writer for
bench.ini, auto-migration of existing `[hardware.*]` sections.
