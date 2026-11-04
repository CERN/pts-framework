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
| `connection_driver.py` | `ConnectionDriver`, one device as test code sees it: **every public name on it is the driver's operation** (its own members are all `_private`, so no name is reserved), with `CALL_TIMEOUT_S` (30 s, the same for every device) and its teardown ladder: `_close()` and `_abandon()` (`ABANDON_TEARDOWN_TIMEOUT_S`) escalating to the rescue (`_rescue()`, `RESCUE_TIMEOUT_S`); below it, the driver process: `driver_process_main()`, `load_driver_class()` with `load_driver_file()`, `split_driver_file()`, `driver_module_name()` and `DRIVER_FILE_MODULE_PREFIX`, `answer()` |
| `device_control.py` | What test code does to a device beyond its operations: `recover_device()`, `device_info()` → `DeviceInfo` (name, device type, operations, is open). Functions rather than methods, so they take no name away from drivers |
| `local_setup.py` | `LocalSetup`, the devices of one run, with `abandon()` (it calls the devices' private `_open()` / `_close()` / `_abandon()`); `get_device()`; `abandon_active_setup()`; `split_section()`; `anchor_driver_files()`; the section readers `bench_sections()` (the cached bench.ini, via `config_handler.bench_config`) and `ini_device_sections()` |
| `drivers/loopback.py` | `LoopbackDriver` (Other): no hardware; tests, demo, smoke check |
| `drivers/ssh.py` | `SshDriver` (SSH): the reference driver, paramiko |
| `drivers/weather.py` | `OpenMeteoDriver` (Other): a weather station on the internet, standard library only; the showcase driver |

`local_setup.py` imports `pypts.config_handler` lazily, inside the functions that need it,
because a driver process imports `pypts.hal` too and has no use for the configuration.

## How a call travels

1. Test code calls `get_device("ssh1")`. The **active local setup** (the run's, see
   *Lifetime*) reads the device sections of `bench.ini` once (the cached `bench_config()`
   result), builds a `ConnectionDriver` and calls its private `_open()`.
2. `_open()` creates a `multiprocessing` Pipe and starts a **spawn** process, a daemon, named
   `Device ssh1`, that runs `driver_process_main()`. Spawn hands the child this process's
   `sys.path`, so a source-tree run (`run_pypts.py`) and a driver beside it import there too.
3. The driver process sends its log records and printed lines back over the Pipe, imports and
   builds the driver, and sends `hello` (device type and operations) or `fatal` with the reason.
   `_open()` then calls `connect(settings)`. If anything in `_open()` fails, including an
   interrupt, the process is killed and nothing is left running.
4. `device.execute("uname -r")` goes through `__getattr__`: ConnectionDriver has no public
   name of its own, so every public name lands there. A name among the driver's operations
   becomes a call, and any other raises `AttributeError` without a round trip. A driver may
   therefore call an operation `close`, `open` or `name` and test code reaches it.
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

Devices are declared in `bench.ini`, beside `config.ini`
(`%LOCALAPPDATA%\pypts\bench.ini` / `~/.config/pypts/bench.ini`): one **bare-named** section
per device (or, outside PyPTS, any INI file in the same format given to
`LocalSetup.from_ini()`):

```ini
[ssh1]
driver = pypts.hal.drivers.ssh.SshDriver    ; required: the driver class, dotted
host = 192.168.0.10                          ; everything else goes to the driver's connect()
username = tester
key_filename = C:\Users\tester\.ssh\id_ed25519
```

`split_section()` reads only `driver`; every other key goes to the driver as text. A `python`
key, the per-device interpreter of the previous design, is refused with a `DriverError` telling
the user to remove it: every driver runs on PyPTS's own Python. The call timeout is not
configurable: every call, `connect()` included, has `CALL_TIMEOUT_S` (30 s); a
`call_timeout_s` key is just one more key for the driver.

Keys are lower-cased (configparser). The `connect` / `recover` DEBUG trace shows the settings
as they are, a password included - nothing is masked. `bench.ini` itself is plain text and
appears in no configuration dump.

`driver` has two spellings, both read by `load_driver_class()`:

- a **dotted import path**, `bench_drivers.acme_psu.AcmePsuDriver`: the module must be
  importable by the driver process - installed, or on this process's `sys.path`;
- a **driver file and its class**, `C:\bench\acme_psu.py:AcmePsuDriver` (`split_driver_file()`
  splits at the last colon, so a drive letter stays in the file). The driver process loads the
  file with `load_driver_file()` as module `pypts_driver_file_<stem>`
  (`DRIVER_FILE_MODULE_PREFIX`), registered in `sys.modules` - it holds that one driver only.
  Only the file is loaded: its folder is not put on `sys.path`, so it imports what is installed,
  not what sits beside it. `anchor_driver_files()` expands `~` and makes a relative file
  relative to the folder of the INI file that declares it (`bench.ini`, or the file given to
  `from_ini()`), before the section reaches `split_section()`. A `ConnectionDriver` built
  directly with a relative file resolves it against the current directory.

`driver_module_name()` gives the module either spelling names; a forwarded log record keeps its
level when its logger is that module or a child of it (see *Logging*).

The device sections are the cached `bench.ini` read at start, so a hand edit of `bench.ini`
applies from the next start: File → Restart in the GUI. Restore default settings (GUI)
recreates `config.ini` only; `bench.ini` and its devices are untouched.

## Lifetime

- **Per run.** A run is one Start press: one top-level sequence and every sequence it calls.
  `Sequencer.execute_sequence()` wraps the step layer in
  `with LocalSetup(self.read_hardware_sections):`. A device opens on the first `get_device()`.
  All devices close, newest first, after the teardown steps and before `RunFinished`, whatever
  the result. A run that asks for no device never reads the device sections — the launcher
  still reads `bench.ini` once at every start, for the discarded-bench notice. Headless
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
  alive. This net is skipped when a `teardown` call already ran (`_close()` sends one), so
  teardown runs exactly once at a device's end - never twice.
- **The teardown ladder** (`_close()`): one serialized escalation, and the only place a device
  is torn down. First `teardown()` on the live process; failing that - it hung, crashed or was
  stopped by a call timeout - a fresh driver process connects and tears down instead
  (`_rescue()`, within `RESCUE_TIMEOUT_S`, 10 s); failing that too, the ERROR line says the
  device `... could not be torn down and may still be energised: ...` and nothing tries again:
  the driver's stability is the driver's own job, not the framework's. A call that exceeds its
  timeout only kills the stuck process and raises - nothing rescues mid-run - so the instrument
  keeps its state until the run ends and `_close()` runs the ladder, or test code calls
  `recover_device()`. `Device 'x' disconnected.` is logged only when a teardown ran; a failed ladder
  ends on the ERROR line instead.
- **An abandoned run** (the Sequencer's stop gave up on its thread): its `with` block never
  ends, so `Sequencer.tear_down_abandoned_devices()` calls `abandon_active_setup()`. That
  empties the active slot and calls `LocalSetup.abandon()`: the setup opens nothing more
  (`get_device()` on it raises "this run was abandoned"; the abandoned flag and the device
  registration share one small registry lock, so a device that finishes opening beside
  `abandon()` is either in abandon's copy of the list or refused and closed by `get_device()`
  itself - never silently left running), and every device it opened runs the teardown ladder
  (`ConnectionDriver._abandon()`) in turn, newest first, on one shared deadline
  (`ABANDONED_DEVICES_TIMEOUT_S`, 16 s). No lock the stuck run may hold is waited for: an
  idle device gets one `teardown()` within `ABANDON_TEARDOWN_TIMEOUT_S` (5 s) and its process
  is killed if that hangs; a device in a call has its process killed at once (the call then
  fails as a crash in the stuck thread). A device that is not down after that is torn down on
  a fresh process (the rescue) with whatever is left of the deadline; one the deadline has
  already passed is killed and reported. `_abandon()` returns False whenever no teardown ran,
  and the names of those devices come back, for one CRITICAL ("stopped without running
  teardown"). Abandonment is final: `_open()` and `recover_device()` on an abandoned device raise,
  and `_close()` returns without touching it, so test code in the abandoned run that still
  holds the device cannot switch the instrument back on.

## Failure

| What happens | What test code sees |
|---|---|
| Driver raises | `DriverError("Device 'x': 'op' failed: Type: message")`; the device stays usable; traceback at DEBUG |
| Argument not picklable | `DriverError("Device 'x': the arguments of 'op' cannot be sent: ...")`; nothing was sent |
| Return value not picklable | `DriverError("Device 'x': 'op' failed: TypeError: 'op' returned a value that cannot be sent: ...")` |
| Argument cannot be unpickled in the driver process | `DriverError("Device 'x': 'op' failed: <Type>: the call could not be read in the driver process: ...")` |
| Return value cannot be unpickled in PyPTS | `DriverError("Device 'x': the answer 'op' could not be read: ...")` |
| Call exceeds `CALL_TIMEOUT_S` (30 s) | `DriverError("... did not answer 'op' within N s; its driver process was stopped.")`; the instrument keeps its state until `_close()` runs the teardown ladder |
| Driver process dies | `DriverError("Device 'x' stopped unexpectedly (exit code N).")` |
| Cannot import / build / connect | `DriverError("Device 'x' could not be opened: ...")`, or the failed `'connect'` |
| Driver file missing, or a file without a class | `DriverError("Device 'x' could not be opened: ValueError: Driver file '...' does not exist.")` / `... names a file but no class; write it as '...:ClassName'.` |
| Unknown device | `DriverError("No device 'x' is configured. Add a [x] section to bench.ini. Configured devices: ...")` |
| Bench file discarded at startup | `DriverError("bench.ini was discarded at startup, so this start has no devices: ...")` |
| Section has no `driver` key | `DriverError("Device 'x': the [x] section has no 'driver' key naming its driver class.")` |
| `python` key in the section | `DriverError("Device 'x': the 'python' key is not supported any more ...")` |
| No active local setup | `DriverError("No local setup is active. ...")` |

Uncaught in test code, each makes the step ERROR through the normal step path. Nothing recovers
on its own: test code calls `recover_device(device)`, which escalates until the device is usable or
hopeless — the driver's own `recover()` (teardown + connect, overridable) while the process
lives; when that fails or the process is gone, teardown (`_close()`) and a fresh process with
`connect()`. Only when the fresh process cannot connect does a `DriverError` reach test code.
The one exception is an abandoned device: `_open()` and `recover_device()` refuse it
(`DriverError("Device 'x' cannot be opened/recovered: its run was abandoned and the device was
torn down.")`) — a new driver process would belong to a run that will not end, and nothing
would ever tear it down.

## Logging

INFO (technician): `Device 'x' connected.`, `Device 'x' disconnected.`,
`Recovering device 'x'.`, `Device 'x' recovered.`, `Device 'x' was torn down on a fresh
connection.` WARNING: `Device 'x' did not disconnect cleanly: ...`, `Device 'x' is being
connected again, to tear it down.`, `Device 'x' did not recover and is being connected
again: ...` ERROR: `Device 'x' could not be torn down and may still be
energised: ...`. Forwarded records are logged as `Device 'x': <message>`: at their own level
when the logger is the driver's own module (or a child of it), and at DEBUG when another library
logs below WARNING. Lines printed through `sys.stdout` / `sys.stderr` in the driver process are
DEBUG (`Device 'x' printed: ...`), as are every call and its return value (cut to
`TRACE_MAX_CHARS`) and tracebacks. The `connect` and `recover` trace shows the settings, and
ordinary calls their arguments, as given - nothing is masked.

## Writing a driver

The user-facing walkthrough of this section is `docs/Usage_manuals/how_to_write_a_driver.html`,
and its AI-model context is `docs/Usage_manuals/how_to_write_a_driver.md` — a change here
changes both files too.

1. Derive from the device type it belongs to (`from pypts.hal import PSU`), never from
   `BaseDriver` directly: a driver of no device type is refused.
2. Implement `connect(config)` (all values are text), `teardown()` and the device type's verbs.
   Every other public method becomes an operation too. **`teardown()` is where the instrument
   is left safe** - outputs and loads off - and then disconnected. There is no separate
   safe-state method: teardown runs at every end of a device, on a fresh connection when the
   driver was stuck (the ladder's rescue rung), so it must work right after `connect()` on an
   instrument in any state, and be harmless when nothing is open.
3. Log with `logging.getLogger(__name__)`. Any public method name is allowed - `close`,
   `open` and `name` included: ConnectionDriver keeps all its own members `_private`, so no
   name is reserved. Do not start
   `multiprocessing` processes from a
   driver: the driver process is a daemon, and a daemon cannot have children.
4. Import the vendor library at the top of the driver module, with an `ImportError` that names
   the extra to install (see `drivers/ssh.py`). A driver that needs no vendor library and
   turns every failure of its far end into one `DriverError` is `drivers/weather.py`.
5. Test it in-process with the vendor library mocked (`test_hal_ssh.py`), and through a real
   driver process with the loopback pattern (`test_hal_connection.py`).
6. A driver outside the framework is one file named in `bench.ini` by its path
   (`driver = acme_psu.py:AcmePsuDriver`, relative to `bench.ini`), or a package of the user's
   own named by its dotted path - see *Configuration*.

Device-type verbs: PSU `set_voltage`, `set_current_limit`, `output_on`, `output_off`,
`measure_voltage`, `measure_current` (channel from 1); DMM
`configure_waveform_acquisition(function, range, sample_rate_hz, points)` (function
`DC_VOLTS` / `AC_VOLTS` / `DC_CURRENT` / `AC_CURRENT` / `RESISTANCE`), `read_waveform()`,
`measure_point()` (one reading, however the meter is configured), `get_frequency()`; Scope
`configure_waveform_acquisition(channel, volts_per_division, seconds_per_division, points)`,
`read_waveform(channel)`, `measure_point(channel)`. A waveform is `{"x_origin", "x_increment",
"samples"}`. Load `set_mode` (CC/CV/CR/CP), `set_level`,
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

- A call blocked inside a driver is not interrupted by Stop; `CALL_TIMEOUT_S` (30 s) bounds it.
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
- `_abandon()` arriving while the run thread is already inside `_close()`'s ladder sees a busy
  device and kills its main process; the ladder's own rescue process, if one is in flight, is
  not tracked and runs until it finishes or dies with PyPTS (a daemon). Accepted: the ladder
  is serialized per device, not across callers, and the CRITICAL is reported either way.
- PyPTS killed outright (the launcher's terminate, a crash) runs none of this: the driver
  process's own `teardown()` at the end of the Pipe is the only net, and only when it is not
  stuck in a call.
- Output a C library writes straight to the process's file descriptors (not through
  `sys.stdout`) is not forwarded. It goes to PyPTS's own console, if there is one.
- No automatic recovery policy, only `recover_device()` from test code.
- No PSU, DMM, Scope or Load driver ships yet; only the device-type bases.
- Every driver runs on PyPTS's own Python: a vendor library that needs another interpreter
  (for example a 32-bit DLL) is not supported.
