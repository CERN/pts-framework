<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Writing a PyPTS device driver — context for an AI model

You are helping a user write a **device driver** for PyPTS's hardware layer (`pypts.hal`).
Everything you need is in this file; the human-readable version is
`how_to_write_a_driver.html` beside it.

## Your task, and its limits

- Write **one Python class** for the user's instrument, in **one file of the user's own**
  (for example `~/bench/<instrument>.py`, `C:\bench\<instrument>.py` on Windows). **Never edit, add or patch anything inside `pypts`** — it is not needed.
- Import from the framework only what `pypts.hal` exports: the device type to derive from and
  `DriverError`.
- If you do not know the instrument's protocol (SCPI commands, vendor library calls, port,
  units), **ask the user or ask for the manual** — never invent commands.
- Deliver: the driver module ending in an `if __name__ == "__main__":` check (see the
  template), and its `bench.ini` section.

## How PyPTS uses the driver

`bench.ini` names the driver file and its class (`~/bench/acme_dmm.py:AcmeDmmDriver`). On the
first `get_device("<name>")` in a test run, PyPTS starts a **separate process** for that
device, loads the file, builds the class with **no arguments**, and calls `connect(config)`.
Test code then calls the driver's public methods by name; every call and its answer travel
over a pipe, pickled. When the run ends — in any way — PyPTS calls `teardown()`.

## Device types — derive from exactly one

```python
from pypts.hal import PSU, DMM, Scope, Load, SSH, Other, DriverError
```

Never derive from `BaseDriver` directly (refused at open). The verbs below are
`@abstractmethod`: implement **all** of the chosen type's verbs with these exact signatures,
or the class fails at open with `TypeError: Can't instantiate abstract class`.

```python
class PSU:                       # programmable power supply; channels numbered from 1
    def set_voltage(self, channel: int, volts: float) -> None
    def set_current_limit(self, channel: int, amps: float) -> None
    def output_on(self, channel: int) -> None
    def output_off(self, channel: int) -> None
    def measure_voltage(self, channel: int) -> float
    def measure_current(self, channel: int) -> float

class DMM:                       # multimeter: configure once, then read
    def configure_waveform_acquisition(self, function: str, range: float,
                                       sample_rate_hz: float, points: int) -> None
        # function: "DC_VOLTS", "AC_VOLTS", "DC_CURRENT", "AC_CURRENT" or "RESISTANCE";
        # range in the function's unit (V, A or ohm)
    def read_waveform(self) -> dict[str, Any]
        # {"x_origin": float, "x_increment": float, "samples": list[float]}
    def measure_point(self) -> float          # one reading, however it is configured
    def get_frequency(self) -> float          # Hz

class Scope:                     # oscilloscope; channels numbered from 1
    def configure_waveform_acquisition(self, channel: int, volts_per_division: float,
                                       seconds_per_division: float, points: int) -> None
    def read_waveform(self, channel: int) -> dict[str, Any]
        # {"x_origin": float, "x_increment": float, "samples": list[float]}
    def measure_point(self, channel: int) -> float   # one reading, however it is configured

class Load:                      # electronic load
    def set_mode(self, mode: str) -> None          # "CC", "CV", "CR" or "CP"
    def set_level(self, value: float) -> None
    def input_on(self) -> None
    def input_off(self) -> None
    def measure_voltage(self) -> float
    def measure_current(self) -> float

class SSH:                       # remote shell
    def execute(self, command: str, timeout_s: float | None = None) -> dict[str, Any]
        # {"stdout": str, "stderr": str, "exit_code": int}
    def put_file(self, local_path: str, remote_path: str) -> None
    def get_file(self, remote_path: str, local_path: str) -> None

class Other:                     # anything else: no verbs; your public methods are the interface
```

A driver may add more public methods than its type declares.

## Lifecycle — required by every type

```python
def connect(self, config: dict[str, str]) -> None      # abstract
def teardown(self) -> None                             # abstract
def recover(self, config: dict[str, str]) -> None      # optional; default: teardown() then connect(config)
```

- `__init__` takes no arguments; only set attributes to `None` there. No I/O.
- `connect(config)`: `config` is the device's `bench.ini` section **minus** `driver`.
  **Every value is a `str`** and every key is **lower-case**: convert
  numbers yourself, give optional keys a default with `config.get("port", "5025")`. Raise
  (preferably `DriverError` with a clear message) when the instrument cannot be reached.
- `teardown()`: **the only place the instrument is made safe** — outputs/loads off, then
  disconnect. It must work right after `connect()` on an instrument in any state (PyPTS may
  call it on a fresh connection when the old process got stuck), and must **do nothing and not
  raise when nothing is open**. Use `try/finally` so the connection is closed even when the
  safe-state command fails.
- `recover(config)`: override only when the instrument has a cheaper reset.

## Rules

1. **Every public method is an operation** test code can call. Put wire/protocol helpers in
   `_private` methods.
