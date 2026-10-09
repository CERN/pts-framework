# HAL — Devices in Driver Processes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Project rule overrides the skill template:** there are **no commit steps**. Never `git add`,
> `git commit` or `git mv` (which stages). The user commits everything themselves.

**Goal:** Test code reaches bench devices by logical name — `pypts.hal.get_device("ssh1")` —
each device running its driver in a process of its own, with SSH as the first real driver.

**Architecture:** `src/pypts/hardware_layer/` becomes `src/pypts/hal/`. A driver is a plain
class derived from one of six family bases (PSU, DMM, Scope, SSH, Load, Other). A `Bench`
reads `[hardware.<name>]` sections from `config.ini`, and on the first `get_device(name)` a
`DriverProxy` starts `python -m pypts.hal.runner`, which connects back over TCP on 127.0.0.1
and answers JSON-line calls; the driver's log records and printed output come back into the
PyPTS run log. The Sequencer enters one `Bench` per run (one Start press: one top-level
sequence and every sequence it calls) and closes every device when the run ends.

**Tech Stack:** Python 3.11 standard library (`socket`, `subprocess`, `json`, `threading`,
`configparser`), `paramiko` for the SSH driver only (optional extra `pts-framework[ssh]`).

**Spec:** there is no separate spec document. The decisions below were taken with the user on
2026-10-08 and *are* the spec; they supersede the "Agreed shape" section of the old
`hardware_layer/hal.md` (in-process library, sidecar only after an incident).

## Decisions (the spec)

| # | Decision |
|---|---|
| D1 | **Every driver runs in its own process** (sidecar), always. No in-process mode. |
| D2 | **Access from test code first**: `from pypts.hal import get_device`; `get_device("ssh1")` inside a run. Recipe-level access (a `devices:` key on a step) is **designed, not built**: recorded in `hal.md` and the roadmap as a TODO. |
| D3 | **Lifetime per run** — a run is one Start press: one top-level sequence plus the sequences it calls. Devices open lazily on first `get_device()`, all close when the run ends (after teardown steps), whatever the result. |
| D4 | **Standalone use**: `with Bench.from_ini("bench.ini"):` activates a bench outside PyPTS, so the same test functions work in a plain script. |
| D5 | **Families**: `PSU`, `DMM`, `Scope`, `SSH`, `Load`, `Other`. SSH gets its full verb set; PSU/DMM/Scope/Load get a minimal abstract verb set (listed in Task 2 — **for the user's review**); Other has none. A driver must derive from a family. |
| D6 | **Package**: `src/pypts/hardware_layer/` moves to `src/pypts/hal/`; `hal.py` (design notes only) is deleted; `hal.md` stays the context file. |
| D7 | **Failure**: a dead or timed-out driver process makes the call raise `DriverError`, so the step ends ERROR through the normal step path. No automatic recovery. `device.recover()` is callable from test code: it calls the driver's `recover()`, or starts a fresh process if the old one is gone. |
| D8 | **Logging**: the driver process forwards its log records over the connection; the proxy logs them in CORE as `Device '<name>': <message>`. Records from the driver's own module keep their level; records from other libraries below WARNING are logged at DEBUG. Everything the process prints is drained and logged at DEBUG. |
| D9 | **SSH security**: unknown host keys are refused (system `known_hosts` plus optional `known_hosts =` file); `accept_unknown_host = true` opts out per device. `password` is allowed but plain text; `key_filename` preferred. Secret-looking keys are never written to the log. |
| D10 | **Dependencies**: `paramiko` → `[ssh]`, `nidmm` + `hightime` → `[ni]`, `pyserial` → `[serial]`, `[hardware]` = all three. `nptdms` is **removed** (only `spikes/` use it). |
| D11 | **Extras in scope**: a demo recipe + test module; headless/API runs get the HAL for free (it lives in the Sequencer) and the docs say so. |
| D12 | `CONFIG_VERSION` is **not** changed: nothing mandatory is added. `[hardware.<name>]` sections become recognised (no WARNING), values stay text. |

## Global Constraints

- Python ≥ 3.11; ruff line length 100; `ruff check src tests`, `mypy`, `pytest tests` must pass.
- Logging is `%`-style, never f-strings (`G004`). Wording per `src/pypts/logger/logging_rules.md`:
  sentence case, full stop, names in single quotes, ASCII only; INFO+ is for the technician,
  everything developer-facing is DEBUG.
- `pypts.hal.driver`, `families`, `protocol`, `runner` and `drivers/*` import **only the
  standard library and `pypts.hal`** (+ the driver's own vendor library). The driver process
  imports `pypts.hal/__init__.py`, so that file and everything it imports at module level
  (`proxy.py`, `bench.py` → `pypts.logger.log`, `pypts.messages`, `pypts.utilities.common`)
  must stay standard-library-only too. `bench.py` imports `pypts.config_handler` **lazily,
  inside functions**, never at module level.
- No inline SPDX header in `src/pypts/**/*.py` or `tests/**/*.py` (`reuse.toml` covers them).
  `hal.md`, `.yml` files under `resources/` and repo-root HTML keep their inline headers.
- A `# noqa:` names an enabled rule and gives the reason on the same line.
- Old-school plain Python: `if`/`else` over conditional expressions, named locals.
- Never `git checkout` a file to undo an experiment. Move files with the shell, not `git mv`.
- Do not change `CONFIG_VERSION`. Do not import `helper_applications/debug_monitor/`.
- Use the `Edit` tool for file edits (exact string replacement); the old strings below are
  quoted from the current source.
- **"Append" with imports:** when a test snippet to append begins with `import`/`from` lines,
  put those lines into the file's top import block and append only the rest (ruff `E402`,
  `I001`). Let `ruff check --fix` sort them.
- **Unused `noqa`:** ruff's `RUF100` is enabled. If ruff reports a `# noqa: BLE001` (or any
  other) in this plan's code as unused, delete that `noqa` — do not add a broader one.

## Review Focus

The input classes and failure modes most likely to bite a real bench that no task's
happy-path tests cover. Each line has its pinning test in the task named.

1. **PyPTS dies hard (killed, crash) while a device is open** — the driver process must notice
   the dropped connection and exit, never linger holding the instrument. → Task 4,
   `test_the_runner_exits_when_its_connection_drops`.
2. **Non-ASCII and large payloads** (`5 µA ± 2 °C`, a 1 MB command output) — must arrive
   intact through the line protocol. → Task 5, `test_non_ascii_and_large_values_round_trip`.
3. **Test code calls `get_device()` from a thread it started itself** — must get the run's
   device, not "no bench is active". → Task 7, `test_get_device_works_from_another_thread`.
4. **PyPTS run from a source tree** (`run_pypts.py`, nothing installed) — the driver process
   must still import `pypts`. → Task 5, `test_the_child_environment_carries_this_sys_path`.
5. **A password in `[hardware.<name>]`** — must never reach the run log, neither from the
   configuration dump nor from the proxy's call trace. → Task 6
   `test_a_secret_is_masked_in_the_active_configuration_lines`, Task 5
   `test_connect_settings_are_masked_in_the_trace`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Move | `src/pypts/hardware_layer/` → `src/pypts/hal/` | Package rename (D6) |
| Delete | `src/pypts/hal/hal.py` | Design notes, superseded by `hal.md` |
| Rewrite | `src/pypts/hal/__init__.py` | Public API |
| Create | `src/pypts/hal/driver.py` | `Driver`, `DriverError`, `LIFECYCLE_METHODS`, `operations_of()` |
| Create | `src/pypts/hal/families.py` | `PSU`, `DMM`, `Scope`, `SSH`, `Load`, `Other`, `FAMILIES`, `FAMILY_NAMES` |
| Create | `src/pypts/hal/protocol.py` | Message kinds, `encode()`, `decode()`, `LineReader`, `ProtocolError` |
| Create | `src/pypts/hal/runner.py` | The driver process (`python -m pypts.hal.runner`) |
| Create | `src/pypts/hal/proxy.py` | `DriverProxy`, `child_environment()` |
| Create | `src/pypts/hal/bench.py` | `DeviceConfig`, `Bench`, `get_device()`, section readers |
| Create | `src/pypts/hal/drivers/__init__.py` | Package marker (imports nothing) |
| Create | `src/pypts/hal/drivers/loopback.py` | `LoopbackDriver` (Other) — tests, demo, smoke check |
| Create | `src/pypts/hal/drivers/ssh.py` | `SshDriver` (SSH) — reference driver |
| Rewrite | `src/pypts/hal/hal.md` | Context file |
| Modify | `src/pypts/utilities/common.py` | `SECRET_KEY_WORDS`, `MASK`, `is_secret_key()`, `masked()` |
| Modify | `src/pypts/config_handler/configuration_schema.py` | `HARDWARE_PREFIX`, `is_hardware_section()` |
| Modify | `src/pypts/config_handler/config_handler.py` | Hardware sections without WARNING; secrets masked |
| Modify | `src/pypts/config_handler/config_template.ini` | Commented `[hardware.<name>]` example |
| Modify | `src/pypts/sequencer/sequencer.py` | One `Bench` per run |
| Modify | `pyproject.toml` | Dependencies → extras, `nptdms` removed, mypy scope |
| Create | `resources/recipes/Development_recipes/hal_demo.yml` | Demo recipe |
| Create | `resources/recipes/Development_recipes/hal_demo_tests.py` | Demo test code |
| Create | `tests/unit_tests/test_hal.py` | driver, families, protocol, runner, bench |
| Create | `tests/unit_tests/test_hal_proxy.py` | proxy against real driver processes |
| Create | `tests/unit_tests/test_hal_ssh.py` | SSH driver against a mocked paramiko |
| Create | `tests/unit_tests/hal_test_drivers.py` | Deliberately broken drivers for the proxy tests |
| Modify | `tests/unit_tests/test_config_handler.py`, `test_utilities.py`, `test_sequencer.py`, `test_recipe.py` | New/changed tests |
| Modify | docs: `CLAUDE.md`, `config_handler.md`, `sequencer.md`, `step.md`, `utilities.md`, `usage_manual.html`, `pypts_implementation_status.html`, `TODO.txt` | Documentation moves with the code |

---

## Protocol Reference (read before Tasks 3–5)

The **proxy** listens on `127.0.0.1:<ephemeral port>` and starts:

```
<python> -m pypts.hal.runner --port <n> --driver <dotted.Class> --log-level <int>
```

The **runner** connects back, builds the driver, and sends one `hello` (or `fatal`). After that
the proxy sends `call`s one at a time; the runner may send any number of `log` lines before the
`result`/`error` that answers a call. One JSON object per line, ASCII-encoded (`ensure_ascii`),
newline-terminated:

```json
{"kind": "hello",  "family": "SSH", "operations": ["execute", "get_file", "put_file"]}
{"kind": "fatal",  "message": "ModuleNotFoundError: No module named 'paramiko'"}
{"kind": "call",   "id": 7, "method": "execute", "args": ["uname -a"], "kwargs": {}}
{"kind": "log",    "level": 20, "logger": "pypts.hal.drivers.ssh", "message": "..."}
{"kind": "result", "id": 7, "value": {"stdout": "Linux\n", "stderr": "", "exit_code": 0}}
{"kind": "error",  "id": 7, "type": "TimeoutError", "message": "...", "traceback": "..."}
```

`connect`, `teardown` and `recover` are callable over the wire but not listed in
`operations`. When the connection closes the runner calls `teardown()` and exits — this is also
what happens when PyPTS dies, so a driver process never outlives the framework.

---

### Task 1: Move `hardware_layer/` to `hal/`

**Files:**
- Move: `src/pypts/hardware_layer/` → `src/pypts/hal/`
- Delete: `src/pypts/hal/hal.py`
- Rewrite: `src/pypts/hal/__init__.py`
- Modify: `tests/unit_tests/test_utilities.py:96-102`
- Test: `tests/unit_tests/test_hal.py` (create)

**Interfaces:**
- Produces: importable package `pypts.hal` (empty public API for now).

- [ ] **Step 1: Write the failing test**

Create `tests/unit_tests/test_hal.py`:

```python
"""
Unit tests for the hardware layer (src/pypts/hal/): the driver base and the
families, the wire protocol, the runner's call handling, and the bench.

Nothing here starts a process; test_hal_proxy.py does that.
"""

import importlib

import pytest


def test_the_hal_package_is_importable_and_the_old_one_is_gone():
    importlib.import_module("pypts.hal")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pypts.hardware_layer")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/unit_tests/test_hal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pypts.hal'`.

- [ ] **Step 3: Move the package (shell, not git)**

PowerShell:

```powershell
Move-Item src\pypts\hardware_layer src\pypts\hal
Remove-Item src\pypts\hal\hal.py
if (Test-Path src\pypts\hal\__pycache__) { Remove-Item -Recurse -Force src\pypts\hal\__pycache__ }
```

Replace the whole of `src/pypts/hal/__init__.py` with:

```python
"""
The hardware layer: devices on the bench, reached by logical name.

    from pypts.hal import get_device

    def read_kernel():
        result = get_device("ssh1").execute("uname -r")
        return {"kernel": result["stdout"].strip()}

Every device runs its driver in a process of its own. How it works, the
configuration format and how to write a driver: hal.md beside this file.
"""
```

In `tests/unit_tests/test_utilities.py` the decorator test uses the old module path as an
arbitrary label. Replace both occurrences of `"pypts.hardware_layer.hal"` with
`"pypts.hal.bench"` (lines 96 and 102).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal.py tests/unit_tests/test_utilities.py -v`
Expected: PASS.

- [ ] **Step 5: Fix the references in CLAUDE.md and step.md**

`CLAUDE.md` line 26 — old: ``Still stubs: `hardware_layer/hal.py` (design notes only) and `stream_handler/` (empty).``
new: ``Still a stub: `stream_handler/` (empty).``

`CLAUDE.md` module table — old: ``| `hardware_layer/` | `hardware_layer/hal.md` |`` new: ``| `hal/` | `hal/hal.md` |``

`CLAUDE.md` architecture block — old line: `  hardware_layer/ stream_handler/   stubs` replace with two lines:

```
  hal/           hardware layer: devices by logical name, one driver process each, SSH driver
  stream_handler/   stub
```

`src/pypts/step/step.md` §2.7 is rewritten in Task 11; leave it for now.

---

### Task 2: `Driver`, `DriverError` and the six families

**Files:**
- Create: `src/pypts/hal/driver.py`, `src/pypts/hal/families.py`
- Modify: `src/pypts/hal/__init__.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Produces:
  - `DriverError(Exception)`
  - `LIFECYCLE_METHODS: tuple[str, ...] = ("connect", "teardown", "recover")`
  - `class Driver(ABC)`: `FAMILY: ClassVar[str] = ""`; abstract `connect(self, config: dict[str, str]) -> None`, abstract `teardown(self) -> None`; `recover(self, config: dict[str, str]) -> None` (teardown + connect)
  - `operations_of(driver_class: type) -> list[str]` — sorted public callables minus lifecycle
  - `families.PSU`, `DMM`, `Scope`, `SSH`, `Load`, `Other` (each sets `FAMILY` to its class name), `FAMILIES: tuple[type[Driver], ...]`, `FAMILY_NAMES: tuple[str, ...]`

> **Verb sets for the user's review (D5).** PSU: `set_voltage`, `set_current_limit`,
> `output_on`, `output_off`, `measure_voltage`, `measure_current` (all take `channel: int`,
> from 1). DMM: `measure_dc_voltage`, `measure_ac_voltage`, `measure_dc_current`,
> `measure_resistance`. Scope: `set_timebase`, `set_vertical_scale`, `arm_single`,
> `read_waveform`. Load: `set_mode` (`"CC"`, `"CV"`, `"CR"`, `"CP"`), `set_level`, `input_on`,
> `input_off`, `measure_voltage`, `measure_current`. SSH: `execute`, `put_file`, `get_file`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit_tests/test_hal.py`:

```python
from pypts.hal import DMM, PSU, SSH, Driver, DriverError, Load, Other, Scope
from pypts.hal.driver import LIFECYCLE_METHODS, operations_of
from pypts.hal.families import FAMILIES, FAMILY_NAMES


