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
| `__init__.py` | The public API: `get_device`, `LocalSetup`, `ConnectionDriver`, `BaseDriver`, `DriverError`, the six families |
| `base_driver.py` | `BaseDriver` (ABC: `connect`, `teardown`, `recover`), `DriverError`, `LIFECYCLE_METHODS`, `operations_of()` |
| `families.py` | `PSU`, `DMM`, `Scope`, `SSH`, `Load`, `Other`; `FAMILIES`, `FAMILY_NAMES` |
| `connection_driver.py` | `ConnectionDriver`, one device as test code sees it; below it, the driver process: `driver_process_main()`, `load_driver_class()`, `answer()` |
| `local_setup.py` | `LocalSetup`, the devices of one run; `get_device()`; `split_section()`; the section readers |
| `drivers/loopback.py` | `LoopbackDriver` (Other): no hardware; tests, demo, smoke check |
| `drivers/ssh.py` | `SshDriver` (SSH): the reference driver, paramiko |

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
   builds the driver, and sends `hello` (family and operations) or `fatal` with the reason.
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
| `("hello", family, operations)` | driver process → PyPTS, once, first |
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
`config.ini` applies from the next start. Restore default settings (GUI) recreates `config.ini`
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
- **PyPTS exits normally with a device still open** (an abandoned run): the driver process is a
  daemon, so multiprocessing terminates it at exit **without** `teardown()`.

## Failure

| What happens | What test code sees |
|---|---|
| Driver raises | `DriverError("Device 'x': 'op' failed: Type: message")`; the device stays usable; traceback at DEBUG |
| Argument not picklable | `DriverError("Device 'x': the arguments of 'op' cannot be sent: ...")`; nothing was sent |
| Return value not picklable | `DriverError("Device 'x': 'op' failed: TypeError: 'op' returned a value that cannot be sent: ...")` |
| Argument cannot be unpickled in the driver process | `DriverError("Device 'x': 'op' failed: <Type>: the call could not be read in the driver process: ...")` |
| Return value cannot be unpickled in PyPTS | `DriverError("Device 'x': the answer 'op' could not be read: ...")` |
| Call exceeds `call_timeout_s` | `DriverError("... did not answer 'op' within N s; its driver process was stopped.")` |
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
`Recovering device 'x'.`, `Device 'x' recovered.` WARNING: `Device 'x' did not disconnect
cleanly: ...`. Forwarded records are logged as `Device 'x': <message>`: at their own level
when the logger is the driver's own module (or a child of it), and at DEBUG when another library
logs below WARNING. Lines printed through `sys.stdout` / `sys.stderr` in the driver process are
DEBUG (`Device 'x' printed: ...`), as are every call and its return value (cut to
`TRACE_MAX_CHARS`) and tracebacks. The `connect` and `recover` trace shows the settings masked;
the arguments of ordinary calls are traced as given.

## Writing a driver

1. Derive from the family it belongs to (`from pypts.hal import PSU`), never from `BaseDriver`
   directly: a driver of no family is refused.
2. Implement `connect(config)` (all values are text), `teardown()` (harmless when nothing is
   open) and the family's verbs. Every other public method becomes an operation too.
3. Log with `logging.getLogger(__name__)`. Do not name a method `name`, `family`, `operations`,
   `open`, `close`, `recover` or `is_open` (`connection_driver.RESERVED_NAMES`). Do not start
   `multiprocessing` processes from a driver: the driver process is a daemon, and a daemon
   cannot have children.
4. Import the vendor library at the top of the driver module, with an `ImportError` that names
   the extra to install (see `drivers/ssh.py`).
5. Test it in-process with the vendor library mocked (`test_hal_ssh.py`), and through a real
   driver process with the loopback pattern (`test_hal_connection.py`).

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
`[serial]` pyserial, `[hardware]` all three. `.gitignore` carries `!/src/pypts/hal/drivers/`
because its bare `drivers` rule would otherwise hide the shipped drivers.

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

It reuses the run's active local setup (`get_device()`), so nothing in this module changes; it
is a recipe-format change (`recipe_guide.html`, the schema in `recipe/recipe_schema.py`, the
verificator). Roadmap TODO in §1.54.

## Known gaps

- A call blocked inside a driver is not interrupted by Stop; `call_timeout_s` bounds it.
- No side channel for bulk data: a waveform is pickled through the Pipe.
- Log records and printed lines are read only while PyPTS waits for a call. Records from a
  driver's own threads between calls (paramiko's transport thread at DEBUG, say) wait in the
  Pipe. They are logged late, stamped with the time PyPTS read them, and once the Pipe's buffer
  is full every thread of the driver process that logs or prints blocks until the next call.
- `sys.stdout` / `sys.stderr` in the driver process are a line forwarder, not a real stream:
  `encoding` is `None`, and there is no `buffer` and no `fileno()`.
- An abandoned run's devices stay open until CORE exits, and are then terminated without
  `teardown()`.
- Output a C library writes straight to the process's file descriptors (not through
  `sys.stdout`) is not forwarded. It goes to PyPTS's own console, if there is one.
- No automatic recovery policy, only `device.recover()` from test code.
- No PSU, DMM, Scope or Load driver ships yet; only the family bases.
- Every driver runs on PyPTS's own Python: a vendor library that needs another interpreter
  (for example a 32-bit DLL) is not supported.
