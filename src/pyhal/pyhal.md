<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# pyhal — the hardware layer

Devices on the bench, reached by **logical name** from test code. Every device runs its
driver in **a process of its own**: a driver that crashes, hangs or leaks takes its own
process down, not the HAL server or PyPTS. Decided 2026-10-08 (roadmap §1.54); the process is started with
`multiprocessing` and reached over a Pipe since 2026-10-09 (roadmap §1.57).

The package is a standalone HAL server (`docs/superpowers/specs/2026-11-04-hal-server-design.md`,
rev 5; phase 3 of 4 is done). The server, its protocol, its client and `python -m pyhal` are
described in *The HAL server* to *Logs* below. **PyPTS reaches its devices through the
server:** CORE connects to it at startup (`core/hal_link.py`, `core/core.md` → *The HAL link*)
and the Sequencer runs each run inside `pyhal.run_scope()` (`sequencer/sequencer.md`). There is
no in-process way any more: the top-level `pyhal.get_device()`, `recover_device()` and
`device_info()` (`dispatch.py`) forward to the client (`client.py`). The sections *How a call
travels* to *Failure* describe the driver layer, which now runs inside the HAL server.

```python
from pyhal import get_device

def read_kernel():
    result = get_device("ssh1").execute("uname -r")
    return {"kernel": result["stdout"].strip()}
```

## Files

