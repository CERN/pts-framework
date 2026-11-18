<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# HAL server — design

Status: draft for approval, revision 4, 2026-11-05. Revision 4 turns the HAL into a
**standalone local service** that PyPTS connects to or starts (user, 2026-11-05) — simpler
than revisions 2-3, which tied the HAL's life to PyPTS. Branch `architecture_refactor`.

Marked *Claude's call* = decided by Claude, for the user to check. Everything in the decision
table (§5) was decided by the user.

## 1. Intent

Today the hardware layer (`src/pypts/hal/`, see `hal/hal.md`) is a library inside the CORE
process: the Sequencer thread's `ConnectionDriver` spawns one driver process per device and
talks to it over a `multiprocessing` Pipe with pickled tuples.

The redesign makes the HAL **a package of its own, `pyhal`, running as a standalone local
service, the HAL server**, reached over **TCP on localhost**. PyPTS connects to a HAL that is
already running, or starts one. Why:

- **Clarity.** One process owns the bench; every device call visibly goes to one place.
- **Standalone use.** The HAL is usable without PyPTS — by a Python script, and later by
  clients in other languages (LabVIEW, C#, ...). Later `pyhal` becomes its own distribution
  (a subrepository).
- **Independence.** The HAL lives on its own: PyPTS crashing does not touch it.
- **Visibility.** A developer can look at the HAL and the bench from the PyPTS GUI.

The framework is meant to stay **as small as possible**: fewer code paths beat fewer
processes.

## 2. Goals

1. The HAL server is a standalone process (`python -m pyhal`). PyPTS, at startup, connects to
   one that is running or starts one; it idles when the bench declares no device.
2. One connect path for everyone: PyPTS and scripts both use `pyhal.connect()`.
3. Test code calls devices the same way: `get_device("x").operation(...)`, and the same test
   module runs under PyPTS and in a plain script. Only the import path changes (D11).
4. The driver contract unchanged: `BaseDriver`, the device types and their verbs, every
   shipped driver's behaviour. Only import paths change (D11). Value differences: §7.4.
5. A developer-only **View → HAL** window in the GUI showing the HAL and the bench.
6. A normal close of PyPTS tears every device down (`close_all`), as today.

## 3. Non-goals

- **More than one client at a time.** A second connection is refused.
- **Teardown when PyPTS dies** (D36). The HAL does nothing; devices stay as they are.
- **Keeping the HAL alive at all costs, or restarting it** (D28).
- **Device probing / live availability.**
- **A separate distribution now.** `pyhal` ships inside `pts-framework`.
- **Remote (non-localhost) access, authentication.**
- **Streams** (D33).
- **A rich or fancy panel.**

## 4. Anti-goals — failure even if it works

- A **normal** close of PyPTS leaving an instrument energised.
- A device handle from an earlier Start press able to reach a device again.
- Pickle on the TCP link (a remote-code-execution hole, and Python-only).
- A protocol that cannot be swapped without touching the architecture.
- Two code paths: one for "PyPTS started the HAL", one for "it was already running".
- `pyhal` importing `pypts`.

## 5. Decisions (made by the user)

Superseded decisions from revisions 2-3 are struck through in place, so the trail stays.

| # | Decision |
|---|---|
| D1 | One HAL server process; idle with an empty bench. |
| D2 | TCP on localhost. |
| D3 | Exactly one client at a time; a second is refused. Two programs sharing one bench is not supported. |
| D4 | One driver process per device is kept, **inside** the HAL server (crash isolation stays). |
| D5 | A device opens on the first `get_device()` during a Start press. When the press ends PyPTS sends `close_all`, as today. No probing. |
| D6 | HAL death is accepted, not prevented. |
| D7 | Protocol language-neutral, **dead simple for now**, easy to change later. |
| D8 | View → HAL panel: plain, developer-facing, HAL status and device status. |
| D9 | The `pyrade_xy_graph` pattern: **`src/pyhal/`**, a separate top-level package shipped in the `pts-framework` distribution for now, later its own package (subrepository) and a dependency. |
| D10 | One place for configuration: `bench.ini` stays beside `config.ini`, and `config_handler` keeps owning where it lives. `pyhal` logs with plain Python logging; `pyhal` reads the bench INI file it is given. |
| D11 | Package name `pyhal`. **Rename everything, no shim:** `pypts.hal` disappears. Drivers import `from pyhal import PSU`; bench.ini names `driver = pyhal.drivers.ssh.SshDriver`. Users edit their own bench.ini and driver files (usage manual, migration notes). |
| D12 | **Scripts:** the in-process `LocalSetup.from_ini()` mode is removed; scripts use `pyhal.connect()`. |
| D13 | Plan from the **working tree as it is** on 2026-11-04, uncommitted changes included. |
| D14 | ~~Free port + token~~ → superseded by D37. |
| D15 | **NaN, infinity and bytes are encoded** in small tagged forms (§7.4). |
| D16 | **HAL log:** the HAL always writes its own log file (it outlives PyPTS, so it cannot use PyPTS's Logger): `--log-dir`, default a fixed per-user folder of `pyhal`'s own. |
| D17 | **The Sequencer's worker thread holds the `pyhal` client directly**, as it holds the Pipe today. The HAL link stays outside the message layer. |
| D18 | **One request at a time** on the connection (no request ids). A second caller waits behind a request in progress; threads in test code take turns. |
| D19 | **Heartbeat on the same connection, from its own thread** of the HAL server; a beat never waits behind a device call. CORE watches it; losing it marks the HAL lost (D28) and does not end the session. |
| D20 | **The heartbeat carries the panel snapshot:** HAL pid, the bench file, each open device's state and last error, what the device thread is busy with — no address. View → HAL shows the latest snapshot; it never sends a request. |
| D21 | **HAL cannot be reached or started → PyPTS starts anyway**, with a warning; every `get_device()` fails with the reason. |
| D22 | **The HAL knows devices, not runs.** Requests: `open`, `call`, `recover`, `info`, `close`, `close_all`, `shutdown`. A run (one press of Start) stays a PyPTS idea. |
| D23 | ~~Start order with the launcher waiting for the HAL~~ → superseded by D37. |
| D24 | **CORE connects at startup** and keeps the connection for the session. |
| D25 | **Bench read once per HAL start**; an edit applies when the HAL is restarted. |
| D26 | **Closing PyPTS with a test stuck in a call:** closing waits for the stuck call to end (bounded by `CALL_TIMEOUT_S`), then sends `close_all`. Closing can take about 30 s longer in that rare case; CORE's and the launcher's shutdown budgets grow to match. The operator sees "Closing devices safely...". |
| D27 | **Safety rules:** (1) the HAL never exits without tearing down every open device; ~~(2) owner gone → tear down and exit~~ (superseded by D36); (3) the answer to `close_all` never arrives → PyPTS logs `Device 'x' could not be torn down and may still be energised: ...` for every device that may be open. |
| D28 | **HAL death is one case, whenever it happens:** device calls fail with a `DriverError` through the normal step-error path; PyPTS shows the HAL lost; devices come back after restarting PyPTS (which connects to, or starts, a HAL). No automatic restart. |
| D29 | **Accepted gap:** a driver process stuck inside a call does not notice the HAL dying; its teardown runs when the call returns. |
| D30 | **Sending takes plain Python:** `send("close_all")`, `send("call", device=..., operation=...)`; the send function does all wrapping and encoding. |
| D31 | **No protocol version** for now. Added when `pyhal` is split out. |
| D32 | **Message size limit 16 MB** (about 700-800k float samples in the compact waveform form). |
| D33 | **Streams are out of this design**; a driver's own rule. A later `stream` message kind fits the protocol. Constraint: a driver process cannot reach CORE's `StreamSession`. |
| D34 | ~~Abandonment = dropping the connection~~ → superseded by D26 and D36. |
| D35 | ~~Refuse new clients after a failed release~~ → removed: a disconnect no longer triggers a release. |
| D36 | **Client gone → the HAL does nothing.** If PyPTS (or a script) dies or disconnects, the HAL keeps running and keeps every device exactly as it is, and waits for the next client. *Consequence, accepted:* after a PyPTS crash mid-test an instrument may stay energised until someone closes it. |
| D37 | **Connect or start.** The HAL listens on one fixed localhost port. `pyhal.connect()` tries it: a HAL there → use it; none → start `python -m pyhal --bench <file>` **detached** (it survives its starter), wait until it listens, connect. No token, no free port. |
| D38 | **On normal close, stop the HAL only if this client started it.** PyPTS (or a script) that started the HAL sends `close_all`, then `shutdown`. One that found the HAL already running sends `close_all` and leaves it running. |
| D39 | **A running HAL with a different bench file:** connect anyway, with a WARNING naming both bench files. |
| D40 | **Leftover open devices** (e.g. after a crash): PyPTS logs a WARNING listing them, View → HAL shows them, and `get_device()` reuses them. Nothing is switched off automatically. |
| D41 | **CORE owns every HAL operation except the steps' own device calls.** The steps (test code on the Sequencer's worker thread) call devices through `pyhal.get_device()`. Everything else — connect or start, heartbeat watch, snapshot, opening the device slot for a Start press, `close_all` after it, `close_all` / `shutdown` when PyPTS closes — is CORE's. **The Sequencer never touches the HAL.** *Consequences, accepted:* `close_all` runs after `RunFinished`, so teardown results are in the run log but not in that run's report; CORE runs it off its event loop and holds the next Start until it is done. |

## 6. Architecture

```
 PyPTS (launcher, Logger, CORE, frontend)            a script
        │ pyhal.connect()                               │ pyhal.connect()
        └──────────── TCP 127.0.0.1:<fixed port> ───────┘   (one client at a time)
                                │
                       HAL server (standalone, detached)
                         ├── Pipe ──> driver process "Device ssh1"
                         └── Pipe ──> driver process "Device psu1"
```

### 6.1 Who does what

- **The HAL server** owns the bench: it reads the bench file at start, opens a device on the
  first `open`, keeps it open until `close` / `close_all` / its own exit, and serves one
  client at a time. Clients come and go; devices stay (D36).
- **Inside the HAL server, today's machinery moves across nearly as-is:** spawning driver
  processes, the pickle Pipe protocol to each, the timeouts, the teardown ladder with its
  rescue, recover. The Pipe link stays pickle; it never leaves the HAL.
- **CORE is PyPTS's client and owns every HAL operation except the steps' device calls
  (D41).** At startup it calls `pyhal.connect()` (D24, D37) with the path of PyPTS's
  `bench.ini` — the same call a script makes; the launcher does nothing new. CORE's event
  loop, the Sequencer and the Report are threads of the CORE process, so they share the one client
  object; **the Sequencer itself never touches the HAL.** Only test code on the Sequencer's
  worker thread does: it gets a **device handle** from `pyhal.get_device()`, and a call on it
  becomes a request (D17). The handle keeps today's
  surface: `__getattr__` turns a name in the device's operations into a call and any other
  name raises `AttributeError` without a round trip (the `open` answer carries
  `device_type` and `operations`).
- **`get_device()`, `recover_device()`, `device_info()` live in `pyhal`** (*Claude's call*)
  and read a module-level **active-client slot** — the successor of today's `_active_setup`.
  CORE fills it when it sends `RunSequence` to the Sequencer and clears it when it receives
  `RunFinished` (D41); a script's `with pyhal.connect(...)` fills it for the script.

### 6.2 Connect or start (D37)

1. `pyhal.connect(bench=..., port=DEFAULT_PORT)` connects to `127.0.0.1:<port>`.
2. **A HAL answers** → handshake (§7.2). Its `hello` names its bench file and lists the
   devices it has open. A different bench file → WARNING naming both (D39); open devices →
   WARNING listing them, and they are reused (D40).
3. **Nothing answers** → the client starts `python -m pyhal --bench <file> --port <port>` as
   a **detached** process (Windows: `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, no console;
   Linux: `start_new_session=True`), passing its own `sys.path` so dotted driver paths resolve
   as today, then retries the connection until `HAL_START_TIMEOUT_S` (15 s). It remembers
   that **it started this HAL** (for D38).
4. **Two starters at once** (PyPTS and a script): both see nothing, both start a HAL; the
   second cannot bind the port and exits; both retry the connection; one gets in, the other
   is refused as a second client (D3) with a clear error.
5. **Timeout, or a HAL that refuses** → D21: PyPTS starts anyway; `get_device()` fails with
   the reason.

### 6.3 Devices and Start presses (D5, D22)

A *run* is one press of Start: the top-level sequence, every sequence it calls, and the
teardown steps (`Sequencer.execute_sequence()`). It is a PyPTS idea; the HAL never sees it.

- **End of a Start press** (pass, fail or error): **CORE**, on receiving `RunFinished` (D41),
  raises the fence counter, clears the active-client slot, and sends `close_all` from a helper
  thread, so its event loop never blocks. Until that answer is in, CORE holds a new
  `RunSequence` and shows "Closing devices..." as status. The HAL tears down every open
  device, newest first, through today's ladder, and answers with every device that was
  **not** torn down; CORE logs today's ERROR lines for them. (Today the Sequencer closes
  devices before `RunFinished`, in the `LocalSetup` `with` block, `sequencer.py:517`; that
  block goes, and teardown results are in the run log, not in that run's report.) If the answer never arrives, PyPTS logs
  `Device 'x' could not be torn down and may still be energised: ...` for every device that
  may be open — counted from the moment `open` was sent (D27 rule 3).
- **The fence against leftover handles lives in the client** (*Claude's call*; required for
  anti-goal 2): the client keeps a counter; each device handle remembers the counter it was
  created under; the counter is raised and the active-client slot cleared **before**
  `close_all` is sent, under the request lock; every handle request compares its counter
  **under the request lock, in the same step as the send**. A stale handle raises locally
  with today's text (`Device 'x' cannot be opened/recovered: its run was abandoned and the
  device was torn down.` and the equivalents). Outside a Start press `get_device()` refuses as
  today (`No local setup is active. ...`, reworded for the new names).

### 6.4 Lifetime

| Event | What happens |
|---|---|
| PyPTS closes normally | CORE stops the Sequencer, then sends `close_all` (D5/D27, D41). Then, **if this PyPTS started the HAL**, `shutdown` → the HAL exits; otherwise it stays running (D38). With a test stuck in a call, `close_all` waits on the request lock for that call to end, bounded by `CALL_TIMEOUT_S` (D26). The Sequencer no longer tears anything down when it stops. |
| PyPTS crashes, or is killed | **Nothing** happens in the HAL (D36). It keeps devices as they are and waits for the next client. |
| PyPTS starts again | Connects to the running HAL; WARNING for leftover open devices, which are reused (D40). |
| A script ends its `with pyhal.connect(...)` block | The same as PyPTS's normal close (D38). |
| The HAL is stopped (`shutdown` request, Ctrl+C, closing its console) | It tears down every open device first, on one shared deadline, and logs any that failed (D27 rule 1). |
| The HAL dies | D28. Driver processes see their Pipe close and run `teardown()` — except one stuck in a call (D29). |

- **The HAL never exits without tearing down** (D27 rule 1). Every exit path — `shutdown`,
  Ctrl+C / console close, an uncaught exception in the server loop — first tears down every
  open device. Driver processes must never be ended by `multiprocessing`'s exit-time
  terminate of daemon children (today `daemon=True`, `connection_driver.py:320`, which on a
  clean parent exit kills them without running `teardown()`); how is the builder's call.
- **A client disconnecting** (clean or not) changes nothing on the bench (D36); the HAL just
  waits for the next client. *Builder's note:* if the old client's connection is half-open
  (no FIN/RST seen), the new client must not be refused forever — the heartbeat write to a
  dead peer fails within a few seconds, and that ends the old connection.

### 6.5 Inside `pyhal` (*Claude's proposal*)

| File | Holds | From |
|---|---|---|
| `base_driver.py`, `device_types.py`, `drivers/` | the driver contract, shipped drivers | moved, imports renamed |
| `driver_process.py` | one device's process: spawn, Pipe, timeouts, teardown ladder, rescue, recover | today's `connection_driver.py`, minus the test-code-facing surface |
| `devices.py` | open devices by name: open on first use (or reuse), `close`, `close_all` newest first | today's `local_setup.py`, minus everything run-related |
| `protocol/` | `messages.py` (typed requests/answers, the kind table), `values.py` (value domain, tagged forms, validator), `codec.py` (JSON lines) | new |
| `server.py` | TCP listener, one client at a time, device thread, heartbeat thread, teardown on every exit | new |
| `client.py` | `connect()` (connect or start), device handles, the counter fence, the active-client slot, the reader thread, `get_device()` / `recover_device()` / `device_info()` | new + today's `device_control.py` |
| `bench.py` | reads a bench INI file (format only) | split from today's `local_setup.py` |
| `__main__.py` | `python -m pyhal` | new |

The builder may refine names and splits; the responsibilities stay as listed.

## 6a. Packaging — the `pyrade_xy_graph` pattern

- `src/pyhal/`, beside `src/pypts/` and `src/pyrade_xy_graph/`, added to
  `[tool.setuptools.packages.find] include` in `pyproject.toml`.
- **It never imports `pypts`**, enforced by a test in `tests/quality_tests/`. Today's HAL code
  imports `pypts` in three small places: `pypts.logger.log.log` (`connection_driver.py:56`,
  `local_setup.py:27`) is only the root logger (`logger/log.py:52`) and becomes
  `logging.getLogger(__name__)`; `bench_sections()` (`local_setup.py:90-107`, the lazy
  `pypts.config_handler` import) goes — the HAL reads the bench file itself (§9).
- **`pyhal/__init__.py` stays import-light:** a driver's `from pyhal import PSU` runs in every
  driver process and must not pull in socket or client code.
- **Our own code**, unlike `pyrade_xy_graph`: no `DEVIATIONS.md`, under every quality gate.
- **What stays in `pypts`:** all in CORE (D41) — `pyhal.connect()` at startup, the HAL
  heartbeat watch, the active-client slot and `close_all` around a Start press, the close
  sequence (D26, D38), the View → HAL answer; plus the View → HAL window in the GUI.
- Its context file `src/pyhal/pyhal.md` (inline SPDX header) replaces `src/pypts/hal/hal.md`.

## 7. Protocol (public, TCP)

### 7.1 Three layers, one seam (*Claude's call*, so D7's "easy to change" holds)

1. **Typed messages:** a dataclass per request and answer with a `kind` discriminator, one
   union per direction (`ClientToHal`, `HalToClient`), handled with `match` closed by an
   `unhandled()` (CLAUDE.md convention). `pyhal` carries its own small `unhandled()` and TRACE
   line per send/receive.
2. **The value domain:** one recursive `PlainValue` type and one validator that names the path
   of anything outside it.
3. **The codec:** JSON, one object per line (UTF-8, `\n`), `allow_nan=False`. Swapping it
   touches only this layer.

**Sending (D30):** `send("close_all")`, `send("call", device="psu1", operation="output_off")`.
`send()` looks the kind up in one `kind → dataclass` table and builds the dataclass at once (a
misspelt kind or field raises before anything is encoded), validates and encodes. A test
checks the table covers both unions.

Example exchange:

```
client → HAL  (connects)
HAL → client  {"kind":"hello","pid":4120,"bench":"C:\\Users\\...\\pypts\\bench.ini","open":["psu1"]}
client → HAL  {"kind":"open","device":"psu1"}
HAL → client  {"kind":"opened","device":"psu1","device_type":"PSU","operations":["measure_voltage","output_off"]}
client → HAL  {"kind":"call","device":"psu1","operation":"measure_voltage","args":[1],"kwargs":{}}
HAL → client  {"kind":"heartbeat","pid":4120,"busy":{"device":"psu1","operation":"measure_voltage","since":"..."},"devices":{"psu1":{"state":"open","last_error":null}}}
HAL → client  {"kind":"result","value":12.03}
```

### 7.2 Connection and handshake

- **Bind** to `127.0.0.1` only, on a fixed default port (`--port` overrides it; PyPTS uses the
  default). On Windows bind with `SO_EXCLUSIVEADDRUSE`, never `SO_REUSEADDR`.
- **Handshake:** the server's first message is `hello`: pid, the absolute path of its bench
  file, the devices it has open. No protocol version (D31). The client compares the bench path
  after `os.path.normcase(os.path.realpath(...))` and warns on a difference (D39).
- **A second client** gets an `error` (origin `hal`, naming the HAL's pid) instead of `hello`,
  and the connection is closed.
- **Maximum message size: 16 MB** (D32). An answer that would exceed it is not sent: the HAL
  answers with an `error` (origin `hal`, `'op' ran, but its result is too large to send: N
  bytes.`) and the connection stays open. Only a malformed or oversized line *arriving* at
  either end closes the connection.

### 7.3 Requests and answers

- **One request outstanding at a time** (D18), no request ids.
- **From the HAL:** the answer to the outstanding request, and unprompted `heartbeat`s, which
  can arrive at any time, also between a request and its answer. **Every `pyhal` client runs a
  reader thread** (an answer to the waiting thread, a heartbeat to the latest-snapshot slot);
  a non-Python client skips heartbeats while it waits (`pyhal.md` says so).
- **Requests (D22):** `open` (opens, or reuses an open device; answers `device_type` and
  `operations`), `call`, `recover`, `info`, `close` (one device), `close_all`, `shutdown`
  (tear down everything, then exit; PyPTS sends it only under D38).
- **Errors carry an origin:**
  - `driver` — the driver raised; the client formats today's `Device 'x': 'op' failed: Type:
    message`;
  - `hal` — the HAL produced the whole message (timeout, stopped unexpectedly, not
    configured, could not be opened, cannot be sent, too large, second client); raised
    verbatim;
  - `protocol` — malformed request, value outside the domain, unknown kind; raised as
    `DriverError("HAL protocol error: ...")` and logged at ERROR.
  - The "its run was abandoned" refusal is produced in the client (§6.3), never by the HAL.
- The test-code-facing `DriverError` texts in today's `hal.md` *Failure* table are kept.

### 7.4 The value domain (D15)

- JSON-native values: numbers, strings, booleans, null, lists, objects with string keys.
- **Tagged forms:** `{"$float": "nan" | "inf" | "-inf"}`, `{"$bytes": "<base64>"}`, decoded
  back to `float` / `bytes`. A dict key starting with `$` is refused, so a driver's own dict
  is never mistaken for one.
- A **tuple arrives as a list.**
- **Refused, with a `DriverError` naming the path:** non-string dict keys, numpy values (the
  validator checks exact types — `numpy.float64` subclasses `float`), custom objects. An
  argument is refused in the client before anything is sent; a return value is refused in the
  HAL **after the operation ran**, and the text says so.
- Integers beyond 2^53 lose precision for non-Python clients; `pyhal.md` says so.

### 7.5 Threads (D18, D19)

- **HAL server:** a **device thread** serves the one outstanding request; a **heartbeat
  thread** sends a beat every 1 s (today's `DEFAULT_INTERVAL_S`) with the snapshot (D20),
  copied under a lock the device thread holds only while it updates state. Socket writes go
  through one lock held for one line; the heartbeat thread **drops a beat** rather than block
  when the socket is not writable.
- **Client:** one **request lock**, held by whoever sends a request until its answer arrives
  (D18); the fence check happens under it (§6.3). One **reader thread**.
- **CORE's HAL heartbeat watch is non-fatal** (*Claude's call*, required by D28): today a
  silent module ends the session (`Core.end_run_for_silent_module()`, `core.py:961-1010`).
  For the HAL, silence past `HEARTBEAT_FATAL_S` only marks it *lost*: waiting requests fail
  at once, View → HAL shows it lost. `core/core.md` documents the variant.

### 7.6 Timeouts (*Claude's call*, numbers from today's constants)

All HAL constants live in `pyhal` (today `connection_driver.py:66-84`). Every request has a
deadline counted from the moment it is sent:

| Request / wait | Deadline |
|---|---|
| `open` | `STARTUP_TIMEOUT_S` (30 s) + `CALL_TIMEOUT_S` (30 s, the `connect()`) + margin |
| `call`, `info` | `CALL_TIMEOUT_S` + margin |
| `recover` | driver recover (`CALL_TIMEOUT_S`) + one close ladder + `open` + margin |
| `close` | one close ladder: teardown (`CALL_TIMEOUT_S`) + `EXIT_TIMEOUT_S` (5 s) + `RESCUE_TIMEOUT_S` (10 s) + margin |
| `close_all`, `shutdown` | N × one close ladder + margin (N = devices that may be open) |
| `HAL_START_TIMEOUT_S` (connect-or-start) | 15 s |

- **Expiry** of a deadline: the client closes the connection, raises `DriverError` (`the HAL
  server did not answer ...`), and counts the HAL as lost (D28). The HAL itself does nothing
  (D36). Margins are generous.
- **Shutdown budgets grow** (D26): closing PyPTS may wait for a stuck call
  (`CALL_TIMEOUT_S`) and then `close_all`. `Core.SHUTDOWN_TIMEOUT_S` (25 s, `core.py:243`)
  and the launcher's `CORE_SHUTDOWN_TIMEOUT_S` (30 s, `startup.py:60`) are re-sized above
  that sum; the builder documents the sum in `core.md` and `launcher.md`.
  `ABANDONED_DEVICES_TIMEOUT_S` and `tear_down_abandoned_devices()` (`sequencer.py:86`,
  `:821`) are replaced by CORE's "wait for the stuck call, then `close_all`" (D41).

## 8. View → HAL panel

- A new item **HAL** in the GUI's **View** menu (`hmi/gui/gui.py`, beside *Appearance* and
  *Full Screen*), opening a small plain window. Nothing HAL-related elsewhere in the GUI.
- **Shows:** the HAL — connected / lost / not reachable, pid, bench file, whether this PyPTS
  started it, the time of the last heartbeat, what the device thread is busy with and since
  when; one row per device the HAL knows — name, device type (once known), state
  (*configured* / *open* / *failed* with its last error).
- A **Refresh** button; no polling. Read-only.
- **Data path:** GUI → CORE (a new request/answer pair on the HMI↔CORE link,
  `messages/core_hmi_communication.py`, `messages/messages.md`, routing in `core/core.md`).
  CORE answers from the **latest heartbeat snapshot** (D20): no TCP request. The answer is
  plain data (pickle-safe).

## 9. Configuration, bench data and logs

- **`bench.ini`** stays beside `config.ini` (D10). PyPTS passes its **path** to
  `pyhal.connect()`; the HAL reads the file itself with `pyhal`'s INI reader (`bench.py`),
  anchoring relative driver files to the file's folder (today's `anchor_driver_files()`,
  moved). `config_handler` keeps owning the path and its discarded-file check: when PyPTS's
  `bench.ini` was discarded at startup, PyPTS does not start a HAL with it, and
  `get_device()` raises today's text (`bench.ini was discarded at startup, so this start has
  no devices: ...`).
- **Logging (D16):** `pyhal` logs with the standard library only; the HAL process writes its
  own log file in `--log-dir` (default: a fixed per-user folder of `pyhal`'s own), because it
  outlives PyPTS. Technician lines keep today's text (`Device 'x' connected.` ...). Driver
  processes' records are forwarded to the HAL's log as today. PyPTS's run log still gets every
  `DriverError` test code sees, and CORE logs at INFO which HAL it connected to (pid, bench,
  started or found).
- **Port** is a command-line option of `python -m pyhal` and an argument of `connect()`, not a
  `config.ini` key, so `CONFIG_VERSION` is untouched.

## 10. Failure behaviour

| What happens | Result |
|---|---|
| No HAL running, and starting one fails or times out | D21: PyPTS starts anyway; `get_device()` fails with the reason; View → HAL shows "not reachable". |
| A HAL is running but another client holds it | `error` (second client) → D21. |
| HAL dies, mid-press or between presses | D28: calls fail through the normal step-error path; "may still be energised" for devices that may be open; View → HAL shows it lost. |
| HAL alive, device thread stuck | Heartbeats continue with "busy since"; the waiting request's deadline expires (§7.6) → HAL counted lost. |
| HAL process frozen | Heartbeats stop → the non-fatal watch marks it lost (§7.5). |
| PyPTS crashes | Nothing in the HAL (D36). |
| PyPTS closes with a test stuck | Waits for the call (≤ `CALL_TIMEOUT_S`), then `close_all` (D26). |
| A stuck test thread from an earlier Start press calls a device | Refused in the client (§6.3). |
| An answer over 16 MB | `error`: the operation ran, the result is too large; the connection stays open. |
| Every failure in today's `hal.md` *Failure* table | Same `DriverError` text reaches test code. |

## 11. Scripts and standalone use

```python
import pyhal

with pyhal.connect(bench="my_bench.ini") as hal:   # connect, or start a HAL
    print(pyhal.get_device("ssh1").execute("uname -r"))
# leaving the block: close_all; shutdown only if this script started the HAL (D38)
```

- **By hand:** `python -m pyhal --bench FILE [--port N] [--log-dir DIR]` starts a HAL in a
  console; it stays running until Ctrl+C or the console is closed (then it tears down, D27
  rule 1). PyPTS and scripts then connect to it.
- **A non-Python client** implements one TCP connection, JSON lines, `hello`, the seven
  request kinds, and skipping heartbeats while waiting (§7.3). `pyhal.md` documents them with
  examples.

## 12. What changes, what does not

- **Unchanged:** the driver contract and behaviour, device types and verbs, how test code
  calls a device, `close_all` at the end of a Start press, the teardown ladder and its
  timeouts, the Pipe protocol between the HAL and a driver process, the `DriverError` texts.
- **New:** `src/pyhal/` (server, client with connect-or-start, protocol layers,
  `python -m pyhal`); CORE's connection and non-fatal HAL heartbeat watch; the View → HAL
  window; HMI↔CORE status messages.
- **Moved:** the contents of `src/pypts/hal/` into `src/pyhal/`.
- **Removed:** `pypts.hal` (D11); `LocalSetup.from_ini()` (D12); `bench_sections()`; the
  Sequencer's `read_hardware_sections` seam in its current form (tests get a replacement,
  *builder's call*); `tear_down_abandoned_devices()` and `ABANDONED_DEVICES_TIMEOUT_S` as they
  are (D26).
- **Changed — and a behaviour change for the user to know:** PyPTS dying no longer tears
  devices down (D36). Today it does (the driver process's Pipe closes → `teardown()`).
  `usage_manual.html` and the migration notes say so.
- **Changed — code:** `core/core.py` (connect at startup, the HAL watch, the snapshot, the
  View → HAL answer, the active-client slot and `close_all` around a Start press with the
  next Start held until it is done, the close sequence and its budget — D41);
  `launcher/startup.py` (`CORE_SHUTDOWN_TIMEOUT_S`); `sequencer/sequencer.py` (no HAL code
  left: the `LocalSetup` `with` block, `read_hardware_sections`,
  `tear_down_abandoned_devices()` and `ABANDONED_DEVICES_TIMEOUT_S` go);
  `messages/core_sequencer_communication.py` (`ClosingDevices` goes — CORE shows the status
  itself); `step` docs (values are plain data, tuples become lists).

### 12.1 Repository housekeeping (same change)

- `.gitignore`: `!/src/pypts/hal/drivers/` (line 205) → `!/src/pyhal/drivers/`.
- `reuse.toml`: add `src/pyhal/**/*.py`; `pyhal.md` gets an inline header (reuse.toml covers
  only `README.md` and `docs/**/*.md`). CLAUDE.md's licence paragraph follows.
- `pyproject.toml`: packages `include` gets `pyhal`, `pyhal.*`; `[tool.mypy] files`
  `"src/pypts/hal"` → `"src/pyhal"` (line 196); ruff isort `known-first-party` gets `pyhal`
  (line 170).
- `DRIVER_FILE_MODULE_PREFIX = "pypts_driver_file_"` (`connection_driver.py:92`) → a `pyhal`
  name.
- `.gitlab-ci.yml`: no HAL path; nothing to change.

### 12.2 Tests to update or add

- Update: `tests/unit_tests/test_hal*.py`, `hal_test_drivers.py`, `test_sequencer.py`,
  `test_utilities.py` (`"pypts.hal.local_setup"`), `tests/conftest.py` (keep tests off the
  real `bench.ini` **and off the real HAL port** — tests use their own port), `test_core.py`,
  `tests/functional_tests/test_engine_in_process.py`, and the engine-starting tests
  (`test_api.py`, `test_headless.py`, `test_startup.py`,
  `tests/functional_tests/test_api_processes.py`).
- Add: "pyhal never imports pypts" (`tests/quality_tests/`); the kind-table coverage; the
  fence rules; connect-or-start (found / started / two starters / timeout); D36 (disconnect
  changes nothing) and D38 (shutdown only if started); the oversized-answer error; the
  non-fatal watch.

### 12.3 Documents to update (same change)

- `src/pypts/hal/hal.md` → `src/pyhal/pyhal.md`.
- `launcher/launcher.md`, `core/core.md`, `messages/messages.md`, `sequencer/sequencer.md`,
  `hmi/gui/gui.md`, `step/step.md`, `config_handler/config_handler.md`,
  `logger/logging_rules.md` (HAL lines now in the HAL's own log), `src/pypts/README.md`.
- Code-side text: `stream_handler/stream_session.py` docstring,
  `config_handler/bench_config.py` docstring, `config_handler/bench_template.ini`, the
  `No local setup is active ...` text (`local_setup.py:280-281`).
- `docs/Usage_manuals/`: `usage_manual.html` (the HAL as a standalone service, connect or
  start, View → HAL, D36's behaviour change, scripts), `quick_start.html`, `recipe_guide.html`,
  `pypts_implementation_status.html`, `how_to_write_a_driver.html` / `.md`,
  `migration_instructions.html`.
- Recipes: `resources/recipes/HAL_recipes/` (`hal_demo*`, `meteo_demo*`),
  `showcase_recipes/showcase_automated.yml`, `showcase_full.yml`.
- `CLAUDE.md`: module table, architecture block, process list (the HAL is a standalone
  process PyPTS connects to), messaging paragraph (the TCP link is outside the message layer).
  Existing CLAUDE.md drift (root paths of three manuals, a `spikes/**` glob reuse.toml lacks)
  is reported to the user, not fixed unasked.

## 13. Left to the builder

- Exact message fields, port number, option names, margins in §7.6.
- How driver processes are kept from being killed un-torn-down at HAL exit (§6.4).
- Detached-start details per OS, and the half-open-connection rule (§6.2, §6.4).
- Layout refinements inside `src/pyhal/`; log file naming.
- The test seam replacing `read_hardware_sections`; test strategy within the quality gates.

## 14. Known gaps that stay

- PyPTS dying leaves instruments as they are (D36, accepted).
- A call blocked inside a driver is not interrupted by Stop; `CALL_TIMEOUT_S` bounds it.
- A driver process stuck in a call ignores its Pipe closing (D29).
- Under D18, a second caller waits behind a request in progress.
- Large waveforms travel as JSON arrays; no side channel for bulk data.
- The working tree of `src/pypts/hal/` is uncommitted (D13), and its device-type verbs already
  differ from today's `hal.md` list; the plan reads the source.