class _Plain(Other):
    def connect(self, config):
        self.calls = [("connect", config)]

    def teardown(self):
        self.calls.append(("teardown",))

    def measure(self):
        return 1.0

    def _helper(self):
        return 2.0


def test_driver_cannot_be_built_without_connect_and_teardown():
    with pytest.raises(TypeError):
        Driver()  # type: ignore[abstract]


def test_recover_tears_down_then_connects_again():
    driver = _Plain()
    driver.connect({"host": "a"})
    driver.recover({"host": "b"})
    assert driver.calls == [("connect", {"host": "a"}), ("teardown",), ("connect", {"host": "b"})]


def test_operations_are_the_public_methods_without_the_lifecycle():
    assert operations_of(_Plain) == ["measure"]
    assert LIFECYCLE_METHODS == ("connect", "teardown", "recover")


def test_every_family_names_itself():
    assert FAMILY_NAMES == ("PSU", "DMM", "Scope", "SSH", "Load", "Other")
    assert [family.FAMILY for family in FAMILIES] == list(FAMILY_NAMES)
    assert Driver.FAMILY == ""


def test_family_verbs_are_abstract():
    assert operations_of(PSU) == [
        "measure_current",
        "measure_voltage",
        "output_off",
        "output_on",
        "set_current_limit",
        "set_voltage",
    ]
    assert operations_of(DMM) == [
        "measure_ac_voltage",
        "measure_dc_current",
        "measure_dc_voltage",
        "measure_resistance",
    ]
    assert operations_of(Scope) == [
        "arm_single",
        "read_waveform",
        "set_timebase",
        "set_vertical_scale",
    ]
    assert operations_of(Load) == [
        "input_off",
        "input_on",
        "measure_current",
        "measure_voltage",
        "set_level",
        "set_mode",
    ]
    assert operations_of(SSH) == ["execute", "get_file", "put_file"]
    assert operations_of(Other) == []
    with pytest.raises(TypeError):
        SSH()  # type: ignore[abstract]


def test_driver_error_is_an_exception():
    assert issubclass(DriverError, Exception)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_hal.py -v`
Expected: FAIL — `ImportError: cannot import name 'DMM' from 'pypts.hal'`.

- [ ] **Step 3: Write `driver.py`**

```python
"""
The base every driver derives from, and the error the hardware layer raises.

Standard library only: this module is imported inside the driver's own process
(runner.py), which may run another interpreter than PyPTS itself.
"""

import inspect
from abc import ABC, abstractmethod
from typing import ClassVar

#: The three methods every driver has. The hardware layer calls them; they are
#: not offered to test code as operations of the device.
LIFECYCLE_METHODS = ("connect", "teardown", "recover")


class DriverError(Exception):
    """A device could not be reached, or an operation on it failed."""


class Driver(ABC):
    """
    One instrument, or one remote connection, as a plain class.

    No IPC and no framework import: the runner wraps it. `connect()` receives
    the device's `[hardware.<name>]` keys as text, minus the keys the hardware
    layer reads itself (`driver`, `python`, `call_timeout_s`).

    Derive from a family in families.py, never from Driver directly - the
    runner refuses a driver that belongs to no family. Every public method
    becomes an operation test code can call; return values and arguments must
    be what JSON can carry (str, int, float, bool, None, list, dict).
    """

    #: The family this driver belongs to. Set by each family base.
    FAMILY: ClassVar[str] = ""

    @abstractmethod
    def connect(self, config: dict[str, str]) -> None:
        """Open the connection `config` describes."""

    @abstractmethod
    def teardown(self) -> None:
        """Close the connection. Must not raise when nothing is open."""

    def recover(self, config: dict[str, str]) -> None:
        """Bring a misbehaving device back: teardown, then connect again."""
        self.teardown()
        self.connect(config)


def operations_of(driver_class: type) -> list[str]:
    """
    The public methods test code may call on a device of this class, sorted.

    Read from the class rather than an instance, so a property is never
    evaluated just to find out what it is.
    """
    names = []
    for name, member in inspect.getmembers(driver_class):
        if name.startswith("_"):
            continue
        if name in LIFECYCLE_METHODS:
            continue
        if callable(member):
            names.append(name)
    return names
```

- [ ] **Step 4: Write `families.py`**

```python
"""
The device families. A driver derives from exactly one of them.

A family names the verbs every driver of that family offers, so test code
written against "a PSU" runs against any PSU driver. The lists are short on
purpose; a driver may offer more operations than its family declares, and test
code that uses those is tied to that driver.

Standard library only, for the same reason as driver.py.
"""

from abc import abstractmethod
from typing import Any

from pypts.hal.driver import Driver


class PSU(Driver):
    """A programmable power supply. Channels are numbered from 1."""

    FAMILY = "PSU"

    @abstractmethod
    def set_voltage(self, channel: int, volts: float) -> None:
        """Set the output voltage of a channel."""

    @abstractmethod
    def set_current_limit(self, channel: int, amps: float) -> None:
        """Set the current limit of a channel."""

    @abstractmethod
    def output_on(self, channel: int) -> None:
        """Switch a channel's output on."""

    @abstractmethod
    def output_off(self, channel: int) -> None:
        """Switch a channel's output off."""

    @abstractmethod
    def measure_voltage(self, channel: int) -> float:
        """The voltage a channel is delivering, in volts."""

    @abstractmethod
    def measure_current(self, channel: int) -> float:
        """The current a channel is delivering, in amperes."""


class DMM(Driver):
    """A digital multimeter. Each call takes one reading."""

    FAMILY = "DMM"

    @abstractmethod
    def measure_dc_voltage(self) -> float:
        """One DC voltage reading, in volts."""

    @abstractmethod
    def measure_ac_voltage(self) -> float:
        """One AC (RMS) voltage reading, in volts."""

    @abstractmethod
    def measure_dc_current(self) -> float:
        """One DC current reading, in amperes."""

    @abstractmethod
    def measure_resistance(self) -> float:
        """One resistance reading, in ohms."""


class Scope(Driver):
    """An oscilloscope. Channels are numbered from 1."""

    FAMILY = "Scope"

    @abstractmethod
    def set_timebase(self, seconds_per_division: float) -> None:
        """Set the horizontal scale."""

    @abstractmethod
    def set_vertical_scale(self, channel: int, volts_per_division: float) -> None:
        """Set a channel's vertical scale."""

    @abstractmethod
    def arm_single(self) -> None:
        """Arm one single-shot acquisition."""

    @abstractmethod
    def read_waveform(self, channel: int) -> dict[str, Any]:
        """
        The last acquisition of a channel:
        {"x_origin": float, "x_increment": float, "samples": list[float]}.
        """


class SSH(Driver):
    """A remote shell."""

    FAMILY = "SSH"

    @abstractmethod
    def execute(self, command: str, timeout_s: float | None = None) -> dict[str, Any]:
        """Run one command: {"stdout": str, "stderr": str, "exit_code": int}."""

    @abstractmethod
    def put_file(self, local_path: str, remote_path: str) -> None:
        """Copy a file from this machine to the remote one."""

    @abstractmethod
    def get_file(self, remote_path: str, local_path: str) -> None:
        """Copy a file from the remote machine to this one."""


class Load(Driver):
    """An electronic load."""

    FAMILY = "Load"

    @abstractmethod
    def set_mode(self, mode: str) -> None:
        """Constant current, voltage, resistance or power: "CC", "CV", "CR" or "CP"."""

    @abstractmethod
    def set_level(self, value: float) -> None:
        """The set point, in the unit of the mode: A, V, ohm or W."""

    @abstractmethod
    def input_on(self) -> None:
        """Start sinking."""

    @abstractmethod
    def input_off(self) -> None:
        """Stop sinking."""

    @abstractmethod
    def measure_voltage(self) -> float:
        """The voltage at the input, in volts."""

    @abstractmethod
    def measure_current(self) -> float:
        """The current through the input, in amperes."""


class Other(Driver):
    """Anything that is none of the above. No verbs of its own."""

    FAMILY = "Other"


#: Every family, in the order the documentation lists them.
FAMILIES: tuple[type[Driver], ...] = (PSU, DMM, Scope, SSH, Load, Other)

#: Their names - what a driver's FAMILY must be one of.
FAMILY_NAMES: tuple[str, ...] = tuple(family.FAMILY for family in FAMILIES)
```

- [ ] **Step 5: Export them from `pypts/hal/__init__.py`**

Append below the docstring:

```python
from pypts.hal.driver import Driver, DriverError
from pypts.hal.families import DMM, PSU, SSH, Load, Other, Scope

__all__ = ["DMM", "PSU", "SSH", "Driver", "DriverError", "Load", "Other", "Scope"]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal.py -v`
Expected: PASS (all tests so far).

---

### Task 3: The wire protocol

**Files:**
- Create: `src/pypts/hal/protocol.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Produces: constants `HELLO`, `FATAL`, `CALL`, `LOG`, `RESULT`, `ERROR` (str);
  `ProtocolError(Exception)`; `encode(message: dict[str, Any]) -> bytes` (raises
  `TypeError`/`ValueError` for a value JSON cannot carry); `decode(line: bytes) -> dict[str, Any]`
  (raises `ProtocolError`); `LineReader(sock)` with
  `read_line(timeout_s: float | None = None) -> bytes | None` (None = closed; raises
  `TimeoutError`).

- [ ] **Step 1: Write the failing tests**

Append:

```python
import socket

from pypts.hal import protocol


def test_a_message_is_one_ascii_line():
    data = protocol.encode({"kind": protocol.LOG, "message": "5 µA ± 2 °C"})
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1
    data.decode("ascii")
    assert protocol.decode(data.rstrip(b"\n"))["message"] == "5 µA ± 2 °C"


def test_a_value_json_cannot_carry_is_refused_by_encode():
    with pytest.raises(TypeError):
        protocol.encode({"kind": protocol.RESULT, "value": object()})


@pytest.mark.parametrize("line", [b"not json", b"[1, 2]", b'{"no_kind": 1}', b"\xff\xfe"])
def test_anything_but_a_message_is_a_protocol_error(line):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(line)


def test_the_line_reader_splits_and_keeps_the_rest():
    left, right = socket.socketpair()
    with left, right:
        right.sendall(b"one\ntwo\nthr")
        reader = protocol.LineReader(left)
        assert reader.read_line(1.0) == b"one"
        assert reader.read_line(1.0) == b"two"
        right.sendall(b"ee\n")
        assert reader.read_line(1.0) == b"three"


def test_the_line_reader_says_none_when_the_other_side_closes():
    left, right = socket.socketpair()
    with left:
        right.close()
        assert protocol.LineReader(left).read_line(1.0) is None


def test_the_line_reader_times_out():
    left, right = socket.socketpair()
    with left, right, pytest.raises(TimeoutError):
        protocol.LineReader(left).read_line(0.1)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_hal.py -k "line or message or protocol or encode" -v`
Expected: FAIL — `ImportError: cannot import name 'protocol'`.

- [ ] **Step 3: Write `protocol.py`**

```python
"""
The wire format between DriverProxy and the runner: one JSON object per line
over a TCP connection on 127.0.0.1. The message kinds and their fields are
listed in hal.md -> Protocol.

ASCII on the wire (`ensure_ascii`): text such as "5 uA" with a real micro sign
travels escaped and arrives as it was sent, whatever the console code page.

Standard library only.
"""

import json
import socket
import time
from typing import Any

#: Runner -> proxy, once, first: the driver is built. Carries family, operations.
HELLO = "hello"
#: Runner -> proxy, instead of hello: the driver could not be built. Carries message.
FATAL = "fatal"
#: Proxy -> runner: run one operation. Carries id, method, args, kwargs.
CALL = "call"
#: Runner -> proxy, at any time: one log record. Carries level, logger, message.
LOG = "log"
#: Runner -> proxy: the answer to a call. Carries id, value.
RESULT = "result"
#: Runner -> proxy: the call raised. Carries id, type, message, traceback.
ERROR = "error"

#: How much a received line can be read at once.
RECEIVE_BYTES = 65536


class ProtocolError(Exception):
    """A line that is not a protocol message."""


def encode(message: dict[str, Any]) -> bytes:
    """One message as one line. Raises TypeError or ValueError for a value JSON cannot carry."""
    return (json.dumps(message, ensure_ascii=True) + "\n").encode("ascii")


def decode(line: bytes) -> dict[str, Any]:
    """One line back into a message. Raises ProtocolError for anything else."""
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Not a protocol message: {line[:80]!r}.") from exc
    if not isinstance(message, dict) or "kind" not in message:
        raise ProtocolError(f"Not a protocol message: {line[:80]!r}.")
    return message


class LineReader:
    """Reads whole lines from a socket, keeping what came after a newline for the next call."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buffer = b""

    def read_line(self, timeout_s: float | None = None) -> bytes | None:
        """
        The next line, without its newline. None when the other side has closed
        the connection (or reset it - a process that was killed). Raises
        TimeoutError if `timeout_s` passes first; None waits for ever.
        """
        deadline = None
        if timeout_s is not None:
            deadline = time.monotonic() + timeout_s
        while b"\n" not in self._buffer:
            if deadline is None:
                self._sock.settimeout(None)
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("No complete line arrived in time.")
                self._sock.settimeout(remaining)
            try:
                chunk = self._sock.recv(RECEIVE_BYTES)
            except TimeoutError:
                raise
            except OSError:
                return None
            if not chunk:
                return None
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal.py -v`
Expected: PASS.

---

### Task 4: The runner and the loopback driver

**Files:**
- Create: `src/pypts/hal/runner.py`, `src/pypts/hal/drivers/__init__.py`, `src/pypts/hal/drivers/loopback.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Consumes: `Driver`, `LIFECYCLE_METHODS`, `operations_of` (Task 2), `FAMILY_NAMES` (Task 2), `protocol` (Task 3).
- Produces:
  - `runner.load_driver_class(dotted: str) -> type[Driver]` (raises `ValueError`, `ImportError`)
  - `runner.answer(driver: Any, operations: list[str], message: dict[str, Any]) -> dict[str, Any]`
  - `runner.Channel(sock)` with `.send(message)` and `.reader: LineReader`
  - `runner.serve(channel: Channel, driver: Any, operations: list[str]) -> None` (returns on EOF)
  - `runner.main(argv: list[str] | None = None) -> int`
  - `pypts.hal.drivers.loopback.LoopbackDriver(Other)` with operations `crash(exit_code)`,
    `echo(value)`, `fail(message)`, `is_connected()`, `log_message(message)`,
    `print_text(text)`, `process_id()`, `settings()`, `sleep(seconds)`

- [ ] **Step 1: Write the failing tests**

Append:

```python
import subprocess
import sys
import threading

from pypts.hal import runner
from pypts.hal.drivers.loopback import LoopbackDriver

LOOPBACK = "pypts.hal.drivers.loopback.LoopbackDriver"


def _call(method, *args, **kwargs):
    return {"kind": protocol.CALL, "id": 1, "method": method, "args": list(args), "kwargs": kwargs}


def test_the_loopback_driver_is_an_other():
    assert LoopbackDriver.FAMILY == "Other"
    assert "echo" in operations_of(LoopbackDriver)


def test_load_driver_class_finds_a_driver():
    assert runner.load_driver_class(LOOPBACK) is LoopbackDriver


@pytest.mark.parametrize(
    ("dotted", "words"),
    [
        ("LoopbackDriver", "not a dotted path"),
        ("pypts.hal.drivers.loopback.Nope", "has no class 'Nope'"),
        ("pypts.hal.driver.DriverError", "is not a driver"),
        ("pypts.hal.driver.Driver", "belongs to no device family"),
    ],
)
def test_load_driver_class_explains_a_bad_path(dotted, words):
    with pytest.raises(ValueError, match=words):
        runner.load_driver_class(dotted)


def test_answer_runs_an_operation():
    driver = LoopbackDriver()
    reply = runner.answer(driver, ["echo"], _call("echo", 42))
    assert reply == {"kind": protocol.RESULT, "id": 1, "value": 42}


