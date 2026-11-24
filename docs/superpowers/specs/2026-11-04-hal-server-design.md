<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# HAL server — design

Status: draft for review, **revision 5, 2026-11-23**. Branch `architecture_refactor`.

Revision 5 takes in every decision of the Claude Doc "HAL server — what is to be done"
(https://claude.ai/artifact/7HRP7hqmvsdCciJkS1DWe9, answered 2026-11-20), the three answers of
2026-11-23 (D56-D58), the fixes of the rev 4 review (Claude Doc "HAL server spec rev 4 — review
and decisions") and the code as it is after the teardown refactor (`9d056f4`). Revision 4 is in
git history (`db8edc6`).

What changed from revision 4, in one paragraph: **several clients may share one HAL** and its
devices; the HAL runs every request first in, first out. **The Sequencer closes a run's devices
again**, before `RunFinished`, as `LocalSetup` does today. **PyPTS sends `close_all` without
waiting for it**, on every close, crash close included. **No "HAL lost" state, no HAL heartbeat,
no shutdown budget:** a dead HAL shows up as a failed call. PyPTS reads the HAL's log file to get
its lines. The client sends a heartbeat instead, and the HAL drops a silent client.

Marked *Claude's call* = decided by Claude, for the user to check. Every row of the decision
table (§5) was decided by the user. *Review fix* = a fix from the review of revision 4.
*Review 5* = a fix from the review of this revision on 2026-11-23 (two reviewers: the spec
against the code, and safety and failure modes). Every finding of that review is fixed in
place; none needed a new decision.

## 1. Intent

Today the hardware layer (`src/pypts/hal/`, `hal/hal.md`) is a library inside the CORE process.
The Sequencer's `run_body()` wraps each run in `with LocalSetup(...)`; a `ConnectionDriver`
spawns one driver process per device and talks to it over a `multiprocessing` Pipe with pickled
tuples.

The redesign makes the HAL **a package of its own, `pyhal`, running as a standalone local
service, the HAL server**, reached over **TCP on localhost**. PyPTS connects to a HAL that is
already running, or starts one. Why:

- **Clarity.** One process owns the bench; every device call visibly goes to one place.
- **Standalone use.** The HAL is usable without PyPTS — by a Python script, and later by
  clients in other languages (LabVIEW, C#, ...). Later `pyhal` becomes its own distribution.
- **Independence.** The HAL lives on its own: PyPTS crashing does not take it down.
- **Visibility.** A developer can look at the HAL and the bench from the PyPTS GUI.

The framework stays **as small as possible**: fewer code paths beat fewer processes. The user's
rule for closing (2026-11-19): handle the standard close and a crash, nothing more.

## 2. Goals

1. The HAL server is a standalone process (`python -m pyhal`). PyPTS, at startup, connects to one
   that is running or starts one. With an empty bench it starts anyway, idle (D50).
2. One connect path for everyone: PyPTS and scripts both use `pyhal.connect()`.
3. Test code calls devices the same way: `get_device("x").operation(...)`, and the same test
   module runs under PyPTS and in a plain script. Only the import path changes (D11).
4. The driver contract unchanged: `BaseDriver`, the device types and their verbs, every shipped
   driver's behaviour. Only import paths change (D11). Value differences: §7.4.
5. Several clients at once — PyPTS and a script, say — on one HAL and the same devices (D51).
6. A run ends with its devices torn down, before `RunFinished`, as today (D42).
7. Every close of PyPTS that runs Python code sends `close_all` (D45).
8. A developer-only **View → HAL** window in the GUI: the HAL, the bench, two buttons (D49).

## 3. Non-goals

- **PyPTS killed outright** (terminated, power cut): nothing sends `close_all`; the HAL keeps
  every device as it is (D36).
- **Detecting a dead or frozen HAL ahead of a call**, restarting it, or keeping it alive (D47,
  D28).
- **Locking a device to one client** between calls (D52).
- **Device probing / live availability.**
- **A separate distribution now.** `pyhal` ships inside `pts-framework`.
- **Remote (non-localhost) access, authentication.** Anyone on the machine can reach the port.
- **Streams** (D33).
- **A rich panel.**

## 4. Anti-goals — failure even if it works

- A **normal** close of PyPTS, or a crash close, that does not send `close_all`.
- A run that ends with a device it opened still open, when the HAL is alive.
- A device handle from an earlier run reaching a device again.
- Pickle on the TCP link (a remote-code-execution hole, and Python-only).
- A protocol that cannot be swapped without touching the architecture.
- Two code paths: one for "PyPTS started the HAL", one for "it was already running".
- `pyhal` importing `pypts`.

## 5. Decisions (made by the user)

Superseded decisions are struck through in place, so the trail stays. D42-D55 are the rows of
the "what is to be done" doc (its row id in brackets); D56-D58 were answered on 2026-11-23.

| # | Decision |
|---|---|
| D1 | One HAL server process. |
| D2 | TCP on localhost. |
| D3 | ~~Exactly one client at a time~~ → superseded by D51. |
| D4 | One driver process per device, **inside** the HAL server (crash isolation stays). |
| D5 | ~~`close_all` when a press ends~~ → superseded by D42. A device opens on the first `get_device()`. No probing. |
| D6 | HAL death is accepted, not prevented. |
| D7 | Protocol language-neutral, **dead simple for now**, easy to change later. |
| D8 | View → HAL panel: plain, developer-facing, HAL status and device status. ~~Read-only~~ → two buttons, D49. |
| D9 | The `pyrade_xy_graph` pattern: **`src/pyhal/`**, a separate top-level package shipped in the `pts-framework` distribution for now, later its own package and a dependency. |
| D10 | One place for configuration: `bench.ini` stays beside `config.ini`, and `config_handler` keeps owning where it lives. `pyhal` logs with plain Python logging and reads the bench INI file it is given. |
| D11 | Package name `pyhal`. **Rename everything, no shim:** `pypts.hal` disappears. Drivers import `from pyhal import PSU`; bench.ini names `driver = pyhal.drivers.ssh.SshDriver`. Users edit their own bench.ini and driver files (usage manual, migration notes). |
| D12 | **Scripts:** the in-process `LocalSetup.from_ini()` mode is removed; scripts use `pyhal.connect()`. |
| D13 | ~~Plan from the uncommitted working tree~~ → obsolete: the HAL is committed; plan from the code as it is. |
| D14 | ~~Free port + token~~ → superseded by D37. |
| D15 | **NaN, infinity and bytes are encoded** in small tagged forms (§7.4). |
| D16 | **HAL log:** the HAL always writes its own log file: `--log-dir`, default a fixed per-user folder of `pyhal`'s own. |
| D17 | **Test code on the Sequencer's worker thread uses the `pyhal` client directly**, as it uses the Pipe today. The HAL link stays outside the message layer. |
| D18 | **One request at a time per connection** (no request ids). A second caller on the same connection waits behind the request in progress; threads in test code take turns. |
| D19 | ~~HAL heartbeat on the connection~~ → superseded by D47 and D53. |
| D20 | ~~The heartbeat carries the panel snapshot~~ → superseded by D47: View → HAL asks with a `status` request (§8). |
| D21 | **HAL cannot be reached or started → PyPTS starts anyway**, with a warning; every `get_device()` fails with the reason. |
| D22 | **The HAL knows devices and clients, not runs.** A run (one press of Start) stays a PyPTS idea. Requests: §7.3. |
| D23 | ~~Start order with the launcher waiting~~ → superseded by D37. |
| D24 | **CORE connects at startup** and keeps the connection for the session. |
| D25 | **Bench read once per HAL start**; an edit applies when the HAL is restarted. |
| D26 | ~~Closing waits for a stuck call~~ → superseded by D45. |
| D27 | **Safety rule:** the HAL never exits through a path Python can observe without tearing down every open device (§6.5). ~~(2) owner gone → tear down~~ (D36). ~~(3) PyPTS logs "may still be energised" when the `close_all` answer never arrives~~ (D47: PyPTS does not wait for it). |
| D28 | **HAL death:** device calls fail with a `DriverError` through the normal step-error path. Devices come back after restarting PyPTS. No automatic restart. ~~PyPTS shows the HAL lost~~ (D47). |
| D29 | **Accepted gap:** a driver process stuck inside a call does not notice the HAL dying; its teardown runs when the call returns. |
| D30 | **Sending takes plain Python:** `send("close_all")`, `send("call", device=..., operation=...)`; the send function does all wrapping and encoding. |
| D31 | ~~No protocol version~~ → superseded by D48. |
| D32 | **Message size limit 16 MB** (about 700-800k float samples in a waveform). |
| D33 | **Streams are out of this design**; a driver's own rule. A later `stream` message kind fits the protocol. A driver process cannot reach CORE's `StreamSession`. |
| D34 | ~~Abandonment = dropping the connection~~ → superseded. |
| D35 | ~~Refuse new clients after a failed release~~ → removed. |
| D36 | **Client gone → the HAL does nothing to the bench.** A client that disconnects or is dropped (D53) leaves every device exactly as it is. *Consequence, accepted:* PyPTS killed outright mid-test may leave an instrument energised until someone closes it (D49's buttons, `--close-all`). |
| D37 | **Connect or start.** `pyhal.connect()` tries the port: a HAL there → use it; none → start `python -m pyhal --bench <file> --port <port>` **detached** (it survives its starter), wait until it listens, connect. No token, no free port. |
| D38 | **On a close, stop the HAL only if this client started it** (`close_all`, then `shutdown`). One that found the HAL running sends `close_all` and leaves it running. |
| D39 | ~~A different bench file: WARNING~~ → widened by D48. |
| D40 | **Leftover open devices** (after a crash): `get_device()` reuses them; nothing is switched off automatically. When to warn: §6.2. |
| D41 | ~~CORE owns every HAL operation~~ → superseded by D42 (the Sequencer owns the run's devices) and D45 (CORE owns connect and the close). |
| D42 | [Q1] **The Sequencer closes a run's devices** after the teardown steps, before the run log closes and before `RunFinished`: `with pyhal.run_scope():` in place of today's `with LocalSetup(...)`. It closes them even when another client is using one (B). |
| D43 | [Q2] **A HAL this PyPTS started is stopped when PyPTS closes:** `close_all`, then `shutdown` (D38), even with other clients connected (C). |
| D44 | [Q3, + 2026-11-23] **A driver process that dies, or is killed because a call ran past `CALL_TIMEOUT_S`:** the HAL runs the rescue teardown at once, and the device is closed. The next request for it opens it again. **A driver method that raises:** `DriverError`, the device stays open, as today. |
| D45 | [Close] **Orderly close:** CORE sends `close_all` after `SequencerStopped` and does not wait. **Crash close:** `close_all`, then the Stops. The client half-closes the socket after sending. A standalone HAL runs `close_all` before it exits. **The HAL crashing:** nothing; the next call raises `DriverError`. |
| D46 | [2] **PyPTS gets the HAL's log lines by reading the HAL's log file as it grows**; nothing goes over the client connection. |
| D47 | [3, 4, 5] **No "HAL lost" state, no shutdown budget.** The HAL finishes a `close_all` it received, even after its client has gone, and logs what it could not tear down. |
| D48 | [6] **A running HAL with a different version or bench file:** WARNING, and PyPTS uses it. `hello` carries the version. |
| D49 | [7] **Stopping a standalone HAL:** `python -m pyhal --close-all` and `--stop`, and two buttons in View → HAL. |
| D50 | [8] **Empty bench:** an idle HAL starts anyway; tests get a seam to use their own HAL or none. |
| D51 | [9] **One HAL per machine.** Several clients can be connected at the same time and use the same device. `close_all` and `shutdown` from any client act on everything, cutting the others off (C). |
| D52 | [D] **The HAL queues the requests and runs them one at a time, in arrival order**; nothing locks a device between calls. |
| D53 | [10] **Client watchdog:** the client sends a beat every 1 s; the HAL drops a client silent for 5 s and leaves the bench as it is. |
| D54 | [11] **A script that skips `with pyhal.connect(...)`:** `atexit` sends `close_all`, plus `shutdown` if it started the HAL. |
| D55 | [12] **The one-device `close` request stays;** test code gets `close_device(device)`. |
| D56 | [A, + 2026-11-23] **One fixed port for all clients;** the HAL refuses to start if the port is taken. No pool. **Not a `config.ini` key:** a default in `pyhal`, a `--port` option, a `connect()` argument; `CONFIG_VERSION` untouched. |
| D57 | [2026-11-23] **No client-side deadline.** A client waits for its answer until it comes or the connection closes. The HAL bounds every driver call (`CALL_TIMEOUT_S`); a busy HAL is slow, not wrong. |

## 6. Architecture

```
 PyPTS (launcher, Logger, CORE, frontend)          a script            View → HAL, --stop
        │ pyhal.connect()                             │ pyhal.connect()        │ short connections
        └────────────── TCP 127.0.0.1:<fixed port> ───┴────────────────────────┘   (many clients)
                                │
                       HAL server (standalone, detached)
                         ├── one connection thread per client  (reads, beats, status)
                         ├── the request thread: one FIFO queue, one request at a time
                         ├── Pipe ──> driver process "Device ssh1"
                         └── Pipe ──> driver process "Device psu1"
```

### 6.1 Who does what

- **The HAL server** owns the bench. It reads the bench file at start, opens a device on the
  first `open` (or `call`) for it, keeps it open until `close` / `close_all` / a rescue (D44) /
  its own exit, and serves any number of clients. Clients come and go; devices stay (D36).
- **Inside the HAL server, today's machinery moves across nearly as-is:** spawning driver
  processes, the pickle Pipe protocol, `CALL_TIMEOUT_S`, the teardown ladder with its rescue,
  recover. The Pipe stays pickle; it never leaves the HAL. One change: D44.
- **`pyhal`'s client** (`client.py`) is one object per process, made by `pyhal.connect()`. It
  holds the **long connection** test code uses, a beat thread (D53) and the log tail (§9). `get_device()`, `recover_device()`, `device_info()`, `close_device()` and
  `run_scope()` are module functions of `pyhal` that use the process's connected client.
- **CORE** connects at startup (D24) through a small `core/hal_link.py`, on a worker thread of
  its own, never on its event loop (review fix for B3: connect-or-start can take
  `HAL_START_TIMEOUT_S`, the frontend gives up on a CORE silent for `HEARTBEAT_FATAL_S` = 15 s).
  It owns the close (D45) and View → HAL (§8). Each of CORE's own requests — `close_all`,
  `shutdown`, `status` — goes on a **short connection of its own**, so it never waits behind a
  test call holding the long connection (D18). *Claude's call.* A short connection: connect
  only, never start (1 s timeout); **read `hello` first** (1 s), so no unread data is waiting
  when the socket closes; send **one** request; then either read its answer, or half-close
  (`shutdown(SHUT_WR)`) and close without reading (review 5).
- **The Sequencer** wraps each run in `with pyhal.run_scope():` (D42), where `LocalSetup` is
  today. It never connects, and holds no HAL object: it uses the module function. *Claude's
  call*, so no module calls another (CLAUDE.md: modules never call each other).
- **Test code** on the Sequencer's worker thread, and threads it starts, gets a **device
  handle** from `pyhal.get_device()`. A call on the handle is a request on the long connection.
  The handle keeps today's surface: `__getattr__` turns a name among the device's operations
  into a call, and any other name raises `AttributeError` without a round trip (the `opened`
  answer carries `device_type` and `operations`).

### 6.2 Connect or start (D37)

1. `pyhal.connect(bench=..., port=DEFAULT_PORT, log_sink=None)` connects to `127.0.0.1:<port>`.
2. **A HAL answers** → `hello` (§7.2). The client compares:
   - the version (D48) and the bench file (path after `os.path.normcase(os.path.realpath())`,
     and a SHA-256 of its bytes, so an edited `bench.ini` counts as different — *Claude's
     call*): a difference is a WARNING naming both, and the client uses the HAL anyway;
   - the open devices: a WARNING listing them **only when no other client is connected**
     (`hello` carries the count), since with other clients they are theirs, not leftovers
     (D40, *Claude's call*); otherwise DEBUG. The count is of connections that have sent a
     `beat` or a request other than `status`: one that only polls `status` (the HAL monitor
     window) is not a client using the devices (phase 3 final review, 2026-11-23).
3. **Nothing answers** → the client starts `python -m pyhal --bench <file> --port <port>`
   detached, passing its own `sys.path` so dotted driver paths resolve as today, then retries
   the connection until `HAL_START_TIMEOUT_S` (15 s).
   - Windows: `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, not `DETACHED_PROCESS`, so the
     driver processes do not open console windows an operator can close (review fix).
   - Linux: `start_new_session=True`.
   - stdout/stderr go to a startup file in `--log-dir`; when the HAL fails to start, the
     client's error quotes its tail (review fix).
4. **"I started it"** (D38): the client passes a one-time random **start nonce**
   (`--nonce`) to the HAL it starts, and `hello` echoes it. A pid does not work: on Windows a
   `.venv`'s `python.exe` is a redirector that runs the real interpreter as a child, so the
   spawned pid never matches (review 5). The nonce also settles **two starters at once**: both
   start a HAL, the second cannot bind the port and exits (D56), both connect to the first; only
   its starter's nonce matches.
5. **The wait for `hello`** is a handshake, not an answer, so D57 does not apply: it is bounded
   by `HAL_START_TIMEOUT_S` on the long connection, 1 s on a short one. Something on the port
   that accepts and stays silent is "not a HAL".
6. **A HAL that is shutting down** (a `shutdown` is queued or running) answers a new connection
   with an `error` (origin `hal`, `the HAL server is shutting down`) instead of `hello`, and
   keeps its listener until it exits, so no second HAL can bind while the first is still
   tearing down. `connect()`, on that error, retries until the port is free, then starts a HAL,
   bounded by `HAL_SHUTDOWN_WAIT_S` (builder sizes it above a few close ladders). This is what
   File → Restart hits: the old CORE has just sent `shutdown` (review 5).
7. **Timeout, or no `hello`** → D21: PyPTS starts anyway; `get_device()` raises the reason. No
   retry later in the session (D28).
8. **While the startup connect is still running** (on `hal_link`'s worker thread),
   `run_scope()` waits for it to finish, bounded by the same timeouts, then goes on or raises
   the D21 reason. A headless run starts at once, so this case is ordinary (review 5).

### 6.3 A run and its devices (D42)

A *run* is one press of Start: the top-level sequence, every sequence it calls, and the teardown
steps (`Sequencer.execute_sequence()` → `run_body()`). The HAL never sees it.

- `run_body()` today: `with LocalSetup(self.read_hardware_sections):` around
  `run_sequence_body()`. Rev 5: `with pyhal.run_scope():` in the same place. The run log closes
  (`end_run_log()`) and `RunFinished` goes out after it, exactly as today.
- **`run_scope()` on entry** fills the process's **active-scope slot** (successor of today's
  `_active_setup`), raising the scope counter.
- **`get_device(name)`** inside the scope sends `open` (which opens, or reuses an open device),
  and records the name in the scope. Outside a scope it raises, as today
  (`No local setup is active. ...`, reworded: `get_device() works in test code PyPTS is
  running, or inside 'with pyhal.connect(...)' in a script of your own.`).
- **`run_scope()` on exit:** (1) clear the slot and raise the counter — no lock needed, so a
  polling test thread cannot delay it (review fix for B4); (2) send `close` for each device the
  run asked for, newest first, each waiting for its answer, so the teardown lines are in the run
  log (B1); (3) drain the log tail synchronously (§9). Never raises; a failed close is logged as today's
  `Device 'x' did not close: ...`.
- **The fence** (anti-goal 3): each handle remembers the counter it was made under. Every request
  from a handle compares it with the client's counter **in the same step as the send, under the
  long connection's lock**. A stale handle raises locally: `Device 'x' belongs to a run that has
  ended; call get_device('x') again.` The HAL never produces it. The `open` inside
  `get_device()` is fenced the same way (closes B4's first hole).
- **Another client using the same device** (D42 B, D51): the run's `close` tears it down anyway.
  That client's next call opens the device again (D44's rule: the next request for a closed
  device opens it).
- **A script:** `pyhal.connect(...)` opens a scope itself, `with` or not, so a script that
  skips `with` still gets devices (D54, review 5). Leaving the `with`, `hal.close()` or the
  `atexit` ends it: the same close as PyPTS's (§6.4), not per-device closes. CORE's
  `connect()` passes `scope=False`; the Sequencer's `run_scope()` is PyPTS's scope.
- **Not fenced (gap, `pyhal.md` says so):** the active-scope slot is one per process, as
  `_active_setup` is today. A thread that test code started in run 1 and that calls
  `pyhal.get_device("x")` again during run 2 gets a valid handle of run 2. The fence covers
  handles, which is what anti-goal 3 asks.

### 6.4 Closing (D45, D47)

| Event | PyPTS | HAL server |
|---|---|---|
| A run ends | `run_scope()` closes the run's devices (§6.3) | Tears each down with today's ladder |
| Orderly close (GUI close, CLI `exit`, `Pts.close()`) | The Sequencer finishes the run as today (`sequencer.md` *Stop*). On `SequencerStopped`, CORE runs **the close** (below) and carries on without waiting | Finishes the `close_all` even after the client has gone (D47) |
| Crash close (`close_at_once()`: CLI Ctrl+C, the launcher's `stop_core()`, CORE's watchdog) | CORE runs **the close** first, then sends the Stops, then exits | Same. A call already running finishes first (D52), bounded by `CALL_TIMEOUT_S` |
| PyPTS killed outright | Nothing | Nothing (D36) |
| A script's `with` ends, `hal.close()`, or `atexit` (D54) | The close (below) | Same |
| The HAL crashes | Nothing; the next call raises `DriverError` (D28) | Its driver processes see their Pipe close and run `teardown()` (D29) |
| The HAL is stopped (`shutdown`, Ctrl+C, its console closed, `--stop`, the View → HAL button) | — | Tears down every open device, then exits (D27) |

- **The close** (`hal_link.close()`, the same for both closes and for a script — review 5):
  1. Raise the scope counter and **close the long connection**. The HAL drops a disconnected
     client's queued `open` / `call` / `recover` / `info` (§7.5), so a teardown step or a test
     thread still running in a crash close cannot reopen a device behind the `close_all`
     (D44 would otherwise reopen it on its next call).
  2. If the startup connect is still running, wait for it (§6.2 step 8). No HAL → nothing to
     send.
  3. Send **one** request on a short connection: `shutdown` if this PyPTS started the HAL
     (`shutdown` runs `close_all` itself), otherwise `close_all`. Do not wait for its answer.
  4. **On the closing thread itself**, never handed to a worker: CORE's threads are daemons
     and `close_at_once()` leaves at once, so a send on another thread could die unsent.
     Bounded by the 1 s connect and the 1 s `hello`.
- **Sending without waiting is safe only with three rules:** the HAL finishes a `close_all` it
  has read, even after the client has gone (D47); the client reads `hello` before it sends; and
  it half-closes after sending (`shutdown(SHUT_WR)`, then close). Closing a socket with unread
  data waiting makes the OS reset the connection, and the reset can drop the request still in
  the HAL's receive buffer.
- **No shutdown budget changes:** `CORE_SHUTDOWN_TIMEOUT_S` (30 s, `launcher/startup.py`) and
  CORE's deadline-free closes (`core/core.md`, *Shutdown choreography*) stay as they are.
- **The crash close's CRITICAL** (`BENCH_MAY_BE_ENERGISED`, logged by `close_at_once()` with a
  run open, and by `end_run_for_silent_module()` before it) **stays as it is**: PyPTS does not
  wait for the `close_all`, so "may still be energised" stays true (review 5 dropped rev 5's
  rewording). Only its code comment, which says the driver processes end with CORE, changes.
- **Cutting other clients off** (D51 C): a `close_all` or `shutdown` from PyPTS also closes the
  devices a script is using, and `shutdown` ends its connection. Accepted.

### 6.5 The HAL's own exit (D27)

- Every exit path Python can observe — `shutdown`, Ctrl+C, console close (`CTRL_CLOSE_EVENT` on
  Windows, `SIGTERM`/`SIGHUP` on Linux), an uncaught exception in any server thread — first
  tears down every open device, newest first, then exits. **The death of any server thread is
  fatal:** teardown, then exit (review fix).
- **One thread owns the exit teardown, and it never runs beside a request** (review 5): two
  threads on one driver Pipe would corrupt it. The exit path stops accepting new clients (§6.2
  step 6), empties the queue of everything but the `close_all` / `shutdown` that caused it,
  and lets the request thread finish the request it is running (≤ `CALL_TIMEOUT_S`). The
  request thread then runs the teardown. If the request thread itself is what died, the main
  thread runs it; nothing else touches a driver then.
- A second Ctrl+C during that teardown does not abort it (review fix).
- Driver processes must not be ended by `multiprocessing`'s exit-time terminate of daemon
  children: today they are `daemon=True` (`ConnectionDriver._start()`), which on a clean parent
  exit kills them without `teardown()`. How is the builder's call.
- Driver processes ignore Ctrl+C, as today (`driver_process_main()` calls
  `ignore_keyboard_interrupt()`).
- **Not covered, listed as gaps:** `TerminateProcess` / `SIGKILL`, logoff of a detached HAL,
  a job-object close. Then D29 applies. **Only partly covered:** closing the console of a HAL
  started by hand — Windows kills the process about 5 s after `CTRL_CLOSE_EVENT`, less than
  one close ladder (review 5).
- **The port after exit** (review 5): the HAL closes its listener last, after the teardown
  (§6.2 step 6). On Linux it binds with `SO_REUSEADDR`, which still allows only one listener,
  so connections the HAL closed (in TIME_WAIT) do not block the next HAL's bind. On a
  `shutdown` it sends `bye` and lets the client close first.

### 6.6 Inside `pyhal` (*Claude's proposal*)

| File | Holds | From |
|---|---|---|
| `base_driver.py`, `device_types.py`, `drivers/` | the driver contract, shipped drivers | moved, imports renamed |
| `driver_process.py` | one device's process: spawn, Pipe, timeouts, teardown ladder, rescue, recover; D44's rescue on death or timeout | today's `connection_driver.py`, minus the test-code-facing surface |
| `devices.py` | open devices by name: open on first request (or reuse), `close`, `close_all` newest first | today's `local_setup.py`, minus everything run-related |
| `protocol/` | `messages.py` (typed requests/answers, the kind table), `values.py` (value domain, tagged forms, validator), `codec.py` (JSON lines) | new |
| `server.py` | TCP listener, connection threads, the request queue and thread, the client watchdog, teardown on every exit | new |
| `client.py` | `connect()` (connect or start), the long connection, the beat thread, device handles, the scope and its fence, the log tail, `get_device()` / `recover_device()` / `device_info()` / `close_device()` / `run_scope()`, `atexit` (D54) | new + today's `device_control.py` |
| `bench.py` | reads a bench INI file (format only); `anchor_driver_files()` | split from today's `local_setup.py` |
| `__main__.py` | `python -m pyhal` (§11) | new |

The builder may refine names and splits; the responsibilities stay as listed.

## 6a. Packaging — the `pyrade_xy_graph` pattern

- `src/pyhal/`, beside `src/pypts/` and `src/pyrade_xy_graph/`, added to
  `[tool.setuptools.packages.find] include` in `pyproject.toml`.
- **It never imports `pypts`**, enforced by a test in `tests/quality_tests/`. Today's HAL imports
  `pypts` in three places: `pypts.logger.log.log` (`connection_driver.py`, `local_setup.py`)
  becomes `logging.getLogger(__name__)`; `ignore_keyboard_interrupt` (`pypts.utilities.common`,
  in `connection_driver.py`) gets a copy in `pyhal`; `bench_sections()` (`local_setup.py`, the
  lazy `pypts.config_handler` import) goes — the HAL reads the bench file itself (§9).
- **`pyhal/__init__.py` stays import-light:** a driver's `from pyhal import PSU` runs in every
  driver process and must not pull in socket or client code. The client names
  (`connect`, `get_device`, `run_scope`, `DEFAULT_PORT`, ...) are reached through a module-level
  `__getattr__` that imports `client.py` on first use (review 5).
- **The version** in `hello` (D48) is `importlib.metadata.version("pts-framework")` for now (the
  distribution's version, from setuptools-scm), never `pypts._version`.
- **Our own code**, unlike `pyrade_xy_graph`: no `DEVIATIONS.md`, under every quality gate.
- **What stays in `pypts`:** `core/hal_link.py` (connect at startup, the close, `status` and the
  two buttons for View → HAL, the log sink), the `run_scope()` line in the Sequencer, and the
  View → HAL window in the GUI.
- Its context file `src/pyhal/pyhal.md` (inline SPDX header) replaces `src/pypts/hal/hal.md`.

## 7. Protocol (public, TCP)

### 7.1 Three layers, one seam (*Claude's call*, so D7's "easy to change" holds)

1. **Typed messages:** a dataclass per request and answer with a `kind` discriminator, one union
   per direction (`ClientToHal`, `HalToClient`), handled with `match` closed by `unhandled()`
   (CLAUDE.md convention). `pyhal` carries its own small `unhandled()` and a TRACE line per
   send/receive.
2. **The value domain:** one recursive `PlainValue` type and one validator that names the path
   of anything outside it.
3. **The codec:** JSON, one object per line (UTF-8, `\n`), `allow_nan=False` on output, and
   `NaN`/`Infinity` refused on input; deep nesting or huge integers count as a malformed line
   (review fix). Swapping the codec touches only this layer.

**Sending (D30):** `send("close_all")`, `send("call", device="psu1", operation="output_off")`.
`send()` looks the kind up in one `kind → dataclass` table and builds the dataclass at once (a
misspelt kind or field raises before anything is encoded), validates and encodes. A test checks
the table covers both unions.

Example exchange:

```
client → HAL  (connects)
HAL → client  {"kind":"hello","pid":4120,"nonce":"c41d...","version":"0.9.1","bench":"C:\\...\\bench.ini","bench_sha256":"9f2c...","log":"C:\\...\\pyhal\\hal.log","open":["psu1"],"clients":1}
client → HAL  {"kind":"beat"}
client → HAL  {"kind":"open","device":"psu1"}
HAL → client  {"kind":"opened","device":"psu1","device_type":"PSU","operations":["measure_voltage","output_off"]}
client → HAL  {"kind":"call","device":"psu1","operation":"measure_voltage","args":[1],"kwargs":{}}
HAL → client  {"kind":"result","value":12.03}
```

### 7.2 Connection and handshake

- **Bind** to `127.0.0.1` only, on the fixed default port (D56; `--port` overrides it). On
  Windows bind with `SO_EXCLUSIVEADDRUSE`, never `SO_REUSEADDR`. The port taken → the HAL exits
  with an error naming it.
- **Handshake:** the server's first message is `hello`: pid, the start nonce it was given (or
  null), version, the absolute path of its bench file and its SHA-256, the path of its log file
  (§9), the devices it has open, how many other clients are connected. A HAL shutting down sends
  an `error` instead (§6.2 step 6).
- **Maximum message size: 16 MB** (D32). An answer that would exceed it is not sent: the HAL
  answers with an `error` (origin `hal`, `'op' ran, but its result is too large to send: N
  bytes.`) and the connection stays open. The client refuses an oversized **request** itself,
  before sending, and keeps the connection (review fix). Only a malformed or oversized line
  *arriving* at either end closes the connection.
- **An answer goes only to the connection its request came in on** (review fix): a client that
  reconnects never receives an older connection's result.

### 7.3 Requests and answers

- **One request outstanding per connection** (D18), no request ids. The HAL sends nothing
  unprompted after `hello`: there is no HAL heartbeat (D47). A client therefore reads exactly
  one answer per request (none for `beat`).
- **Requests (D22, D55):**

| Request | Answer | Queued (D52) |
|---|---|---|
| `open` (device) | `opened` (device type, operations); opens or reuses | yes |
| `call` (device, operation, args, kwargs) | `result`; opens the device first if it is closed (D44) | yes |
| `recover` (device) | `recovered` | yes |
| `info` (device) | `info` (device type, operations, is open) — a round trip now, new | yes |
| `close` (device) | `closed` | yes |
| `close_all` | `closed_all`, listing every device **not** torn down — new | yes |
| `shutdown` | `bye`, after `close_all`; then the HAL exits | yes |
| `status` | `status` (§8) | **no**: answered by the connection thread |
| `beat` | none | **no**: only resets the watchdog (D53) |

- **The queue (D52):** one queue for all clients, one request thread, first in first out.
  Nothing locks a device between two requests, so two clients' calls to one device interleave
  request by request. `close`, `close_all` and `shutdown` wait their turn like any request.
- **Errors carry an origin:**
  - `driver` — the driver raised; the client formats today's `Device 'x': 'op' failed: Type:
    message`;
  - `hal` — the HAL produced the whole message (timeout, stopped unexpectedly, not configured,
    could not be opened, cannot be sent, too large, shutting down); raised verbatim. (A HAL
    whose port is taken exits before it can answer anyone; the starter sees it in the startup
    file's tail.)
  - `protocol` — malformed request, value outside the domain, unknown kind; raised as
    `DriverError("HAL protocol error: ...")` and logged at ERROR.
  - The stale-handle refusal is produced in the client (§6.3), never by the HAL.
- The test-code-facing `DriverError` texts in today's `hal.md` *Failure* table are kept. New:
  the connection closing while a request waits → `DriverError("The HAL server closed the
  connection while 'op' on device 'x' was running.")`; that connection is not reopened (D28).

### 7.4 The value domain (D15)

- JSON-native values: numbers, strings, booleans, null, lists, objects with string keys.
- **Tagged forms:** `{"$float": "nan" | "inf" | "-inf"}`, `{"$bytes": "<base64>"}`, decoded back
  to `float` / `bytes`. A dict key starting with `$` is refused, so a driver's own dict is never
  mistaken for one.
- A **tuple arrives as a list** — a behaviour change for test code (`step/step.md` says so).
- **Refused, with a `DriverError` naming the path:** non-string dict keys, numpy values (the
  validator checks exact types — `numpy.float64` subclasses `float`), custom objects. An argument
  is refused in the client before anything is sent; a return value is refused in the HAL
  **after the operation ran**, and the text says so.
- Integers beyond 2^53 lose precision for non-Python clients; `pyhal.md` says so.

### 7.5 Threads

- **HAL server:**
  - an **accept thread**;
  - **one connection thread per client:** reads lines, answers `status`, resets the watchdog on
    `beat` (and on any line), puts every other request on the queue;
  - **the request thread:** takes the queue first in first out, runs one request, writes the
    answer to the connection it came from;
  - **the watchdog** (D53): a client silent for `CLIENT_SILENCE_S` (5 s) is dropped. A client
    with a request queued or running is never counted as silent: it is waiting for the HAL, not
    frozen, so a short connection that waits 50 s for `closed_all` is not dropped (review 5).
  - **A client that is gone** — dropped, or its connection closed or reset: its queued
    `open` / `call` / `recover` / `info` are removed; a request of its that is already running
    finishes and its answer is discarded; its queued `close`, `close_all` and `shutdown` stay
    and run (D47). The bench is left as it is (D36). *Claude's call* on what stays queued; the
    close relies on it (§6.4 step 1).
  - Socket writes go through one lock per connection, held for one line.
- **Client:** two locks on the long connection (review 5). The **request lock** is held by
  whoever sends a request until its answer arrives (D18); the fence check happens under it
  (§6.3). The **write lock** is held for one line only, by a request's send and by the beat
  thread; the beat thread never takes the request lock, so beats go on during a long call. The thread that sent the
  request reads its answer itself: the HAL sends nothing unprompted, so no reader thread is
  needed (rev 4 had one for the HAL's heartbeats). A closed connection ends that read with
  `DriverError` (§7.3). One **beat thread**: `beat` every `CLIENT_BEAT_S` (1 s), under the write
  lock alone. One **log tail thread** (§9).
- **No client-side deadline** (D57): a wait ends with the answer or with the connection closing.

### 7.6 Timeouts

All HAL constants live in `pyhal` (today in `connection_driver.py`: `STARTUP_TIMEOUT_S` 30 s,
`CALL_TIMEOUT_S` 30 s, `EXIT_TIMEOUT_S` 5 s, `RESCUE_TIMEOUT_S` 10 s, `LIVENESS_POLL_S` 0.2 s).
They bound the HAL's work, not the client's wait:

| What | Bound |
|---|---|
| One driver call, `connect()` and `teardown()` included | `CALL_TIMEOUT_S` |
| A driver process saying hello | `STARTUP_TIMEOUT_S` |
| One close ladder | teardown (`CALL_TIMEOUT_S`) + `EXIT_TIMEOUT_S` + rescue (`RESCUE_TIMEOUT_S`, plus its own `EXIT_TIMEOUT_S` join): about 50 s (review fix: not 45) |
| Connect-or-start, and the long connection's `hello` | `HAL_START_TIMEOUT_S` (15 s) |
| Waiting for a HAL that is shutting down to free the port (§6.2 step 6) | `HAL_SHUTDOWN_WAIT_S` (builder sizes it) |
| A short connection's connect, and its `hello` | 1 s each |
| Client watchdog | `CLIENT_BEAT_S` 1 s, `CLIENT_SILENCE_S` 5 s |

A request waiting in the queue is bounded only by the requests ahead of it (D52, D57).

## 8. View → HAL panel

- A new item **HAL** in the GUI's **View** menu (`hmi/gui/gui.py`, beside *Appearance* and *Full
  Screen*), opening a small plain window. Nothing HAL-related elsewhere in the GUI.
- **Shows** (from the `status` answer): the HAL — connected / not reachable (D21), pid, version,
  bench file, log file, whether this PyPTS started it, how many clients are connected, what the
  request thread is running and since when, how many requests are queued; one row per device on
  the bench — name, device type (once known), state (*configured* / *open* / *failed* with its
  last error).
- A **Refresh** button; no polling.
- **A standalone monitor exists** (user decision 2026-11-23): `python -m pyhal.monitor`
  (`src/pyhal/monitor/`, a PySide6 window with its own connections to the HAL, built outside
  PyPTS; `pyhal.md`, *The monitor*). It polls `status` every second and has Close all, Stop,
  Start and a log view. In phase 4 *View -> HAL* may open that window instead of building the
  panel described here.
- **Two buttons (D49):** *Close all devices* (`close_all`) and *Stop HAL* (`close_all`, then
  `shutdown`, which runs `close_all` itself). Both disabled while a run is open; CORE refuses
  them then too, and holds a `StartSequence` while a button request is still being sent, so the
  button's `close_all` cannot land after the next run's first `open` (*Claude's call*, review 5:
  closing the devices under a running test is what the run scope is for). After *Stop HAL*,
  `get_device()` fails until PyPTS is restarted (D28).
- **Data path:** GUI → CORE, new request/answer pairs on the HMI↔CORE link
  (`messages/core_hmi_communication.py`, `messages/messages.md`, routing in `core/core.md`).
  CORE's `hal_link` sends `status` / `close_all` / `shutdown` on a short connection, off the
  event loop, and answers the HMI with plain data (pickle-safe). `status` is answered by the
  HAL's connection thread, so Refresh never waits behind a device call.

## 9. Configuration, bench data and logs

- **`bench.ini`** stays beside `config.ini` (D10). PyPTS passes its **path** to
  `pyhal.connect()`; the HAL reads the file itself with `bench.py`, anchoring relative driver
  files to the file's folder (today's `anchor_driver_files()`, moved). `config_handler` keeps
  owning the path and its discarded-file check: when PyPTS's `bench.ini` was discarded at
  startup, CORE does not connect, and `get_device()` raises today's text (`bench.ini was
  discarded at startup, so this start has no devices: ...`).
- **The port (D56)** is `pyhal.DEFAULT_PORT`, a `--port` option and a `connect()` argument, not a
  `config.ini` key, so `CONFIG_VERSION` is untouched. PyPTS uses the default.
- **The HAL log (D16):** the HAL process writes its own log file in `--log-dir` (default: a fixed
  per-user folder of `pyhal`'s own), with the standard library only. Technician lines keep
  today's text (`Device 'x' connected.` ...). Driver processes' records reach it as today.
  The format is the builder's call, with two constraints: each record's level can be read back,
  and a multi-line record (a traceback) can be told from the next record.
- **PyPTS reads that file (D46).** `hello` names it. The client's log tail thread starts at the
  file's end at connect time, reads new records every `LIVENESS_POLL_S`-like interval, and hands
  each to the `log_sink` given to `connect()`. CORE's sink re-logs it through PyPTS's log at its
  own level, as `HAL: <message>` (*Claude's call* on the prefix). `run_scope()`'s exit drains the
  tail to the file's end **before** it returns, so a run's teardown lines land in that run's log
  (the HAL writes a request's lines before it sends the answer). A script passes no sink: it
  reads nothing.
- **Why the drain works, and what it needs** (checked in review 5): the sink re-logs inside
  CORE, and `end_run_log()`'s message and log records go to the Logger on one queue, in order.
  So a line re-logged before `end_run_log()` lands in the run log, given three rules:
  1. the drain calls the sink **itself, synchronously**, before it returns — handing lines to
     the tail thread is not enough;
  2. the drain emits the **last** record it holds too — a parser that holds a record back until
     the next record's header (for multi-line records) must flush at end of file;
  3. the drain and the tail thread share **one lock**, so no record is logged twice or out of
     order.
- **Log level:** `python -m pyhal --log-level LEVEL` (a number or a name, `TRACE` = 5 included,
  defined in `pyhal` as PyPTS defines it in `logger/levels.py`). PyPTS passes its own level to a
  HAL it starts, so today's DEBUG call traces still reach its run log. A HAL found running
  keeps its own level.
- **Accepted consequence of D46 + D51:** PyPTS's log also shows the HAL lines of other clients'
  requests made while it is connected.
- PyPTS's run log still gets every `DriverError` test code sees. CORE logs at INFO that it
  connected to the HAL, started it or found it; pid, port and paths at DEBUG
  (`logging_rules.md` §5, review fix).

## 10. Failure behaviour

| What happens | Result |
|---|---|
| No HAL running, and starting one fails or times out | D21: PyPTS starts anyway; `get_device()` fails with the reason and the startup file's tail; View → HAL shows "not reachable". |
| Port taken by something that is not a HAL | No `hello` → D21. A HAL started then exits, port in use. |
| HAL dies, mid-run or between runs | D28: the waiting call, and every later one, fails with `DriverError` through the normal step-error path. The run's `close`s fail too and are logged. |
| HAL alive, a driver call stuck | `CALL_TIMEOUT_S` → the driver process is killed and rescued (D44); the call raises today's timeout text. |
| HAL process frozen, its socket still open | The waiting call waits for ever (D57). **Known gap.** |
| A driver process dies | The HAL rescues it at once (D44); the call raises today's "stopped unexpectedly" text. |
| PyPTS crash close | `close_all` sent first (D45). |
| PyPTS killed outright | Nothing (D36). |
| A client freezes | Dropped after 5 s (D53); its `close_all` already queued still runs. |
| A stuck test thread from an earlier run calls a device | Refused in the client (§6.3). |
| An answer over 16 MB | `error`: the operation ran, the result is too large; the connection stays open. |
| Every failure in today's `hal.md` *Failure* table | Same `DriverError` text reaches test code. |

## 11. Scripts and standalone use

```python
import pyhal

with pyhal.connect(bench="my_bench.ini") as hal:   # connect, or start a HAL
    print(pyhal.get_device("ssh1").execute("uname -r"))
# leaving the block: close_all; shutdown only if this script started the HAL (D38)
```

- A script that never uses `with`: `connect()` registers an `atexit` that does the same (D54);
  leaving the `with` unregisters it.
- **By hand:** `python -m pyhal --bench FILE [--port N] [--log-dir DIR]` starts a HAL in a
  console; it runs until Ctrl+C, its console is closed, or a `shutdown`.
- **`python -m pyhal --close-all [--port N]`** and **`--stop [--port N]`** (D49): connect only,
  never start; send `close_all` (`--stop` sends `close_all`, then `shutdown`, so it can report what was not
  torn down: `bye` carries no list) (Phase 2 build, 2026-11-23); wait for the answers and print
  the devices not torn down; exit 1 when there were any, 2 when no HAL answered (also when it is
  already shutting down); serving exits 3 when the port is in use. `--bench`, `--port`, `--log-dir`, `--log-level` and `--nonce` (set by a
  starting client, §6.2) are the other options.
- **A non-Python client** implements one TCP connection, JSON lines, `hello`, the requests of
  §7.3, and a `beat` every second (a client with a request waiting is never dropped, §7.5).
  `pyhal.md` documents them with examples.

## 12. What changes, what does not

- **Unchanged:** the driver contract and behaviour, device types and verbs, how test code calls a
  device, devices closed at the end of a run before `RunFinished`, the teardown ladder and its
  timeouts, the Pipe protocol between the HAL and a driver process, the `DriverError` texts
  except those listed next.
- **Changed `DriverError` texts and `hal.md` *Failure* rows** (review 5): `No local setup is
  active ...` is reworded (§6.3); the "cannot be sent / could not be read" rows that speak of
  pickle become the value-domain refusals of §7.4; the timeout row's "the instrument keeps its
  state until `_close()`" becomes D44's rescue at once; new: the stale handle (§6.3), the closed
  connection and "shutting down" (§7.3).
- **New:** `src/pyhal/` (server, client with connect-or-start, protocol, `python -m pyhal`);
  `core/hal_link.py`; the View → HAL window and its HMI↔CORE messages; `close_device()`;
  `close_all` on every close; several clients.
- **Moved:** the contents of `src/pypts/hal/` into `src/pyhal/`.
- **Removed:** `pypts.hal` (D11); `LocalSetup` and `LocalSetup.from_ini()` (D12);
  `bench_sections()`; the Sequencer's `read_hardware_sections` seam (tests get D50's seam,
  *builder's call*).
- **Changed — behaviour the user should know** (`usage_manual.html`, migration notes):
  - PyPTS killed outright no longer tears devices down. Today a driver process whose Pipe
    closes runs `teardown()` (`hal.md`, *Lifetime*); under the HAL its Pipe is the HAL's (D36).
  - A crash close now tears devices down (through the HAL's `close_all`); today it does not
    (`hal.md`, *A crash*).
  - A call that times out, or a driver process that dies, is torn down at once, not at run end
    (D44).
  - Tuples come back as lists; numpy values are refused (§7.4).
  - Another client may be using the same device (D51, D52).
- **Changed — code:** `core/core.py` (start `hal_link` at startup; `close_all` on
  `SequencerStopped` and in `close_at_once()`; the View → HAL requests);
  `hmi/hmi_client.py` (the shared routing table needs the new `CoreToHmi` answers, closed with
  `unhandled()`);
  `sequencer/sequencer.py` (`run_scope()` in `run_body()`, the `read_hardware_sections`
  attribute and the `pypts.hal` import go); `hmi/gui/gui.py` and a new window module;
  `messages/core_hmi_communication.py`; `config_handler/bench_config.py` (its docstring); `recipe/recipe_schema.py`
  (the two `pypts.hal.get_device()` hints).

### 12.1 Repository housekeeping (same change)

- `.gitignore`: `!/src/pypts/hal/drivers/` → `!/src/pyhal/drivers/`.
- `reuse.toml`: add `src/pyhal/**/*.py`; `pyhal.md` gets an inline header (reuse.toml covers only
  `README.md` and `docs/**/*.md`). CLAUDE.md's licence paragraph follows.
- `pyproject.toml`: packages `include` gets `pyhal`, `pyhal.*`; `[tool.mypy] files`
  `"src/pypts/hal"` → `"src/pyhal"`; ruff isort `known-first-party` (today `["pypts"]`) gets
  `pyhal`.
- `DRIVER_FILE_MODULE_PREFIX = "pypts_driver_file_"` → a `pyhal` name.
- `.gitlab-ci.yml`: no HAL path; nothing to change.

### 12.2 Tests to update or add

- Update: `tests/unit_tests/test_hal.py`, `test_hal_connection.py`, `test_hal_ssh.py`,
  `test_hal_weather.py`, `hal_test_drivers.py`, `test_sequencer.py`, `test_core.py`,
  `test_messages.py`, `test_hmi_client.py`, `test_hmi_gui.py`, `test_utilities.py` (it names
  `"pypts.hal.local_setup"`), `tests/conftest.py` (tests stay off the real `bench.ini` **and off the
  real HAL port**), `tests/functional_tests/test_engine_in_process.py`, and the engine-starting
  tests (`test_api.py`, `test_headless.py`, `test_startup.py`,
  `tests/functional_tests/test_api_processes.py`).
- Add: "pyhal never imports pypts" (`tests/quality_tests/`); the kind-table coverage; the fence;
  connect-or-start (found / started / two starters / timeout / port in use); D36 (disconnect
  changes nothing); D38 / D43 (shutdown only if started, even with other clients); two clients
  on one device, FIFO (D52); the watchdog drop keeping a queued `close_all` (D53, D47);
  half-close delivering a `close_all` from a client that exits at once (D45); D44's rescue on
  death and on timeout; the oversized answer and request; `run_scope()` draining the log tail
  before it returns (D46); the beat going on during a long call; the close dropping a stray
  test thread's queued call (§6.4 step 1); the start nonce; a HAL shutting down refusing new
  clients and `connect()` waiting for the port; the View → HAL window.

### 12.3 Documents to update (same change)

- `src/pypts/hal/hal.md` → `src/pyhal/pyhal.md`.
- `launcher/launcher.md`, `core/core.md` (`hal_link`, the close), `hmi/hmi.md`,
  `messages/messages.md`, `sequencer/sequencer.md`, `hmi/gui/gui.md` (View → HAL, the Restart
  passage), `step/step.md` (values are plain data, tuples become lists),
  `config_handler/config_handler.md`, `logger/logging_rules.md` (HAL lines arrive as
  `HAL: ...`), `stream_handler/stream_handler.md`, `api/api.md`,
  `tests/quality_tests/quality_tests.md`, `src/pypts/README.md`.
- Code-side text: the `stream_handler/stream_session.py` docstring and comment that compare a
  `StreamSession` to `LocalSetup`, the `config_handler/bench_config.py` docstring,
  `config_handler/bench_template.ini`, the `No local setup is active ...` text.
- `docs/Usage_manuals/`: `usage_manual.html` (the HAL as a standalone service, connect or start,
  View → HAL, `--close-all` / `--stop`, the behaviour changes of §12, scripts),
  `quick_start.html`, `recipe_guide.html`, `pypts_implementation_status.html`,
  `how_to_write_a_driver.html` / `.md`, `migration_instructions.html`.
- Recipes: `resources/recipes/HAL_recipes/` — the recipes `hal_demo*` / `meteo_demo*` and their
  test code `hal_demo_tests.py` / `meteo_demo_tests.py` (`from pypts.hal import get_device`),
  `showcase_recipes/showcase_automated.yml`, `showcase_full.yml`.
- `CLAUDE.md`: module table, architecture block, process list (the HAL is a standalone process
  PyPTS connects to), messaging paragraph (the TCP link is outside the message layer).

## 13. Left to the builder

- Exact message fields, the port number, option names, the HAL log format (§9's two
  constraints) and file naming.
- How driver processes are kept from being killed un-torn-down at HAL exit (§6.5).
- Detached-start details per OS (§6.2).
- Layout refinements inside `src/pyhal/`.
- The test seam of D50 (own HAL on its own port, or none); test strategy within the quality
  gates.

Calls taken in phase 3 (2026-11-23), one line each:

- **D50's seam:** none - the environment variable `PYPTS_HAL=off` makes CORE's `HalLink.start()`
  connect to nothing (`get_device()` raises `HAL_OFF`); `tests/conftest.py` sets it for the suite.
- **`CLOSE_WAIT_S` = 5 s** (`core/hal_link.py`): the longest `HalLink.close()` waits for a startup
  connect still running, under the frontend's 15 s limit for a silent CORE.
- **The window start:** with `show_window`, `connect()` starts `python -m pyhal.monitor --serve
  --exit-with-hal` with the start nonce, so the monitor's Start makes PyPTS the owner; the wait is
  `HAL_WINDOW_START_TIMEOUT_S` (2 x `HAL_START_TIMEOUT_S`); the window closes itself after two
  empty polls in a row (`EXIT_AFTER_MISSED_POLLS`) once it has seen its HAL.
- **§6.2 step 8:** CORE's connect runs on a thread; `connect_pending()` announces it, so
  `run_scope()` waits for it (at most `CONNECT_WAIT_S`), and `note_unavailable(reason)` settles it
  for a start that makes no connect.

## 14. Known gaps that stay

- PyPTS killed outright leaves instruments as they are (D36).
- A HAL that freezes with its socket open freezes the test that waits on it (D57).
- A HAL killed outright (`TerminateProcess`, `SIGKILL`) tears nothing down itself; its driver
  processes do when their Pipe closes, unless stuck in a call (D29).
- A call blocked inside a driver is not interrupted by Stop; `CALL_TIMEOUT_S` bounds it.
- Two clients' calls to one device interleave; nothing serialises a sequence of calls (D52).
- `close_all` / `shutdown` from one client cut the others off (D51).
- PyPTS's log shows other clients' HAL lines (§9).
- A thread test code started in one run can get a fresh handle in the next run (§6.3).
- Closing the console of a HAL started by hand gives it about 5 s on Windows (§6.5).
- Anyone on the machine can reach the port; no authentication.
- Large waveforms travel as JSON arrays; no side channel for bulk data.
