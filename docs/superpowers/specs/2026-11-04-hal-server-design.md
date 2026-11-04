<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# HAL server — design

Status: draft for approval, 2026-11-04. Branch `architecture_refactor`.

## 1. Intent

Today the hardware layer (`src/pypts/hal/`, see `hal/hal.md`) is a library inside the CORE
process: the Sequencer thread's `ConnectionDriver` spawns one driver process per device and
talks to it over a `multiprocessing` Pipe with pickled tuples.

The redesign moves the HAL into **one process of its own, the HAL server**, reached over
**TCP on localhost**. Why:

- **Clarity.** One process owns the bench; every device call visibly goes to one place,
  the same way CORE, the Logger and the frontend are each one process today.
- **Standalone use.** The HAL must be usable without the rest of PyPTS — by a Python script,
  and later by clients in other languages (LabVIEW, C#, ...).
- **Visibility.** A developer can look at the HAL process and the bench from the PyPTS GUI.

The framework is meant to stay **as small as possible**: fewer code paths beat fewer
processes. Every decision below leans that way.

## 2. Goals

1. A HAL server process that the launcher **always** starts, in every mode (GUI, CLI,
   headless, and `pypts.api` — all go through `launcher.startup.start_engine()`), and that
   simply **idles** when `bench.ini` declares no device.
2. The HAL server runnable **on its own**, without PyPTS (e.g. `python -m pyhal`), for
   scripts and other-language clients.
3. Test code calls devices the same way: `get_device("x").operation(...)`. Only the import
   path changes (D11).
4. The driver contract unchanged: `BaseDriver`, the device types and their verbs, and every
   shipped driver's behaviour. Only import paths change (D11).
5. A developer-only **View → HAL** window in the GUI showing the HAL process and the bench.

## 3. Non-goals

- **More than one client.** One client at a time. A second connection is refused. Two
  programs using one bench at once is not supported, by decision.
- **Keeping the HAL alive at all costs.** If the HAL dies, it dies: calls fail with a
  `DriverError`, and each driver process tears its device down when its Pipe closes (the
  existing safety net). No restart, no failover.
- **Device probing / live availability.** Devices are not connected outside a run. No
  `ping()`, no probe at startup.
- **A separate distribution now.** The HAL package ships inside the `pts-framework`
  distribution (like `pyrade_xy_graph`); splitting it into its own distribution later must be
  a move of files, not a redesign.
- **Remote (non-localhost) access and authentication.**
- **A rich or fancy panel.** Plain, for developers.

## 4. Anti-goals — failure even if it works

- Any change to *when* devices are torn down or to the teardown ladder's guarantees: an
  instrument must never be left energised by the redesign.
- Pickle on the TCP link (a remote-code-execution hole, and Python-only).
- A protocol that cannot be swapped without touching the architecture.
- A second code path for "HAL running" vs "HAL not running" inside PyPTS.

## 5. Decisions (made by the user)

| # | Decision |
|---|---|
| D1 | One HAL server process; the launcher always starts it; idle with an empty bench. |
| D2 | TCP on localhost. |
| D3 | Exactly one client at a time; a second is refused. |
| D4 | One driver process per device is kept, **inside** the HAL server (crash isolation stays). |
| D5 | Device lifetime unchanged: a device opens on the first `get_device()` in a run and is torn down at the run's end through the existing ladder. No probing. |
| D6 | HAL death is accepted, not prevented. |
| D7 | Protocol language-neutral but **dead simple for now**, and easy to change later. |
| D8 | View → HAL panel: plain, developer-facing, shows HAL process status and device status. |
| D9 | Same pattern as `src/pyrade_xy_graph/`: a **separate top-level package** under `src/`, shipped inside the `pts-framework` distribution for now, later its own package and a dependency. Runnable on its own. See §6a. |
| D10 | One place for configuration (`bench.ini` beside `config.ini`), one place for logs. |
| D11 | Package name `pyhal`. **Rename everything, no shim:** `pypts.hal` disappears. Drivers import `from pyhal import PSU`; bench.ini names `driver = pyhal.drivers.ssh.SshDriver`. Shipped drivers, the HAL demo recipes and their test code, `bench_template.ini`, tests and every document are updated in the change; users edit their own bench.ini and driver files (say so in the usage manual and the migration notes). Where `get_device()` lives for test code (`pyhal` client vs a `pypts` helper) is the builder's call, as long as `pyhal` never imports `pypts`. |
| D12 | **Scripts without PyPTS:** the in-process `LocalSetup.from_ini()` mode is removed. A script uses the `pyhal` Python client, which **starts a HAL server for the script** when none is running (on a bench file the script names, or `bench.ini` by default) and stops it when the script's client closes. The script marks its own run boundaries through the client (a `with` block is the natural shape). One code path: the HAL server. |
| D13 | Plan from the **working tree as it is** on 2026-11-04, uncommitted changes included (`device_control.py` with `recover_device()` / `device_info()`). |

## 6. Architecture

```
 launcher ──starts──> Logger      CORE (Sequencer thread, Report thread)      frontend
          └─starts──> HAL server <──── TCP localhost, one connection ─────┘
                         │  (CORE is the one client)
                         ├── Pipe ──> driver process "Device ssh1"
                         └── Pipe ──> driver process "Device psu1"
```

- **CORE is the HAL's one client.** `ConnectionDriver` (or its successor) inside CORE becomes
  a thin client stub that turns a call into a request on the TCP connection. Test code still
  sees the same object, the same operations and the same `DriverError` messages.
- **Inside the HAL server, today's machinery moves across nearly as-is:** spawning driver
  processes, the pickle Pipe protocol between the HAL and each driver process, the call
  timeout, the teardown ladder with its rescue, `abandon()`. The Pipe link stays pickle — it
  never leaves the HAL and is not part of the public protocol.
- **The HAL server must not be a daemon process**: a daemon cannot have children, and the HAL
  spawns driver processes. (CLAUDE.md's process list changes: the HAL server becomes a fourth
  long-lived process; driver processes are its children, not CORE's.)
- **Runs.** The client marks run boundaries: at run end (today: the `LocalSetup` `with` block
  closing) the client asks the HAL to tear down every device it opened, newest first. An
  abandoned run (today: `abandon_active_setup()`) becomes an "abandon" request with the same
  semantics as today's `LocalSetup.abandon()`: nothing more opens, devices are torn down on
  one deadline, names that could not be torn down come back for the CRITICAL line.
- **Client disconnect = release.** If the client's connection drops, the HAL tears down every
  open device (the TCP equivalent of today's "PyPTS dies → Pipe closes → teardown").
- **Single client.** While a client is connected, further connections are refused with a
  clear error.

## 6a. Packaging — the `pyrade_xy_graph` pattern

- The HAL becomes its own top-level package, `src/pyhal/`, beside `src/pypts/` and
  `src/pyrade_xy_graph/`, added to `[tool.setuptools.packages.find] include` in
  `pyproject.toml`. Package name: `pyhal` (decided).
- **It never imports `pypts`.** Dependency points one way only: `pypts` may import the HAL
  package, never the reverse. This is what makes the later split a move of files.
- **It holds:** the HAL server and its entry point, the driver-process machinery (today's
  `connection_driver.py` internals, teardown ladder), `BaseDriver`, the device types,
  `DriverError`, the shipped drivers, the TCP protocol module, and the **Python client** (so a
  plain Python script can use the HAL without PyPTS).
- **Unlike `pyrade_xy_graph`** it is our own code, not an upstream copy: no `DEVIATIONS.md`,
  and it stays under the quality gates (ruff, mypy, tests), not in the ruff exclude list.
- **What stays in `pypts`:** the integration only — the launcher starting/stopping the HAL
  process (a small pypts-side entry wrapper may set up logging toward the Logger, then hand
  over to the HAL package's server), CORE's use of the client, the Sequencer's run
  boundaries, the View → HAL window and its messages.
- Its own context file `pyhal/pyhal.md` replaces `pypts/hal/hal.md`, and
  CLAUDE.md's module table and architecture block change accordingly.

## 7. Protocol (public, TCP)

Dead simple, behind one swappable seam (D7):

- **Framing and encoding:** one JSON object per line (UTF-8, `\n`-terminated). *Builder's
  call if a better simple framing is preferred; it must stay language-neutral.*
- **Request:** a kind (call, release/end-of-run, abandon, status, ...), the device name, the
  operation and its arguments.
- **Answer:** a result value, or an error carrying the error type name, message and
  traceback text — the same information today's `("error", type_name, message, traceback)`
  carries, so the client raises the same `DriverError` text test code sees today.
- **Values are plain data** (numbers, strings, booleans, null, lists, objects with string
  keys). *Claude's call:* lists and tuples both travel as lists, so a tuple arrives as a list
  (documented for test code and driver writers). Anything else (`bytes`, non-string dict
  keys, numpy values, NaN or infinity, custom objects) is **refused before sending** with a
  `DriverError` naming the value: an argument in the client, a return value in the HAL
  server. This is the same behaviour as an unpicklable argument or return value today. All
  shipped drivers return plain data.
- **Device control is part of the protocol** (*Claude's call*): today's `recover_device()`
  and `device_info()` (`device_control.py`) become requests. Recovery runs its whole
  escalation inside the HAL server, as `ConnectionDriver._recover()` does today.
- **One seam per side.** Encoding/decoding and send/receive live in one small module used by
  both the server and the client stub, so swapping to msgpack (or anything else) touches that
  module only.
- **Address** (*Claude's call*): a fixed default port on `127.0.0.1`. PyPTS always uses it
  and **never attaches to a HAL that is already running**. If the port is taken (another
  PyPTS, a standalone HAL), PyPTS's HAL fails to start with a clear error naming the port
  (two users of one bench on one machine is not supported, D3). The standalone server and
  the `pyhal` client accept a port, so tests can use their own. *Exact port number and option
  name: builder's call.*

The exact message catalogue is the builder's to define, but it must be documented in
`pyhal/pyhal.md` the way the Pipe messages are today.

## 8. View → HAL panel

- A new item **HAL** in the GUI's **View** menu (`hmi/gui/gui.py`, beside *Appearance* and
  *Full Screen*). It opens a small plain window. Nothing HAL-related appears anywhere else in
  the GUI. There is no developer mode in PyPTS; "developer-only" means tucked away in View,
  not gated.
- **Shows:**
  - the HAL process: running / stopped, process id, TCP address, whether CORE is connected;
  - one row per device in `bench.ini`: name, driver, device type (once known), state —
    *configured* (not open), *open* (used by the current run), *failed* (with the last error).
- A **Refresh** button; no automatic polling.
- Read-only: it cannot open, close or test devices.
- **Data path:** because of D3 (one client, which is CORE), the GUI does not connect to the
  HAL. It asks **CORE** through a new request/answer pair on the HMI↔CORE link, and CORE asks
  the HAL. This keeps the project rule that modules talk only through CORE. The new messages
  go into `messages/core_hmi_communication.py` and `messages/messages.md`; the routing into
  `core/core.md`.
- A status request must be answered promptly (about a second) **even while a run is inside a
  long device call** (up to the 30 s call timeout). How the HAL server and the client stub
  achieve that (concurrent handling of requests on the one connection, a separate status
  path, ...) is the builder's call.

## 9. Configuration and logs

- `bench.ini` stays where it is: beside `config.ini` (`%LOCALAPPDATA%\pypts\` on Windows,
  `~/.config/pypts/` on Linux), same format, read once at HAL start. The HAL server, not
  CORE, reads it.
- **Under PyPTS**, the HAL server logs through the Logger process like every other process,
  and forwards its driver processes' records as today (`Device 'x': <message>`). Log wording
  and levels follow `logger/logging_rules.md`; the existing HAL lines (`Device 'x'
  connected.` etc.) keep their text.
- **Standalone**, it writes its own log file into the same logs folder PyPTS uses
  (`%LOCALAPPDATA%\pypts\logs` / `~/.local/share/pypts/logs`) — one place for logs (D10).
  *File naming: builder's call.*
- The HAL package cannot import `pypts` (§6a), so it needs the bench-file location and bench
  reading itself (today `config_handler.file_locations.bench_file_path()` and
  `config_handler.bench_config`). There must stay **one source of truth** for the folder: the
  builder decides which side owns it, with `pypts` allowed to import from the HAL package
  and never the reverse.
- The launcher's "bench.ini was discarded" notice must keep working.

## 10. Failure behaviour

| What happens | Result |
|---|---|
| HAL server fails to start (port taken, crash at start) | PyPTS still starts; every `get_device()` fails with a `DriverError` naming the reason; the View → HAL panel shows it stopped. *Whether startup should instead refuse to continue: builder may propose, default is "start anyway".* |
| HAL server dies mid-run | The call in progress and every later call fail with a `DriverError` ("the HAL server stopped ..."); driver processes tear down when their Pipes close. |
| Client (CORE) dies | HAL tears down every open device (client disconnect = release). |
| Every failure today's table in `hal/hal.md` lists | Same `DriverError` text reaches test code. |

## 11. What changes, what does not

- **Unchanged:** the driver contract and driver behaviour, device types, how test code calls
  a device, per-run device lifetime, the teardown ladder and its timeouts, the Pipe protocol
  between the HAL and a driver process, the error texts test code sees. Import paths do
  change (D11).
- **Removed:** `pypts.hal` (D11) and the in-process `LocalSetup.from_ini()` script mode (D12).
- **New:** the top-level HAL package (§6a) holding the HAL server and its entry point, the TCP
  protocol module and the Python client; the View → HAL window; HMI↔CORE status messages;
  launcher start/stop of the HAL; the `pyproject.toml` package entry.
- **Moved:** today's `src/pypts/hal/` contents (drivers, `BaseDriver`, device types, the
  driver-process machinery) into the HAL package.
- **Changed:** `ConnectionDriver`/`LocalSetup` split between client (CORE) and server (HAL);
  `Sequencer`'s use of `LocalSetup` and `abandon_active_setup()`; `launcher/startup.py`
  (`start_engine` / `stop_engine`); the documents listed below.
- **Documents to update in the same change** (CLAUDE.md rule): `hal/hal.md` (becomes
  `pyhal/pyhal.md`), `config_handler/config_handler.md`, `step/step.md` (SSH reference),
  the HAL demo recipes under `resources/recipes/HAL_recipes/`, `launcher/launcher.md`, `core/core.md`, `messages/messages.md`, `sequencer/sequencer.md`,
  `hmi/gui/gui.md`, `usage_manual.html` (View → HAL, the HAL process),
  `docs/Usage_manuals/pypts_implementation_status.html`,
  `docs/Usage_manuals/how_to_write_a_driver.html` / `.md` (new import path, plain-data
  values), `docs/Usage_manuals/migration_instructions.html` (the rename),
  `CLAUDE.md` (module table, architecture block, process list).

## 12. Left to the builder

- Exact message catalogue, framing details, port number and option names (§7).
- How status stays responsive during a long call (§8).
- Where bench-file reading lives so the HAL stays standalone (§9).
- Standalone log file naming (§9).
- Module/file layout inside `src/pyhal/`.
- How the client started by a script (D12) finds or starts its server, and the script-side
  API shape, within D12.
- Run identity on the protocol (so an abandoned run's devices stay refused), parallel calls
  to different devices, tearing devices down before the HAL server exits.
- Test strategy, within the quality gates (`pytest`, `ruff`, `mypy`) — today's HAL tests
  (`test_hal*.py`) should keep covering the in-HAL machinery.

## 13. Note on work in progress

`src/pypts/hal/` has uncommitted changes as of 2026-11-04, including a new
`device_control.py` (`recover_device()`, `device_info()`). Per D13 the plan starts from the
**working tree as it is**, uncommitted changes included, read from the source rather than
from this document's description of it.
