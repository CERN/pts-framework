<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# hal — the hardware layer

Devices on the bench, reached by **logical name** from test code. Every device runs its
driver in **a process of its own**: a driver that crashes, hangs or leaks takes its own
process down, not PyPTS. Decided 2026-10-08 (roadmap §1.54); the process is started with
`multiprocessing` and reached over a Pipe since 2026-10-09 (roadmap §1.57).

```python
from pypts.hal import get_device

def read_kernel():
    result = get_device("ssh1").execute("uname -r")
    return {"kernel": result["stdout"].strip()}
```

## Files

| File | Holds |
|---|---|
| `__init__.py` | The public API: `get_device`, `LocalSetup`, `ConnectionDriver`, `BaseDriver`, `DriverError`, the six device types |
| `base_driver.py` | `BaseDriver` (ABC: `connect`, `teardown`, `recover`), `DriverError`, `LIFECYCLE_METHODS`, `operations_of()` |
| `device_types.py` | `PSU`, `DMM`, `Scope`, `SSH`, `Load`, `Other`; `DEVICE_TYPES`, `DEVICE_TYPE_NAMES` |
| `connection_driver.py` | `ConnectionDriver`, one device as test code sees it, with its rescue (`RESCUE_TIMEOUT_S`) and `abandon()`; below it, the driver process: `driver_process_main()`, `load_driver_class()`, `answer()` |
| `local_setup.py` | `LocalSetup`, the devices of one run, with `abandon()`; `get_device()`; `abandon_active_setup()`; `split_section()`; the section readers |
| `drivers/loopback.py` | `LoopbackDriver` (Other): no hardware; tests, demo, smoke check |
| `drivers/ssh.py` | `SshDriver` (SSH): the reference driver, paramiko |
| `drivers/weather.py` | `OpenMeteoDriver` (Other): a weather station on the internet, standard library only; the showcase driver |

`local_setup.py` imports `pypts.config_handler` lazily, inside the functions that need it,
because a driver process imports `pypts.hal` too and has no use for the configuration.

## How a call travels

1. Test code calls `get_device("ssh1")`. The **active local setup** (the run's, see
   *Lifetime*) reads the `[hardware.*]` sections once, builds a `ConnectionDriver` and calls
   `open()`.
2. `open()` creates a `multiprocessing` Pipe and starts a **spawn** process, a daemon, named
   `Device ssh1`, that runs `driver_process_main()`. Spawn hands the child this process's
   `sys.path`, so a source-tree run (`run_pypts.py`) and a driver beside it import there too.
3. The driver process sends its log records and printed lines back over the Pipe, imports and
   builds the driver, and sends `hello` (device type and operations) or `fatal` with the reason.
   `open()` then calls `connect(settings)`. If anything in `open()` fails, including an
   interrupt, the process is killed and nothing is left running.
4. `device.execute("uname -r")` goes through `__getattr__`: a name in `operations` becomes a
   call, and any other name raises `AttributeError` without a round trip.
5. The driver process answers with `result` or `error`. `log` and `printed` messages may come
   first and are logged. Calls are one at a time (a lock), so a second thread waits for the first.

## Pipe messages

Each message is a pickled tuple whose first item is its kind (constants in
`connection_driver.py`).

| Message | Direction |
|---|---|
| `(method, args, kwargs)` | PyPTS → driver process: one call |
| `("hello", device_type, operations)` | driver process → PyPTS, once, first |
| `("fatal", reason)` | driver process → PyPTS, instead of hello |
| `("log", level, logger_name, message)` | driver process → PyPTS, any time |
| `("printed", line)` | driver process → PyPTS, any time |
| `("result", value)` | driver process → PyPTS |
| `("error", type_name, message, traceback)` | driver process → PyPTS |