def test_answer_runs_a_lifecycle_method_that_is_not_an_operation():
    driver = LoopbackDriver()
    reply = runner.answer(driver, ["echo"], _call("connect", {"a": "1"}))
    assert reply["kind"] == protocol.RESULT
    assert driver.settings() == {"a": "1"}


def test_answer_refuses_what_is_not_an_operation():
    reply = runner.answer(LoopbackDriver(), ["echo"], _call("__class__"))
    assert reply["kind"] == protocol.ERROR
    assert reply["type"] == "AttributeError"


def test_answer_reports_an_exception_with_its_traceback():
    reply = runner.answer(LoopbackDriver(), ["fail"], _call("fail", "instrument said no"))
    assert reply["kind"] == protocol.ERROR
    assert reply["type"] == "RuntimeError"
    assert reply["message"] == "instrument said no"
    assert "Traceback" in reply["traceback"]


def test_serve_answers_until_the_connection_closes():
    left, right = socket.socketpair()
    channel = runner.Channel(left)
    server = threading.Thread(target=runner.serve, args=(channel, LoopbackDriver(), ["echo"]))
    server.start()
    with right:
        right.sendall(protocol.encode(_call("echo", "hi")))
        reader = protocol.LineReader(right)
        assert protocol.decode(reader.read_line(5.0))["value"] == "hi"
    server.join(timeout=5.0)
    assert not server.is_alive()
    left.close()


def test_serve_reports_a_value_that_cannot_be_sent():
    class _Odd(LoopbackDriver):
        def odd(self):
            return object()

    left, right = socket.socketpair()
    channel = runner.Channel(left)
    server = threading.Thread(target=runner.serve, args=(channel, _Odd(), ["odd"]))
    server.start()
    with right:
        right.sendall(protocol.encode(_call("odd")))
        reply = protocol.decode(protocol.LineReader(right).read_line(5.0))
    server.join(timeout=5.0)
    left.close()
    assert reply["kind"] == protocol.ERROR
    assert "cannot be sent" in reply["message"]


def test_the_runner_exits_when_its_connection_drops():
    """Review Focus 1: PyPTS dying must take the driver process with it."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "pypts.hal.runner", "--port", str(port), "--driver", LOOPBACK],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        server.settimeout(30.0)
        connection, _ = server.accept()
        hello = protocol.decode(protocol.LineReader(connection).read_line(30.0))
        assert hello["kind"] == protocol.HELLO
        assert hello["family"] == "Other"
        connection.close()
        assert process.wait(timeout=10.0) == 0
    finally:
        server.close()
        if process.poll() is None:
            process.kill()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_hal.py -v`
Expected: FAIL — `ImportError: cannot import name 'runner'`.

- [ ] **Step 3: Write `drivers/__init__.py` and `drivers/loopback.py`**

`src/pypts/hal/drivers/__init__.py`:

```python
"""
The drivers PyPTS ships. Importing this package imports none of them: each one
pulls in its own vendor library (paramiko for ssh.py), which may not be installed.
"""
```

`src/pypts/hal/drivers/loopback.py`:

```python
"""
Loopback - a device with nothing behind it.

Used by the hardware layer's own tests and by the hal demo recipe, and the
quickest way to see the layer work on a machine with no instrument:

    [hardware.loop1]
    driver = pypts.hal.drivers.loopback.LoopbackDriver
"""

import logging
import os
import time
from typing import Any

from pypts.hal.families import Other

logger = logging.getLogger(__name__)


class LoopbackDriver(Other):
    """Answers with what it was given; can also fail, stall and crash on request."""

    def __init__(self) -> None:
        self._settings: dict[str, str] = {}
        self._connected = False

    def connect(self, config: dict[str, str]) -> None:
        self._settings = dict(config)
        self._connected = True

    def teardown(self) -> None:
        self._connected = False

    def echo(self, value: Any) -> Any:
        """The value, back."""
        return value

    def settings(self) -> dict[str, str]:
        """The keys connect() was given."""
        return dict(self._settings)

    def is_connected(self) -> bool:
        return self._connected

    def fail(self, message: str) -> None:
        """Raise, the way a driver does when its instrument refuses."""
        raise RuntimeError(message)

    def sleep(self, seconds: float) -> None:
        """Take this long to answer."""
        time.sleep(seconds)

    def log_message(self, message: str) -> None:
        """Write one INFO record from the driver's own logger."""
        logger.info("%s", message)

    def print_text(self, text: str) -> None:
        """Print, the way a careless vendor library does."""
        print(text, flush=True)

    def crash(self, exit_code: int) -> None:
        """End the driver process on the spot, as a crashing C library would."""
        os._exit(exit_code)

    def process_id(self) -> int:
        """The id of the driver process."""
        return os.getpid()
```

- [ ] **Step 4: Write `runner.py`**

```python
"""
The driver's own process. Started by DriverProxy, never by hand:

    python -m pypts.hal.runner --port 50123 --driver pypts.hal.drivers.ssh.SshDriver
                               --log-level 20

It connects back to the proxy on 127.0.0.1:<port>, builds the driver, says
hello, then answers calls one at a time until the proxy closes the connection.
That is also what happens when PyPTS dies, so a driver process never outlives
the framework: on the way out it calls the driver's teardown().

Every log record of this process goes to the proxy over the same connection.
Printed output is not read here; the proxy drains and logs it.

Standard library only, apart from pypts.hal itself.
"""

import argparse
import contextlib
import importlib
import logging
import socket
import sys
import threading
import traceback
from typing import Any

from pypts.hal import protocol
from pypts.hal.driver import LIFECYCLE_METHODS, Driver, operations_of
from pypts.hal.families import FAMILY_NAMES


