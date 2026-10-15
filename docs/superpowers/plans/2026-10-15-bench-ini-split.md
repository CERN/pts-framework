<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# bench.ini Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move device sections out of `config.ini` into a new `bench.ini`, read by a small dedicated reader, so a discarded config.ini can no longer take the bench's devices with it (codebase review finding #11).

**Architecture:** A new module `config_handler/bench_config.py` reads (or creates) `bench.ini` once per process and returns verbatim device sections plus an outcome; the launcher shows a notice when the file was discarded; `hal/local_setup.py` takes its default device sections from it and raises honest `DriverError`s. config.ini drops its hardware special-case: a leftover `[hardware.*]` section gets a one-time WARNING pointing at bench.ini and is otherwise an ordinary unknown section.

**Tech Stack:** Python ≥ 3.11, configparser, pytest, ruff, mypy. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-15-bench-ini-split-design.md` — read it first.

## Global Constraints

- Quality gates for every task: `pytest tests`, `ruff check src tests` (line length 100), `mypy`. The final task also runs the documentation check.
- Logging is `%`-style, never f-strings (ruff `G004`). INFO and above is for the technician, in plain sentences; developer detail is DEBUG. Exception messages may use f-strings.
- **`CONFIG_VERSION` must NOT change.** Nothing mandatory is added.
- `reuse.toml` covers `src/pypts/**/*.py`, `src/pypts/**/*.ini` and `tests/**/*.py` — no inline SPDX headers in those new files. (Other `.py` files in the repo start with the SPDX comment block only where reuse.toml does not cover them.)
- Never `git checkout` a file to undo an experiment.
- Every commit message ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Old-school plain Python: `if`/`else` over conditional expressions, named locals over one-liners.
- Docstrings and comments follow the module's existing voice (read neighbouring code first).

---

### Task 1: The bench file — location, template, reader

**Files:**
- Modify: `src/pypts/config_handler/file_locations.py`
- Create: `src/pypts/config_handler/bench_template.ini`
- Create: `src/pypts/config_handler/bench_config.py`
- Modify: `src/pypts/config_handler/__init__.py`
- Test: `tests/unit_tests/test_bench_config.py` (new)

**Interfaces:**
- Consumes: `file_locations.config_dir()`, `template_writer.write(path: Path, text: str) -> None` (both exist).
- Produces (later tasks rely on these exact names):
  - `file_locations.BENCH_FILE_NAME: str = "bench.ini"`, `file_locations.bench_file_path() -> Path`
  - `bench_config.BenchOutcome` (Enum: `CREATED`, `LOADED`, `DISCARDED`)
  - `bench_config.BenchConfig` (frozen dataclass: `devices: dict[str, dict[str, str]]`, `outcome: BenchOutcome`, `problem: str | None`, `path: Path`)
  - `bench_config.bench_config() -> BenchConfig` (cached per process, never raises)
  - `bench_config.reset_for_testing() -> None`
  - Re-exported from `pypts.config_handler`: `BenchConfig`, `BenchOutcome`, `bench_config`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit_tests/test_bench_config.py`:

