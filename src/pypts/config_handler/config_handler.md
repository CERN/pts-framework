# Config Handler — module context

One place that answers *"how is this installation set up"*. Everything the framework needs
to know before it can do anything — where the log goes, where reports go, at what level to
log, which instruments are on the bench — lives in one INI file, and this package is the
only code that touches it.

This document is the whole context of `src/pypts/config_handler/`. Read it instead of
re-reading the four modules.

---

## The four files

| File | Owns |
|---|---|
| `file_locations.py` | *Where* the file is. `platformdirs`, and the seam tests monkeypatch. |
| `configuration_schema.py` | *What* the file contains: section → key → type, default, allowed values; the deprecation map; `CONFIG_VERSION`. |
| `config_template.ini` | The shipped defaults **and** the comments the user reads. |
| `template_writer.py` | Writing the file without throwing the comments away. |
| `config_handler.py` | The singleton: load, create, migrate, validate, get/set, dump. |

`__init__.py` re-exports `ConfigHandler`, `Role` and the five exception types. Nothing else
is public.

---

## The three rules

**One instance per _process_, not per application.** `ConfigHandler()` returns the same
object however often it is called, so any module reaches the configuration without it being
threaded through constructors. A spawned child shares no memory with its parent, so it
builds its own instance and reads the same file — nothing is passed through
`Process(args=...)`. That is why **reading is pure**: it parses, it never writes. (The old
implementation called `create_config_from_template()` on every read, so five processes
rewrote one file per run.)

**One writer.** The launcher calls `ConfigHandler.bootstrap()` before anything else exists:
it creates the file if the machine has none, migrates it if it predates this pypts, repairs
missing keys, and validates the result. From then on the file is read-only to everyone.
`set_parameter()` on a reader raises `ConfigWriteError` rather than racing. A reader can
never be promoted to writer — `open_for_writing()` in a process that already holds a reader
raises.

**It has to work before logging does.** `bootstrap()` runs before the Logger process exists
— it is what decides where the log file goes — so it cannot log. It buffers its messages in
`_bootstrap_log` and the launcher calls `replay_bootstrap_log()` once `init_logging()` has
run. `_note()` checks for root handlers, so once logging is up nothing is buffered any more.

---

## Lifecycle

```
launcher/startup.py
  ConfigHandler.bootstrap()          # may create / migrate / repair; buffers its log
      ├─ file missing → _build_from_defaults() → _write()
      └─ file present → _read_raw() → _repair() → _write() only if something changed
  _validate()                        # every value converted to its declared type
  get_parameter("paths.logs_dir")    # decides the log file path
  init_logging(...)
  config.replay_bootstrap_log()      # the buffered narration finally reaches the run log

any other process / module
  ConfigHandler().get_parameter(...) # read-only; raises ConfigFileMissing if bootstrap never ran
```

A `ConfigError` out of `bootstrap()` is fatal by design: the launcher prints one line to
stderr (no traceback — it would bury the message the user has to act on) and exits with
`CONFIG_EXIT_CODE`.

---

## The file

Location is **computed, never configured** — no `--config` flag, no environment variable.
That is exactly what lets a child process find the same file with nothing passed to it.

```
Windows   config  %LOCALAPPDATA%\pypts\config.ini
          data    %LOCALAPPDATA%\pypts\{logs,reports}
Linux     config  ~/.config/pypts/config.ini
          data    ~/.local/share/pypts/{logs,reports}
```

Sections currently in the schema:

| Section | Keys |
|---|---|
| `meta` | `config_version` (int, managed by pypts) |
| `operating_system` | `name`, `version`, `architecture`, `kernel` — **derived**, recorded once at creation, never recomputed |
| `paths` | `base_dir`, `logs_dir`, `reports_dir` — **derived** paths |
| `logging` | `level` — one of `DEBUG/INFO/WARNING/ERROR/CRITICAL` |
| `report` | `type` (`html`/`csv`), `theme` |
| `gui` | `theme` (`default`/`light`/`dark`), `window_width`, `window_height` |
| `hardware.example_device` | `driver`, `resource`, `timeout_s` — the worked example of a section family |

Two ideas explain the shape of the file:

- **Derived values** ship *blank* in the template and are filled at creation from
  `platformdirs` / `platform`. This is how the template avoids `/tmp/pypts` (wrong on
  Windows) without hardcoding a Windows path (wrong on Linux). Once written they are
  ordinary values the user may edit, and nothing recomputes them. `_add_missing_keys()`
  refills a derived key only when it is *absent or empty*.
- **Section families** are how a flat INI file carries structured data. Any section named
  `hardware.<logical name>` is validated against the fields of `hardware.example_device`
  (`SECTION_FAMILIES` in `configuration_schema.py`), so a bench can declare `[hardware.dmm1]`,
  `[hardware.psu2]`, … without the schema knowing their names.

---

## Reading

```python
config = ConfigHandler()
config.get_parameter("paths.logs_dir")               # -> Path
config.get_parameter("gui.window_width")             # -> int
config.get_parameter("hardware.dmm1.timeout_s")      # -> float
config.get_parameter("paths.nothing", default=None)  # -> None instead of raising
```

Keys are dotted; **everything before the *last* dot is the section name**, which is what
makes dotted section families work. Values come back as `Path` / `int` / `float` / `bool` /
`str` per the schema; anything in a section the schema does not know is returned as text and
warned about once. A missing key raises `ConfigKeyError` naming what the section actually
holds — unless a `default` was passed (`_UNSET` sentinel distinguishes "no default" from
"the default is `None`").

Also available: `get_whole_config()` (a `MappingProxyType`, read-only so nobody can mutate
the process's configuration without going through `set_parameter()`), `dump()` (full text
for a log or console, naming the file it came from), and the `config_path` / `config_version`
properties.

---

## Writing

`set_parameter(key, value)` and `restore_default()` require `Role.WRITER`; a reader gets
`ConfigWriteError` pointing at the `SetConfigParameter` message instead. A value is parsed
against the schema *before* it reaches the file, so a bad value is refused here rather than
at the next start when the file is all there is.

Writing goes through `template_writer.py`, never `configparser.write()`, because the parsed
structure has no comments in it and one write would turn a documented file into a bare list
of `key = value`. Instead the **template is the layout**: its comments, blank lines and
ordering are copied out verbatim and only the text to the right of each `=` is replaced.
Sections or keys the template does not know about (a user-added `[hardware.*]`, most often)
are appended under an explanatory banner so nothing is ever lost. The rewrite is line based,
which keeps the output diffable — change one value and `git diff` shows one line.

`template_writer.write()` renders to `config.ini.tmp` in the same directory and `replace()`s
it into place, so an interrupted write cannot leave a half-written config behind.

---

## Migration

`CONFIG_VERSION` (in `configuration_schema.py`, currently **1**) is bumped whenever a
section or key is added, removed or renamed.

- File version **<** code version → migrated on the next `bootstrap()`: `DEPRECATED` keys are
  renamed or dropped, new keys are added, empty derived keys are filled. Every user value
  survives. The previous file is kept as `config.ini.v<n>.bak`, and every individual change
  is logged at INFO.
- File version **==** code version and complete → **nothing is written**; a second run leaves
  the file byte-identical.
- File version **>** code version → refused with `ConfigSchemaError`. This code cannot know
  what a future pypts meant.

`DEPRECATED` maps old dotted key → replacement, or `None` if the key was simply dropped. It
currently covers the pre-versioned layout (`[OperatingSystem]`, `[Paths]`, `[Application]`,
`[Misc]`), which had no `[meta]` section at all and is therefore treated as version 0. When
both the old and new key are present with a value, **the new one wins** — the user set it in
the new place and the old key is a leftover.

---

## Validation

`_validate()` converts every value and refuses the file if one does not fit. It raises
`ConfigSchemaError` naming the key and saying what *is* allowed, because the message is read
by whoever has to fix the file. An unknown section or key is not fatal — it is kept as text
and warned about once, since a typo that silently does nothing is worse than one that is
mentioned. A *missing* key in a known section **is** fatal, with the advice to start through
the launcher (which repairs) or delete the file.

Two file-format details worth knowing:

- Reading uses `interpolation=None` — a Windows path or a password may legitimately contain
  `%`, and configparser's default would read it as a reference and raise.
- Reading uses `utf-8-sig`, writing uses plain `utf-8`. The file is meant to be hand-edited
  and Notepad writes a BOM by default; without this, saving it in the most obvious editor on
  Windows makes the first section header unreadable and pypts will not start.

---

## Who uses it

| Caller | Uses |
|---|---|
| `launcher/startup.py` | `bootstrap()`, `paths.logs_dir`, `logging.level` (overridden by `--log-level`), the `operating_system.*` line in the run log, `replay_bootstrap_log()` |
| `report/report.py` | `ConfigHandler().get_parameter("paths.reports_dir")` unless a tmp path is injected |
| `core/core.py` | receives `SetConfigParameter` (HMI→CORE) and **logs a warning and ignores it** |

`local_storage.get_log_file_path()` no longer decides a location; it is given one.

---

## Adding or changing a key

1. Add the `Field` to `SCHEMA` in `configuration_schema.py`.
2. Add the same key, with its default and a comment, to `config_template.ini`. Derived keys
   ship **blank**.
3. Bump `CONFIG_VERSION` in `configuration_schema.py` **and** the literal `config_version`
   in the template — the two are checked against each other.
4. If you renamed or removed a key, add it to `DEPRECATED` so existing files migrate.

`tests/unit_tests/test_config_handler.py::test_schema_and_template_agree` fails if a key
exists in one and not the other; `test_every_template_default_is_valid_for_its_type` fails if
a shipped default cannot be parsed as its declared type; and
`test_the_template_declares_the_current_structure_version` catches a forgotten bump. Together
these are the "config structure verification tool integrated into the pytest pipeline" the
specification asks for, and the `dev_test` CI job already runs them.

---

## Testing

`file_locations.config_file_path()` is *the* seam: a test monkeypatches it at `tmp_path` and
the whole handler follows, with no environment variable and no constructor argument. That is
also why `config_handler.py` calls `file_locations.config_file_path()` rather than importing
the name — a `from … import` would bind the original function and make the monkeypatch
invisible.

`ConfigHandler.reset_for_testing()` forgets the singleton, which tests need because it would
otherwise outlive the `tmp_path` it was pointed at. **Only tests may call it**: a process that
dropped its configuration mid-run would be reading a different file from its own threads.

`tests/unit_tests/test_config_handler.py` (~60 tests) covers creation, reading, the singleton
and its thread safety, write permission, validation, section families, migration, the
bootstrap-log narration, comment preservation, and the schema/template agreement.

---

## Known gaps and sharp edges

Roadmap §1.3 is the authority; the TODOs live there, not in code comments. In short:

- **`SetConfigParameter` is declared and not implemented.** Nothing sends it and CORE only
  logs it. Two questions are open: whether CORE answers with a confirmation or an error, and
  how a process already running learns that a value it read at startup has changed. Until
  then a configuration change takes effect **on the next start**.
- **CORE does not actually open the config for writing yet.** `open_for_writing()` exists and
  the policy is decided, but no caller in the framework uses it — consequently
  `set_parameter()`, `restore_default()`, `dump()` and `get_whole_config()` are API surface
  that only the tests exercise today.
- **A user-added device section is validated but not repaired.** `_add_missing_keys()`
  iterates `SCHEMA` only, so a hand-written `[hardware.dmm1]` missing one of the family's
  keys is a hard `ConfigSchemaError` at startup, not something bootstrap fills in.
- **`hardware.*` is a placeholder.** The family and its validation exist; nothing consumes
  them. Phase 5 should read `[hardware.<name>]` into a `DeviceConfig` and hand it to drivers
  by logical name.
- **`report.type` / `report.theme` and the `[gui]` keys are read but not yet used** —
  Phases 4 and 3 respectively.
- **`stdout_logging_enabled` is still derived from `--mode`**, not from the configuration.
  Probably correct — it follows from having a console rather than from a preference — but it
  is the one logging decision the config does not own.
- **Per-run log folders do not exist.** `paths.logs_dir` is honoured, but it is still one
  timestamped file per run rather than a folder per run with a file per process.