class Channel:
    """The connection to the proxy. send() is locked: a driver thread may log at any time."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._lock = threading.Lock()
        self.reader = protocol.LineReader(sock)

    def send(self, message: dict[str, Any]) -> None:
        """Raises TypeError or ValueError, before sending anything, if JSON cannot carry it."""
        data = protocol.encode(message)
        with self._lock:
            self._sock.sendall(data)


class ForwardingHandler(logging.Handler):
    """Sends every log record of this process to the proxy, for PyPTS's run log."""

    def __init__(self, channel: Channel) -> None:
        super().__init__()
        self._channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._channel.send(
                {
                    "kind": protocol.LOG,
                    "level": record.levelno,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
            )
        except Exception:  # noqa: BLE001 - a log record must never take the driver down
            self.handleError(record)


def load_driver_class(dotted: str) -> type[Driver]:
    """The class `dotted` names, checked to be a driver of a known family."""
    module_name, _, class_name = dotted.rpartition(".")
    if not module_name:
        raise ValueError(f"'{dotted}' is not a dotted path to a class.")
    module = importlib.import_module(module_name)
    found = getattr(module, class_name, None)
    if found is None:
        raise ValueError(f"Module '{module_name}' has no class '{class_name}'.")
    if not isinstance(found, type) or not issubclass(found, Driver):
        raise ValueError(f"'{dotted}' is not a driver: it does not derive from Driver.")
    if found.FAMILY not in FAMILY_NAMES:
        raise ValueError(
            f"'{dotted}' belongs to no device family; derive it from one of "
            f"{', '.join(FAMILY_NAMES)}."
        )
    return found


def error(call_id: Any, type_name: str, message: str, trace: str) -> dict[str, Any]:
    return {
        "kind": protocol.ERROR,
        "id": call_id,
        "type": type_name,
        "message": message,
        "traceback": trace,
    }


def answer(driver: Any, operations: list[str], message: dict[str, Any]) -> dict[str, Any]:
    """Run one call against the driver and build the reply. Never raises."""
    call_id = message.get("id")
    if message.get("kind") != protocol.CALL:
        return error(call_id, "ProtocolError", f"Expected a call, got {message.get('kind')!r}.", "")
    method_name = str(message.get("method", ""))
    if method_name not in operations and method_name not in LIFECYCLE_METHODS:
        return error(call_id, "AttributeError", f"No operation '{method_name}'.", "")
    args = message.get("args", [])
    kwargs = message.get("kwargs", {})
    try:
        value = getattr(driver, method_name)(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - every failure goes back to the caller
        return error(call_id, type(exc).__name__, str(exc), traceback.format_exc())
    return {"kind": protocol.RESULT, "id": call_id, "value": value}


def serve(channel: Channel, driver: Any, operations: list[str]) -> None:
    """Answer calls until the proxy closes the connection."""
    while True:
        line = channel.reader.read_line()
        if line is None:
            return
        if not line.strip():
            continue
        try:
            message = protocol.decode(line)
        except protocol.ProtocolError as exc:
            channel.send(error(None, "ProtocolError", str(exc), ""))
            continue
        reply = answer(driver, operations, message)
        try:
            channel.send(reply)
        except (TypeError, ValueError) as exc:
            channel.send(
                error(
                    reply.get("id"),
                    "TypeError",
                    f"'{message.get('method')}' returned a value that cannot be sent: {exc}",
                    "",
                )
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A PyPTS driver process.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--driver", required=True)
    parser.add_argument("--log-level", type=int, default=logging.INFO)
    args = parser.parse_args(argv)

    sock = socket.create_connection(("127.0.0.1", args.port))
    channel = Channel(sock)
    root = logging.getLogger()
    root.setLevel(args.log_level)
    root.addHandler(ForwardingHandler(channel))

    try:
        driver_class = load_driver_class(args.driver)
        driver = driver_class()
    except Exception as exc:  # noqa: BLE001 - reported to the proxy, which raises it
        channel.send({"kind": protocol.FATAL, "message": f"{type(exc).__name__}: {exc}"})
        sock.close()
        return 1

    operations = operations_of(driver_class)
    channel.send({"kind": protocol.HELLO, "family": driver_class.FAMILY, "operations": operations})
    try:
        serve(channel, driver, operations)
    finally:
        # The proxy is gone - closed normally after its own teardown call, or
        # because PyPTS died. Either way this is the last chance to release
        # the instrument; teardown() must be harmless when nothing is open.
        # Suppressed, not reported: nothing is left to report it to.
        with contextlib.suppress(Exception):
            driver.teardown()
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal.py -v`
Expected: PASS. If `test_the_runner_exits_when_its_connection_drops` fails with
`ModuleNotFoundError: pypts` in the child, the package is not installed in the environment:
run `pip install -e .[dev]` (Task 5 adds the `PYTHONPATH` hand-over for the proxy path).

---

### Task 5: `DriverProxy`

**Files:**
- Create: `src/pypts/hal/proxy.py`, `tests/unit_tests/test_hal_proxy.py`, `tests/unit_tests/hal_test_drivers.py`
- Modify: `src/pypts/utilities/common.py` (secret helpers), `tests/unit_tests/test_utilities.py`

**Interfaces:**
- Consumes: `protocol` (Task 3), `DriverError` (Task 2), the runner command line (Task 4).
- Produces:
  - `pypts.utilities.common.SECRET_KEY_WORDS = ("password", "passphrase", "secret", "token")`,
    `MASK = "******"`, `is_secret_key(key: str) -> bool`, `masked(settings: Mapping[str, Any]) -> dict[str, Any]`
  - `proxy.child_environment() -> dict[str, str]`
  - `proxy.DriverProxy(name: str, driver_path: str, settings: Mapping[str, str], *, python: str = sys.executable, call_timeout_s: float = 60.0)`
    - attributes `name: str`, `family: str` ("" until open), `operations: tuple[str, ...]`
    - `open() -> None`, `close() -> None` (never raises), `recover() -> None`, `is_open() -> bool`
    - any name in `operations` is a callable that runs remotely; others raise `AttributeError`
    - every failure is `DriverError` with a message starting `Device '<name>'`
  - constants `STARTUP_TIMEOUT_S = 30.0`, `EXIT_TIMEOUT_S = 5.0`, `OUTPUT_TAIL_LINES = 20`,
    `RESERVED_NAMES`

- [ ] **Step 1: Write the failing tests for the secret helpers**

Append to `tests/unit_tests/test_utilities.py` (add the import to the existing import block):

```python
from pypts.utilities.common import MASK, is_secret_key, masked


@pytest.mark.parametrize(
    ("key", "secret"),
    [
        ("password", True),
        ("SSH_Password", True),
        ("key_passphrase", True),
        ("api_token", True),
        ("client_secret", True),
        ("host", False),
        ("key_filename", False),
    ],
)
def test_is_secret_key(key, secret):
    assert is_secret_key(key) is secret


def test_masked_hides_only_the_secrets():
    assert masked({"host": "h", "password": "hunter2"}) == {"host": "h", "password": MASK}
```

(If `pytest` is not yet imported in `test_utilities.py`, add `import pytest`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_utilities.py -k "secret or masked" -v`
Expected: FAIL — `ImportError: cannot import name 'MASK'`.

- [ ] **Step 3: Add the helpers to `src/pypts/utilities/common.py`**

Append at the end of the file (`Mapping` is already imported; add `from typing import Any`
to the imports if it is not there):

```python
#: Words that mark a configuration key as a secret. A key that contains one of
#: them - `password`, `ssh_password`, `key_passphrase` - is never written to a log.
SECRET_KEY_WORDS = ("password", "passphrase", "secret", "token")

#: What a log shows in place of a secret.
MASK = "******"


def is_secret_key(key: str) -> bool:
    """Whether a configuration key holds a secret, by its name."""
    lowered = key.lower()
    for word in SECRET_KEY_WORDS:
        if word in lowered:
            return True
    return False


def masked(settings: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `settings` fit for a log: every secret value replaced by MASK."""
    result: dict[str, Any] = {}
    for key, value in settings.items():
        if is_secret_key(key):
            result[key] = MASK
        else:
            result[key] = value
    return result
```

Run: `pytest tests/unit_tests/test_utilities.py -v` — Expected: PASS.

- [ ] **Step 4: Write the test-only drivers**

Create `tests/unit_tests/hal_test_drivers.py`:

```python
"""
Drivers that are broken on purpose, for test_hal_proxy.py.

They run in a driver process of their own, and are importable there as
`hal_test_drivers` because pytest puts this folder on sys.path (the default
`prepend` import mode) and DriverProxy hands its sys.path on to the child.
"""

from pypts.hal.driver import Driver
from pypts.hal.families import Other


class NoFamilyDriver(Driver):
    def connect(self, config):
        pass

    def teardown(self):
        pass


class BrokenConstructorDriver(Other):
    def __init__(self):
        raise RuntimeError("constructor exploded")

    def connect(self, config):
        pass

    def teardown(self):
        pass


class FailingConnectDriver(Other):
    def connect(self, config):
        raise ConnectionError("instrument is switched off")

    def teardown(self):
        pass
```

- [ ] **Step 5: Write the failing proxy tests**

Create `tests/unit_tests/test_hal_proxy.py`:

```python
"""
Unit tests for DriverProxy (src/pypts/hal/proxy.py) against real driver
processes - the loopback driver, and the broken ones in hal_test_drivers.py.

Each test starts at least one process, so each costs a fraction of a second.
"""

import logging
import os
import sys
import time

import pytest

from pypts.hal import DriverError
from pypts.hal.proxy import DriverProxy, child_environment

LOOPBACK = "pypts.hal.drivers.loopback.LoopbackDriver"


@pytest.fixture
def device():
    proxy = DriverProxy("loop1", LOOPBACK, {"mode": "test"})
    proxy.open()
    yield proxy
    proxy.close()


def test_open_says_hello_and_connects(device):
    assert device.is_open()
    assert device.family == "Other"
    assert "echo" in device.operations
    assert device.is_connected() is True
    assert device.settings() == {"mode": "test"}


def test_an_operation_runs_in_another_process(device):
    assert device.echo({"a": [1, 2.5, None]}) == {"a": [1, 2.5, None]}
    assert device.process_id() != os.getpid()


def test_non_ascii_and_large_values_round_trip(device):
    """Review Focus 2."""
    assert device.echo("5 µA ± 2 °C") == "5 µA ± 2 °C"
    big = "x" * 1_000_000
    assert device.echo(big) == big


def test_a_driver_exception_is_a_driver_error_and_the_device_stays_usable(device):
    with pytest.raises(DriverError, match=r"Device 'loop1': 'fail' failed: RuntimeError: nope"):
        device.fail("nope")
    assert device.echo(1) == 1


def test_an_unknown_operation_is_an_attribute_error(device):
    with pytest.raises(AttributeError, match="has no operation 'nope'"):
        device.nope()
    assert not hasattr(device, "nope")


def test_an_argument_json_cannot_carry_is_refused_before_sending(device):
    with pytest.raises(DriverError, match="cannot be sent"):
        device.echo(object())
    assert device.echo(2) == 2


def test_driver_log_records_reach_the_run_log(caplog):
    caplog.set_level(logging.DEBUG)
    proxy = DriverProxy("loop1", LOOPBACK, {})
    proxy.open()
    try:
        proxy.log_message("relay 3 closed")
    finally:
        proxy.close()
    records = [r for r in caplog.records if r.getMessage() == "Device 'loop1': relay 3 closed"]
    assert records
    assert records[0].levelno == logging.INFO


def test_printed_output_is_logged_at_debug(caplog):
    caplog.set_level(logging.DEBUG)
    proxy = DriverProxy("loop1", LOOPBACK, {})
    proxy.open()
    try:
        proxy.print_text("vendor banner")
        deadline = time.monotonic() + 5.0
        while "Device 'loop1' printed: vendor banner" not in caplog.text:
            assert time.monotonic() < deadline, "the printed line never reached the log"
            time.sleep(0.05)
    finally:
        proxy.close()


def test_connect_settings_are_masked_in_the_trace(caplog):
    """Review Focus 5."""
    caplog.set_level(logging.DEBUG)
    proxy = DriverProxy("loop1", LOOPBACK, {"password": "hunter2"})
    proxy.open()
    proxy.close()
    assert "hunter2" not in caplog.text


def test_a_call_that_takes_too_long_stops_the_process():
    proxy = DriverProxy("loop1", LOOPBACK, {}, call_timeout_s=0.5)
    proxy.open()
    try:
        with pytest.raises(DriverError, match="did not answer 'sleep' within"):
            proxy.sleep(10)
        assert not proxy.is_open()
    finally:
        proxy.close()


def test_a_crash_is_a_driver_error_with_the_exit_code():
    proxy = DriverProxy("loop1", LOOPBACK, {})
    proxy.open()
    try:
        with pytest.raises(DriverError, match=r"stopped unexpectedly \(exit code 3\)"):
            proxy.crash(3)
        assert not proxy.is_open()
        with pytest.raises(DriverError, match="is not open"):
            proxy.echo(1)
    finally:
        proxy.close()


def test_recover_starts_a_fresh_process_after_a_crash():
    proxy = DriverProxy("loop1", LOOPBACK, {"mode": "test"})
    proxy.open()
    try:
        first = proxy.process_id()
        with pytest.raises(DriverError):
            proxy.crash(1)
        proxy.recover()
        assert proxy.process_id() != first
        assert proxy.settings() == {"mode": "test"}
    finally:
        proxy.close()


def test_recover_on_a_live_process_keeps_the_process(device):
    first = device.process_id()
    device.recover()
    assert device.process_id() == first
    assert device.is_connected() is True


@pytest.mark.parametrize(
    ("driver_path", "words"),
    [
        ("pypts.hal.drivers.nothing.Here", "No module named"),
        ("hal_test_drivers.NoFamilyDriver", "belongs to no device family"),
        ("hal_test_drivers.BrokenConstructorDriver", "constructor exploded"),
        ("hal_test_drivers.FailingConnectDriver", "instrument is switched off"),
    ],
)
def test_a_device_that_cannot_open_says_why_and_leaves_nothing_running(driver_path, words):
    proxy = DriverProxy("bad1", driver_path, {})
    with pytest.raises(DriverError, match=words):
        proxy.open()
    assert not proxy.is_open()
    proxy.close()


def test_a_python_that_does_not_exist_is_a_driver_error():
    proxy = DriverProxy("loop1", LOOPBACK, {}, python="no-such-python-here")
    with pytest.raises(DriverError, match="could not be started"):
        proxy.open()


def test_close_is_safe_twice_and_before_open():
    proxy = DriverProxy("loop1", LOOPBACK, {})
    proxy.close()
    proxy.open()
    proxy.close()
    proxy.close()
    assert not proxy.is_open()


def test_the_child_environment_carries_this_sys_path(monkeypatch):
    """Review Focus 4: a source-tree run must still import pypts in the child."""
    monkeypatch.setenv("PYTHONPATH", "already-there")
    paths = child_environment()["PYTHONPATH"].split(os.pathsep)
    for entry in sys.path:
        if entry:
            assert entry in paths
    assert paths[-1] == "already-there"
```

- [ ] **Step 6: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_hal_proxy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pypts.hal.proxy'`.

- [ ] **Step 7: Write `proxy.py`**

```python
"""
DriverProxy - one device as test code sees it: a local object whose methods
run in the driver's own process.

open() listens on 127.0.0.1, starts the driver process (runner.py), waits for
it to connect back and say hello, and calls the driver's connect(). After that
every operation of the driver is a method of the proxy. close() calls
teardown() and ends the process. Every failure is a DriverError that names the
device, so it reads well on the operator's ERROR line.

Calls are one at a time: a lock makes a second thread wait for the first.
"""

import collections
import contextlib
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from pypts.hal import protocol
from pypts.hal.driver import DriverError
from pypts.logger.log import log
from pypts.utilities.common import masked

#: How long open() waits for the driver process to connect back and say hello.
#: Generous: importing a vendor library can take seconds on a cold machine.
STARTUP_TIMEOUT_S = 30.0

#: How long close() waits for the driver process to end before killing it.
EXIT_TIMEOUT_S = 5.0

#: How many lines of the process's own output a startup error quotes.
OUTPUT_TAIL_LINES = 20

#: How often open() looks whether the process died while it waits for it.
ACCEPT_POLL_S = 0.2

#: Names the proxy itself uses. A driver operation with one of these names
#: cannot be reached through a proxy - do not give a driver method these names.
RESERVED_NAMES = ("name", "family", "operations", "open", "close", "recover", "is_open")


def child_environment() -> dict[str, str]:
    """
    The environment of a driver process: this one's, with PYTHONPATH extended
    by this process's sys.path - so whatever imports here imports there too:
    pypts itself when it runs from a source tree, and a driver beside it.
    """
    environment = dict(os.environ)
    paths = []
    for entry in sys.path:
        if entry:
            paths.append(entry)
    existing = environment.get("PYTHONPATH", "")
    if existing:
        paths.append(existing)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return environment


class DriverProxy:
    """One device, its driver running in a process of its own."""

    def __init__(
        self,
        name: str,
        driver_path: str,
        settings: Mapping[str, str],
        *,
        python: str = sys.executable,
        call_timeout_s: float = 60.0,
    ) -> None:
        self.name = name
        #: The driver's family and operations, as its hello said. Empty until open().
        self.family = ""
        self.operations: tuple[str, ...] = ()
        self._driver_path = driver_path
        self._driver_module = driver_path.rpartition(".")[0]
        self._settings = dict(settings)
        self._python = python
        self._call_timeout_s = call_timeout_s
        self._process: subprocess.Popen[str] | None = None
        self._output_thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._reader: protocol.LineReader | None = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._output_tail: collections.deque[str] = collections.deque(maxlen=OUTPUT_TAIL_LINES)

    # --- what test code calls ----------------------------------------------------

    def __getattr__(self, name: str) -> Callable[..., Any]:
        """An operation of the driver, as a method. Only called for names the proxy lacks."""
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self.operations:
            known = ", ".join(self.operations) or "none"
            family = self.family or "not open"
            raise AttributeError(
                f"Device '{self.name}' ({family}) has no operation '{name}'. It has: {known}."
            )

        def operation(*args: Any, **kwargs: Any) -> Any:
            return self._call(name, list(args), kwargs)

        operation.__name__ = name
        return operation

    def is_open(self) -> bool:
        return self._sock is not None

    def recover(self) -> None:
        """
        Bring the device back: the driver's own recover() while its process is
        alive, a fresh process and connect() when it is not. The hardware layer
        never calls this by itself - test code decides.
        """
        log.info("Recovering device '%s'.", self.name)
        alive = self._process is not None and self._process.poll() is None
        if self._sock is not None and alive:
            self._call("recover", [self._settings], {})
        else:
            self._discard()
            self.open()
        log.info("Device '%s' recovered.", self.name)

    # --- what the Bench calls ------------------------------------------------------

    def open(self) -> None:
        """Start the driver process and connect the device. Leaves nothing running on failure."""
        log.debug(
            "Starting the driver process of device '%s': %s, with %s.",
            self.name,
            self._driver_path,
            self._python,
        )
        try:
            server = socket.create_server(("127.0.0.1", 0))
            try:
                port = server.getsockname()[1]
                self._spawn(port)
                self._sock = self._accept(server)
            finally:
                server.close()
            self._reader = protocol.LineReader(self._sock)
            self._receive_hello()
            log.debug("Device '%s': calling connect(%r).", self.name, masked(self._settings))
            self._call("connect", [self._settings], {}, trace=False)
        except Exception:
            self._kill()
            raise
        log.info("Device '%s' connected.", self.name)

    def close(self) -> None:
        """teardown(), then end the process. Never raises: a failure is a WARNING."""
        if self._sock is None and self._process is None:
            return
        try:
            if self._sock is not None:
                self._call("teardown", [], {})
        except DriverError as exc:
            log.warning("Device '%s' did not disconnect cleanly: %s", self.name, exc)
        finally:
            self._discard()
        log.info("Device '%s' disconnected.", self.name)

    # --- the process ------------------------------------------------------------

    def _spawn(self, port: int) -> None:
        command = [
            self._python,
            "-m",
            "pypts.hal.runner",
            "--port",
            str(port),
            "--driver",
            self._driver_path,
            "--log-level",
            str(logging.getLogger().getEffectiveLevel()),
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_environment(),
                # No console window per device when PyPTS runs as a GUI on Windows.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise DriverError(
                f"Device '{self.name}': its driver process could not be started: {exc}"
            ) from exc
        self._process = process
        self._output_thread = threading.Thread(
            target=self._drain_output,
            args=(process,),
            name=f"Device {self.name} output",
            daemon=True,
        )
        self._output_thread.start()

    def _drain_output(self, process: subprocess.Popen[str]) -> None:
        """Log every line the process prints, so a full pipe can never block it."""
        if process.stdout is None:
            return
        for line in process.stdout:
            text = line.rstrip()
            self._output_tail.append(text)
            log.debug("Device '%s' printed: %s", self.name, text)

    def _accept(self, server: socket.socket) -> socket.socket:
        """The driver process's connection, or a DriverError saying why it never came."""
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        server.settimeout(ACCEPT_POLL_S)
        while True:
            try:
                connection, _ = server.accept()
                return connection
            except TimeoutError:
                pass
            if self._process is not None and self._process.poll() is not None:
                reason = f"its driver process ended with exit code {self._process.returncode}"
                raise DriverError(self._startup_failure(reason))
            if time.monotonic() > deadline:
                reason = f"its driver process did not start within {STARTUP_TIMEOUT_S:.0f} s"
                raise DriverError(self._startup_failure(reason))

    def _startup_failure(self, reason: str) -> str:
        if self._output_thread is not None:
            self._output_thread.join(timeout=1.0)
        message = f"Device '{self.name}' could not be opened: {reason}."
        if self._output_tail:
            message += " Last output: " + " | ".join(self._output_tail)
        return message

    def _receive_hello(self) -> None:
        message = self._read_message(STARTUP_TIMEOUT_S, "at start-up")
        kind = message.get("kind")
        if kind == protocol.FATAL:
            raise DriverError(
                f"Device '{self.name}' could not be opened: {message.get('message')}"
            )
        if kind != protocol.HELLO:
            raise DriverError(
                f"Device '{self.name}' could not be opened: it began with {kind!r}, not hello."
            )
        self.family = str(message.get("family", ""))
        self.operations = tuple(message.get("operations", []))
        log.debug(
            "Device '%s' is a %s with operations %s.", self.name, self.family, self.operations
        )

    def _discard(self) -> None:
        """Close the connection - the runner then exits - and wait for the process."""
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None
            self._reader = None
        if self._process is not None:
            try:
                self._process.wait(timeout=EXIT_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                log.debug("The driver process of device '%s' did not exit; killing it.", self.name)
                self._process.kill()
                self._process.wait()
            self._process = None

    def _kill(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
        self._discard()

    def _exit_code(self) -> str:
        if self._process is None:
            return "unknown"
        try:
            return str(self._process.wait(timeout=1.0))
        except subprocess.TimeoutExpired:
            return "unknown"

    # --- one call -----------------------------------------------------------------

    def _call(
        self, method: str, args: list[Any], kwargs: dict[str, Any], trace: bool = True
    ) -> Any:
        with self._lock:
            if self._sock is None:
                raise DriverError(f"Device '{self.name}' is not open.")
            self._next_id += 1
            call_id = self._next_id
            request = {
                "kind": protocol.CALL,
                "id": call_id,
                "method": method,
                "args": args,
                "kwargs": kwargs,
            }
            try:
                data = protocol.encode(request)
            except (TypeError, ValueError) as exc:
                raise DriverError(
                    f"Device '{self.name}': the arguments of '{method}' cannot be sent: {exc}"
                ) from exc
            if trace:
                log.debug("Device '%s': calling %s(*%r, **%r).", self.name, method, args, kwargs)
            try:
                self._sock.sendall(data)
            except OSError:
                code = self._exit_code()
                self._discard()
                raise DriverError(
                    f"Device '{self.name}' stopped unexpectedly (exit code {code})."
                ) from None
            while True:
                reply = self._read_message(self._call_timeout_s, f"'{method}'")
                reply_id = reply.get("id")
                if reply_id == call_id or reply_id is None:
                    break
                log.debug("Device '%s': ignoring a reply to call %r.", self.name, reply_id)

        if reply.get("kind") == protocol.RESULT:
            value = reply.get("value")
            if trace:
                log.debug("Device '%s': %s returned %r.", self.name, method, value)
            return value
        trace_text = reply.get("traceback")
        if trace_text:
            log.debug("Traceback in device '%s' for '%s':\n%s", self.name, method, trace_text)
        raise DriverError(
            f"Device '{self.name}': '{method}' failed: "
            f"{reply.get('type')}: {reply.get('message')}"
        )

    def _read_message(self, timeout_s: float, waiting_for: str) -> dict[str, Any]:
        """The next message that is not a log record, logging the records on the way."""
        if self._reader is None:
            raise DriverError(f"Device '{self.name}' is not open.")
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = max(deadline - time.monotonic(), 0.0)
            try:
                line = self._reader.read_line(remaining)
            except TimeoutError:
                self._kill()
                raise DriverError(
                    f"Device '{self.name}' did not answer {waiting_for} within "
                    f"{timeout_s:.1f} s; its driver process was stopped."
                ) from None
            if line is None:
                code = self._exit_code()
                self._discard()
                raise DriverError(f"Device '{self.name}' stopped unexpectedly (exit code {code}).")
            try:
                message = protocol.decode(line)
            except protocol.ProtocolError:
                log.debug("Device '%s' sent a line that is not a message: %r", self.name, line[:200])
                continue
            if message.get("kind") == protocol.LOG:
                self._relog(message)
                continue
            return message

    def _relog(self, message: dict[str, Any]) -> None:
        """
        One forwarded record, into the run log. The driver's own records keep
        their level; another library's (paramiko's INFO chatter) is DEBUG unless
        it is a WARNING or worse - the technician's panel shows INFO.
        """
        level = int(message.get("level", logging.INFO))
        logger_name = str(message.get("logger", ""))
        own = bool(self._driver_module) and logger_name.startswith(self._driver_module)
        if level < logging.WARNING and not own:
            level = logging.DEBUG
        log.log(level, "Device '%s': %s", self.name, message.get("message", ""))
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal_proxy.py tests/unit_tests/test_hal.py -v`
Expected: PASS. Then `ruff check src/pypts/hal tests/unit_tests/test_hal_proxy.py` — clean.

---

### Task 6: The configuration knows hardware sections and hides secrets

**Files:**
- Modify: `src/pypts/config_handler/configuration_schema.py`
- Modify: `src/pypts/config_handler/config_handler.py:274-283` (`_note_active_configuration`), `:342-362` (`dump`), `:578-585` (`_validate`)
- Modify: `src/pypts/config_handler/config_template.ini` (end of file)
- Test: `tests/unit_tests/test_config_handler.py`

**Interfaces:**
- Produces: `configuration_schema.HARDWARE_PREFIX = "hardware."`,
  `configuration_schema.is_hardware_section(section: str) -> bool`.
- Consumes: `masked()` (Task 5).

- [ ] **Step 1: Change and add the tests**

In `tests/unit_tests/test_config_handler.py`, the existing
`test_a_user_added_section_is_kept_as_text_and_reported` uses a hardware section, which stops
being "unknown". Replace that whole test function with these three:

```python
def test_a_user_added_section_is_kept_as_text_and_reported(config, config_path, caplog):
    """
    A section the schema does not know may be a typo, and a typo that silently
    does nothing is worse than one that is mentioned: its values come back
    exactly as written, and it is reported once.
    """
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n[gui_extra]\ntimeout_s = 2.5\n",
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with caplog.at_level(logging.WARNING):
        reopened = ConfigHandler.bootstrap()

    assert reopened.get_parameter("gui_extra.timeout_s") == "2.5"
    assert "[gui_extra] is not part of the schema" in caplog.text


def test_a_hardware_section_is_kept_as_text_without_a_warning(config, config_path, caplog):
    """`[hardware.<name>]` declares a device: the hardware layer reads it, untyped."""
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[hardware.dmm1]\ndriver = nidmm\nresource = PXI1Slot2\ntimeout_s = 2.5\n",
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with caplog.at_level(logging.WARNING):
        reopened = ConfigHandler.bootstrap()

    assert reopened.get_parameter("hardware.dmm1.driver") == "nidmm"
    assert reopened.get_parameter("hardware.dmm1.timeout_s") == "2.5"
    assert "hardware.dmm1" not in caplog.text


def test_a_secret_is_masked_in_the_active_configuration_lines(config, config_path, caplog):
    """Review Focus 5: a password in config.ini never reaches the run log."""
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[hardware.ssh1]\ndriver = x.Y\npassword = hunter2\n",
        encoding="utf-8",
    )
    ConfigHandler.reset_for_testing()

    with caplog.at_level(logging.DEBUG):
        reopened = ConfigHandler.bootstrap()

    assert reopened.get_parameter("hardware.ssh1.password") == "hunter2"
    assert "hunter2" not in caplog.text
    assert "hunter2" not in reopened.dump()
    assert "hardware.ssh1.password = ******" in caplog.text
```

- [ ] **Step 2: Run them to verify the new ones fail**

Run: `pytest tests/unit_tests/test_config_handler.py -k "section or secret" -v`
Expected: `test_a_hardware_section_is_kept_as_text_without_a_warning` and
`test_a_secret_is_masked_in_the_active_configuration_lines` FAIL; the reworded test passes.

- [ ] **Step 3: Add the prefix to `configuration_schema.py`**

Replace the module docstring paragraph

```
The schema is a flat list of named sections and nothing else. A section the user
adds that is not in it - `[hardware.dmm1]`, most likely - is not an error: it is
kept as it was written, reported once at WARNING, and its values come back as
text. How hardware is configured is Phase 5's question, and this module does not
pre-empt the answer.
```

with

```
The schema is a flat list of named sections and nothing else. A section the user
adds that is not in it is not an error: it is kept as it was written, reported
once at WARNING, and its values come back as text. The one family of sections it
knows without typing them is `[hardware.<name>]`: each declares a device for the
hardware layer (pypts.hal), whose keys belong to the device's driver - kept as
text, without a warning. See hal/hal.md.
```

Add below `READ_ONLY_SECTIONS`:

```python
#: The prefix of a device section: `[hardware.ssh1]` declares the device the
#: hardware layer knows as 'ssh1'. Its keys are the driver's, so none is typed
#: here; they come back as text. Nothing in such a section is mandatory, which
#: is why adding this did not change CONFIG_VERSION.
HARDWARE_PREFIX = "hardware."


def is_hardware_section(section: str) -> bool:
    """Whether a section declares a device: `hardware.` followed by a logical name."""
    return section.startswith(HARDWARE_PREFIX) and len(section) > len(HARDWARE_PREFIX)
```

And in `schema_for_section()`'s docstring, replace

```
    A plain lookup today. It stays a function rather than a dict access because
    it is the one place that decides what a section name means, and Phase 5 will
    have to answer that question again for hardware.
```

with

```
    A plain lookup. A device section is not in the schema either - its keys are
    the driver's - and is_hardware_section() is what tells the two apart.
```

- [ ] **Step 4: Change `config_handler.py`**

Add to the imports from `pypts.config_handler.configuration_schema` the name
`is_hardware_section`, and add `from pypts.utilities.common import masked`.

In `_validate`, replace

```python
            fields = schema_for_section(section)
            if fields is None:
                self._note(
                    logging.WARNING,
                    f"Configuration section [{section}] is not part of the schema; "
                    f"its values are available as text and nothing else reads them.",
                )
                values[section] = dict(options)
                continue
```

with

```python
            fields = schema_for_section(section)
            if fields is None:
                if is_hardware_section(section):
                    self._note(
                        logging.DEBUG,
                        f"Configuration section [{section}] declares a device; its values "
                        f"are kept as text for the hardware layer.",
                    )
                else:
                    self._note(
                        logging.WARNING,
                        f"Configuration section [{section}] is not part of the schema; "
                        f"its values are available as text and nothing else reads them.",
                    )
                values[section] = dict(options)
                continue
```

In `_note_active_configuration`, replace

```python
        for section, values in self._values.items():
            for key, value in values.items():
                self._note(logging.DEBUG, f"Configuration value {section}.{key} = {value}")
```

with

```python
        for section, values in self._values.items():
            for key, value in masked(values).items():
                self._note(logging.DEBUG, f"Configuration value {section}.{key} = {value}")
```

and extend its docstring with the sentence: `A secret (a key named like a password, see
utilities/common.py) is shown masked.`

In `dump()`, replace

```python
            lines.extend(f"    {key} = {value}" for key, value in self._values[section].items())
```

with

```python
            shown = masked(self._values[section])
            lines.extend(f"    {key} = {value}" for key, value in shown.items())
```

- [ ] **Step 5: Add the commented example to `config_template.ini`**

Append at the very end of `src/pypts/config_handler/config_template.ini`:

```ini

# Devices on the bench, one section each: [hardware.<logical name>]. Test code
# asks for a device by that name: pypts.hal.get_device("ssh1"). `driver` names
# the driver class; every other key goes to the driver. Optional: `python` (the
# interpreter of the driver process) and `call_timeout_s` (default 60). Keys
# named like a password are never written to the log, but this file is plain
# text: prefer key_filename to password.
#
# [hardware.ssh1]
# driver = pypts.hal.drivers.ssh.SshDriver
# host = 192.168.0.10
# username = tester
# key_filename = C:\Users\tester\.ssh\id_ed25519
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_config_handler.py tests/unit_tests/test_hal.py -v`
Expected: PASS — including `test_schema_and_template_agree` (the example is comments only).

---

### Task 7: `Bench` and `get_device()`

**Files:**
- Create: `src/pypts/hal/bench.py`
- Modify: `src/pypts/hal/__init__.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Consumes: `DriverProxy` (Task 5), `DriverError` (Task 2), `HARDWARE_PREFIX` and
  `is_hardware_section` (Task 6, imported lazily inside `hardware_sections()`).
- Produces:
  - `DEFAULT_CALL_TIMEOUT_S = 60.0`; `FRAMEWORK_KEYS = ("driver", "python", "call_timeout_s")`
  - `@dataclass(frozen=True) DeviceConfig(name, driver, python, call_timeout_s, settings: dict[str, str])` with `DeviceConfig.from_section(name: str, section: Mapping[str, Any]) -> DeviceConfig`
  - `hardware_sections(whole: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, str]]`
  - `ini_hardware_sections(path: str | os.PathLike[str]) -> dict[str, dict[str, str]]`
  - `hardware_sections_from_config() -> dict[str, dict[str, str]]`
  - `Bench(read_sections: Callable[[], Mapping[str, Mapping[str, Any]]])` with
    `Bench.from_ini(path)`, `get_device(name) -> DriverProxy`, `device_names() -> list[str]`,
    `close() -> None`, context manager (enter activates, exit closes + deactivates)
  - module function `get_device(name: str) -> DriverProxy`
  - `pypts.hal` exports `Bench`, `DriverProxy`, `get_device`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit_tests/test_hal.py`:

```python
from typing import ClassVar

from pypts.hal import Bench, get_device
from pypts.hal import bench as bench_module
from pypts.hal.bench import (
    DEFAULT_CALL_TIMEOUT_S,
    DeviceConfig,
    hardware_sections,
    hardware_sections_from_config,
    ini_hardware_sections,
)


class _FakeProxy:
    """Stands in for DriverProxy: records what the Bench does with it."""

    made: ClassVar[list["_FakeProxy"]] = []

    def __init__(self, name, driver_path, settings, *, python, call_timeout_s):
        self.name = name
        self.driver_path = driver_path
        self.settings = settings
        self.python = python
        self.call_timeout_s = call_timeout_s
        self.events: list[str] = []
        _FakeProxy.made.append(self)

    def open(self):
        self.events.append("open")

    def close(self):
        self.events.append("close")


@pytest.fixture
def fake_proxies(monkeypatch):
    _FakeProxy.made = []
    monkeypatch.setattr(bench_module, "DriverProxy", _FakeProxy)
    return _FakeProxy.made


SECTIONS = {
    "ssh1": {"driver": "pkg.Ssh", "host": "h", "call_timeout_s": "5"},
    "loop1": {"driver": "pkg.Loop"},
}


def test_device_config_splits_framework_keys_from_driver_keys():
    config = DeviceConfig.from_section("ssh1", {"driver": " pkg.Ssh ", "host": "h", "port": 22})
    assert config.driver == "pkg.Ssh"
    assert config.python == sys.executable
    assert config.call_timeout_s == DEFAULT_CALL_TIMEOUT_S
    assert config.settings == {"host": "h", "port": "22"}


def test_device_config_reads_python_and_call_timeout():
    config = DeviceConfig.from_section(
        "x", {"driver": "pkg.X", "python": "C:/py32/python.exe", "call_timeout_s": "2.5"}
    )
    assert config.python == "C:/py32/python.exe"
    assert config.call_timeout_s == 2.5
    assert config.settings == {}


@pytest.mark.parametrize(
    ("section", "words"),
    [
        ({"host": "h"}, "has no 'driver' key"),
        ({"driver": "pkg.X", "call_timeout_s": "soon"}, "positive number of seconds"),
        ({"driver": "pkg.X", "call_timeout_s": "0"}, "positive number of seconds"),
    ],
)
def test_device_config_explains_a_bad_section(section, words):
    with pytest.raises(DriverError, match=words):
        DeviceConfig.from_section("x", section)


def test_hardware_sections_keeps_only_devices_and_strips_the_prefix():
    whole = {
        "gui": {"theme": "dark"},
        "hardware.ssh1": {"host": "h", "port": 22},
        "hardware.": {"driver": "nameless"},
    }
    assert hardware_sections(whole) == {"ssh1": {"host": "h", "port": "22"}}


def test_ini_hardware_sections_reads_a_file(tmp_path):
    path = tmp_path / "bench.ini"
    path.write_text("[hardware.loop1]\ndriver = pkg.Loop\n[other]\nx = 1\n", encoding="utf-8")
    assert ini_hardware_sections(path) == {"loop1": {"driver": "pkg.Loop"}}


def test_hardware_sections_from_config_asks_the_config_handler(monkeypatch):
    class _Config:
        def get_whole_config(self):
            return {"hardware.loop1": {"driver": "pkg.Loop"}, "gui": {"theme": "dark"}}

    monkeypatch.setattr("pypts.config_handler.ConfigHandler", _Config)
    assert hardware_sections_from_config() == {"loop1": {"driver": "pkg.Loop"}}


def test_a_device_opens_once_and_is_reused(fake_proxies):
    bench = Bench(lambda: SECTIONS)
    first = bench.get_device("ssh1")
    assert bench.get_device("ssh1") is first
    assert len(fake_proxies) == 1
    assert first.events == ["open"]
    assert first.settings == {"host": "h"}
    assert first.call_timeout_s == 5.0


def test_the_sections_are_read_lazily_and_once(fake_proxies):
    reads = []

    def read():
        reads.append(1)
        return SECTIONS

    bench = Bench(read)
    with bench:
        pass
    assert reads == []
    bench.get_device("ssh1")
    bench.get_device("loop1")
    assert reads == [1]


def test_an_unknown_device_names_the_configured_ones(fake_proxies):
    bench = Bench(lambda: SECTIONS)
    with pytest.raises(DriverError, match=r"No device 'dmm1'.*Configured devices: loop1, ssh1"):
        bench.get_device("dmm1")
    assert bench.device_names() == ["loop1", "ssh1"]


def test_one_bad_section_does_not_stop_the_others(fake_proxies):
    bench = Bench(lambda: {"bad": {"host": "h"}, "loop1": {"driver": "pkg.Loop"}})
    with pytest.raises(DriverError):
        bench.get_device("bad")
    assert bench.get_device("loop1").events == ["open"]


def test_close_closes_every_device_newest_first(fake_proxies):
    bench = Bench(lambda: SECTIONS)
    order = []
    ssh = bench.get_device("ssh1")
    loop = bench.get_device("loop1")
    ssh.close = lambda: order.append("ssh1")
    loop.close = lambda: order.append("loop1")
    bench.close()
    assert order == ["loop1", "ssh1"]
    bench.close()
    assert order == ["loop1", "ssh1"]


def test_get_device_needs_an_active_bench():
    with pytest.raises(DriverError, match="No bench is active"):
        get_device("ssh1")


def test_get_device_asks_the_active_bench_until_it_closes(fake_proxies):
    with Bench(lambda: SECTIONS) as bench:
        device = get_device("ssh1")
        assert device is bench.get_device("ssh1")
    assert device.events == ["open", "close"]
    with pytest.raises(DriverError, match="No bench is active"):
        get_device("ssh1")


def test_get_device_works_from_another_thread(fake_proxies):
    """Review Focus 3: test code may start threads of its own."""
    found = []
    with Bench(lambda: SECTIONS):
        worker = threading.Thread(target=lambda: found.append(get_device("loop1")))
        worker.start()
        worker.join(timeout=5.0)
    assert found and found[0].name == "loop1"


def test_a_newer_bench_replaces_an_older_one(fake_proxies):
    """An abandoned run never leaves its with-block; the next run must still work."""
    old = Bench(lambda: SECTIONS)
    new = Bench(lambda: {"loop1": {"driver": "pkg.Other"}})
    old.__enter__()
    with new:
        assert get_device("loop1").driver_path == "pkg.Other"
    old.__exit__(None, None, None)
    with pytest.raises(DriverError, match="No bench is active"):
        get_device("loop1")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_hal.py -v`
Expected: FAIL — `ImportError: cannot import name 'Bench' from 'pypts.hal'`.

- [ ] **Step 3: Write `bench.py`**

```python
"""
The bench: the devices of one run, by logical name.

A Bench reads its devices from `[hardware.<name>]` sections, opens a device the
first time it is asked for it, and closes every device it opened when it is
closed. Entering it (`with bench:`) also makes it the *active* bench, which is
what get_device() asks - the Sequencer enters one per run, and a script outside
PyPTS does the same with `with Bench.from_ini("bench.ini"):`.

pypts.config_handler is imported inside the one function that needs it: this
module is imported by the driver process too (through pypts.hal), and that
process must not need what the configuration needs.
"""

import configparser
import os
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any

from pypts.hal.driver import DriverError
from pypts.hal.proxy import DriverProxy
from pypts.logger.log import log

#: How long one call may take when the section does not say (`call_timeout_s`).
DEFAULT_CALL_TIMEOUT_S = 60.0

#: The keys of a device section the hardware layer reads itself; every other
#: key goes to the driver's connect().
FRAMEWORK_KEYS = ("driver", "python", "call_timeout_s")


@dataclass(frozen=True)
class DeviceConfig:
    """One `[hardware.<name>]` section, split into what the layer reads and what the driver gets."""

    name: str
    driver: str
    python: str
    call_timeout_s: float
    settings: dict[str, str]

    @classmethod
    def from_section(cls, name: str, section: Mapping[str, Any]) -> "DeviceConfig":
        values: dict[str, str] = {}
        for key, value in section.items():
            values[key] = str(value)
        driver = values.pop("driver", "").strip()
        if not driver:
            raise DriverError(
                f"Device '{name}': [hardware.{name}] has no 'driver' key naming its driver class."
            )
        python = values.pop("python", "").strip()
        if not python:
            python = sys.executable
        timeout_text = values.pop("call_timeout_s", "").strip()
        if timeout_text:
            try:
                call_timeout_s = float(timeout_text)
            except ValueError:
                call_timeout_s = 0.0
            if call_timeout_s <= 0:
                raise DriverError(
                    f"Device '{name}': call_timeout_s must be a positive number of seconds, "
                    f"not '{timeout_text}'."
                )
        else:
            call_timeout_s = DEFAULT_CALL_TIMEOUT_S
        return cls(name, driver, python, call_timeout_s, values)


def hardware_sections(whole: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """The device sections of a whole configuration, by logical name, values as text."""
    from pypts.config_handler.configuration_schema import HARDWARE_PREFIX, is_hardware_section

    devices: dict[str, dict[str, str]] = {}
    for section, values in whole.items():
        if not is_hardware_section(section):
            continue
        text_values: dict[str, str] = {}
        for key, value in values.items():
            text_values[key] = str(value)
        devices[section[len(HARDWARE_PREFIX) :]] = text_values
    return devices


def ini_hardware_sections(path: str | os.PathLike[str]) -> dict[str, dict[str, str]]:
    """The device sections of an INI file of one's own - a bench outside PyPTS."""
    parser = configparser.ConfigParser(interpolation=None)
    with open(path, encoding="utf-8") as handle:
        parser.read_file(handle)
    whole: dict[str, dict[str, str]] = {}
    for section in parser.sections():
        whole[section] = dict(parser[section])
    return hardware_sections(whole)


def hardware_sections_from_config() -> dict[str, dict[str, str]]:
    """The device sections of this process's config.ini - what the Sequencer reads."""
    from pypts.config_handler import ConfigHandler

    return hardware_sections(ConfigHandler().get_whole_config())


class Bench:
    """The devices of one run. Thread-safe: test code may use it from threads of its own."""

    def __init__(self, read_sections: Callable[[], Mapping[str, Mapping[str, Any]]]) -> None:
        """
        Args:
            read_sections: returns the device sections by logical name. Called
                once, the first time a device is asked for - a run that uses
                no device never reads the configuration.
        """
        self._read_sections = read_sections
        self._sections: Mapping[str, Mapping[str, Any]] | None = None
        self._devices: dict[str, DriverProxy] = {}
        self._lock = threading.RLock()

    @classmethod
    def from_ini(cls, path: str | os.PathLike[str]) -> "Bench":
        """A bench described by an INI file of `[hardware.<name>]` sections."""
        return cls(lambda: ini_hardware_sections(path))

    def device_names(self) -> list[str]:
        with self._lock:
            return sorted(self._loaded_sections())

    def get_device(self, name: str) -> DriverProxy:
        """The device called `name`, opened on first use. Raises DriverError."""
        with self._lock:
            device = self._devices.get(name)
            if device is not None:
                return device
            sections = self._loaded_sections()
            section = sections.get(name)
            if section is None:
                known = ", ".join(sorted(sections)) or "none"
                raise DriverError(
                    f"No device '{name}' is configured. Add a [hardware.{name}] section to "
                    f"config.ini. Configured devices: {known}."
                )
            config = DeviceConfig.from_section(name, section)
            device = DriverProxy(
                config.name,
                config.driver,
                config.settings,
                python=config.python,
                call_timeout_s=config.call_timeout_s,
            )
            device.open()
            self._devices[name] = device
            return device

    def close(self) -> None:
        """Close every device this bench opened, newest first. Never raises."""
        with self._lock:
            names = list(self._devices)
            names.reverse()
            for name in names:
                try:
                    self._devices[name].close()
                except Exception as exc:  # noqa: BLE001 - one device must not keep the others open
                    log.warning("Device '%s' did not close: %s", name, exc)
            self._devices.clear()

    def _loaded_sections(self) -> Mapping[str, Mapping[str, Any]]:
        if self._sections is None:
            self._sections = self._read_sections()
            log.debug("Devices configured for this bench: %s.", sorted(self._sections))
        return self._sections

    def __enter__(self) -> "Bench":
        _activate(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        finally:
            _deactivate(self)


# --- the active bench -------------------------------------------------------------
#
# One per process. Not thread-local on purpose: test code may start threads of
# its own, and they belong to the same run. Two runs never overlap in one
# process - the Sequencer refuses a second Start - so one slot is enough.

_active_bench: Bench | None = None
_active_lock = threading.Lock()


def _activate(bench: Bench) -> None:
    global _active_bench
    with _active_lock:
        if _active_bench is not None and _active_bench is not bench:
            # Only an abandoned run (stop_running_sequence gave up on its
            # thread) leaves a bench active behind it.
            log.debug("A new bench replaces one that was never closed.")
        _active_bench = bench


def _deactivate(bench: Bench) -> None:
    global _active_bench
    with _active_lock:
        if _active_bench is bench:
            _active_bench = None


def get_device(name: str) -> DriverProxy:
    """
    The device called `name` on the active bench - what test code calls.

    Raises DriverError when no bench is active, when no such device is
    configured, or when it cannot be opened.
    """
    with _active_lock:
        bench = _active_bench
    if bench is None:
        raise DriverError(
            "No bench is active. get_device() works in test code PyPTS is running, or inside "
            "'with Bench.from_ini(path):' in a script of your own."
        )
    return bench.get_device(name)
```

Then update `src/pypts/hal/__init__.py` — replace the import block and `__all__` with:

```python
from pypts.hal.bench import Bench, get_device
from pypts.hal.driver import Driver, DriverError
from pypts.hal.families import DMM, PSU, SSH, Load, Other, Scope
from pypts.hal.proxy import DriverProxy

__all__ = [
    "DMM",
    "PSU",
    "SSH",
    "Bench",
    "Driver",
    "DriverError",
    "DriverProxy",
    "Load",
    "Other",
    "Scope",
    "get_device",
]
```

(If ruff's `RUF022` asks for a different `__all__` order, apply its order.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal.py tests/unit_tests/test_hal_proxy.py -v`
Expected: PASS.

---

### Task 8: One bench per run in the Sequencer

**Files:**
- Modify: `src/pypts/sequencer/sequencer.py`
- Test: `tests/unit_tests/test_sequencer.py` (append)

**Interfaces:**
- Consumes: `Bench`, `hardware_sections_from_config` (Task 7).
- Produces: `Sequencer.read_hardware_sections: Callable[[], Mapping[str, Mapping[str, Any]]]`
  (default `hardware_sections_from_config`); `execute_sequence()` runs the step layer inside
  `with Bench(self.read_hardware_sections):`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit_tests/test_sequencer.py` (add `from pypts.hal import DriverError, get_device`,
`from pypts.hal import bench as hal_bench` and `from pypts.hal.proxy import DriverProxy` to the
imports):

```python
# --- the hardware layer: one bench per run -------------------------------------

LOOPBACK_SECTIONS = {"loop1": {"driver": "pypts.hal.drivers.loopback.LoopbackDriver"}}

BENCH_CODE = '''
from pypts.hal import get_device


def echo_twice(text):
    device = get_device("loop1")
    return device.echo(text) + device.echo(text)


def use_a_missing_device():
    get_device("nothing_here")
'''

BENCH_RECIPE = f"""\
name: Bench run
version: {CURRENT_VERSION}
---
sequence_name: Main
steps:
  - steptype: PythonModule
    step_name: Missing device
    module: bench_code.py
    method_name: use_a_missing_device
  - steptype: PythonModule
    step_name: Echo through the device
    module: bench_code.py
    method_name: echo_twice
    inputs:
      text: hi
    outputs:
      output: {{type: equals, value: hihi}}
"""


def write_bench_recipe(tmp_path):
    (tmp_path / "bench_code.py").write_text(BENCH_CODE, encoding="utf-8")
    recipe_path = tmp_path / "bench.yml"
    recipe_path.write_text(BENCH_RECIPE, encoding="utf-8")
    return Recipe.from_file(str(recipe_path))


def test_a_run_reaches_its_devices_and_closes_them_at_the_end(sequencer, tmp_path, monkeypatch):
    instance, outbox, inbox = sequencer
    opened = []

    class RecordingProxy(DriverProxy):
        def open(self):
            super().open()
            opened.append(self)

    monkeypatch.setattr(hal_bench, "DriverProxy", RecordingProxy)
    instance.read_hardware_sections = lambda: LOOPBACK_SECTIONS
    instance.recipe = write_bench_recipe(tmp_path)

    instance.execute_sequence("Main")

    finished = {}
    for message in drain(outbox):
        if isinstance(message, StepFinished):
            finished[message.outcome.step_name] = message.outcome
    assert finished["Missing device"].result is ResultType.ERROR
    assert finished["Echo through the device"].result is ResultType.PASS
    assert len(opened) == 1
    assert not opened[0].is_open()
    with pytest.raises(DriverError, match="No bench is active"):
        get_device("loop1")


def test_a_run_that_uses_no_device_never_reads_the_hardware_sections(sequencer):
    instance, outbox, inbox = sequencer

    def must_not_be_called():
        raise AssertionError("the hardware sections were read")

    instance.read_hardware_sections = must_not_be_called
    load_wait_recipe(instance, inbox)

    instance.execute_sequence("Main")

    finished = [m.outcome for m in drain(outbox) if isinstance(m, StepFinished)]
    assert all(o.result is ResultType.DONE for o in finished)


def test_the_default_reads_config_ini(sequencer):
    instance, _, _ = sequencer
    assert instance.read_hardware_sections is hal_bench.hardware_sections_from_config
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_sequencer.py -k "device or hardware or config_ini" -v`
Expected: FAIL — `AttributeError: 'Sequencer' object has no attribute 'read_hardware_sections'`
(the first test fails at the step result: `get_device` raises "No bench is active").

- [ ] **Step 3: Wire the bench into `sequencer.py`**

Imports — replace `from collections.abc import Callable` with
`from collections.abc import Callable, Mapping`, and add after the `pypts._version` import
(keep ruff's isort order):

```python
from pypts.hal.bench import Bench, hardware_sections_from_config
```

In `Sequencer.__init__`, after `self.goodbye_sent = False`, add:

```python
        #: Where a run's devices are declared - the [hardware.<name>] sections
        #: of config.ini. Read only when test code first asks for a device, so
        #: a run that uses none never reads them. Tests replace it.
        self.read_hardware_sections: Callable[[], Mapping[str, Mapping[str, Any]]] = (
            hardware_sections_from_config
        )
```

Add to the class docstring's `Attributes:` list:

```
        read_hardware_sections: returns the device sections of config.ini by
              logical name; handed to the Bench each run builds.
```

In `execute_sequence()`, replace

```python
        step_results: list[StepResult] = []
        try:
            result, step_results = run_sequence_body(runtime, sequence)
        except Exception as error:  # noqa: BLE001 - step failures must not crash the sequencer
            report_error(self, error, operation="Sequencer.execute_sequence")
            result = ResultType.ERROR
```

with

```python
        step_results: list[StepResult] = []
        # The run's devices: opened by test code on first use, all closed when
        # this block ends - after the teardown steps, which may use them too,
        # and before RunFinished, so a run that has ended holds no device open.
        with Bench(self.read_hardware_sections):
            try:
                result, step_results = run_sequence_body(runtime, sequence)
            except Exception as error:  # noqa: BLE001 - step failures must not crash the sequencer
                report_error(self, error, operation="Sequencer.execute_sequence")
                result = ResultType.ERROR
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_sequencer.py -v`
Expected: PASS (the whole file — the existing tests never ask for a device).

---

### Task 9: `SshDriver`

**Files:**
- Create: `src/pypts/hal/drivers/ssh.py`, `tests/unit_tests/test_hal_ssh.py`

**Interfaces:**
- Consumes: `SSH` (Task 2), `DriverError` (Task 2).
- Produces: `pypts.hal.drivers.ssh.SshDriver(SSH)`; config keys `host`, `username` (required),
  `port` (22), `password`, `key_filename`, `known_hosts`, `accept_unknown_host` (false),
  `connect_timeout_s` (10); operations `execute(command, timeout_s=None) -> {"stdout", "stderr", "exit_code"}`,
  `put_file(local_path, remote_path)`, `get_file(remote_path, local_path)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit_tests/test_hal_ssh.py`:

```python
"""
Unit tests for the SSH driver (src/pypts/hal/drivers/ssh.py), in-process, with
paramiko's SSHClient replaced by a mock - no host is needed. Skipped where
paramiko is not installed (pip install pts-framework[ssh]).
"""

from unittest.mock import MagicMock

import pytest

paramiko = pytest.importorskip("paramiko")

from pypts.hal import DriverError  # noqa: E402 - after the importorskip on purpose
from pypts.hal.driver import operations_of  # noqa: E402 - after the importorskip on purpose
from pypts.hal.drivers import ssh as ssh_module  # noqa: E402 - after the importorskip on purpose
from pypts.hal.drivers.ssh import SshDriver  # noqa: E402 - after the importorskip on purpose


@pytest.fixture
def client(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(ssh_module.paramiko, "SSHClient", lambda: mock)
    return mock


def connected(client):
    driver = SshDriver()
    driver.connect({"host": "bench-pc", "username": "tester"})
    return driver


def test_the_ssh_driver_is_an_ssh():
    assert SshDriver.FAMILY == "SSH"
    assert operations_of(SshDriver) == ["execute", "get_file", "put_file"]


def test_connect_passes_the_settings_and_refuses_unknown_hosts(client):
    SshDriver().connect(
        {"host": "bench-pc", "username": "tester", "port": "2222", "password": "pw"}
    )
    client.load_system_host_keys.assert_called_once_with()
    policy = client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.RejectPolicy)
    client.connect.assert_called_once_with(
        hostname="bench-pc",
        port=2222,
        username="tester",
        password="pw",
        key_filename=None,
        timeout=10.0,
    )


def test_accept_unknown_host_opts_out_per_device(client):
    SshDriver().connect({"host": "h", "username": "u", "accept_unknown_host": "yes"})
    policy = client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.AutoAddPolicy)


def test_a_known_hosts_file_is_read_too(client):
    SshDriver().connect({"host": "h", "username": "u", "known_hosts": "C:/keys/known_hosts"})
    client.load_host_keys.assert_called_once_with("C:/keys/known_hosts")


@pytest.mark.parametrize(
    ("config", "words"),
    [
        ({"username": "u"}, "needs 'host' and 'username'"),
        ({"host": "h"}, "needs 'host' and 'username'"),
        ({"host": "h", "username": "u", "port": "ssh"}, "port must be a whole number"),
        ({"host": "h", "username": "u", "connect_timeout_s": "soon"}, "connect_timeout_s"),
    ],
)
def test_a_bad_config_is_a_driver_error(client, config, words):
    with pytest.raises(DriverError, match=words):
        SshDriver().connect(config)
    client.connect.assert_not_called()


def test_a_failed_connection_is_a_driver_error_and_closes_the_client(client):
    client.connect.side_effect = OSError("No route to host")
    with pytest.raises(DriverError, match=r"tester@bench-pc:22 failed: No route to host"):
        connected(client)
    client.close.assert_called_once_with()


def test_execute_returns_output_and_exit_code(client):
    stdout = MagicMock()
    stdout.read.return_value = "Linux bench 6.1 µs\n".encode()
    stdout.channel.recv_exit_status.return_value = 0
    stderr = MagicMock()
    stderr.read.return_value = b""
    client.exec_command.return_value = (MagicMock(), stdout, stderr)

    result = connected(client).execute("uname -a", timeout_s=5.0)

    client.exec_command.assert_called_once_with("uname -a", timeout=5.0)
    assert result == {"stdout": "Linux bench 6.1 µs\n", "stderr": "", "exit_code": 0}


def test_execute_before_connect_is_a_driver_error():
    with pytest.raises(DriverError, match="not connected"):
        SshDriver().execute("ls")


def test_put_and_get_file_use_sftp_and_close_it(client):
    sftp = client.open_sftp.return_value
    driver = connected(client)
    driver.put_file("local.bin", "/tmp/remote.bin")
    driver.get_file("/tmp/log.txt", "log.txt")
    sftp.put.assert_called_once_with("local.bin", "/tmp/remote.bin")
    sftp.get.assert_called_once_with("/tmp/log.txt", "log.txt")
    assert sftp.close.call_count == 2


def test_teardown_closes_once_and_is_safe_twice(client):
    driver = connected(client)
    driver.teardown()
    driver.teardown()
    client.close.assert_called_once_with()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_hal_ssh.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pypts.hal.drivers.ssh'` (or SKIPPED if
paramiko is not installed — then `pip install paramiko` first; Task 10 adds it to `[test]`).

- [ ] **Step 3: Write `drivers/ssh.py`**

```python
"""
SSH - a remote shell, over paramiko. The reference driver: a new driver
follows its shape.

Keys of its [hardware.<name>] section (all text):

    host                 required
    username             required
    port                 default 22
    password             optional - config.ini is plain text, prefer key_filename
    key_filename         optional, path to a private key
    known_hosts          optional, a known_hosts file read beside the system one
    accept_unknown_host  default false: a host whose key is not known is refused
    connect_timeout_s    default 10

Needs paramiko: pip install pts-framework[ssh].
"""

from typing import Any

try:
    import paramiko
except ImportError as exc:
    raise ImportError("The SSH driver needs paramiko: pip install pts-framework[ssh]") from exc

from pypts.hal.driver import DriverError
from pypts.hal.families import SSH

#: How a yes is written in config.ini - the configuration's own vocabulary.
TRUE_TEXT = ("1", "yes", "true", "on")

DEFAULT_PORT = 22
DEFAULT_CONNECT_TIMEOUT_S = 10.0


class SshDriver(SSH):
    """One SSH session to one host."""

    def __init__(self) -> None:
        self._client: Any = None

    def connect(self, config: dict[str, str]) -> None:
        host = config.get("host", "").strip()
        username = config.get("username", "").strip()
        if not host or not username:
            raise DriverError("SSH needs 'host' and 'username' in its [hardware.<name>] section.")
        port_text = config.get("port", "").strip()
        if port_text:
            if not port_text.isdigit():
                raise DriverError(f"SSH port must be a whole number, not '{port_text}'.")
            port = int(port_text)
        else:
            port = DEFAULT_PORT
        timeout_text = config.get("connect_timeout_s", "").strip()
        if timeout_text:
            try:
                timeout_s = float(timeout_text)
            except ValueError:
                raise DriverError(
                    f"SSH connect_timeout_s must be a number of seconds, not '{timeout_text}'."
                ) from None
        else:
            timeout_s = DEFAULT_CONNECT_TIMEOUT_S
        password = config.get("password") or None
        key_filename = config.get("key_filename") or None
        known_hosts = config.get("known_hosts", "").strip()
        accept_unknown = config.get("accept_unknown_host", "").strip().lower() in TRUE_TEXT

        client = paramiko.SSHClient()
        try:
            client.load_system_host_keys()
            if known_hosts:
                client.load_host_keys(known_hosts)
            if accept_unknown:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                key_filename=key_filename,
                timeout=timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - paramiko raises many types; one for the caller
            client.close()
            raise DriverError(
                f"SSH connection to {username}@{host}:{port} failed: {exc}"
            ) from exc
        self._client = client

    def execute(self, command: str, timeout_s: float | None = None) -> dict[str, Any]:
        """Run one command and wait for it. Output is read before the exit status, so a
        command that prints a lot cannot fill the channel and hang."""
        client = self._connected()
        _, stdout, stderr = client.exec_command(command, timeout=timeout_s)
        out_text = stdout.read().decode("utf-8", errors="replace")
        err_text = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        return {"stdout": out_text, "stderr": err_text, "exit_code": exit_code}

    def put_file(self, local_path: str, remote_path: str) -> None:
        sftp = self._connected().open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def get_file(self, remote_path: str, local_path: str) -> None:
        sftp = self._connected().open_sftp()
        try:
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()

    def teardown(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _connected(self) -> Any:
        if self._client is None:
            raise DriverError("SSH is not connected.")
        return self._client
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_hal_ssh.py -v`
Expected: PASS.

---

### Task 10: Dependencies, extras and type checking

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Move the driver libraries out of the core dependencies**

Replace the `dependencies = [ ... ]` list with:

```toml
dependencies = [
  "matplotlib",
  "numpy",
  # Per-user config/data directories, so config.ini and the run output land
  # where the platform expects rather than in the temp directory.
  "platformdirs",
  "PySide6==6.9.1",
  "pydantic>=2.6",
  "PyYAML==6.0.2",
  "ruamel.yaml",
]
```

(`nptdms` is gone entirely — D10; only `spikes/` used it, and spikes install what they need.)

- [ ] **Step 2: Add the extras**

In `[project.optional-dependencies]`, change `test` and add the hardware extras after `doc`:

```toml
test = [
  "pytest",
  "pytest-qt",
  # The SSH driver's tests run against a mocked client, but import paramiko.
  "paramiko",
]
```

```toml
# Hardware drivers. The core ships none of their libraries; a bench installs
# what its drivers need: pip install pts-framework[ssh], or [hardware] for all.
ssh = ["paramiko"]
ni = ["nidmm==1.4.8", "hightime==0.2.2"]
serial = ["pyserial"]
hardware = ["pts-framework[ssh,ni,serial]"]
```

- [ ] **Step 3: Put the hardware layer under mypy**

Add `"src/pypts/hal",` to `[tool.mypy] files` (after `"src/pypts/api",`), and add an override
below the pydantic one:

```toml
[[tool.mypy.overrides]]
# The SSH driver imports paramiko, which ships no type information, and the CI
# typecheck job installs only mypy.
module = ["paramiko", "paramiko.*"]
ignore_missing_imports = true
```

- [ ] **Step 4: Reinstall and run the gates**

```
pip install -e .[dev]
pytest tests
ruff check src tests
mypy
```

Expected: all pass. Fix any mypy finding in `src/pypts/hal` (likely spots: `subprocess.Popen[str]`
generics, `inspect.getmembers` typing) **without** `# type: ignore` unless it names the error code
and the reason.

---

### Task 11: Demo recipe and documentation

**Files:**
- Create: `resources/recipes/Development_recipes/hal_demo.yml`, `.../hal_demo_tests.py`
- Modify: `tests/unit_tests/test_recipe.py`
- Rewrite: `src/pypts/hal/hal.md`
- Modify: `src/pypts/config_handler/config_handler.md`, `src/pypts/sequencer/sequencer.md`,
  `src/pypts/step/step.md`, `src/pypts/utilities/utilities.md`, `usage_manual.html`,
  `pypts_implementation_status.html`, `TODO.txt`

- [ ] **Step 1: Write the failing demo test**

In `tests/unit_tests/test_recipe.py`, add beside the other demo constants
(`PYTHONMODULE_DEMO` etc.): `HAL_DEMO = DEMOS / "hal_demo.yml"`, and append:

```python
def test_the_hal_demo_recipe_parses():
    """resources/recipes/Development_recipes/hal_demo.yml shows test code reaching
    devices by logical name; running it needs [hardware.loop1] (and ssh1) in config.ini."""
    recipe = Recipe.from_file(str(HAL_DEMO))

    assert recipe.name == "HAL demo"
    names = [step.name for step in recipe.sequences["Main"].steps]
    assert names == ["Loopback echo", "Remote system name"]
```

Run: `pytest tests/unit_tests/test_recipe.py -k hal_demo -v` — Expected: FAIL (file missing).

- [ ] **Step 2: Write the demo files**

`resources/recipes/Development_recipes/hal_demo_tests.py`:

```python
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The test functions hal_demo.yml calls: test code reaching bench devices by
logical name. The names are declared in config.ini, one [hardware.<name>]
section each - see the comment at the top of hal_demo.yml.
"""

from pypts.hal import get_device


def loopback_echo(text):
    """Send text to the loopback device and get it back."""
    device = get_device("loop1")
    return {"echoed": device.echo(text)}


def ssh_uname():
    """Ask the remote host what it runs."""
    result = get_device("ssh1").execute("uname -a")
    return {"exit_code": result["exit_code"], "system": result["stdout"].strip()}
```

`resources/recipes/Development_recipes/hal_demo.yml`:

```yaml
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# The hardware layer showcase: test code asks for a device by its logical name,
# PyPTS opens it on first use and closes it when the run ends. The devices are
# declared in config.ini (File -> Open Config), not in the recipe:
#
#   [hardware.loop1]
#   driver = pypts.hal.drivers.loopback.LoopbackDriver
#
#   [hardware.ssh1]
#   driver = pypts.hal.drivers.ssh.SshDriver
#   host = <a machine you can reach>
#   username = <you>
#   key_filename = <your private key>
#
# Without [hardware.ssh1] the second step ends ERROR with "No device 'ssh1' is
# configured" - which is itself what that looks like. The SSH driver needs
# pip install pts-framework[ssh].
name: HAL demo
description: Two devices reached by logical name from test code.
version: 0.2
---
sequence_name: Main
description: A loopback device, then a remote shell.
steps:
  - steptype: PythonModule
    step_name: Loopback echo
    description: The device sends the text back.
    module: hal_demo_tests.py
    method_name: loopback_echo
    inputs:
      text: hello
    outputs:
      echoed: {type: equals, value: hello}
  - steptype: PythonModule
    step_name: Remote system name
    description: uname -a on the SSH host must succeed.
    module: hal_demo_tests.py
    method_name: ssh_uname
    outputs:
      exit_code: {type: equals, value: 0}
```

Run: `pytest tests/unit_tests/test_recipe.py -k hal_demo -v` — Expected: PASS. If the recipe
loader reports a different version than `0.2` as current, match the version the other demos in
that folder declare.

- [ ] **Step 3: Rewrite `src/pypts/hal/hal.md`**

Replace the whole file with:

````markdown
<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# hal — the hardware layer

Devices on the bench, reached by **logical name** from test code. Every device runs its
driver in **a process of its own**: a driver that crashes, hangs or leaks takes its own
process down, not PyPTS. Decided 2026-10-08 (roadmap §1.53), replacing the earlier
"in-process library, sidecar only after an incident" design.

```python
from pypts.hal import get_device

def read_kernel():
    result = get_device("ssh1").execute("uname -r")
    return {"kernel": result["stdout"].strip()}
```

## Files

| File | Holds |
|---|---|
| `__init__.py` | The public API: `get_device`, `Bench`, `DriverProxy`, `Driver`, `DriverError`, the six families |
| `driver.py` | `Driver` (ABC: `connect`, `teardown`, `recover`), `DriverError`, `LIFECYCLE_METHODS`, `operations_of()` |
| `families.py` | `PSU`, `DMM`, `Scope`, `SSH`, `Load`, `Other`; `FAMILIES`, `FAMILY_NAMES` |
| `protocol.py` | The wire format: message kinds, `encode()`, `decode()`, `LineReader`, `ProtocolError` |
| `runner.py` | The driver process: `python -m pypts.hal.runner` |
| `proxy.py` | `DriverProxy` — one device as test code sees it; `child_environment()` |
| `bench.py` | `Bench` — the devices of one run; `get_device()`; `DeviceConfig`; section readers |
| `drivers/loopback.py` | `LoopbackDriver` (Other) — no hardware; tests, demo, smoke check |
| `drivers/ssh.py` | `SshDriver` (SSH) — the reference driver, paramiko |

## How a call travels

1. Test code calls `get_device("ssh1")`. The **active bench** (the run's, see *Lifetime*)
   reads the `[hardware.*]` sections once, builds a `DriverProxy` and calls `open()`.
2. `open()` listens on `127.0.0.1:<ephemeral>` and starts
   `<python> -m pypts.hal.runner --port <n> --driver <dotted.Class> --log-level <root level>`
   with `child_environment()` — this process's `sys.path` added to `PYTHONPATH`, so a source
   tree run (`run_pypts.py`) imports in the child too. On Windows no console window opens.
3. The runner connects back, imports and builds the driver, and sends `hello` (family and
   operations) — or `fatal` with the reason. The proxy then calls `connect(settings)`.
4. `device.execute("uname -r")` is `__getattr__`: a name in `operations` becomes a `call`; any
   other name raises `AttributeError` without a round trip.
5. The runner answers with `result` or `error`; `log` lines may come first and are logged.

## Protocol

One JSON object per line, ASCII on the wire (`ensure_ascii`), over TCP on 127.0.0.1.

| Kind | Direction | Fields |
|---|---|---|
| `hello` | runner → proxy, once, first | `family`, `operations` |
| `fatal` | runner → proxy, instead of hello | `message` |
| `call` | proxy → runner | `id`, `method`, `args`, `kwargs` |
| `log` | runner → proxy, any time | `level`, `logger`, `message` |
| `result` | runner → proxy | `id`, `value` |
| `error` | runner → proxy | `id`, `type`, `message`, `traceback` |

Arguments and return values must be what JSON carries (str, int, float, bool, None, list,
dict). An argument that is not is refused before sending; a return value that is not comes
back as an `error`. `connect`, `teardown`, `recover` are callable but not `operations`.

## Configuration

One section per device in `config.ini` (or, outside PyPTS, any INI file given to
`Bench.from_ini()`):

```ini
[hardware.ssh1]
driver = pypts.hal.drivers.ssh.SshDriver    ; required: the driver class, dotted
python = C:\Python311-32\python.exe          ; optional: the driver process's interpreter
call_timeout_s = 120                         ; optional: longest one call may take, default 60
host = 192.168.0.10                          ; everything else goes to the driver's connect()
username = tester
key_filename = C:\Users\tester\.ssh\id_ed25519
```

`config_handler` recognises `[hardware.<name>]` (`configuration_schema.is_hardware_section()`):
kept as text, no WARNING, nothing mandatory — `CONFIG_VERSION` unchanged. Keys are lower-cased
(configparser). A key named like a password (`utilities/common.py` → `is_secret_key()`) is
masked in every log line, including the proxy's call trace. The file itself is plain text.

A custom driver's module must be importable by the driver process: installed, or on this
process's `sys.path` (which the child inherits through `PYTHONPATH`).

## Lifetime

- **Per run.** A run is one Start press: one top-level sequence and every sequence it calls.
  `Sequencer.execute_sequence()` wraps the step layer in `with Bench(self.read_hardware_sections):`.
  A device opens on first `get_device()`; all close, newest first, after the teardown steps and
  before `RunFinished`, whatever the result. A run that asks for no device never reads the
  sections. Headless (`--mode headless`) and API (`pypts.api.Pts`) runs go through the same
  Sequencer, so they get the same bench.
- **The active bench** is one slot per process, not thread-local: threads test code starts
  belong to the run. A newer bench replaces an older one that was never closed (an abandoned
  run); closing a bench only clears the slot if it is still the active one.
- **Standalone**: `with Bench.from_ini("bench.ini"):` activates a bench in a plain script, so the
  same test functions run outside PyPTS.
- **PyPTS dies**: the connection drops, the runner calls `teardown()` and exits.

## Failure

| What happens | What test code sees |
|---|---|
| Driver raises | `DriverError("Device 'x': 'op' failed: Type: message")`; the device stays usable; traceback at DEBUG |
| Call exceeds `call_timeout_s` | `DriverError("... did not answer 'op' within N s; its driver process was stopped.")` |
| Driver process dies | `DriverError("Device 'x' stopped unexpectedly (exit code N).")` |
| Cannot start / import / build / connect | `DriverError("Device 'x' could not be opened: ...")`, with the last printed lines |
| Unknown device | `DriverError("No device 'x' is configured. ... Configured devices: ...")` |
| No active bench | `DriverError("No bench is active. ...")` |

Uncaught in test code, each makes the step ERROR through the normal step path. Nothing recovers
on its own: `device.recover()` calls the driver's `recover()` while the process lives, or starts a
fresh process and connects when it does not.

## Logging

INFO (technician): `Device 'x' connected.`, `Device 'x' disconnected.`,
`Recovering device 'x'.`, `Device 'x' recovered.`; WARNING: `Device 'x' did not disconnect
cleanly: ...`. Forwarded records are logged as `Device 'x': <message>` — at their own level
when they come from the driver's module, at DEBUG when another library logs below WARNING.
Printed output, every call and its return value, and tracebacks are DEBUG.

## Writing a driver

1. Derive from the family it belongs to (`from pypts.hal import PSU`), never from `Driver`
   directly — the runner refuses a driver of no family.
2. Implement `connect(config)` (all values are text), `teardown()` (harmless when nothing is
   open) and the family's verbs. Every other public method becomes an operation too.
3. Standard library + your vendor library only; log with `logging.getLogger(__name__)`.
   Do not name a method `name`, `family`, `operations`, `open`, `close`, `recover` or
   `is_open` (`proxy.RESERVED_NAMES`).
4. Import the vendor library at the top of the driver module with an `ImportError` that names
   the extra to install (see `drivers/ssh.py`).
5. Test it in-process with the vendor library mocked (`test_hal_ssh.py`), and through a real
   driver process with the loopback pattern (`test_hal_proxy.py`).

Family verbs: PSU `set_voltage`, `set_current_limit`, `output_on`, `output_off`,
`measure_voltage`, `measure_current` (channel from 1); DMM `measure_dc_voltage`,
`measure_ac_voltage`, `measure_dc_current`, `measure_resistance`; Scope `set_timebase`,
`set_vertical_scale`, `arm_single`, `read_waveform`; Load `set_mode` (CC/CV/CR/CP), `set_level`,
`input_on`, `input_off`, `measure_voltage`, `measure_current`; SSH `execute`, `put_file`,
`get_file`; Other none.

## SSH

`SshDriver` keys: `host`, `username` (required), `port` (22), `password`, `key_filename`,
`known_hosts`, `accept_unknown_host` (false), `connect_timeout_s` (10). Unknown host keys are
refused (`RejectPolicy`) unless `accept_unknown_host` is true. Needs
`pip install pts-framework[ssh]`. The old engine's `SSHConnectStep`/`SSHCloseStep` are replaced
by this; see `step/step.md` §2.7.

## Packaging

The core ships no driver library. Extras: `[ssh]` paramiko, `[ni]` nidmm + hightime,
`[serial]` pyserial, `[hardware]` all three.

## Planned: devices from the recipe (not built)

A step will name the devices it needs, and the step layer will hand them to the function as
keyword arguments:

```yaml
- steptype: PythonModule
  step_name: Kernel version
  module: bench_tests.py
  method_name: read_kernel
  devices:
    dut: ssh1          # parameter name: logical device name
```

It reuses the run's active bench (`get_device()`), so nothing in this module changes; it is a
recipe-format change (`recipe_guide.html`, the schema in `recipe/recipe_schema.py`, the
verificator). Roadmap TODO in §1.53.

## Known gaps

- A call blocked inside a driver is not interrupted by Stop; `call_timeout_s` bounds it.
- No side channel for bulk data: a waveform travels as a JSON list.
- An abandoned run's devices stay open until CORE exits (the connection then drops).
- No automatic recovery policy — only `device.recover()` from test code.
- No PSU, DMM, Scope or Load driver ships yet; only the family bases.
````

- [ ] **Step 4: Update the other context files**

`src/pypts/config_handler/config_handler.md`:
- Replace the paragraph that begins `**There is no hardware section.**` (lines 122–128) with:

  ```markdown
  **Hardware sections.** A `[hardware.<logical name>]` section declares one device for the
  hardware layer (`hal/hal.md` → *Configuration*). The schema types none of its keys — they are
  the driver's — so it is kept verbatim and returned as text, like an unknown section, but
  **without** the WARNING: `configuration_schema.is_hardware_section()` tells the two apart.
  Nothing in it is mandatory, so `CONFIG_VERSION` did not change. The template ends with a
  commented example.
  ```
- In *Reading*, replace the line
  `config.get_parameter("hardware.dmm1.timeout_s")      # -> str: not in the schema` with
  `config.get_parameter("hardware.dmm1.timeout_s")      # -> str: a device section, untyped`.
- In *Known gaps*, replace the bullet beginning `- **Hardware is not configurable yet, at all.**`
  with:

  ```markdown
  - **Device sections are untyped.** A wrong key in `[hardware.<name>]` is found only when the
    driver reads it (at the first `get_device()`), not at start-up.
  - **Secrets are masked in the log, not protected on disk.** `_note_active_configuration()`
    and `dump()` show a key named like a password (`utilities/common.py` → `is_secret_key()`)
    as `******`; `config.ini` itself stays plain text.
  ```

`src/pypts/sequencer/sequencer.md` — in *What it owns*, after the `execute_sequence()` bullet,
add:

```markdown
- **The run's devices** — `execute_sequence()` runs the step layer inside
  `with Bench(self.read_hardware_sections):` (`hal/hal.md` → *Lifetime*). Test code opens a
  device on first `get_device()`; every device closes when the block ends — after the teardown
  steps, before `RunFinished`. `read_hardware_sections` defaults to
  `hal.bench.hardware_sections_from_config` and is only called on the first `get_device()`, so a
  run that uses no device never reads `config.ini`; tests replace it.
```

and in *Known gaps* add: `- A run abandoned by stop_running_sequence() leaves its devices open
until CORE exits; the next run's bench replaces it as the active one.`

`src/pypts/step/step.md` §2.7 — replace the paragraph beginning `Open for the implementation
session:` and its four bullets with:

```markdown
**Landed 2026-10-08 (roadmap §1.53).** SSH is the hardware layer's `SshDriver`
(`pypts.hal.drivers.ssh`), reached from test code with `pypts.hal.get_device("<name>")`.
Credentials live in `[hardware.<name>]` in `config.ini`, masked in the log. The session belongs
to the run's bench, which closes it after the teardown steps on every outcome, abort included —
what the old `teardown_steps` rule stood in for. The live client stays in the driver's own
process; only JSON crosses. Details: `hal/hal.md`. A recipe-level `devices:` key is planned,
not built.
```

`src/pypts/utilities/utilities.md` §`common.py` — append to the paragraph:
`` Also `SECRET_KEY_WORDS`, `MASK`, `is_secret_key()` and `masked()`: which configuration keys
are secrets, and a copy of a mapping fit for a log (the config dump, the hardware layer's call
trace). ``

- [ ] **Step 5: Update `usage_manual.html`**

Insert a new section after the `<h2 id="files">9. Where files go</h2>` section (before
`<h2 id="tools">`), and renumber `10. Helper tools` → `11.` and `11. Troubleshooting` → `12.`
(grep the file for `§10`, `§11`, `#tools`, `#trouble` and fix any number that refers to them):

```html
<h2 id="hardware">10. Hardware devices</h2>
<p>Test code reaches a device by a <strong>logical name</strong>; <code>config.ini</code> says what
that name is. Each device runs its driver in a process of its own, opened the first time a run
asks for it and closed when the run ends.</p>
<pre><code>[hardware.ssh1]
driver = pypts.hal.drivers.ssh.SshDriver
host = 192.168.0.10
username = tester
key_filename = C:\Users\tester\.ssh\id_ed25519</code></pre>
<pre><code>from pypts.hal import get_device

def read_kernel():
    result = get_device("ssh1").execute("uname -r")
    return {"kernel": result["stdout"].strip()}</code></pre>
<ul>
  <li><strong>Install the driver's library</strong>: <code>pip install pts-framework[ssh]</code>
      (also <code>[ni]</code>, <code>[serial]</code>, or <code>[hardware]</code> for all).</li>
  <li><strong>Optional keys</strong>: <code>call_timeout_s</code> (longest one call may take,
      default 60) and <code>python</code> (another interpreter for the driver process).</li>
  <li><strong>SSH</strong>: an unknown host key is refused; add the host to your
      <code>known_hosts</code>, name a file with <code>known_hosts =</code>, or set
      <code>accept_unknown_host = true</code>. A <code>password</code> key works, but the file is
      plain text: prefer <code>key_filename</code>. Passwords are never written to the log.</li>
  <li><strong>No hardware?</strong> <code>driver = pypts.hal.drivers.loopback.LoopbackDriver</code>
      answers with whatever it is sent; <code>resources/recipes/Development_recipes/hal_demo.yml</code>
      uses it.</li>
  <li><strong>Outside PyPTS</strong>: <code>with Bench.from_ini("bench.ini"):</code> (from
      <code>pypts.hal</code>) makes <code>get_device()</code> work in a script of your own.</li>
  <li>Headless and API runs get the same devices.</li>
</ul>
```

- [ ] **Step 6: Update the roadmap and the inbox**

`pypts_implementation_status.html`:
- In the *Package layout* row (line 142), replace `<code>hardware_layer/</code>`` with
  `<code>hal/</code>``.
- Append before the closing `</div>` at the end (after §1.52):

```html
<h3 id="1-53-hal-devices-in-driver-processes-done">1.53 The hardware layer: devices by logical name, each in a driver process — <strong>done</strong></h3>
<p>2026-10-08, from <code>TODO.txt</code> ("SSH steps - create the HAL layer, move the SSH there"). Plan: <code>docs/superpowers/plans/2026-10-07-hal-subprocess-drivers.md</code>. Replaces the earlier "in-process library, sidecar only after an incident" design.</p>
<ul>
<li><strong>Package.</strong> <code>hardware_layer/</code> is now <code>hal/</code>; <code>hal.py</code> (design notes) is gone. Public API: <code>from pypts.hal import get_device, Bench, PSU, DMM, Scope, SSH, Load, Other</code>.</li>
<li><strong>One process per device.</strong> <code>DriverProxy</code> starts <code>python -m pypts.hal.runner</code>, which connects back over TCP on 127.0.0.1 and answers JSON-line calls. Driver log records and printed output reach the run log.</li>
<li><strong>Per run.</strong> The Sequencer wraps each run in <code>with Bench(...)</code>: a device opens on first <code>get_device()</code> and closes after the teardown steps. Headless and API runs share it.</li>
<li><strong>Configuration.</strong> <code>[hardware.&lt;name&gt;]</code> is recognised (no WARNING, values as text, <code>CONFIG_VERSION</code> unchanged); secret-looking keys are masked in the log.</li>
<li><strong>SSH.</strong> <code>SshDriver</code> over paramiko, unknown host keys refused by default. <code>paramiko</code>, <code>nidmm</code>/<code>hightime</code> and <code>pyserial</code> moved to extras; <code>nptdms</code> removed.</li>
</ul>
<p><strong>TODOs this opened:</strong></p>
<ul>
<li>[ ] <strong>TODO:</strong> devices from the recipe — a <code>devices:</code> key on a step handing proxies to the function as keyword arguments (design in <code>hal/hal.md</code>; recipe-format change: <code>recipe_guide.html</code>, schema, verificator).</li>
<li>[ ] <strong>TODO:</strong> Stop does not interrupt a call blocked inside a driver; only <code>call_timeout_s</code> bounds it.</li>
<li>[ ] <strong>TODO:</strong> an automatic recovery policy (who calls <code>recover()</code>, when).</li>
<li>[ ] <strong>TODO:</strong> a side channel for bulk data (waveforms) instead of JSON lists.</li>
<li>[ ] <strong>TODO:</strong> the first PSU / DMM / Scope / Load drivers; the family verb sets get reviewed against them.</li>
<li>[ ] <strong>TODO:</strong> an abandoned run's devices stay open until CORE exits.</li>
</ul>
<p>Context: <code>hal/hal.md</code>. Tests: <code>test_hal.py</code>, <code>test_hal_proxy.py</code>, <code>test_hal_ssh.py</code> (new); additions in <code>test_sequencer.py</code>, <code>test_config_handler.py</code>, <code>test_utilities.py</code>, <code>test_recipe.py</code>.</p>
```

`TODO.txt` — replace the line `- SSH steps - create the HAL layer, move the SSH there` with:

```
[x] SSH steps - create the HAL layer, move the SSH there
    -> done 2026-10-08: pypts/hal/ - devices by logical name, one driver process each,
       SshDriver; status 1.53. Recipe-level `devices:` is a TODO there.
```

---

### Task 12: Final quality gates and documentation check

- [ ] **Step 1: Run all four gates**

```
pytest tests
ruff check src tests
mypy
```

Expected: all pass. Report the counts honestly; if anything fails, fix it before claiming done.

- [ ] **Step 2: Look for stale names**

Run: `rg -n "hardware_layer|pypts\.api\.hal|nptdms" --glob "!docs/superpowers/**" --glob "!*.egg-info/**" --glob "!spikes/**"`
Expected: no hits (spikes may still import `nptdms`; that is allowed).

- [ ] **Step 3: Documentation check (gate 4)**

Re-read each document this change touched against the final code — `hal.md`, `CLAUDE.md`,
`config_handler.md`, `sequencer.md`, `step.md` §2.7, `utilities.md`, `usage_manual.html`,
`pypts_implementation_status.html` §1.53, `TODO.txt` — and confirm every identifier and file
they name exists. `recipe_guide.html` and `messages/messages.md` need **no** change: no recipe
format and no message changed. Say so in the report.

- [ ] **Step 4: Manual smoke run (report whether it was done)**

Add `[hardware.loop1]` / `driver = pypts.hal.drivers.loopback.LoopbackDriver` to your
`config.ini`, run `python -m pypts --mode headless --recipe resources/recipes/Development_recipes/hal_demo.yml`,
and check the run log shows `Device 'loop1' connected.` and `Device 'loop1' disconnected.`, step
1 PASS, step 2 ERROR (no `ssh1`) unless an SSH host is configured.

---

## Self-Review

**Decision coverage:** D1 → Tasks 4–5; D2 → Task 7 (`get_device`) + Task 11 (design note, TODO);
D3 → Task 8; D4 → Task 7 (`from_ini`, `__enter__`); D5 → Task 2 (verb sets flagged for review);
D6 → Task 1; D7 → Task 5 (timeout, crash, `recover`); D8 → Task 5 (`_relog`, `_drain_output`);
D9 → Tasks 7 + 9 + 5 (masking); D10 → Task 10; D11 → Task 11 (demo) + Task 8/`hal.md` (headless);
D12 → Task 6.

**Placeholder scan:** every code step carries its code; the only conditional steps are the
`__all__` order (ruff decides) and the demo recipe version (match the folder).

**Type consistency:** `DriverProxy(name, driver_path, settings, *, python, call_timeout_s)` —
Task 5 defines, Task 7 calls with those keywords, `_FakeProxy` mirrors it. `Bench(read_sections)`
— Task 7 defines, Task 8 passes `self.read_hardware_sections`. `hardware_sections_from_config`
— Task 7 defines, Task 8 imports and tests identity. `HARDWARE_PREFIX`/`is_hardware_section` —
Task 6 defines, Task 7 imports lazily. `masked()` — Task 5 defines, Tasks 5 and 6 use.

**Review Focus:** all five lines have tests in their owning tasks (Tasks 4, 5, 6, 7).