```python
"""
Unit tests for config_handler/bench_config.py: the bench file reader.

Everything runs against tmp_path: the `bench_path` fixture monkeypatches
`file_locations.bench_file_path`, the only place the reader asks where its
file lives, and clears the per-process cache around each test.
"""

import configparser
import logging
from pathlib import Path

import pytest

from pypts.config_handler import bench_config as bench_module
from pypts.config_handler import file_locations
from pypts.config_handler.bench_config import BenchOutcome, bench_config


@pytest.fixture
def bench_path(tmp_path, monkeypatch):
    """Point the reader at tmp_path and give every test a cold cache."""
    path = tmp_path / "bench.ini"
    monkeypatch.setattr(file_locations, "bench_file_path", lambda: path)
    bench_module.reset_for_testing()
    yield path
    bench_module.reset_for_testing()


# --- creation ---------------------------------------------------------------


def test_a_missing_file_is_created_from_the_template_with_no_devices(bench_path):
    assert not bench_path.exists()

    result = bench_config()

    assert result.outcome is BenchOutcome.CREATED
    assert result.devices == {}
    assert result.problem is None
    assert result.path == bench_path
    assert bench_path.exists()
    # The created file documents the format but declares nothing.
    assert "driver" in bench_path.read_text(encoding="utf-8")


def test_the_shipped_template_declares_no_device():
    text = (Path(bench_module.__file__).parent / bench_module.BENCH_TEMPLATE_FILE_NAME).read_text(
        encoding="utf-8"
    )
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    assert parser.sections() == []


def test_a_file_that_cannot_be_created_is_discarded_with_the_reason(bench_path, monkeypatch):
    def refuse(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(bench_module.template_writer, "write", refuse)

    result = bench_config()

    assert result.outcome is BenchOutcome.DISCARDED
    assert result.devices == {}
    assert "could not be created" in (result.problem or "")


# --- reading ----------------------------------------------------------------


def test_every_section_is_a_device_with_every_value_as_text(bench_path):
    bench_path.write_text(
        "[ssh1]\ndriver = pkg.Mod\nport = 22\n[dmm1]\ndriver = pkg.Dmm\n", encoding="utf-8"
    )

    result = bench_config()

    assert result.outcome is BenchOutcome.LOADED
    assert result.problem is None
    assert result.devices == {
        "ssh1": {"driver": "pkg.Mod", "port": "22"},
        "dmm1": {"driver": "pkg.Dmm"},
    }


def test_the_result_is_cached_per_process(bench_path):
    bench_path.write_text("[a]\ndriver = x.Y\n", encoding="utf-8")

    first = bench_config()
    bench_path.write_text("[b]\ndriver = x.Y\n", encoding="utf-8")

    # A hand edit applies from the next start, the same rule as config.ini.
    assert bench_config() is first


def test_a_file_saved_with_a_notepad_bom_still_reads(bench_path):
    bench_path.write_bytes(b"\xef\xbb\xbf[ssh1]\ndriver = x.Y\n")

    assert bench_config().devices == {"ssh1": {"driver": "x.Y"}}


def test_a_percent_sign_in_a_value_is_kept_verbatim(bench_path):
    bench_path.write_text("[ssh1]\ndriver = x.Y\npath = C:\\x\\%temp%\n", encoding="utf-8")

    assert bench_config().devices["ssh1"]["path"] == "C:\\x\\%temp%"


# --- discarding -------------------------------------------------------------


def test_a_file_that_is_not_ini_is_discarded_with_the_reason(bench_path, caplog):
    bench_path.write_text("not an ini file at all\n", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        result = bench_config()

    assert result.outcome is BenchOutcome.DISCARDED
    assert result.devices == {}
    assert "cannot be read" in (result.problem or "")
    assert "no devices" in caplog.text


def test_a_file_that_cannot_be_opened_is_discarded_with_its_own_reason(bench_path):
    # A directory at the file's path: exists() is true, open() raises OSError.
    bench_path.mkdir()

    result = bench_config()

    assert result.outcome is BenchOutcome.DISCARDED
    assert "cannot be opened" in (result.problem or "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit_tests/test_bench_config.py -v`
Expected: collection error — `ModuleNotFoundError`/`ImportError` for `pypts.config_handler.bench_config`.

- [ ] **Step 3: Add the location**

In `src/pypts/config_handler/file_locations.py`, after `CONFIG_FILE_NAME` (line 58):

```python
#: The bench file beside config.ini: one section per device, bare name.
BENCH_FILE_NAME = "bench.ini"
```

After `config_file_path()` (line 79):

```python
def bench_file_path() -> Path:
    """
    Full path of the bench file - the devices - whether or not it exists yet.

    Monkeypatch this in tests, the way `config_file_path` is monkeypatched.
    """
    return config_dir() / BENCH_FILE_NAME
```

Also add `bench.ini` to the location listing in the module docstring (the Windows/Linux block at lines 23-28): it lives in the same directory as `config.ini`.

- [ ] **Step 4: Create the template**

Create `src/pypts/config_handler/bench_template.ini` (comments only — this is the exact content; it is the current hardware block of `config_template.ini`, de-prefixed and reworded for its own file):

```ini
# The devices on this bench, one section each, by logical name. Test code asks
# for a device by that name: pypts.hal.get_device("ssh1"). `driver` names the
# driver class; every other key goes to the driver. Optional: `call_timeout_s`
# (default 60). Keys named like a password are never written to the log, but
# this file is plain text: prefer key_filename to password.
#
# [ssh1]
# driver = pypts.hal.drivers.ssh.SshDriver
# host = 192.168.0.10
# username = tester
# key_filename = C:\Users\tester\.ssh\id_ed25519
```

- [ ] **Step 5: Write the reader**

Create `src/pypts/config_handler/bench_config.py`:

```python
"""
The bench file: which devices are on this bench.

`bench.ini` lives beside `config.ini` and holds one section per device, bare
name: `[ssh1]`. Nothing in it is typed or mandatory - every value is kept as
text for the hardware layer (`hal/hal.md` -> Configuration) - so it needs none
of ConfigHandler's machinery: no schema, no structure version, no roles and no
writer. Nothing in pypts ever writes a device section; the file is the user's.

One entry point: `bench_config()`, computed once per process. The launcher
calls it first, after logging is up - so unlike `ConfigHandler.bootstrap()` it
never buffers its log lines - and shows the operator a notice if the file was
discarded. The hardware layer reads the devices from the same cached result on
the first `get_device()` of a run, so a hand edit applies from the next start,
the same rule as config.ini.
"""

import configparser
import logging
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pypts.config_handler import file_locations, template_writer

#: The root logger, the way `config_handler.py` logs. Not `pypts.logger.log`:
#: that module imports the message layer, which this package must not depend on.
log = logging.getLogger()

#: Name of the template shipped inside this package: the comments a new
#: bench.ini starts with. It declares no device.
BENCH_TEMPLATE_FILE_NAME = "bench_template.ini"


class BenchOutcome(Enum):
    """What bench_config() found."""

    #: No file existed; one was written from the template, declaring no device.
    CREATED = "created"
    #: The file was read; its sections are the devices, verbatim.
    LOADED = "loaded"
    #: The file exists but cannot be used, or could not be created: there are
    #: no devices this start, and `problem` says why.
    DISCARDED = "discarded"


@dataclass(frozen=True)
class BenchConfig:
    """The devices of this bench, as bench.ini declares them."""

    #: Logical name -> the section's keys, every value as text.
    devices: dict[str, dict[str, str]]
    outcome: BenchOutcome
    #: Why the file was discarded; None unless `outcome` is DISCARDED.
    problem: str | None
    path: Path


_lock = threading.Lock()
_cached: BenchConfig | None = None


def bench_config() -> BenchConfig:
    """
    The bench file, read - or created from the template - once per process.

    Never raises: a file that cannot be used is DISCARDED, with the reason in
    `problem`, and the start simply has no devices.
    """
    global _cached
    with _lock:
        if _cached is None:
            _cached = _read_or_create()
        return _cached


def reset_for_testing() -> None:
    """Forget the cached result. Only tests may call this."""
    global _cached
    with _lock:
        _cached = None


def _read_or_create() -> BenchConfig:
    path = file_locations.bench_file_path()
    if not path.exists():
        return _create(path)

    parser = configparser.ConfigParser(interpolation=None)
    try:
        # Not parser.read(path): that swallows OSError per-file and returns an
        # empty parser, which would misread as a bench with no devices. Opening
        # explicitly makes "exists but cannot be opened" its own reason.
        # utf-8-sig, because this file is meant to be edited by hand and
        # Notepad writes a BOM by default. Interpolation is off: a Windows
        # path or a password may legitimately contain a `%`.
        with open(path, encoding="utf-8-sig") as bench_file:
            parser.read_file(bench_file)
    except OSError as error:
        return _discarded(path, f"{path} exists but cannot be opened: {error}.")
    except configparser.Error as error:
        return _discarded(path, f"{path} cannot be read as an INI file: {error}.")

    devices = {section: dict(parser[section]) for section in parser.sections()}
    log.debug("Bench file %s declares %d device(s).", path, len(devices))
    return BenchConfig(devices=devices, outcome=BenchOutcome.LOADED, problem=None, path=path)


def _create(path: Path) -> BenchConfig:
    template_path = Path(__file__).parent / BENCH_TEMPLATE_FILE_NAME
    try:
        template_writer.write(path, template_path.read_text(encoding="utf-8"))
    except OSError as error:
        return _discarded(
            path, f"No bench file at {path}, and one could not be created: {error}."
        )
    log.info("No bench file was found; an empty one was created at %s.", path)
    return BenchConfig(devices={}, outcome=BenchOutcome.CREATED, problem=None, path=path)


def _discarded(path: Path, problem: str) -> BenchConfig:
    log.error(
        "The bench file is not usable, so this start has no devices. %s "
        "Correct it, or delete it to have it recreated.",
        problem,
    )
    return BenchConfig(devices={}, outcome=BenchOutcome.DISCARDED, problem=problem, path=path)
```

- [ ] **Step 6: Re-export from the package**

In `src/pypts/config_handler/__init__.py`, add to the imports and `__all__` (keep both alphabetical):

```python
from pypts.config_handler.bench_config import BenchConfig, BenchOutcome, bench_config
```

```python
__all__ = [
    "BenchConfig",
    "BenchOutcome",
    "BootstrapOutcome",
    "ConfigError",
    "ConfigFileMissing",
    "ConfigHandler",
    "ConfigKeyError",
    "ConfigSchemaError",
    "ConfigWriteError",
    "Role",
    "bench_config",
]
```

Add one sentence to the package docstring: the devices of the bench live in their own file, `bench.ini`, read by `bench_config.py`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_bench_config.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the other gates**

Run: `pytest tests && ruff check src tests && mypy`
Expected: everything passes (nothing existing is touched yet).

- [ ] **Step 9: Commit**