Arguments and return values must be picklable. An argument that is not is refused before
anything is sent; a return value that is not comes back as an `error`. A call or an answer that
pickles but cannot be unpickled on the other side (an exception class whose `__init__` takes
two arguments, say) is a `DriverError` too. Each message is pickled whole and read whole
(`send_bytes` / `recv_bytes`), so in every case the device stays usable. `connect`, `teardown` and `recover` are callable but are not `operations`.

## Configuration

One section per device in `config.ini` (or, outside PyPTS, any INI file given to
`LocalSetup.from_ini()`):

```ini
[hardware.ssh1]
driver = pypts.hal.drivers.ssh.SshDriver    ; required: the driver class, dotted
call_timeout_s = 120                         ; optional: longest one call may take, default 60
host = 192.168.0.10                          ; everything else goes to the driver's connect()
username = tester
key_filename = C:\Users\tester\.ssh\id_ed25519
```

`split_section()` reads `driver` and `call_timeout_s`; every other key goes to the driver as
text. A `python` key, the per-device interpreter of the previous design, is refused with a
`DriverError` telling the user to remove it: every driver runs on PyPTS's own Python.

`config_handler` recognises `[hardware.<name>]` (`configuration_schema.is_hardware_section()`):
the values are kept as text, there is no WARNING and nothing is mandatory, so `CONFIG_VERSION`
is unchanged. Keys are lower-cased (configparser). A key named like a password
(`utilities/common.py` → `is_secret_key()`) is masked in the configuration dump and in the
`connect` / `recover` trace. The file itself is plain text.

A custom driver's module must be importable by the driver process: installed, or on this
process's `sys.path`.

The device sections are read from the configuration PyPTS loaded at start, so a hand edit of
`config.ini` applies from the next start: File → Restart in the GUI. Restore default settings (GUI) recreates `config.ini`
and so removes the `[hardware.*]` sections too; the confirmation says so.

## Lifetime

- **Per run.** A run is one Start press: one top-level sequence and every sequence it calls.
  `Sequencer.execute_sequence()` wraps the step layer in
  `with LocalSetup(self.read_hardware_sections):`. A device opens on the first `get_device()`.
  All devices close, newest first, after the teardown steps and before `RunFinished`, whatever
  the result. A run that asks for no device never reads the sections. Headless
  (`--mode headless`) and API (`pypts.api.Pts`) runs go through the same Sequencer, so they get
  the same local setup.
- **The active local setup** is one slot per process, not thread-local, because threads that
  test code starts belong to the run. A newer setup replaces an older one that was never closed
  (an abandoned run). Closing a setup clears the slot only if it is still the active one.