2. **Arguments and return values must be picklable plain data**: `int`, `float`, `str`,
   `bytes`, `bool`, `None`, `list`, `dict`, `tuple`. Never return sockets, handles, locks,
   file objects or vendor objects.
3. **No name is reserved:** any public method name — `close`, `open`, `name` included — is an
   operation test code reaches (`ConnectionDriver` keeps all its own members `_private`). Test
   code controls the device itself with functions from `pypts.hal`: `recover_device(device)`
   and `device_info(device)`.
4. **Logging:** `log = logging.getLogger(__name__)`, `%`-style arguments
   (`log.info("answered: %s", idn)`), never f-strings. INFO for what an operator should see,
   DEBUG for the rest. `print()` output is logged at DEBUG.
5. **No `multiprocessing`** inside a driver (its process is a daemon; daemons cannot have
   children). Threads are allowed.
6. **Vendor libraries** are imported at the top of the module, with an install hint:
   ```python
   try:
       import pyvisa
   except ImportError as exc:
       raise ImportError("AcmeDmmDriver needs pyvisa; install it with 'pip install pyvisa'.") from exc
   ```
7. The driver runs on the **same Python interpreter as PyPTS** (≥ 3.11). A library that needs
   another interpreter (e.g. a 32-bit DLL) cannot be used.
8. Calls are one at a time; a call longer than 30 s (`CALL_TIMEOUT_S`, the same for every
   device and not configurable) kills the driver process. Set I/O timeouts in the driver shorter than that.

## Template

```python
"""ACME DM-100 multimeter over TCP (SCPI)."""

import logging
import socket

from pypts.hal import DMM, DriverError

# Plain logging: PyPTS forwards these records to its run log as "Device 'dmm1': ...".
log = logging.getLogger(__name__)

# The DMM type's function names, in this instrument's SCPI.
SCPI_FUNCTIONS = {
    "DC_VOLTS": "VOLT:DC",
    "AC_VOLTS": "VOLT:AC",
    "DC_CURRENT": "CURR:DC",
    "AC_CURRENT": "CURR:AC",
    "RESISTANCE": "RES",
}


class AcmeDmmDriver(DMM):

    def __init__(self):
        self._sock = None
        self._points = 1
        self._sample_interval_s = 0.001

    def connect(self, config):
        host = config["host"]                       # every value arrives as text
        port = int(config.get("port", "5025"))
        try:
            self._sock = socket.create_connection((host, port), timeout=5)
        except OSError as exc:
            raise DriverError("DM-100 at %s:%d could not be reached: %s" % (host, port, exc))
        self._reader = self._sock.makefile("r", encoding="ascii")
        log.info("DM-100 answered: %s", self._query("*IDN?"))

    def teardown(self):
        if self._sock is None:
            return                                  # harmless when nothing is open
        try:
            self._send("*RST")                      # leave the instrument safe
        finally:
            self._sock.close()
            self._sock = None

    def configure_waveform_acquisition(self, function, range, sample_rate_hz, points):
        self._send("CONF:%s %g" % (SCPI_FUNCTIONS[function], range))
        self._send("SAMP:TIM %g" % (1.0 / sample_rate_hz))
        self._points = points
        self._sample_interval_s = 1.0 / sample_rate_hz

    def read_waveform(self):
        self._send("SAMP:COUN %d" % self._points)
        samples = [float(value) for value in self._query("READ?").split(",")]
        return {"x_origin": 0.0, "x_increment": self._sample_interval_s, "samples": samples}

    def measure_point(self):
        self._send("SAMP:COUN 1")                   # one reading, as configured
        return float(self._query("READ?"))

    def get_frequency(self):
        return float(self._query("MEAS:FREQ?"))

    def _send(self, text):                          # _private: not an operation
        self._sock.sendall((text + "\n").encode("ascii"))

    def _query(self, text):
        self._send(text)
        return self._reader.readline().strip()


# Standalone check: python acme_dmm.py - no PyPTS, no bench.ini. The dict stands in
# for the bench.ini section PyPTS passes to connect(). PyPTS imports the module by
# its package name, so this block never runs there.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    dmm = AcmeDmmDriver()
    dmm.connect({"host": "192.168.0.41", "port": "5025"})
    try:
        dmm.configure_waveform_acquisition("DC_VOLTS", 10.0, 1000.0, 1)
        print("DC voltage: %.4f V" % dmm.measure_point())
    finally:
        dmm.teardown()
```

For a PSU, `teardown()` switches every output off (`OUTP OFF`) before closing.

## Installing it — tell the user

1. Save the driver as **one file of its own**, outside the PyPTS source tree, e.g.
   `~/bench/acme_dmm.py` (Windows `C:\bench\acme_dmm.py`). Nothing has to be installed or
   put on `PYTHONPATH`.