```bash
git add src/pypts/config_handler/file_locations.py src/pypts/config_handler/bench_template.ini src/pypts/config_handler/bench_config.py src/pypts/config_handler/__init__.py tests/unit_tests/test_bench_config.py
git commit -m "Add bench.ini reader: the bench's devices in their own file

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: The launcher's startup notice

**Files:**
- Modify: `src/pypts/launcher/startup.py` (imports at :35, new helper near `show_config_popup` at :417, one call in `start_engine` after the run-log header around :325)
- Test: `tests/unit_tests/test_startup.py`

**Interfaces:**
- Consumes: `pypts.config_handler.bench_config() -> BenchConfig`, `BenchOutcome`, `BenchConfig` (Task 1); existing `show_config_popup(mode, title, text, *, warning)`.
- Produces: `startup.show_bench_notice(mode: str) -> None` (module-level function).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit_tests/test_startup.py`, next to the existing `show_config_popup` tests (after line 76; follow that file's import style):

```python
def test_a_discarded_bench_file_shows_a_warning_notice(monkeypatch):
    from pathlib import Path

    from pypts.config_handler import BenchConfig, BenchOutcome

    shown = []
    monkeypatch.setattr(
        startup,
        "show_config_popup",
        lambda mode, title, text, *, warning: shown.append((mode, title, text, warning)),
    )
    monkeypatch.setattr(
        startup,
        "bench_config",
        lambda: BenchConfig(
            devices={},
            outcome=BenchOutcome.DISCARDED,
            problem="the reason",
            path=Path("bench.ini"),
        ),
    )

    startup.show_bench_notice("gui")

    assert len(shown) == 1
    mode, title, text, warning = shown[0]
    assert mode == "gui"
    assert warning is True
    assert "the reason" in text
    assert "bench.ini" in text


def test_a_loaded_or_created_bench_file_shows_no_notice(monkeypatch):
    from pathlib import Path

    from pypts.config_handler import BenchConfig, BenchOutcome

    shown = []
    monkeypatch.setattr(
        startup,
        "show_config_popup",
        lambda mode, title, text, *, warning: shown.append(title),
    )
    for outcome in (BenchOutcome.LOADED, BenchOutcome.CREATED):
        monkeypatch.setattr(
            startup,
            "bench_config",
            lambda outcome=outcome: BenchConfig(
                devices={}, outcome=outcome, problem=None, path=Path("bench.ini")
            ),
        )
        startup.show_bench_notice("gui")

    assert shown == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit_tests/test_startup.py -v -k bench`
Expected: FAIL — `startup` has no attribute `show_bench_notice` / `bench_config`.

- [ ] **Step 3: Implement**

In `src/pypts/launcher/startup.py`:

Extend the import at line 35:

```python
from pypts.config_handler import BenchOutcome, BootstrapOutcome, ConfigHandler, bench_config
```

Add next to `show_config_popup` (after it, around line 440):

```python
def show_bench_notice(mode: str) -> None:
    """
    Tell the operator when bench.ini was discarded; silent otherwise.

    Called once logging is up, so the reader's own ERROR line is already in
    the run log; this is the popup (GUI) or banner (elsewhere) on top of it.
    A created or loaded bench file needs no notice - creating one is the
    normal first start.
    """
    bench = bench_config()
    if bench.outcome is not BenchOutcome.DISCARDED:
        return
    show_config_popup(
        mode,
        "pypts bench file discarded",
        f"The bench file could not be used:\n\n"
        f"{bench.problem}\n\n"
        f"This start has no devices; a step that asks for one will fail.\n"
        f"Correct it, or delete it to have it recreated:\n{bench.path}",
        warning=True,
    )
```

In `start_engine()`, inside the `try:` block, directly after `log_run_log_header(mode, log_file_path)` (line 325):

```python
        # The bench file: read once, after logging, so its lines reach the
        # run log directly. A discarded file is the operator's to fix; the
        # engine still starts, with no devices.
        show_bench_notice(mode)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_startup.py -v`
Expected: all PASS (the new two and the existing ones).

- [ ] **Step 5: Keep the test suite off the real bench.ini**

`start_engine()` now reaches `bench_config()`, which falls back to the real
`%LOCALAPPDATA%\pypts\bench.ini` unless a test points it elsewhere — the config tests
only patch `config_file_path`. Find every test or fixture that bootstraps the real engine
or patches `file_locations.config_file_path` for an end-to-end path:

```bash
grep -rn "config_file_path" tests/
```

Wherever a test can reach `bench_config()` (functional tests, engine/startup fixtures —
not the pure config-handler unit tests), add the twin patch and a cold cache, mirroring
the `bench_path` fixture of Task 1:

```python
monkeypatch.setattr(file_locations, "bench_file_path", lambda: tmp_path / "bench.ini")
bench_config_module.reset_for_testing()
```

If a shared fixture in a `conftest.py` already isolates the config path for those tests,
extend that fixture instead of each test. Then run the whole suite and check no
`bench.ini` appeared in the real per-user directory:

Run: `pytest tests`
Expected: all PASS, and no new file at the real `bench_file_path()` location.

- [ ] **Step 6: Commit**

```bash
git add src/pypts/launcher/startup.py tests/unit_tests/test_startup.py
git commit -m "Show a startup notice when bench.ini was discarded

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: HAL reads bench.ini, and its errors become honest

**Files:**
- Modify: `src/pypts/hal/local_setup.py` (docstring; `split_section` messages at :41-50; functions at :67-97; `from_ini` at :117-120; `get_device` message at :135-140)
- Modify: `src/pypts/sequencer/sequencer.py` (import at :29, docstring at :122, comment + default at :143-148)
- Test: `tests/unit_tests/test_hal.py`

**Interfaces:**
- Consumes: `bench_config()`, `BenchOutcome` from `pypts.config_handler.bench_config` (Task 1).
- Produces:
  - `local_setup.bench_sections() -> dict[str, dict[str, str]]` — the Sequencer's default provider; raises `DriverError` when the bench file was discarded.
  - `local_setup.ini_device_sections(path) -> dict[str, dict[str, str]]` — every section of the given INI is a device (bench.ini format). Replaces `ini_hardware_sections`.
  - `hardware_sections()` and `hardware_sections_from_config()` are **deleted**.
  - The Sequencer attribute keeps its name: `self.read_hardware_sections` (tests in `test_sequencer.py` replace it; do not rename).

- [ ] **Step 1: Update the tests first**

In `tests/unit_tests/test_hal.py`:

Change the import at lines 36-39 from `hardware_sections, hardware_sections_from_config, ini_hardware_sections` to:

```python
    bench_sections,
    ini_device_sections,
```

Change the regex at line 258 to:

```python
    words = r"Device 'x'.*'python' key.*Remove it from the \[x\] section"
```

Replace the three tests at lines 263-284 with:

```python
def test_ini_device_sections_reads_every_section_as_a_device(tmp_path):
    path = tmp_path / "setup.ini"
    path.write_text("[loop1]\ndriver = pkg.Loop\n[dmm1]\ndriver = pkg.Dmm\n", encoding="utf-8")
    assert ini_device_sections(path) == {
        "loop1": {"driver": "pkg.Loop"},
        "dmm1": {"driver": "pkg.Dmm"},
    }


def test_bench_sections_returns_the_devices_of_the_bench_file(monkeypatch):
    from pathlib import Path

    import pypts.config_handler.bench_config as bench_module
    from pypts.config_handler import BenchConfig, BenchOutcome

    monkeypatch.setattr(
        bench_module,
        "bench_config",
        lambda: BenchConfig(
            devices={"loop1": {"driver": "pkg.Loop"}},
            outcome=BenchOutcome.LOADED,
            problem=None,
            path=Path("bench.ini"),
        ),
    )

    assert bench_sections() == {"loop1": {"driver": "pkg.Loop"}}


def test_bench_sections_raises_when_the_bench_file_was_discarded(monkeypatch):
    from pathlib import Path

    import pypts.config_handler.bench_config as bench_module
    from pypts.config_handler import BenchConfig, BenchOutcome

    monkeypatch.setattr(
        bench_module,
        "bench_config",
        lambda: BenchConfig(
            devices={},
            outcome=BenchOutcome.DISCARDED,
            problem="it is broken",
            path=Path("bench.ini"),
        ),
    )

    with pytest.raises(DriverError, match="discarded.*it is broken"):
        bench_sections()
```

Then grep the whole test file for other assertions on the old messages and update them to the new wording defined in Step 3:

```bash
grep -n "hardware\|config.ini" tests/unit_tests/test_hal.py
```

Any test asserting `"Add a [hardware.<name>] section to config.ini"` now expects `"Add a [<name>] section to bench.ini"`; any asserting `"[hardware.{name}] has no 'driver' key"` now expects `"the [{name}] section has no 'driver' key"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit_tests/test_hal.py -v`
Expected: ImportError on `bench_sections` / `ini_device_sections`.

- [ ] **Step 3: Implement in `local_setup.py`**

Module docstring (lines 1-14): replace the first paragraph's `[hardware.<name>]` wording with: a LocalSetup reads its devices from bench.ini's sections — one per device, bare name — opens a device the first time it is asked for, and closes every device it opened when it is closed. Keep the `from_ini("bench.ini")` sentence and the lazy-import paragraph.

In `split_section` (lines 32-50) — docstring now says "One device section as (driver class path, call timeout, the driver's own keys)". The two messages become:

```python
    if "python" in settings:
        raise DriverError(
            f"Device '{name}': the 'python' key is not supported any more - every driver runs "
            f"on PyPTS's own Python. Remove it from the [{name}] section."
        )
    driver_path = settings.pop("driver", "").strip()
    if not driver_path:
        raise DriverError(
            f"Device '{name}': the [{name}] section has no 'driver' key naming its driver class."
        )
```

Replace `hardware_sections()`, `ini_hardware_sections()` and `hardware_sections_from_config()` (lines 67-97) with:

```python
def ini_device_sections(path: str | os.PathLike[str]) -> dict[str, dict[str, str]]:
    """
    The devices of an INI file of one's own - a setup outside PyPTS.

    The file has bench.ini's format: every section is one device, bare name.
    Read as utf-8-sig so a file saved by Notepad, BOM and all, still opens.
    """
    parser = configparser.ConfigParser(interpolation=None)
    with open(path, encoding="utf-8-sig") as handle:
        parser.read_file(handle)
    return {section: dict(parser[section]) for section in parser.sections()}


def bench_sections() -> dict[str, dict[str, str]]:
    """
    The devices of this machine's bench.ini - what the Sequencer reads.

    Raises:
        DriverError: the bench file was discarded at startup; the message
            carries the real reason, so the step's error names the file to
            fix rather than a section to add.
    """
    from pypts.config_handler.bench_config import BenchOutcome, bench_config

    bench = bench_config()
    if bench.outcome is BenchOutcome.DISCARDED:
        raise DriverError(
            f"bench.ini was discarded at startup, so this start has no devices: {bench.problem}"
        )
    return bench.devices
```

In `from_ini` (lines 117-120):

```python
    @classmethod
    def from_ini(cls, path: str | os.PathLike[str]) -> "LocalSetup":
        """A local setup described by an INI file in bench.ini's format: one section per device."""
        return cls(lambda: ini_device_sections(path))
```

In `get_device` (lines 135-140), the unknown-device message becomes:

```python
                raise DriverError(
                    f"No device '{name}' is configured. Add a [{name}] section to "
                    f"bench.ini. Configured devices: {known}."
                )
```

- [ ] **Step 4: Implement in `sequencer.py`**

Line 29: import `bench_sections` instead of `hardware_sections_from_config`.

Docstring line 122-123 becomes:

```
        read_hardware_sections: returns the device sections of bench.ini by
              logical name; handed to the LocalSetup each run builds.
```

Lines 143-148 become:

```python
        #: Where a run's devices are declared - the sections of bench.ini.
        #: Read only when test code first asks for a device, so a run that
        #: uses none never reads them. Tests replace it.
        self.read_hardware_sections: Callable[[], Mapping[str, Mapping[str, Any]]] = (
            bench_sections
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal.py tests/unit_tests/test_sequencer.py -v`
Expected: all PASS. Then the full suite: `pytest tests` — fix any other test still asserting the old messages (search: `grep -rn "hardware\." tests/`).

- [ ] **Step 6: Run ruff and mypy**

Run: `ruff check src tests && mypy`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/pypts/hal/local_setup.py src/pypts/sequencer/sequencer.py tests/unit_tests/test_hal.py
git commit -m "HAL reads its devices from bench.ini

The Sequencer's default sections provider is bench_sections(), which
raises a DriverError naming the real reason when the bench file was
discarded. Device error messages name bench.ini and bare sections.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: config.ini's clean break

**Files:**
- Modify: `src/pypts/config_handler/config_handler.py` (import at :52, the branch at :590-595)
- Modify: `src/pypts/config_handler/configuration_schema.py` (comments at :137-146)
- Modify: `src/pypts/config_handler/config_template.ini` (lines 52-62)
- Test: `tests/unit_tests/test_config_handler.py` (test at :475-489)

**Interfaces:**
- Consumes: `HARDWARE_PREFIX`, `is_hardware_section()` (exist; both survive solely for the warning).
- Produces: no new names. **`CONFIG_VERSION` unchanged.**

- [ ] **Step 1: Update the test first**

In `tests/unit_tests/test_config_handler.py`, replace `test_a_hardware_section_is_kept_as_text_without_a_warning` (lines 475-489) with:

```python
def test_a_leftover_hardware_section_is_pointed_at_bench_ini(config, config_path, caplog):
    """Device sections moved to bench.ini; one left behind gets a WARNING saying where."""
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[hardware.dmm1]\ndriver = nidmm\nresource = PXI1Slot2\ntimeout_s = 2.5\n",
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with caplog.at_level(logging.WARNING):
        reopened = ConfigHandler.bootstrap()

    # Still an unknown section kept as text - but warned about, with the cure.
    assert reopened.get_parameter("hardware.dmm1.driver") == "nidmm"
    assert caplog.text.count("moved to bench.ini") == 1
    assert "[dmm1]" in caplog.text
```

Leave the secret-masking and set_parameter tests at lines 492-540 as they are: a `[hardware.*]` section is still kept as text, so they keep passing.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit_tests/test_config_handler.py -v -k leftover`
Expected: FAIL — no WARNING is logged (the current code logs DEBUG).

- [ ] **Step 3: Implement**

In `src/pypts/config_handler/config_handler.py`, extend the import at line 52 to include `HARDWARE_PREFIX`, and replace the hardware branch at lines 590-595 with:

```python
                if is_hardware_section(section):
                    self._note(
                        logging.WARNING,
                        f"Configuration section [{section}] declares a device, but device "
                        f"sections have moved to bench.ini, next to config.ini. Move it "
                        f"there as [{section[len(HARDWARE_PREFIX):]}] - without the "
                        f"'hardware.' prefix - and delete it here; nothing reads it from "
                        f"config.ini any more.",
                    )
```

In `src/pypts/config_handler/configuration_schema.py`, replace the comment above `HARDWARE_PREFIX` (lines 137-140) and the docstring of `is_hardware_section` so they say: device sections lived in config.ini until October 2026 and are in bench.ini now; the prefix and this check survive only so a leftover section gets a WARNING pointing there (`config_handler._validate`).

In `src/pypts/config_handler/config_template.ini`, replace lines 52-62 (the whole commented device block) with:

```ini
# Devices are not declared here: they live in bench.ini, in this same folder,
# one bare [<logical name>] section per device.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_config_handler.py -v`
Expected: all PASS. Also check nothing asserts the old DEBUG note: `grep -rn "declares a device" tests/`.

- [ ] **Step 5: Run the full gates**

Run: `pytest tests && ruff check src tests && mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/pypts/config_handler/config_handler.py src/pypts/config_handler/configuration_schema.py src/pypts/config_handler/config_template.ini tests/unit_tests/test_config_handler.py
git commit -m "Warn about leftover [hardware.*] sections in config.ini

Device sections live in bench.ini now; a section left behind gets a
one-time WARNING with the move instructions and is otherwise an
ordinary unknown section. CONFIG_VERSION is unchanged - nothing new
is mandatory.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: GUI wording

**Files:**
- Modify: `src/pypts/hmi/gui/settings_dialog.py` (:807-810)
- Modify: `src/pypts/hmi/gui/gui.py` (comment at :452)

**Interfaces:** none — text only, no behaviour change. `_restore_default_settings()` still deletes only config.ini, which is now correct by itself: bench.ini is never touched.

- [ ] **Step 1: Update the restore-defaults confirmation**

In `src/pypts/hmi/gui/settings_dialog.py`, `confirm_restore_defaults` (lines 807-810), the message becomes:

```python
        "Put every setting back to its default value?\n\n"
        "config.ini is recreated from the template and pypts restarts. "
        "Changes not saved yet are lost. The devices in bench.ini are not touched.",
```

- [ ] **Step 2: Update the restart comment**

In `src/pypts/hmi/gui/gui.py` line 452, the comment becomes:

```python
        # a hand edit (a bench.ini device section, say) applies after a restart.
```

- [ ] **Step 3: Run the gates**

Run: `pytest tests && ruff check src tests && mypy`
Expected: clean. If a GUI test asserts the old dialog text (`grep -rn "hardware" tests/unit_tests/test_gui*.py tests/`), update it to the new text.

- [ ] **Step 4: Commit**

```bash
git add src/pypts/hmi/gui/settings_dialog.py src/pypts/hmi/gui/gui.py
git commit -m "Restore default settings no longer claims to remove devices

bench.ini is a separate file now and restoring config.ini defaults
never touches it.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Documentation moves with the code

**Files:**
- Modify: `src/pypts/config_handler/config_handler.md`
- Modify: `src/pypts/hal/hal.md` (Configuration section at :76-105, error table at :161)
- Modify: `src/pypts/sequencer/sequencer.md` (:62-65)
- Modify: `src/pypts/hmi/gui/gui.md` (:756, and any restore-default mention)
- Modify: `usage_manual.html` (repo root)
- Modify: `pypts_implementation_status.html` (repo root)
- Modify: `resources/internal_reports/codebase_review_2026-10-14.html` (finding #11)
- Modify: `CLAUDE.md` (the Config line under *Running*)
- Check: `TODO.txt`, `recipe_guide.html`

Every statement written must be verified against the final code — identifiers, file names, messages. Delete what is no longer true; no stale sentence beside a corrected one.

- [ ] **Step 1: `config_handler.md`**

- File table: add `bench_config.py` ("the bench file: devices, verbatim, read once per process") and `bench_template.ini` ("the comments a new bench.ini starts with; declares no device").
- Replace the **Hardware sections** paragraph (lines 127-133) with a short **The bench file** section: bench.ini beside config.ini, bare `[<name>]` sections, `bench_config()` -> `BenchConfig` (`devices` / `outcome` `CREATED`/`LOADED`/`DISCARDED` / `problem` / `path`), cached per process, created from `bench_template.ini` when missing, discarded (empty devices, reason logged at ERROR, launcher notice) when unreadable or not INI, never written by pypts, no version. A leftover `[hardware.*]` section in config.ini gets a one-time WARNING pointing at bench.ini.
- Lifecycle diagram: add `show_bench_notice(...)` after `init_logging`/`replay_bootstrap_log`.
- "The file" location block: add bench.ini next to config.ini.
- "Who uses it" table: launcher row gains `show_bench_notice()`; add a `hal/local_setup.py` row (`bench_sections()` -> `bench_config()`).
- Reading example at line 142: delete the `hardware.dmm1.timeout_s` line (a leftover hardware key is just an unknown-section key now; say so if an example is kept).
- Known gaps: "Device sections are untyped" stays true — reword to name bench.ini.

- [ ] **Step 2: `hal/hal.md`**

Rewrite the Configuration section (lines 76-105): the example becomes a bare `[ssh1]` section in bench.ini; `config_handler` paragraph (lines 94-98) is replaced by: bench.ini is read by `config_handler/bench_config.py`, once per process, everything text, nothing mandatory; keys lower-cased; secrets masked in the log as before. State the discard behaviour: a broken bench.ini means a startup notice and `bench_sections()` raising `DriverError` with the reason on the first `get_device()`. Update lines 103-105: a hand edit of bench.ini applies from the next start; Restore default settings does **not** touch bench.ini any more. Update the error table at :161 for the new unknown-device message, and `from_ini` mentions (every section is a device). Update line 111's `with LocalSetup(self.read_hardware_sections):` context if the surrounding words mention config.ini.

- [ ] **Step 3: `sequencer.md` and `gui.md`**

- `sequencer.md` lines 62-65: `read_hardware_sections` defaults to `hal.local_setup.bench_sections`, the devices of bench.ini.
- `gui.md` line 756 and any other `[hardware.*]`/config.ini-devices mention (`grep -n "hardware" src/pypts/hmi/gui/gui.md`): devices live in bench.ini; restore default settings leaves them alone.

- [ ] **Step 4: User-facing HTML**

- `usage_manual.html`: `grep -n -i "hardware\|config.ini" usage_manual.html`, then update: the files-on-disk section gains bench.ini (same folder as config.ini, one bare section per device, created empty on first start); the settings/restore-default text matches the new dialog wording; the startup-notices part mentions the bench-file-discarded notice; device configuration examples lose the `hardware.` prefix.
- `recipe_guide.html`: `grep -n -i "hardware\|config.ini" recipe_guide.html`; update only sentences that place device sections in config.ini — the recipe format itself is unchanged, so no verificator change (the sync rule in `recipe_creator.md` is not triggered).
- `pypts_implementation_status.html`: add a numbered status entry in the style of its neighbours (see §1.74/§1.75): device sections moved from config.ini to bench.ini — done, dated, from the codebase review (#11), naming `bench_config.py`, the clean break (WARNING for leftovers), the launcher notice and the honest `DriverError`; context pointers to `config_handler/config_handler.md` and `hal/hal.md`.
- `resources/internal_reports/codebase_review_2026-10-14.html`: finding #11's card — class `card medium` → `card done`, status chip `open` → `fixed`, and replace its `Solution` with a `Now` entry stating what was done (bench.ini split; discarded config.ini no longer touches devices; errors name the real cause). Decrement the "medium/low still open" stat by one. Update any cross-reference to #11 (`grep -n "#11" resources/internal_reports/codebase_review_2026-10-14.html`).

- [ ] **Step 5: `CLAUDE.md` and `TODO.txt`**

- `CLAUDE.md`, the *Running* section's Config line: mention both files, e.g. `Config: %LOCALAPPDATA%\pypts\{config.ini, bench.ini} / ~/.config/pypts/{config.ini, bench.ini}`. Also update the architecture sketch's `config_handler/` line (`per-user config.ini` → `per-user config.ini + bench.ini (devices)`).
- `TODO.txt`: `grep -n -i "hardware\|config" TODO.txt`; if an item covers this split or finding #11, mark it `[x]` with a one-line note. Never delete items.

- [ ] **Step 6: Full gates + documentation check**

Run: `pytest tests && ruff check src tests && mypy`
Expected: clean.

Documentation check: re-read every document touched in this plan against the final code — every identifier and file a document names must exist (`bench_config.py`, `bench_sections`, `ini_device_sections`, `show_bench_notice`, `BENCH_FILE_NAME`, the exact log/ error messages). List in the final report which documents were updated.

- [ ] **Step 7: Commit**

```bash
git add src/pypts/config_handler/config_handler.md src/pypts/hal/hal.md src/pypts/sequencer/sequencer.md src/pypts/hmi/gui/gui.md usage_manual.html pypts_implementation_status.html resources/internal_reports/codebase_review_2026-10-14.html CLAUDE.md TODO.txt recipe_guide.html
git commit -m "Document the bench.ini split

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(Drop `TODO.txt` / `recipe_guide.html` from the add list if they needed no change.)