- **Standalone**: `with LocalSetup.from_ini("bench.ini"):` activates a setup in a plain script,
  so the same test functions run outside PyPTS. The script must keep that code under
  `if __name__ == "__main__":`. Spawn re-imports the script's main module in every driver
  process, and without the guard the setup starts again inside it. The driver process then
  dies at once (its console output says the process had not finished its "bootstrapping
  phase") and the device fails with `Device 'x' stopped unexpectedly (exit code 1).`
  `_read_message()` waits in `LIVENESS_POLL_S` slices and checks that the process is alive, so
  this is noticed immediately: a process that dies before it has taken over its end of the Pipe
  closes nothing PyPTS could see on Windows.
- **PyPTS dies**: its end of the Pipe closes, and the driver process calls `teardown()` and
  exits, once the call in progress returns. A call that never returns keeps the driver process
  alive.
- **An abandoned run** (the Sequencer's stop gave up on its thread): its `with` block never
  ends, so `Sequencer.tear_down_abandoned_devices()` calls `abandon_active_setup()`. That
  empties the active slot and calls `LocalSetup.abandon()`: the setup opens nothing more
  (`get_device()` on it raises "this run was abandoned"; a device that finished opening
  meanwhile is closed again), and every device it opened is torn down by
  `ConnectionDriver.abandon()` on a thread of its own, side by side, all within the time limit
  (`ABANDONED_DEVICES_TIMEOUT_S`, 11 s). No lock is waited for - the stuck run may hold one: an
  idle device gets `teardown()`; a device in a call has its process killed (the call then fails
  as a crash in the stuck thread) and is rescued. The names of the devices not torn down in
  time come back, for one CRITICAL.
- **The rescue** (`_rescue()`): when a call on a connected device exceeds its timeout, the stuck
  process is killed - it cannot run `teardown()` - and a fresh driver process is started,
  connected and torn down, all within `RESCUE_TIMEOUT_S` (10 s), **before** the `DriverError`
  reaches test code, so the device is torn down before the next step. A rescue that fails is an
  ERROR line (`... could not be torn down and may still be energised: ...`). Not for a timeout
  before `connect()` returned (start-up has its own error), not for the rescue's own process
  (`_is_rescue`), and not after `abandon()` (`_abandoned`), which rescues by itself.

## Failure

| What happens | What test code sees |
|---|---|
| Driver raises | `DriverError("Device 'x': 'op' failed: Type: message")`; the device stays usable; traceback at DEBUG |
| Argument not picklable | `DriverError("Device 'x': the arguments of 'op' cannot be sent: ...")`; nothing was sent |
| Return value not picklable | `DriverError("Device 'x': 'op' failed: TypeError: 'op' returned a value that cannot be sent: ...")` |
| Argument cannot be unpickled in the driver process | `DriverError("Device 'x': 'op' failed: <Type>: the call could not be read in the driver process: ...")` |
| Return value cannot be unpickled in PyPTS | `DriverError("Device 'x': the answer 'op' could not be read: ...")` |
| Call exceeds `call_timeout_s` | The rescue runs, then `DriverError("... did not answer 'op' within N s; its driver process was stopped and the device torn down on a fresh connection.")` - or `...; it could not be torn down.` |
| Driver process dies | `DriverError("Device 'x' stopped unexpectedly (exit code N).")` |
| Cannot import / build / connect | `DriverError("Device 'x' could not be opened: ...")`, or the failed `'connect'` |
| Unknown device | `DriverError("No device 'x' is configured. ... Configured devices: ...")` |
| `python` key in the section | `DriverError("Device 'x': the 'python' key is not supported any more ...")` |
| No active local setup | `DriverError("No local setup is active. ...")` |

Uncaught in test code, each makes the step ERROR through the normal step path. Nothing recovers
on its own: `device.recover()` calls the driver's `recover()` while the process lives, or starts a
fresh process and connects when it does not.

## Logging

INFO (technician): `Device 'x' connected.`, `Device 'x' disconnected.`,
`Recovering device 'x'.`, `Device 'x' recovered.`, `Device 'x' was torn down on a fresh
connection.` WARNING: `Device 'x' did not disconnect cleanly: ...`, `Device 'x' is being
connected again, to tear it down.` ERROR: `Device 'x' could not be torn down and may still be
energised: ...`. Forwarded records are logged as `Device 'x': <message>`: at their own level
when the logger is the driver's own module (or a child of it), and at DEBUG when another library
logs below WARNING. Lines printed through `sys.stdout` / `sys.stderr` in the driver process are
DEBUG (`Device 'x' printed: ...`), as are every call and its return value (cut to
`TRACE_MAX_CHARS`) and tracebacks. The `connect` and `recover` trace shows the settings masked;
the arguments of ordinary calls are traced as given.

## Writing a driver

1. Derive from the device type it belongs to (`from pypts.hal import PSU`), never from
   `BaseDriver` directly: a driver of no device type is refused.
2. Implement `connect(config)` (all values are text), `teardown()` and the device type's verbs.
   Every other public method becomes an operation too. **`teardown()` is where the instrument
   is left safe** - outputs and loads off - and then disconnected. There is no separate
   safe-state method: teardown runs at every end of a device, on a fresh connection when the
   driver was stuck (the rescue), so it must work right after `connect()` on an instrument in
   any state, and be harmless when nothing is open.
3. Log with `logging.getLogger(__name__)`. Do not name a method `name`, `device_type`, `operations`,
   `open`, `close`, `recover`, `is_open` or `abandon` (`connection_driver.RESERVED_NAMES`). Do not start
   `multiprocessing` processes from a driver: the driver process is a daemon, and a daemon
   cannot have children.
4. Import the vendor library at the top of the driver module, with an `ImportError` that names
   the extra to install (see `drivers/ssh.py`). A driver that needs no vendor library and
   turns every failure of its far end into one `DriverError` is `drivers/weather.py`.
5. Test it in-process with the vendor library mocked (`test_hal_ssh.py`), and through a real
   driver process with the loopback pattern (`test_hal_connection.py`).

Device-type verbs: PSU `set_voltage`, `set_current_limit`, `output_on`, `output_off`,
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

## Weather

`OpenMeteoDriver` reads the Open-Meteo forecast API (no API key) with `urllib`. Keys:
`latitude` (46.23) and `longitude` (6.05), CERN Meyrin by default; `place`, a label put in
the readings; `http_timeout_s` (10). `connect()` checks the numbers and takes one reading, so
a station that cannot be reached fails the device at open. Verbs beyond `Other`'s none:
`current_conditions()` (`place`, `time`, `temperature_c`, `relative_humidity_pct`,
`pressure_hpa`, `wind_speed_kmh`, `wind_direction_deg`), `temperature()`, `wind_speed()`,
`hourly_forecast(hours)` (1 to 384; `time`, `temperature_c`, `wind_speed_kmh` per hour).
Every failure of the far end (unreachable, HTTP error with Open-Meteo's `reason`, an answer
that is not JSON or lacks a reading) is a `DriverError`. The showcase recipe is
`resources/recipes/HAL_recipes/meteo_demo.yml`: temperature and wind at CERN from
one device, `meteo1`.

## Packaging

The core ships no driver library; `loopback.py` and `weather.py` need none. Extras: `[ssh]` paramiko, `[ni]` nidmm + hightime,
`[serial]` pyserial, `[hardware]` all three. `.gitignore` carries `!/src/pypts/hal/drivers/`
because its bare `drivers` rule would otherwise hide the shipped drivers.

## Known gaps

- A call blocked inside a driver is not interrupted by Stop; `call_timeout_s` bounds it.
- No side channel for bulk data: a waveform is pickled through the Pipe.
- Log records and printed lines are read only while PyPTS waits for a call. Records from a
  driver's own threads between calls (paramiko's transport thread at DEBUG, say) wait in the
  Pipe. They are logged late, stamped with the time PyPTS read them, and once the Pipe's buffer
  is full every thread of the driver process that logs or prints blocks until the next call.
- `sys.stdout` / `sys.stderr` in the driver process are a line forwarder, not a real stream:
  `encoding` is `None`, and there is no `buffer` and no `fileno()`.
- A rescue reconnects with the same settings; an instrument that refuses a second connection
  while the first is half-open, or a `connect()` slower than `RESCUE_TIMEOUT_S` (an SSH host
  with a long `connect_timeout_s`), cannot be torn down this way.
- PyPTS killed outright (the launcher's terminate, a crash) runs none of this: the driver
  process's own `teardown()` at the end of the Pipe is the only net, and only when it is not
  stuck in a call.
- Output a C library writes straight to the process's file descriptors (not through
  `sys.stdout`) is not forwarded. It goes to PyPTS's own console, if there is one.
- No automatic recovery policy, only `device.recover()` from test code.
- No PSU, DMM, Scope or Load driver ships yet; only the device-type bases.
- Every driver runs on PyPTS's own Python: a vendor library that needs another interpreter
  (for example a 32-bit DLL) is not supported.
