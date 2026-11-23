<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# HAL server, phase 1 of 4: rename `pypts.hal` to `pyhal` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. **Never `git add`, `git mv` or `git commit`** — the user
> commits everything himself; move files with a plain move.

**Goal:** the hardware layer becomes the top-level package `pyhal`, still in-process, with no
behaviour change and no import of `pypts`.

**Architecture:** move `src/pypts/hal/` to `src/pyhal/` (the `pyrade_xy_graph` pattern), cut
its three ties to `pypts`, and point every user of it at the new name. `LocalSetup`,
`ConnectionDriver` and the Sequencer's `with LocalSetup(...)` stay as they are; phases 2-4
replace them.

**Tech Stack:** Python ≥ 3.11, setuptools (src layout), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-11-04-hal-server-design.md` rev 5 — §6a (packaging),
§12.1 (housekeeping), D9, D11. Phases: the rev 4 review's proposal, kept by rev 5.

## Global Constraints

- `pyhal` never imports `pypts` (spec §6a), enforced by a quality test.
- Rename everything, no shim: `pypts.hal` disappears (D11). Drivers import `from pyhal import PSU`;
  bench.ini names `driver = pyhal.drivers.ssh.SshDriver`.
- `pyhal/__init__.py` stays import-light (it is imported by every driver process).
- Logging inside `pyhal`: `logging.getLogger(__name__)`, `%`-style, the existing message texts
  unchanged (`logger/logging_rules.md`).
- Line length 100; `pytest tests` green at the end (it runs ruff and mypy too).
- Documentation moves with the code in the same change (CLAUDE.md).

## Review Focus

1. A user's own `bench.ini` still naming `pypts.hal.drivers.…`: the device fails with a message
   that says to write `pyhal.drivers.…` instead (added to Task 1's tests; a hint, not a shim).
2. An editable install made before the move: `import pyhal` may fail until
   `pip install -e ".[dev,hardware]"` is run again (Task 1, Step 2 checks it).
3. A driver file loaded by path keeps its own log level: its module is now named
   `pyhal_driver_file_<stem>` (existing test `test_a_driver_file_runs_in_its_own_process_and_keeps_its_log_level`).
4. The run log still gets the HAL's lines: `pyhal`'s loggers propagate to the root logger the
   Logger handles (existing `test_driver_log_records_reach_the_run_log`).
5. Leftover `pypts/hal/__pycache__` making `import pypts.hal` still succeed in a dev tree:
   delete the old folder whole, cache included (Task 1, Step 3).

---

### Task 1: Move the package and cut its ties to `pypts`

**Files:**
- Move: `src/pypts/hal/` → `src/pyhal/` (whole folder; then delete `src/pypts/hal/` including
  `__pycache__`)
- Modify: every `src/pyhal/**/*.py` (imports `pypts.hal` → `pyhal`)
- Modify: `src/pyhal/connection_driver.py` (logger, `ignore_keyboard_interrupt`, prefix, hint)
- Modify: `src/pyhal/local_setup.py` (logger; `bench_sections()` removed)
- Modify: `src/pypts/sequencer/sequencer.py` (import; receives `bench_sections()`)
- Modify: `pyproject.toml`, `reuse.toml`, `.gitignore`
- Modify tests: `tests/unit_tests/test_hal.py`, `test_hal_connection.py`, `test_hal_ssh.py`,
  `test_hal_weather.py`, `hal_test_drivers.py`, `test_sequencer.py`, `test_utilities.py`
- Create: `tests/quality_tests/test_pyhal_independence.py`

**Interfaces:**
- Produces: package `pyhal` with today's public API unchanged (`get_device`, `LocalSetup`,
  `ConnectionDriver`, `BaseDriver`, `DriverError`, `recover_device`, `device_info`,
  `DeviceInfo`, `PSU`, `DMM`, `Scope`, `SSH`, `Load`, `Other`); `pyhal.local_setup` keeps
  `split_section`, `anchor_driver_files`, `ini_device_sections`; `pyhal.connection_driver.
  DRIVER_FILE_MODULE_PREFIX = "pyhal_driver_file_"`.
- Produces: `pypts.sequencer.sequencer.bench_sections() -> dict[str, dict[str, str]]` — today's
  function, moved verbatim (lazy `config_handler` import no longer needed: a normal import).

- [ ] **Step 1: Write the failing quality test** `tests/quality_tests/test_pyhal_independence.py`

```python
def test_pyhal_never_imports_pypts() -> None:
    # Every import statement in src/pyhal, read with ast (no import executed).
    offenders = []
    for path in sorted((REPO_ROOT / "src" / "pyhal").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                if name == "pypts" or name.startswith("pypts."):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {name}")
    assert offenders == []

def test_pyhal_exists() -> None:
    assert (REPO_ROOT / "src" / "pyhal" / "__init__.py").is_file()
```

- [ ] **Step 2: Run it:** `pytest tests/quality_tests/test_pyhal_independence.py -v` → FAIL
  (`test_pyhal_exists`).

- [ ] **Step 3: Move the folder** with `Move-Item src/pypts/hal src/pyhal` (not `git mv`), then
  delete `src/pyhal/__pycache__` and `src/pyhal/drivers/__pycache__`. Confirm
  `src/pypts/hal` no longer exists. Run `python -c "import pyhal"`; if it fails, run
  `pip install -e ".[dev,hardware]"` and retry.

- [ ] **Step 4: Rename the imports inside `src/pyhal/`**: every `from pypts.hal…` / `pypts.hal.`
  → `pyhal…` / `pyhal.` (code, docstrings and comments, e.g. `drivers/loopback.py`'s
  `driver = pyhal.drivers.loopback.LoopbackDriver`).

- [ ] **Step 5: Cut the three ties to `pypts`:**
  - `connection_driver.py` and `local_setup.py`: `from pypts.logger.log import log` →
    `log = logging.getLogger(__name__)` at module level (same name, so no call site changes).
  - `connection_driver.py`: `from pypts.utilities.common import ignore_keyboard_interrupt` →
    a private copy `_ignore_keyboard_interrupt() -> None` in `connection_driver.py` (body:
    `with contextlib.suppress(ValueError): signal.signal(signal.SIGINT, signal.SIG_IGN)`, a
    docstring saying why: driver processes leave Ctrl+C to their parent, and `pyhal` cannot
    import `pypts`).
  - `local_setup.py`: delete `bench_sections()` and its paragraph in the module docstring.

- [ ] **Step 6: `DRIVER_FILE_MODULE_PREFIX = "pyhal_driver_file_"`** in `connection_driver.py`.

- [ ] **Step 7: Add the old-name hint** (Review Focus 1). Test first, in `test_hal.py`:

```python
def test_an_old_pypts_hal_path_says_to_use_pyhal():
    with pytest.raises(ValueError, match=r"pyhal\.drivers\.loopback\.LoopbackDriver"):
        load_driver_class("pypts.hal.drivers.loopback.LoopbackDriver")
```

  Then in `load_driver_class()`: a dotted path starting with `"pypts.hal."` raises
  `ValueError(f"'{driver_path}' names the old package: the hardware layer is 'pyhal' now. Write
  '{'pyhal.' + driver_path[len('pypts.hal.'):]}' in bench.ini.")` before importing. Run the test
  → PASS.

- [ ] **Step 8: Move `bench_sections()` into `src/pypts/sequencer/sequencer.py`** as a module
  function beside `reports_dir_from_config()`, imports at the top
  (`from pypts.config_handler.bench_config import BenchOutcome, bench_config`,
  `from pyhal import DriverError`, `from pyhal.local_setup import LocalSetup, anchor_driver_files`).
  The Sequencer's `read_hardware_sections` default keeps pointing at it.

- [ ] **Step 9: Point the tests at `pyhal`:** in the seven test files listed, `pypts.hal` →
  `pyhal` (imports, dotted driver strings such as `LOOPBACK`, generated driver source in
  `test_hal_connection.py`, `test_utilities.py`'s `module_name="pyhal.local_setup"`).
  `test_the_old_modules_are_gone`: import `pyhal` instead of `pypts.hal`, and add `"pypts.hal"`
  to the `gone` list. The three `test_bench_sections_*` tests (`test_hal.py:348-410`) move to
  `test_sequencer.py` and import `bench_sections` from `pypts.sequencer.sequencer` (whatever
  they monkeypatch — `bench_config` — is patched in that module now);
  `test_sequencer.py:1427` asserts `instance.read_hardware_sections is sequencer_module.bench_sections`.

- [ ] **Step 10: Housekeeping (spec §12.1):**
  - `pyproject.toml`: `include = ["pypts", "pypts.*", "pyhal", "pyhal.*", "pyrade_xy_graph",
    "pyrade_xy_graph.*"]`; `[tool.mypy] files`: `"src/pypts/hal"` → `"src/pyhal"`;
    `known-first-party = ["pypts", "pyhal"]`.
  - `reuse.toml`: add `"src/pyhal/**/*.py"` to the first annotation's `path` list.
  - `.gitignore:205`: `!/src/pypts/hal/drivers/` → `!/src/pyhal/drivers/`.

- [ ] **Step 11: Run** `pytest tests` → all PASS, ruff and mypy included. Also
  `git status --short` shows `src/pyhal/drivers/*.py` as untracked, not ignored (the `.gitignore`
  exception works).

### Task 2: Recipes, templates and texts that name the old package

**Files:**
- Modify: `resources/recipes/HAL_recipes/hal_demo.yml`, `hal_demo_tests.py`, `meteo_demo.yml`,
  `meteo_demo_tests.py`; `resources/recipes/showcase_recipes/showcase_automated.yml`,
  `showcase_full.yml`
- Modify: `src/pypts/config_handler/bench_template.ini` (lines 2, 8),
  `src/pypts/config_handler/bench_config.py` (docstring line 10),
  `src/pypts/recipe/recipe_schema.py:829-830` (the two `sshconnectstep` / `sshclosestep` hints)
- Modify: `src/pypts/stream_handler/stream_session.py` (docstring line 4 and comment line 99:
  `hal.local_setup.LocalSetup` → `pyhal.local_setup.LocalSetup`)

**Interfaces:** consumes Task 1's `pyhal`.

- [ ] **Step 1:** `pypts.hal` → `pyhal` and `src/pypts/hal/` → `src/pyhal/` in each file (the
  recipe test code's `from pyhal import get_device`; bench examples
  `driver = pyhal.drivers.…`; `hal.md` → `pyhal.md` where a path is named).
- [ ] **Step 2:** `git grep -n -I "pypts\.hal\|pypts/hal" -- src resources tests` → no hit
  outside `resources/recipes/Old_recipes/` and `resources/internal_reports/` (history).
- [ ] **Step 3:** `pytest tests` → PASS (the recipe schema tests read those hints).

### Task 3: Documents

**Files:**
- Move: `src/pyhal/hal.md` → `src/pyhal/pyhal.md` (its inline SPDX header stays)
- Modify: `CLAUDE.md` (module table row, architecture block, licence paragraph's glob list),
  `src/pypts/README.md:34`, `src/pypts/sequencer/sequencer.md:82`, `src/pypts/step/step.md:307,312`,
  `src/pypts/config_handler/config_handler.md:135`
- Modify: `docs/Usage_manuals/how_to_write_a_driver.html` and `.md`, `quick_start.html:164-167`,
  `usage_manual.html:488-529`, `recipe_guide.html:475` (check what it names first),
  `migration_instructions.html` (a short "the hardware layer is `pyhal` now" note: edit
  `driver =` lines in your own bench.ini and `from pypts.hal` in your own test code and
  drivers), `pypts_implementation_status.html` (new entry 1.98)

**Interfaces:** none.

- [ ] **Step 1: `pyhal.md`** — rename, then: title `# pyhal — the hardware layer`; every
  `pypts.hal` → `pyhal`; the *Files* table's `local_setup.py` row loses `bench_sections()` (the
  Sequencer reads bench.ini, `sequencer/sequencer.md`); the paragraph about the lazy
  `pypts.config_handler` import is replaced by: `pyhal` never imports `pypts` (quality test
  `tests/quality_tests/test_pyhal_independence.py`), logs through `logging.getLogger(__name__)`,
  which reaches PyPTS's run log through the root logger; `pypts_driver_file_<stem>` →
  `pyhal_driver_file_<stem>`; *Packaging*: `.gitignore` carries `!/src/pyhal/drivers/`; the
  old-path hint in *Failure*. Add one line under the intro: the package is on its way to a
  standalone HAL server (spec rev 5), and today it still runs in-process.
- [ ] **Step 2:** The other module context files and CLAUDE.md, as listed. CLAUDE.md's module
  table: `| `hal/` | `hal/hal.md` |` becomes a row for `src/pyhal/` (outside `src/pypts/`, like
  `pyrade_xy_graph`) → `src/pyhal/pyhal.md`; architecture block: the `hal/` line moves to a
  `src/pyhal/` line beside `src/pyrade_xy_graph/`; licence paragraph: `src/pyhal/**/*.py` joins
  the globs `reuse.toml` covers.
- [ ] **Step 3:** The usage manuals, as listed.
- [ ] **Step 4:** `pypts_implementation_status.html`: entry `1.98 The hardware layer is the
  package pyhal — done (phase 1 of 4 of the HAL server)`, in the style of 1.97: what moved, the
  three cut ties, the old-path hint, what the user must edit (own bench.ini, own drivers and test
  code), link to the spec and this plan. Historical entries stay as written.
- [ ] **Step 5: Documentation check:** `git grep -n -I "pypts\.hal\|pypts/hal\|hal/hal\.md" --
  . ':!resources/internal_reports' ':!docs/superpowers' ':!resources/recipes/Old_recipes'` → only
  historical status entries remain. Re-read `pyhal.md` against the code: every identifier it
  names exists.
- [ ] **Step 6:** `pytest tests` → PASS.