| File | Holds |
|---|---|
| `__init__.py` | The public API, import-light on purpose (a driver's `from pyhal import PSU` runs in every driver process): `BaseDriver`, `DriverError`, the six device types, `get_device`, `recover_device`, `device_info` are imported at once; `connect`, `run_scope`, `close_device`, `HalClient`, `DEFAULT_PORT`, `ConnectionDriver`, `DeviceInfo` are imported on first use (module `__getattr__`), so importing `pyhal` does not import `socket` |
| `dispatch.py` | `get_device()`, `recover_device()`, `device_info()` as `pyhal` exports them: each forwards to the function of the same name in `client.py`, imported at call time (so `import pyhal` stays light) |
| `bench.py` | `read_bench()` (the bench file's device sections, driver files anchored, and the SHA-256 of its bytes), `split_section()`, `anchor_driver_files()` |
| `devices.py` | `Devices`: the HAL's open devices by name (`open`, `call`, `recover`, `info`, `close`, `close_all`, `open_names`, `snapshot`); owned by the server's one request thread, no lock; the D44 rescue |
| `server.py` | `HalServer`: the TCP server, its four kinds of thread, the queue, the watchdog and the exit (*The HAL server*) |
| `client.py` | `connect()`, `connect_only()`, `connect_pending()`, `note_unavailable()`, `start_hal()`, `HalClient`, `run_scope()`, `get_device()`, `recover_device()`, `device_info()`, `close_device()`, `Device` (the handle), `LogTail` (*The client*) |
| `protocol/values.py`, `protocol/messages.py`, `protocol/codec.py` | The three layers of the wire protocol (*The protocol*) |
| `hal_log.py` | The HAL's own log file: `start_log_file()`, `stop_log_file()`, `default_log_dir()`, `LOG_FORMAT`, `RECORD_START`, `TRACE` (*Logs*) |
| `__main__.py` | `python -m pyhal`: serve (with `--window`, its monitor window: `open_window()`, `close_window()`), `--close-all`, `--stop`; the exit handlers (`ExitHandlers`) |
| `monitor/__init__.py` | Docstring only: the HAL monitor package. **The only place PySide6 is imported**; `pyhal` never imports `pyhal.monitor`, so `import pyhal` (every driver process runs it) stays light (*The monitor*) |
| `monitor/link.py` | `MonitorLink`: the monitor's connections to the HAL, no Qt: `status()`, `close_all()`, `stop()`, `start()` (log folder, log level, nonce), `close()`, `log_tail()`; `POLL_TIMEOUT_S` |
| `monitor/window.py` | `MonitorWindow` (PySide6): the window, its poll timer, workers and log view, and `exit_with_hal`; `REFRESH_S`, `LOG_VIEW_MAX_LINES` |
| `monitor/__main__.py` | `python -m pyhal.monitor [--port N] [--exit-with-hal]`; sets the light colour scheme |
| `base_driver.py` | `BaseDriver` (ABC: `connect`, `teardown`, `recover`), `DriverError`, `LIFECYCLE_METHODS`, `operations_of()` |
| `device_types.py` | `PSU`, `DMM`, `Scope`, `SSH`, `Load`, `Other`; `DEVICE_TYPES`, `DEVICE_TYPE_NAMES` |
| `connection_driver.py` | `ConnectionDriver`, one device as test code sees it: **every public name on it is the driver's operation** (its own members are all `_private`, so no name is reserved), with `CALL_TIMEOUT_S` (30 s, the same for every device) and its teardown ladder: `_close()` escalating to the rescue (`_rescue()`, `RESCUE_TIMEOUT_S`); below it, the driver process: `driver_process_main()`, `load_driver_class()` with `load_driver_file()`, `split_driver_file()`, `driver_module_name()` and `DRIVER_FILE_MODULE_PREFIX`, `answer()` |
| `device_control.py` | `DeviceInfo` (name, device type, operations, is open), what `device_info()` returns. `recover_device()` and `device_info()` are functions, not methods, so they take no name away from drivers; they live in `client.py` |
| `drivers/loopback.py` | `LoopbackDriver` (Other): no hardware; tests, demo, smoke check |
| `drivers/ssh.py` | `SshDriver` (SSH): the reference driver, paramiko |
| `drivers/weather.py` | `OpenMeteoDriver` (Other): a weather station on the internet, standard library only; the showcase driver |

`pyhal` never imports `pypts` (quality test `tests/quality_tests/test_pyhal_independence.py`). It logs
through `logging.getLogger(__name__)`: in the HAL server its records go to the HAL's own log
file (*Logs*), which PyPTS re-logs as `HAL: ...` (`core/hal_link.py`); in a client's process
(PyPTS's CORE, a script) the client's records go to that process's own logging.

## How a call travels

1. Test code calls `get_device("ssh1")`, which opens the device on the HAL server (*The
   client*). In the HAL, `Devices` builds a `ConnectionDriver` from the bench file's section and
   calls its private `_open()`.
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
| `(method, args, kwargs)` | HAL server → driver process: one call |
| `("hello", device_type, operations)` | driver process → HAL server, once, first |
| `("fatal", reason)` | driver process → HAL server, instead of hello |
| `("log", level, logger_name, message)` | driver process → HAL server, any time |
| `("printed", line)` | driver process → HAL server, any time |
| `("result", value)` | driver process → HAL server |
| `("error", type_name, message, traceback)` | driver process → HAL server |

Arguments and return values must be picklable. An argument that is not is refused before
anything is sent; a return value that is not comes back as an `error`. A call or an answer that
pickles but cannot be unpickled on the other side (an exception class whose `__init__` takes
two arguments, say) is a `DriverError` too. Each message is pickled whole and read whole
(`send_bytes` / `recv_bytes`), so in every case the device stays usable. `connect`, `teardown` and `recover` are callable but are not `operations`.

## The HAL server

`server.py`, `HalServer(bench_path, port, nonce=, log_path=, call_timeout_s=)`: a TCP server on
`127.0.0.1` that owns the bench's devices (`Devices`, `devices.py`). It reads the bench file
once, in `__init__` (D25). `start()` binds (on Windows with `SO_EXCLUSIVEADDRUSE`, so no second
HAL can share the port; a port that is taken raises `OSError` and leaves nothing open) and starts
the threads; `serve_until_stopped()` blocks until the server has exited; `request_exit(reason)`
is the one way out.

**Threads.** `HAL accept` takes connections; `HAL client <n>`, one per connection, sends
`hello` and then reads lines; `HAL requests` runs the queue; `HAL watchdog` drops dead clients.
All are daemons. The death of any of them is fatal: the exception is logged and the HAL tears
down and exits (`_thread()`, `_request_thread_main()`); `serve_until_stopped()` runs the exit
itself if the request thread ended without running it. A failed `accept()` is one lost client,
not a reason to exit: the first failure of a row is a WARNING, the repeats DEBUG, until an
accept works again.

**The queue.** A connection thread answers `beat` (nothing) and `status` (at once, from the
snapshot the request thread refreshes after every request; it carries the HAL's pid, version,
bench, log path, client count, what is running, how many are queued and one row per bench
device) itself. Every other request - `open`, `call`, `recover`, `info`, `close`, `close_all`,
`shutdown` - goes on one queue with its connection, and `HAL requests` runs them first in,
first out, one at a time, on `Devices`, which no other thread touches (D52). A device is never
locked between calls; two clients share it.

**Who counts as a client** (`hello.clients`, the other clients; `status.clients`): a connection
that has sent a `beat` or any request but `status` (`_Connection.counted`,
`_clients_counted()`). A `HalClient` beats every second, so it counts from its first beat; a
connection that only asks `status` - the HAL monitor's poll - never counts, so a HAL PyPTS
started with its window still tells the next client that it has devices open that no client
is using (D40). The wire is unchanged: only what the HAL counts.

**Who is answered.** The connection the request came from, and only while that client is still
connected. A client that is gone (end of stream, reset, a failed write, dropped by the
watchdog) loses its queued `open`, `call`, `recover` and `info`; its `close`, `close_all` and
`shutdown` stay and run, a request of its that is running finishes, and the answer is
discarded. Nothing is done to the bench for it (D36). The timing constants are at
the top of `server.py`; the ones that matter: `CLIENT_SILENCE_S` 5, `WRITE_STALL_S` 30,
`EXIT_GRACE_S` 1.

**The watchdog** looks every `WATCHDOG_TICK_S` (0.5 s). It drops a client that has been silent
for `CLIENT_SILENCE_S` (D53: the client's beat is every second, and any line counts) and has
nothing queued or running, and a client whose answer has been on its way for `WRITE_STALL_S`
(it does not read; its write would block the request thread). A drop makes the client gone as
above and then hangs up (`_hang_up()`): `shutdown()` on both platforms, which wakes a blocked
reader or writer on Linux; on Windows it wakes neither, so there the handle is then also
detached and closed, after waiting up to `HANG_UP_WAIT_S` for a write in progress.

**Locks.** `_lock` guards the queue, the client list, the snapshot and the exit state. A
connection has a write lock, held for one line; a write takes it and then `_lock` briefly,
never the other way round. `request_exit()` takes neither: it sets state and wakes the request
thread through a `queue.SimpleQueue`, so a signal handler may call it.

**The exit** (`request_exit()`, a `shutdown` request, a signal, a dead thread; spec §6.5). New
clients are answered `Error("hal", "The HAL server is shutting down.")` and closed instead of
`hello` (the listener stays open, so no second HAL can bind). The running request finishes;
queued requests but a `close_all` or `shutdown` are refused with the same text; every queued
`close_all` and `shutdown` runs. Then `Devices.close_all()` tears down every open device,
newest first; its ladder logs the ERROR `... could not be torn down and may still be
energised: ...` for each device it could not. The HAL waits up to `EXIT_GRACE_S` for the
clients to close their end, closes the rest, ends its threads (`THREAD_JOIN_S` each) and
closes the listener last. The request thread runs all of it, from its `finally`. A `close_all`
answers `closed_all` with the names not torn down; a `shutdown` runs `close_all`, answers
`bye` and then requests the exit.

## The protocol

Three layers, in `src/pyhal/protocol/`. A line is one message; the HAL is a server and a
client is not; every request has exactly one answer, except `beat`, which has none.

1. **Values** (`values.py`). What may cross: `None`, `bool`, `int`, `float`, `str`, `bytes`,
   `list` and `dict` with `str` keys. Types are checked exactly (`type(x) is float`): numpy
   scalars and subclasses are refused with a `ValueError` that names the path
   (`value['x'][2]: ndarray cannot be sent`), not sent as something else. A tuple goes as a
   list and comes back as a list. NaN, infinity and bytes travel tagged: `{"$float": "nan"}`
   (`"inf"`, `"-inf"`) and `{"$bytes": "<base64>"}`; a dict key that starts with `$` is
   therefore refused. Nesting deeper than `MAX_DEPTH` (64) is refused, which also stops a
   circular value.
2. **Messages** (`messages.py`). One frozen dataclass per message, two unions (`ClientToHal`,
   `HalToClient`), two kind tables (`CLIENT_KINDS`, `HAL_KINDS`; `info` names `Info` in one and
   `DeviceInfo` in the other), `kind_of()`, `build()` (an unknown kind, an unknown or missing
   field or a field of the wrong type raises `ValueError` before anything is encoded),
   `hal_version()` and `unhandled()`.
3. **The codec** (`codec.py`). One JSON object per line, UTF-8, `\n`-terminated, `kind` first,
   then the fields. `encode()` raises `ValueError` (the bad value's path) or `MessageTooLarge`
   (over `MAX_MESSAGE_BYTES`, 16 MiB, D32); `decode()` raises `MalformedLine` for bad UTF-8, bad
   JSON, a `NaN` / `Infinity` literal, nesting over `MAX_DEPTH`, a missing kind or any field
   `build()` refuses; `read_line()` never reads more than `MAX_MESSAGE_BYTES + 1` bytes of one
   line, and a longer one is `MalformedLine("line too long")`, after which the connection must
   be closed.

| Client → HAL | Fields | Answer |
|---|---|---|
| `open` | `device` | `opened` |
| `call` | `device`, `operation`, `args`, `kwargs` | `result` |
| `recover` | `device` | `recovered` |
| `info` | `device` | `info` |
| `close` | `device` | `closed` |
| `close_all` | none | `closed_all` |
| `shutdown` | none | `bye` |
| `status` | none | `status` |
| `beat` | none | none |

| HAL → client | Fields |
|---|---|
| `hello` | `pid`, `nonce` (or null), `version`, `bench`, `bench_sha256`, `log`, `open`, `clients` (the other clients connected; below) |
| `opened` | `device`, `device_type`, `operations` |
| `result` | `value` |
| `recovered` | `device` |
| `info` | `device`, `device_type`, `operations`, `is_open` |
| `closed` | `device` |
| `closed_all` | `not_torn_down` (names) |
| `bye` | none |
| `status` | `pid`, `version`, `bench`, `log`, `clients`, `busy` (null, or `device`, `operation`, `since`), `queued`, `devices` (rows: `name`, `device_type`, `state` `open` / `failed` / `configured`, `last_error`) |
| `error` | `origin`, `message` |

**Errors.** Any request may be answered `error` instead. `origin` is `driver` when the driver
raised (the text is `Device 'x': 'op' failed: Type: message`), `hal` for everything else the
HAL refuses (an unknown device, a device that could not be opened, a call timeout, a result
too large to send, `The HAL server is shutting down.`) and `protocol` for a line that is not a
request; a protocol error ends the connection. The client raises `DriverError` with the text
as it is (a protocol error as `HAL protocol error: <text>`). The origin is decided from the
text (*Known gaps*).

One exchange, as it goes over the wire (each line is one message):

```
HAL    -> {"kind":"hello","pid":4242,"nonce":null,"version":"0.1.0","bench":"C:\\bench\\bench.ini","bench_sha256":"...","log":"C:\\logs\\hal_20261123_101500_4242.log","open":[],"clients":0}
client -> {"kind":"call","device":"loop1","operation":"echo","args":["hi",{"$float":"nan"}],"kwargs":{}}
HAL    -> {"kind":"result","value":["hi",{"$float":"nan"}]}
client -> {"kind":"close_all"}
HAL    -> {"kind":"closed_all","not_torn_down":[]}
```

## The client

`client.py`. One client per process, the process's client. `connect(bench, port=DEFAULT_PORT,
scope=True, log_sink=None, log_level=None, log_dir=None, show_window=False)` makes it, starting
a HAL when none answers; `connect_only(port, scope=True)` never starts one. `DEFAULT_PORT` is 29555 (D56):
below 32768, so outside the temporary-port ranges of Linux (32768-60999) and Windows
(49152-65535), where Windows also reserves blocks for Hyper-V/WSL that cannot be bound. Both
return a `HalClient` (a context manager; `send("call", device=..., ...)` for a raw request,
`close()`). A new connect first closes an earlier client of the process that was never closed,
which sends that client's parting request (below) before the new one connects: after, its
`shutdown` would stop the HAL the new client is using. When that parting request was
`shutdown`, the new connect (`connect()` and `connect_only()`) then waits until that HAL no
longer answers - nothing listens, or what answers is a HAL with another pid or not a HAL - for
at most `HAL_SHUTDOWN_WAIT_S` (`_wait_for_exit()`), so it is never welcomed by a HAL that has
not read the `shutdown` yet.

**Connect or start** (spec §6.2). `connect()` tries the port. A `hello` answers: the client
compares the version and the bench (path and SHA-256) with its own and logs a WARNING on a
difference, and uses the HAL anyway (D48); devices left open with no other client connected
are a WARNING too (`The HAL server on port N has devices open that no client is using: ...`;
the monitor window's poll is not a client, below, so it does not hide them). Anything that
raises after the client has connected (the log tail's start, the comparison) closes that
client - with its parting request - before the error goes on, so a HAL it started is not left
running. An `error` instead (a HAL that is shutting down) is retried every
`CONNECT_RETRY_S` until nothing listens, for at most `HAL_SHUTDOWN_WAIT_S` (120 s). Nothing
listens: it starts the HAL and retries until `HAL_START_TIMEOUT_S` (15 s, with its window
or without, below). The reason of a
failed connect is also what `get_device()` reports from then on (D21).

**A pending connect** (spec §6.2 step 8). A caller that connects on another thread (PyPTS's
CORE) first calls `connect_pending()`, which clears the module's `_connect_settled` event (set
at import). `connect()` and `connect_only()` set it in a `finally`, so it is set when they
return or raise. `run_scope()` waits on it before opening the scope, for at most
`CONNECT_WAIT_S` (`HAL_SHUTDOWN_WAIT_S + HAL_START_TIMEOUT_S`); on a timeout it logs a DEBUG
line and goes on, and `get_device()` raises what it has. `note_unavailable(reason)` is for a
start that will make no connect: it sets the reason `get_device()` raises (as a failed connect
does) and sets the event; an existing client is not touched. Without `connect_pending()`
`run_scope()` does not wait.

**Starting the HAL.** `python -P -m pyhal --bench <path> --port <port> --nonce <n>`
(`--log-level`, `--log-dir` when given), with the interpreter that runs the client. `-P` keeps
the starter's working directory off the HAL's `sys.path`; the entries that matter go through
`PYTHONPATH`, made absolute, so the driver classes resolve as they do in the client. The HAL's
working directory is the log folder (it does not hold the starter's folder open); its stdin is
the null device and its stdout and stderr go to `hal_startup.log` in the log folder, appended.
It is its own process group (Windows: `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, so no
console window opens for the driver processes either; elsewhere `start_new_session`), so it
survives its starter. A HAL that exits at once, with any code but 3, fails `connect()` at once
with `The HAL server could not be started: <the tail of what this start wrote to
hal_startup.log, at most 20 lines>`; exit code 3 (the port is taken) means another starter won
the race, and the client waits for that one's HAL.

**Starting it with its window** (`connect(show_window=True)`). When nothing answers, the
client starts the HAL as above with `--window` added (`_launch(window=True)`): the HAL itself
opens its monitor window, once it is bound, and owns it (*python -m pyhal*, *The window*). The
client waits for the HAL's `hello` as for any start, `HAL_START_TIMEOUT_S`; it never starts the
monitor itself, and **the monitor never starts a HAL** (user decision 2026-11-24). A HAL found
running is only connected to; no window is opened. Two `show_window` starters at the same
moment get one window: the HAL that loses the port exits before it opens one.

`start_hal(bench, port=DEFAULT_PORT, log_level=None, log_dir=None, show_window=False)` is that
start on its own, without a client (`run_hal.py`): both go through `_start_and_connect()`
(launch with `_launch()`, then connect in the retry loop above). `start_hal()` closes that
connection again without a parting request and returns the pid its `hello` names - the HAL's
own; on Windows in a venv the process `Popen` starts is the venv's launcher, whose pid is
another. A HAL that fails to start raises `DriverError` with the startup-file tail, as above;
a `hello` with another nonce (another starter's HAL answered first) raises `_AnotherHal`, a
`DriverError`. `connect()` keeps its connection as the long one.

**The nonce** is `secrets.token_hex(16)` per start, handed to the HAL as `--nonce` and echoed
by its `hello`. `HalClient.started_hal` is true when the `hello` of its long connection carries
it (never decided by the pid), so
two starters at the same moment both connect to the first HAL, and only its starter owns it
(D38).

**The long connection and its two locks.** The request lock is held by whoever sends a request
until its answer is read (D18: one request outstanding per connection; threads take turns, and
the thread that sent reads the answer, since the HAL sends nothing unprompted). The write lock
is held for one line: by a request's send, and by the beat thread. Order: request lock, module
lock (the fence), write lock. There is no client-side deadline on an answer (D57): a wait ends
with the answer or with the connection closing. `HAL beat` sends `beat` every `CLIENT_BEAT_S`
(1 s), never taking the request lock, so beats go on during a long call. A connection that
fails ends the client's stream; the request that meets it raises `DriverError`. A send or a
wait ended by anything but a `DriverError` (`KeyboardInterrupt`: Ctrl+C interrupts the
`recv` on Linux) closes the long connection before the exception goes on, since its answer
may still arrive and, with no request ids (D18), the next request would take it as its own;
every later request raises `The connection to the HAL server is closed.`

**Handles and the fence.** `get_device(name)` sends `open` and returns a `Device`: every public
name on it is a driver operation (a name that is not one raises `AttributeError` without a round
trip; the handle's own members are all `_private`). Each handle remembers the scope counter it
was made under; every request it makes compares it with the counter under the request lock, in
the same step as the send, so a handle of an ended scope is refused by the client, never by the
HAL: `Device 'x' belongs to a run that has ended; call get_device('x') again.`

**The scope.** `run_scope()` is a context manager: `get_device()` works inside it, and on exit
every device it asked for is closed (`close` requests), newest first, each waiting for its
answer; the exit never raises, a failed close is a WARNING, and the HAL log is drained to the
sink after the last close. `run_scope()` does not nest: inside an active scope it raises
`DriverError` and changes nothing. `connect(scope=True)` opens a scope that lasts until the
client's close, so a script that wants its own `run_scope()` calls connects with
`scope=False`. `get_device()` outside a scope raises `No HAL scope is active. ...`.
`recover_device(device)`, `device_info(device)` and `close_device(device)` are requests on the
long connection too (`close_device` closes one device; its next request opens it again).

**The close** (spec §6.4): `HalClient.close()`, `with ... :` leaving, and the `atexit` hook
`connect()` registers (not `connect_only()`), all the same, on the calling thread, idempotent,
never raising. (1) End the scope (the counter raised) and close the long connection. (2) On a
short connection, read `hello`, send the parting request, half-close, close, and do not wait
for the answer. The parting request is `shutdown` **only if this client started the HAL and the
short connection's `hello` echoes the same nonce**; otherwise `close_all`. A HAL that took the
port since (the one this client started crashed, another was started) is therefore never shut
down by it. Nothing answering is a DEBUG line. Something that accepts the short connection
but whose `hello` fails (it closes, or sends a line that is not a message) or whose send fails
is a WARNING: `The HAL server did not take the close_all; devices may still be open. Run
'python -m pyhal --close-all' to close them.` (`--stop` for a `shutdown`, and `--port N` when
the port is not 29555). A HAL that answers `error` (it is shutting down) and a listener that is
not a HAL stay DEBUG.

**The log tail.** `connect(log_sink=f)` starts a `LogTail` on the file `hello.log` names:
`HAL log tail` reads it every `LOG_TAIL_POLL_S` and calls `f(level, message)` for each record
written after the connect (D46). The sink must not call `drain()` or `stop()` and must not log
into the HAL's own log file. A file that does not exist yet is tailed from its beginning once
it appears; a file that shrinks is read again from its start.

## python -m pyhal

```
python -m pyhal --bench FILE [--port N] [--log-dir DIR] [--log-level LEVEL] [--nonce TEXT] [--window]
python -m pyhal --close-all [--port N]
python -m pyhal --stop [--port N]
```

`python -m pyhal` is the HAL without a window; with `--window` it opens its monitor window
(*The window* below). `run_hal.py` in the repository root starts it that way (*The monitor*).

Serving needs `--bench`; without it, and without `--close-all` or `--stop`, the command is a
usage error (argparse's exit code 2). `--port` defaults to 29555, `--log-level` to INFO (a
number or a name, `TRACE` included), `--log-dir` to the folder under *Logs*. `--nonce` is for a
starting client. The two client modes only connect, never start a HAL. `--close-all` sends
`close_all`; `--stop` sends `close_all` and then `shutdown`, so it can report what was not torn
down (`bye` carries no list). Both wait for their answers (no deadline, D57) and print
`Every device was torn down.` or `Not torn down: <names>`.

| Exit code | Serving | `--close-all`, `--stop` |
|---|---|---|
| 0 | the server exited after its teardown | every device was torn down |
| 1 | the bench file could not be read (a message on stderr) | a device was not torn down |
| 2 | (argparse: a usage error) | no HAL answered, or what answered is not a HAL, or the HAL is already shutting down |
| 3 | the port cannot be used: taken, or reserved by the system | - |

**The exit handlers** (`ExitHandlers`): SIGINT (Ctrl+C), SIGBREAK, SIGTERM and SIGHUP where
they exist, and on Windows the console's close, logoff and shutdown events, all call
`request_exit()` - the first one only; a second Ctrl+C does nothing, so it cannot cut the
teardown short. The main thread leaves `serve()` only after the server has exited: the driver
processes are daemons, which multiprocessing terminates, without `teardown()`, when the
interpreter exits.

**The window** (`--window`; what `connect(show_window=True)` and `run_hal.py` pass). Once the
server is bound, `serve()` calls `open_window(port, log_dir)`: the monitor as **this HAL's
child process** (not detached: no process group or session of its own), `python -P -m
pyhal.monitor --port <port> --exit-with-hal` (`MONITOR_MODULE`), with this process's `sys.path`
as `PYTHONPATH`, the log folder as its working directory, stdin the null device and its stdout
and stderr appended to `hal_monitor_startup.log` (`MONITOR_STARTUP_FILE`) in the log folder. On
Windows it gets `CREATE_NO_WINDOW`: a HAL a client started has no console, and the console
program it starts would otherwise get one of its own; the Qt window still shows. The HAL never
imports PySide6 and never waits for the window: one that cannot be started is a WARNING (`The
HAL monitor window could not be started: <reason>`) and the HAL serves on; one that cannot open
(no display: Linux over SSH, CI) exits, and says why in its startup file. At the HAL's exit,
after the teardown, `close_window()` ends a window still open (`terminate()`, then `kill()`
after `WINDOW_CLOSE_WAIT_S`, 5 s): the monitor sends nothing on its own, so there is nothing it
could leave half done. Closing the window by hand leaves the HAL running. The window's
`--exit-with-hal` is the net for a HAL killed without its exit (Windows does not end a killed
process's children).

## The monitor

A small standalone window for a running HAL, started with `python -m pyhal.monitor [--port N]
[--exit-with-hal]`, by a HAL started with `--window` (its own window, *python -m pyhal*), or
by `python run_hal.py` from a checkout (below). **It only connects to a HAL: it never starts
one** (user decision 2026-11-24): a HAL is started by PyPTS, a script, `run_hal.py` or by hand.
With no HAL answering it shows *not reachable* and keeps polling. It is always light:
`__main__` sets `Qt.ColorScheme.Light`, whatever the system's scheme (user decision
2026-11-23). It is a client of the HAL like any other, over connections of its own; it does
not need PyPTS. User decision 2026-11-23: standalone first; a later *View -> HAL* in PyPTS may
open this window.

**What it shows.** State (*running* green, *busy* amber, *not reachable* grey), pid, version,
bench file, log file, the other clients connected (the status's `clients`: the window's poll
asks only `status`, so the HAL does not count it, *The HAL server*), what the HAL is running
and since when (`busy`), the queued requests and the time of the last refresh. A table of the
devices: name, type, state, last error. A log view with the latest 500 records
(`LOG_VIEW_MAX_LINES`) and a level filter DEBUG / INFO / WARNING, INFO by default.

**Buttons.** *Close all devices* and *Stop HAL* each ask first, and say that every open device
is torn down, also those of other clients; they are enabled while a HAL answers. One action
runs at a time, and the status bar shows its result; devices that were not torn down also open
a warning.

**Refresh.** Every `REFRESH_S` (1 s, `window.py`) the window polls `status`. A poll that does
not answer within `POLL_TIMEOUT_S` (2 s, `link.py`) shows *not reachable*; the next poll tries
again, so a HAL that comes back, or starts later, is picked up on its own. All network work
runs on worker threads, never on the GUI thread; the HAL answers `status` from its connection
thread, so the window never waits behind a device call.

**Exit with the HAL** (`--exit-with-hal`, `MonitorWindow(exit_with_hal=True)`; what a HAL
started with `--window` opens). Once a poll has seen a HAL answer (`_seen_hal`),
`EXIT_AFTER_MISSED_POLLS` (2) polls in a row that find none close the window - one slow poll
(over `POLL_TIMEOUT_S`) does not, while the HAL still runs - (INFO `The HAL at
127.0.0.1:<port> has gone; the monitor closes with it.`), and the process exits. The window
follows the first HAL it saw, by its pid (`_hal_pid`, `_is_our_hal()`): a poll that finds a HAL
with another pid - another starter's, started on the port after this one had gone - counts as
a poll that found none and never resets the count, so the window does not latch onto that HAL
(it still shows it until it closes). Before any HAL has answered the window stays. The HAL
ends its own window at its exit (*python -m pyhal*, *The window*); this is the net for a HAL
that was killed without one.

**It sends nothing on its own.** The monitor never sends `close_all` or `shutdown` except from
its two buttons, after the user confirmed. Its connections never send a parting request, so
closing the window - by hand, asking nothing - a failed poll or an exit leave the HAL and the
bench alone (D36). Closing the window during *Close all* or *Stop* hides it, but the process
waits for that action to finish (it logs `Waiting for ... to finish before the monitor
exits.`), so a Stop that was pressed always completes.

**The log view** tails the HAL's log file (`LogTail`, *The client*). The time in each line is
when the monitor received the record, not the time in the HAL's log. A tail starts at the
file's end, so the first lines of a HAL that has just been started are not shown. When another
HAL comes up (another pid or log file), the view follows its new log file.

**`run_hal.py`** (repository root) takes no arguments (any: a message, exit 2). It puts `src`
on the path, finds PyPTS's own `bench.ini` - created from the template when missing, by
`pypts.config_handler.bench_config`, as a PyPTS start does - and prints its path and devices.
An unusable bench file stops it with the reason (exit 1, `EXIT_BAD_BENCH`). Then, on the
default port (`running_hal_pid()` asks `status` through a `MonitorLink`):

- no HAL answers: `start_hal(<it>, show_window=True)` starts a detached HAL with its window
  (`python -m pyhal --window`), prints its pid and returns (exit 0; a failed start: the reason,
  `EXIT_START_FAILED`, 1). The HAL keeps running when the window is closed; `python -m pyhal
  --stop` or the window's *Stop HAL* stops it;
- a HAL answers: it says so and runs `pyhal.monitor.__main__.main([])` in its own process, a
  viewer of that HAL; closing it leaves the HAL running.

The launcher imports `pypts`; the package does not. PyPTS's `hal.show_window` setting chooses
the window or none for a HAL that PyPTS starts (`core/hal_link.py`).

**Import lightness.** PySide6 is imported only inside `pyhal.monitor`; `import pyhal` stays
light (`test_import_pyhal_stays_light`), and the HAL server starts its window as a process,
never by importing it.

**`start_hal()`** is public so a launcher can start a HAL without making a client. It returns
the pid the HAL's `hello` names, decides by the nonce, and sends no parting request (*The
client*).

**Extending.** A new field or button goes in `window.py`; anything that talks to the HAL goes
in `link.py`, which has no Qt and is tested without a display.

## Logs

The HAL writes its own log file, because it outlives PyPTS (D16): `hal_log.start_log_file(dir,
level)` puts one handler on the root logger, flushed after every record, and sets the root
level.

- **Name:** `hal_<YYYYmmdd_HHMMSS>_<pid>.log`; a second file started in the same second gets
  `_2`, `_3` ... before `.log` (the name is claimed by creating the file).
- **Folder:** `--log-dir`, else `default_log_dir()`: `%LOCALAPPDATA%\pyhal\logs` on Windows,
  `$XDG_STATE_HOME/pyhal/logs` or `~/.local/state/pyhal/logs` elsewhere. `hal_startup.log`
  (what a started HAL printed before and besides its log) is in the same folder, and so is
  `hal_monitor_startup.log` (what the window of a HAL started with `--window` printed).
- **Format:** one record per line, `;`-separated: `2026-11-23 10:15:00.123;INFO;pyhal.server;message`
  (`LOG_FORMAT`). A record with several lines (a traceback) continues on lines that do not match
  `RECORD_START` (a line starting `YYYY-MM-DD HH:MM:SS.mmm;`), which is how a reader tells the next
  record from the rest of this one. The levels are the standard ones and `TRACE` (5).
- **Content:** the devices' own lines at the levels *Logging* lists; the server's lines are DEBUG
  (client connected, request run, exit) except the WARNINGs and ERRORs named above and the INFO
  `The HAL server is running on ...` / `... has stopped.`

## Configuration

Devices are declared in `bench.ini`, beside `config.ini`
(`%LOCALAPPDATA%\pypts\bench.ini` / `~/.config/pypts/bench.ini`): one **bare-named** section
per device (or, outside PyPTS, any INI file in the same format given to `pyhal.connect()` or
to `python -m pyhal --bench`):

```ini
[ssh1]
driver = pyhal.drivers.ssh.SshDriver    ; required: the driver class, dotted
host = 192.168.0.10                          ; everything else goes to the driver's connect()
username = tester
key_filename = C:\Users\tester\.ssh\id_ed25519
```

`split_section()` reads only `driver`; every other key goes to the driver as text. A `python`
key, the per-device interpreter of the previous design, is refused with a `DriverError` telling
the user to remove it: every driver runs on the HAL server's Python (the interpreter of the
process that started it). The call timeout is not
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
  file with `load_driver_file()` as module `pyhal_driver_file_<stem>`
  (`DRIVER_FILE_MODULE_PREFIX`), registered in `sys.modules` - it holds that one driver only.
  Only the file is loaded: its folder is not put on `sys.path`, so it imports what is installed,
  not what sits beside it. `anchor_driver_files()` expands `~` and makes a relative file
  relative to the folder of the INI file that declares it (`bench.ini`, or the bench file given to
  the HAL server), before the section reaches `split_section()`. A `ConnectionDriver` built
  directly with a relative file resolves it against the current directory.

`driver_module_name()` gives the module either spelling names; a forwarded log record keeps its
level when its logger is that module or a child of it (see *Logging*).

The HAL server reads the bench file once, when it starts (D25), so a hand edit of `bench.ini`
applies from the next HAL start: File → Restart in the GUI when PyPTS started the HAL (its close
stops it); a HAL PyPTS found running keeps its bench until it is stopped (`python -m pyhal
--stop`). Restore default settings (GUI)
rewrites `config.ini` only; `bench.ini` and its devices are untouched.

## Lifetime

- **Per run.** A run is one Start press: one top-level sequence and every sequence it calls.
  `Sequencer.run_body()` (called by `execute_sequence()`) wraps the step layer in
  `with pyhal.run_scope():` (*The client*). A device opens on the HAL server on the first
  `get_device()`. Every device the run asked for closes, newest first, after the teardown steps
  and before `RunFinished`, whatever the result. Headless (`--mode headless`) and API
  (`pypts.api.Pts`) runs go through the same Sequencer, so they get the same scope.
- **Standalone**: `with pyhal.connect("bench.ini"):` in a plain script connects to the HAL
  server (starting one when none runs) and opens a scope, so the same test functions run
  outside PyPTS (*The client*).
  A driver process that dies at once is noticed immediately: `_read_message()` waits in
  `LIVENESS_POLL_S` slices and checks that the process is alive, since a process that dies
  before it has taken over its end of the Pipe closes nothing that could be seen on Windows.
- **The HAL server dies**: its end of the Pipe closes, and the driver process calls `teardown()` and
  exits, once the call in progress returns. A call that never returns keeps the driver process
  alive. This net is skipped when a `teardown` call already ran (`_close()` sends one), so
  teardown runs exactly once at a device's end - never twice.
- **The teardown ladder** (`_close()`): one serialized escalation, and the only place a device
  is torn down. First `teardown()` on the live process; failing that - it hung, crashed or was
  stopped by a call timeout - a fresh driver process connects and tears down instead
  (`_rescue()`, within `RESCUE_TIMEOUT_S`, 10 s); failing that too, the ERROR line says the
  device `... could not be torn down and may still be energised: ...` and nothing tries again:
  the driver's stability is the driver's own job, not the framework's. A call that exceeds its
  timeout kills the stuck process and raises; the HAL server then runs the ladder at once
  (D44, *Under the HAL server* below). `Device 'x' disconnected.` is logged only when a teardown ran; a failed ladder
  ends on the ERROR line instead.
- **The orderly close during a run** (GUI close, CLI `exit`, `Pts.close()`) waits for the run
  (`sequencer/sequencer.md`, *Stop*): the step in progress finishes, the teardown steps run,
  and the run's `run_scope()` closes its devices as at any run end. On `SequencerStopped` CORE
  then closes its HAL link (`core/core.md`): `close_all`, or `shutdown` to a HAL it started.
- **The crash close during a run** (CLI Ctrl+C, the launcher's `stop_core()` once the
  frontend has ended, CORE's watchdog; `core/core.md`) waits for nothing: CORE closes its HAL
  link first (the long connection, then `close_all` or `shutdown`, its answer not waited for),
  sends the Stops and exits; the HAL tears the devices down. With a run open CORE logs a
  CRITICAL that the bench may still be energised.
- **Ctrl+C** (and, on Windows, Ctrl+Break) is ignored by driver processes
  (`driver_process_main()` calls `_ignore_keyboard_interrupt()` first), as by CORE and the
  Logger: only the frontend, the launcher or the HAL server decides what it means.
- **Under the HAL server** (what PyPTS uses): a device opens on the first `open`
  or `call` that names it and stays open until `close`, `close_all`, `shutdown` or the
  exit's teardown closes it. **A client that is gone changes nothing on the bench** (D36): its
  devices stay open, exactly as they were. **D44:** a call that finds the driver process dead
  or killed (a call past `CALL_TIMEOUT_S`, a crash) gets its `DriverError`, and the HAL tears
  the device down at once on a fresh process (`Devices._rescue()`, WARNING `Device 'x' lost its
  driver process: ...`); the device is then closed, and the next request for it opens it again.
  A driver method that raises leaves the device open. The HAL never exits
  without running every open device's teardown ladder (*The HAL server*).

## Failure

| What happens | What test code sees |
|---|---|
| Driver raises | `DriverError("Device 'x': 'op' failed: Type: message")`; the device stays usable; traceback at DEBUG |
| Argument not picklable | `DriverError("Device 'x': the arguments of 'op' cannot be sent: ...")`; nothing was sent |
| Return value not picklable | `DriverError("Device 'x': 'op' failed: TypeError: 'op' returned a value that cannot be sent: ...")` |
| Argument cannot be unpickled in the driver process | `DriverError("Device 'x': 'op' failed: <Type>: the call could not be read in the driver process: ...")` |
| Return value cannot be unpickled in the HAL server | `DriverError("Device 'x': the answer 'op' could not be read: ...")` |
| Call exceeds `CALL_TIMEOUT_S` (30 s) | `DriverError("... did not answer 'op' within N s; its driver process was stopped.")`; the HAL server then tears the device down at once (D44) and the next request opens it again |
| Driver process dies | `DriverError("Device 'x' stopped unexpectedly (exit code N).")` |
| Cannot import / build / connect | `DriverError("Device 'x' could not be opened: ...")`, or the failed `'connect'` |
| Driver file missing, or a file without a class | `DriverError("Device 'x' could not be opened: ValueError: Driver file '...' does not exist.")` / `... names a file but no class; write it as '...:ClassName'.` |
| Unknown device | `DriverError("No device 'x' is configured. Add a [x] section to bench.ini. Configured devices: ...")` |
| Bench file discarded at startup (PyPTS: CORE's HAL link makes no connect and gives this reason through `note_unavailable()`, `core/hal_link.py`; `get_device()` raises it) | `DriverError("bench.ini was discarded at startup, so this start has no devices: ...")` |
| Section has no `driver` key | `DriverError("Device 'x': the [x] section has no 'driver' key naming its driver class.")` |
| `python` key in the section | `DriverError("Device 'x': the 'python' key is not supported any more ...")` |
| `driver` starts with `pypts.hal.` | `ValueError` (inside "could not be opened"): the hardware layer is `pyhal` now; write `pyhal.…` in bench.ini. A hint, not a compatibility shim |

**Through the HAL server**, the same errors arrive as `DriverError` with the HAL's text (the
driver's own texts in the table above are the HAL's too), and these are new:

| What happens | What test code sees |
|---|---|
| No HAL could be reached or started | `DriverError("No HAL server answered on 127.0.0.1:<port>.")` or `"The HAL server could not be started: <startup file tail>"`; `get_device()` repeats the reason |
| `get_device()` without a scope | `DriverError("No HAL scope is active. get_device() works in test code PyPTS is running, or inside 'with pyhal.connect(...)' in a script of your own.")` |
| `run_scope()` inside a scope | `DriverError("A HAL scope is already active; run_scope() does not nest. Connect with scope=False to manage scopes yourself.")` |
| A handle of a scope that has ended | `DriverError("Device 'x' belongs to a run that has ended; call get_device('x') again.")`; refused by the client, never reaches the HAL |
| The connection is closed (by the client's close, or the HAL dropped it) | `DriverError("The connection to the HAL server is closed.")` |
| The HAL closes the connection under a running request | `DriverError("The HAL server closed the connection while 'op' on device 'x' was running.")` |
| The HAL is shutting down | `DriverError("The HAL server is shutting down.")` |
| A lifecycle method called as an operation | `DriverError("Device 'x': 'teardown' is not an operation; the HAL server runs it itself.")` |
| An argument the protocol cannot carry | `DriverError("Device 'x': the arguments of 'op' cannot be sent: <path: type cannot be sent>")`; nothing was sent |
| A result the protocol cannot carry or that is over 16 MiB | `DriverError("'op' ran, but its result cannot be sent: ...")` / `DriverError("'op' ran, but its result is too large to send: N bytes.")` |
| A malformed line | `DriverError("HAL protocol error: <reason>")`; the HAL ends that connection |
| The driver process dies, or a call times out (D44) | `DriverError` as in the table above; the HAL has already torn the device down, and the next request opens it again |

Uncaught in test code, each makes the step ERROR through the normal step path. Nothing recovers
on its own: test code calls `recover_device(device)`, which escalates until the device is usable or
hopeless — the driver's own `recover()` (teardown + connect, overridable) while the process
lives; when that fails or the process is gone, teardown (`_close()`) and a fresh process with
`connect()`. Only when the fresh process cannot connect does a `DriverError` reach test code.

## Logging

The device lines below are written by the driver layer, which runs in the HAL server: they go
into the HAL's log file (*Logs*).

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

1. Derive from the device type it belongs to (`from pyhal import PSU`), never from
   `BaseDriver` directly: a driver of no device type is refused.
2. Implement `connect(config)` (all values are text), `teardown()` and the device type's verbs.
   Every other public method becomes an operation too. **`teardown()` is where the instrument
   is left safe** - outputs and loads off - and then disconnected. There is no separate
   safe-state method: teardown runs at every orderly end of a device, on a fresh connection
   when the driver was stuck (the ladder's rescue rung), so it must work right after
   `connect()` on an instrument in any state, and be harmless when nothing is open. A crash
   close, or CORE crashing, skips it (*Lifetime*).
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
`[serial]` pyserial, `[hardware]` all three. `.gitignore` carries `!/src/pyhal/drivers/`
because its bare `drivers` rule would otherwise hide the shipped drivers.

## Known gaps

- A call blocked inside a driver is not interrupted by Stop; `CALL_TIMEOUT_S` (30 s) bounds it.
- No side channel for bulk data: a waveform is pickled through the Pipe.
- Log records and printed lines are read only while the HAL server waits for a call. Records from a
  driver's own threads between calls (paramiko's transport thread at DEBUG, say) wait in the
  Pipe. They are logged late, stamped with the time the HAL server read them, and once the Pipe's buffer
  is full every thread of the driver process that logs or prints blocks until the next call.
- `sys.stdout` / `sys.stderr` in the driver process are a line forwarder, not a real stream:
  `encoding` is `None`, and there is no `buffer` and no `fileno()`.
- A rescue reconnects with the same settings; an instrument that refuses a second connection
  while the first is half-open, or a `connect()` slower than `RESCUE_TIMEOUT_S` (an SSH host
  with a long `connect_timeout_s`), cannot be torn down this way.
- Output a C library writes straight to the process's file descriptors (not through
  `sys.stdout`) is not forwarded. It goes to the HAL server's own output: its console, or `hal_startup.log` for a HAL a
  client started.
- No automatic recovery policy, only `recover_device()` from test code.
- **HAL server, known gaps** (phase 2):
  - Windows does not honour append mode on the startup file's inherited handle: in a rare
    double start (two starters at once) the tail of `hal_startup.log` can be garbled. (The
    window a HAL opens does not share the file: it writes to `hal_monitor_startup.log`.)
  - Closing the console window of a HAL started by hand ends the HAL's driver processes with it
    (they ignore Ctrl+C and Ctrl+Break, not a console close), and Windows kills the HAL about
    5 s after the close event, which is less than one close ladder. A HAL started by a client
    has no console and is not affected.
  - A HAL frozen with its socket open freezes the waiting test: there is no client-side
    deadline (D57).
  - A thread that test code started in one run can get a fresh handle in the next run
    (`get_device()` in the new scope): the fence covers the handles, not the one-per-process
    scope slot.
  - The origin of an `error` (`driver` or `hal`) is decided from its text (`_DRIVER_RAISED` in
    `server.py`, a pattern on `Device 'x': 'op' failed: `), because a `DriverError` carries no
    origin: a HAL-side error whose text began like that would be called `driver`.
  - `run_scope()` does not nest. A script that wants its own scopes connects with
    `scope=False`.
  - A `call` line already in the HAL's receive buffer when its client hangs up can still run
    after the short connection's `close_all`, if that connection's thread is starved until the
    `close_all` has run; it then opens the device again (D44). The device is closed again by
    the next `close`, `close_all` or the HAL's exit.
  - **Reconnecting at once after closing a HAL you started:** `connect()` waits for a HAL that
    is shutting down only when it replaces a client that was never closed. After an explicit
    `close()` (or the end of a `with`), a `connect()` right away can still be welcomed by that
    HAL before it has read the `shutdown`; the HAL then exits and the new client's calls fail
    (D28). Nothing stays open: the HAL's exit tears every device down.
- No PSU, DMM, Scope or Load driver ships yet; only the device-type bases.
- Every driver runs on the HAL server's Python: a vendor library that needs another interpreter
  (for example a 32-bit DLL) is not supported.