2. Declare the device in `bench.ini` — Linux/macOS `~/.config/pypts/bench.ini`, Windows
   `%LOCALAPPDATA%\pypts\bench.ini`. One section per device; the section name is the
   logical name. `driver` is the file, a colon, and the class. Values are read raw (`%` needs
   no escaping).
   ```ini
   [dmm1]
   driver = ~/bench/acme_dmm.py:AcmeDmmDriver   ; required; Windows: C:\bench\acme_dmm.py:AcmeDmmDriver
   host = 192.168.0.41                          ; everything else -> connect(config)
   port = 5025
   ```
   The path may be absolute, start with `~`, or be relative to the folder `bench.ini` is in.
   Do not add a `python` key (refused). Restart PyPTS after editing `bench.ini`.
3. **Only that one file is loaded**: its folder is not on `sys.path`, so the driver may import
   the standard library and installed packages, but **not a helper module beside it**. Keep a
   driver in one file. If it must span several modules, make it a package
   (`~/bench/bench_drivers/__init__.py`, `.../acme_dmm.py`, ...), name it by dotted path
   (`driver = bench_drivers.acme_dmm.AcmeDmmDriver`), and make it importable in the terminal
   PyPTS is started from: Linux/macOS `export PYTHONPATH=~/bench`, Windows PowerShell
   `$env:PYTHONPATH = "C:\bench"`, or `pip install -e ~/bench` with a `pyproject.toml`.

## Testing it

Standalone, without PyPTS — the `__main__` guard is **required** (the driver process
re-imports the script; without the guard it dies with `stopped unexpectedly (exit code 1)`):

```python
from pypts.hal import LocalSetup, get_device

if __name__ == "__main__":
    with LocalSetup.from_ini("bench.ini"):      # any INI file in bench.ini's format
        dmm = get_device("dmm1")
        dmm.configure_waveform_acquisition("DC_VOLTS", 10.0, 1000.0, 1)
        print(dmm.measure_point())
```

From a recipe — test code never imports the driver, it asks for the device by name:

```python
# dmm_tests.py, beside the recipe
from pypts.hal import get_device


def supply_rail():
    dmm = get_device("dmm1")
    dmm.configure_waveform_acquisition("DC_VOLTS", 10.0, 1000.0, 1)
    return {"v_rail": dmm.measure_point()}
```

```yaml
name: DMM check
description: Reads the 3.3 V rail.
version: 0.1
---
sequence_name: Main
description: One measurement.
steps:
  - steptype: PythonModule
    step_name: 3V3 rail
    description: Within 5 %.
    module: dmm_tests.py
    method_name: supply_rail
    outputs:
      v_rail: {type: range, min: '3.135', max: '3.465'}
```

Run: `python -m pypts --mode headless --recipe dmm_check.yml`. The log shows
`Device 'dmm1' connected.` and, at the end, `Device 'dmm1' disconnected.`

## Errors the user may report

| Message (abridged) | Cause |
|---|---|
| `could not be opened: ValueError: Driver file '...' does not exist.` | Wrong path in `driver =` (step 2) |
| `names a file but no class; write it as '...:ClassName'` | `driver =` lacks `:ClassName` |
| `No module named '...'` raised inside the driver file | It imports a helper beside it (step 3) or a vendor library that is not installed |
| `could not be opened: ... No module named 'bench_drivers'` | A package driver not importable by PyPTS's Python (step 3) |
| `Module '...' has no class '...'` / `is not a dotted path to a class` | Typo in `driver =` |
| `is not a driver: it does not derive from BaseDriver` / `belongs to no device type` | Wrong base class |
| `TypeError: Can't instantiate abstract class` | A verb of the device type is missing |
| `No device 'x' is configured` | Section missing, misspelled, or `bench.ini` edited without restart |
| `the [x] section has no 'driver' key` | Add `driver =` |
| `'op' failed: <Type>: <message>` | The driver raised during a call; the device stays usable |
| `did not answer 'op' within N s` | Call took longer than 30 s; the process was killed |
| `cannot be sent` / `returned a value that cannot be sent` | Non-picklable argument or return value (rule 2) |
| `stopped unexpectedly (exit code 1)` in a standalone script | Missing `__main__` guard |

## Checklist — verify your output against it

- [ ] Derives from exactly one of `PSU`, `DMM`, `Scope`, `Load`, `SSH`, `Other`.
- [ ] Implements every verb of that type with the exact signature, plus `connect` and `teardown`.
- [ ] `__init__` takes no arguments and does no I/O.
- [ ] `connect` converts its string values, defaults optional keys, raises a clear error when unreachable.
- [ ] `teardown` makes the instrument safe, uses `try/finally`, is a no-op when nothing is open.
- [ ] Helpers are `_private`.
- [ ] Only picklable plain data crosses in and out.
- [ ] `logging.getLogger(__name__)` with `%`-style arguments; no `multiprocessing`.
- [ ] One file, importing nothing that sits beside it.
- [ ] Nothing inside `pypts` was modified; the `bench.ini` section (`driver = <file>:<Class>`) and the `__main__` check are supplied.
