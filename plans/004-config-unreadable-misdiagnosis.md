# Plan 004: An unreadable config.ini is reported as unreadable, not as a version mismatch

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 800db1c..HEAD -- src/pypts/config_handler/config_handler.py tests/unit_tests/test_config_handler.py src/pypts/config_handler/config_handler.md`
> If any changed since this plan was written, compare the "Current state"
> excerpts against the live code before proceeding; mismatch = STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `800db1c`, 2026-08-21

## Why this matters

`ConfigParser.read(path)` swallows `OSError` per-file: a `config.ini` that
exists but cannot be opened (wrong ACL on a shared bench, locked by another
tool) is silently skipped, `_read_raw` returns `{}`, and the discard logic then
reads the missing `meta.config_version` as `"0"` and tells the operator *"It
declares structure version 0, but this pypts expects 1."* — in the startup
popup, in `bootstrap_problem`, and as the ERROR in the log. The operator is
sent to fix a version key that is fine, while the run silently proceeds on
template defaults (so `paths.logs_dir`/`paths.reports_dir` revert to the
per-user data directory and the run's output lands somewhere the bench was not
configured to put it). The fix: open the file explicitly so a read failure
becomes its own, correctly-worded `ConfigSchemaError`.

## Current state

Relevant files:

- `src/pypts/config_handler/config_handler.py` — the module. The bug is in the
  module-level function `_read_raw` (lines 636–650). The discard flow that
  consumes it is `_load_or_discard` (lines 460–508); the misleading sentence
  comes from `_structure_version_problem` (lines 510–535).
- `tests/unit_tests/test_config_handler.py` — the test file, with the
  `config_path` fixture (lines 59–66) that points the handler at `tmp_path`
  and resets the singleton.
- `src/pypts/config_handler/config_handler.md` — the module context file;
  `CLAUDE.md` requires it be updated in the same change.

`_read_raw` today (`config_handler.py:642-650`):

```python
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8-sig")
    except configparser.Error as error:
        raise ConfigSchemaError(
            f"{path} cannot be read as a configuration file: {error}. Correct it, or "
            f"delete it and pypts will create it again from the template."
        ) from error
    return {section: dict(parser[section]) for section in parser.sections()}
```

How it is reached — `_load_or_discard` (`config_handler.py:479-498`), which
already turns a `ConfigSchemaError` from `_read_raw` into a DISCARDED outcome
with the error's own text as the operator-facing `problem`:

```python
        try:
            raw = _read_raw(self._path)
        except ConfigSchemaError as error:
            problem = str(error)

        if raw is not None:
            problem = self._structure_version_problem(raw)
        ...
        self.bootstrap_outcome = BootstrapOutcome.DISCARDED
        self.bootstrap_problem = problem
```

Load-bearing fact (verified at `800db1c`): **file existence is already checked
before `_read_raw` is ever called.** `_setup` (`config_handler.py:224-249`)
branches on `self._path.exists()` — the missing-file path raises
`ConfigFileMissing` or creates the file; only the exists-branch calls
`_load_or_discard()`. So inside `_read_raw`, `FileNotFoundError` is a
same-millisecond race, and any `OSError` legitimately means "exists but cannot
be opened". No separate missing-file handling is needed in `_read_raw`.

The version-check that produces today's wrong message
(`config_handler.py:519-535`) is **correct for what it sees** and must not be
changed: with the fix, it simply never sees the `{}` from an unreadable file.

Repo conventions: error messages in this module always end with the user's
remedy ("Correct it, or delete it and pypts will create it again from the
template.") — keep that sentence in the new message. `%`-style logging;
`ConfigSchemaError` is the module's own exception family (`N818` is
deliberately off — do not rename anything).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused | `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_config_handler.py -q` | all pass |
| Full suite | `.venv\Scripts\python.exe -m pytest tests -q` | all pass, exit 0 |
| Lint | `.venv\Scripts\python.exe -m ruff check src tests` | no NEW findings |
| Typecheck | `.venv\Scripts\python.exe -m mypy` | `Success: no issues found` |

If pytest errors with `PermissionError ... pytest-of-Dzbanan`, add
`--basetemp=C:\Git\pts-framework\.pytest-tmp` (disposable, do not commit).

## Scope

**In scope** (the only files you should modify):

- `src/pypts/config_handler/config_handler.py` (the `_read_raw` function only)
- `tests/unit_tests/test_config_handler.py`
- `src/pypts/config_handler/config_handler.md` (one paragraph)
- `resources/roadmap/pypts_roadmap.md` (one line, Step 4)
- `plans/README.md` (your status row)

**Out of scope** (do NOT touch):

- `_load_or_discard`, `_structure_version_problem`, `_validate`, `_setup` —
  the discard pipeline is correct; only the read primitive lies to it.
- `src/pypts/launcher/startup.py` — the popup plumbing is fine; it shows
  whatever `bootstrap_problem` says.
- The no-migration/no-repair policy — settled design (roadmap §1.3).

## Git workflow

- Branch off `architecture_refactor`: `advisor/004-config-unreadable`.
- Commit style: short lowercase summary. One commit.
- Do NOT push or open an MR unless the operator instructed it.

## Steps

### Step 1: Open the file explicitly in `_read_raw`

Replace the `try` block so the OS-level failure surfaces as its own
`ConfigSchemaError` with a message naming the real cause. Target shape:

```python
    parser = configparser.ConfigParser(interpolation=None)
    try:
        # Not parser.read(path): that swallows OSError per-file and returns
        # an empty parser, which downstream then misdiagnoses as a structure-
        # version mismatch. Opening explicitly makes "exists but unreadable"
        # its own, correctly-worded refusal.
        with open(path, encoding="utf-8-sig") as config_file:
            parser.read_file(config_file)
    except OSError as error:
        raise ConfigSchemaError(
            f"{path} exists but cannot be opened: {error}. Correct it, or "
            f"delete it and pypts will create it again from the template."
        ) from error
    except configparser.Error as error:
        raise ConfigSchemaError(
            f"{path} cannot be read as a configuration file: {error}. Correct it, or "
            f"delete it and pypts will create it again from the template."
        ) from error
    return {section: dict(parser[section]) for section in parser.sections()}
```

Note: `parser.read_file()` raises `configparser.Error` subclasses for
malformed content exactly as `parser.read()` did, so the existing
malformed-file tests must keep passing unchanged.

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_config_handler.py -q`
→ all existing tests pass.

### Step 2: Add the regression tests

In `tests/unit_tests/test_config_handler.py`, using the `config_path` fixture
(it monkeypatches `file_locations.config_file_path` and resets the singleton):

1. `test_an_unopenable_file_is_reported_as_unopenable_not_version_zero(config_path)`
   — make the config path exist but be unopenable **as a file**: create a
   *directory* at `config_path` (`config_path.mkdir()`). `path.exists()` is
   True, `open()` raises `PermissionError` on Windows / `IsADirectoryError`
   on Linux — both `OSError`, both platforms deterministic. Then
   `config = ConfigHandler.bootstrap()` and assert:
   - `config.bootstrap_outcome is BootstrapOutcome.DISCARDED`
   - `"cannot be opened" in config.bootstrap_problem`
   - `"structure version" not in config.bootstrap_problem`  ← the regression
   - `config.get_parameter("logging.level")` returns the template default
     (the run proceeds on defaults — copy the how-to from an existing
     discard test in this file).
2. `test_a_malformed_file_message_is_unchanged(config_path)` — only if the
   file does not already have one (grep for `cannot be read as a
   configuration file` in the test file first; at `800db1c` a malformed-INI
   discard test exists — if it already pins this message, skip this item).

**Verify**: `.venv\Scripts\python.exe -m pytest tests/unit_tests/test_config_handler.py -q`
→ all pass including the new test(s).

### Step 3: Update the module context file

`CLAUDE.md`: a module's `.md` is updated in the same change. In
`src/pypts/config_handler/config_handler.md`, find the section describing the
discard policy / bootstrap outcomes and add one sentence where the discard
reasons are enumerated, e.g.:

> A file that exists but cannot be opened (ACL, lock) is its own discard
> reason — "exists but cannot be opened" — distinct from a malformed file and
> from a version mismatch; `_read_raw` opens the file explicitly so
> `configparser` cannot silently swallow the OSError and misreport it as
> structure version 0.

(Adapt to the file's surrounding style; read that section before editing.)

**Verify**: `git diff -- src/pypts/config_handler/config_handler.md` shows one
coherent addition, no rewrapping noise.

### Step 4: Record it in the roadmap

In `resources/roadmap/pypts_roadmap.md`, section **§1.3** ("Config handler
rework"), append to its TODO list:

```
- [x] **DONE (plans/004):** an existing-but-unopenable config.ini is discarded
      with "exists but cannot be opened: <OS error>" instead of being
      misdiagnosed as "declares structure version 0" — `_read_raw` opens the
      file explicitly rather than letting configparser swallow the OSError.
```

**Verify**: `git diff --stat` → exactly the five in-scope files modified.

## Test plan

Step 2 above. Pattern: existing DISCARDED-outcome tests in
`test_config_handler.py` (they bootstrap against a deliberately broken file
and assert on `bootstrap_outcome`/`bootstrap_problem`).

## Done criteria

ALL must hold:

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` exits 0; pass count grows
      by ≥ 1; skips stay at 45 (43 if plan 003 landed first)
- [ ] `.venv\Scripts\python.exe -m ruff check src tests` — no NEW findings
- [ ] `.venv\Scripts\python.exe -m mypy` → `Success: no issues found`
- [ ] `grep -n "parser.read(" src/pypts/config_handler/config_handler.py`
      returns no match (only `read_file` remains)
- [ ] `git status` shows only the five in-scope files modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `_read_raw` or `_load_or_discard` do not match the excerpts (drift).
- Any *existing* test fails after Step 1 — in particular a test that relied on
  `parser.read()`'s silent-skip behavior; that would mean the missing-file
  guard in `_setup` is not what this plan verified it to be.
- The directory-as-config-file trick does not produce an `OSError` on this
  platform (would need a different unopenable-file construction — report
  rather than invent one).

## Maintenance notes

- The launcher popup (`show_config_popup`) now shows the new sentence on this
  failure — no change needed there, but a reviewer should eyeball the popup
  text once (`--mode cli` prints it as a banner) for line-length sanity.
- When Phase 5 adds `[hardware.*]` sections and a `CONFIG_VERSION` bump, the
  discard-reason wording in `config_handler.md` (touched here) is the place
  the new reasons get documented.
- Related but deliberately separate (recorded in plans/README.md, not
  planned): the DEBUG config dump logs unknown-section values verbatim —
  masking belongs with the Phase-5 credentials design.
