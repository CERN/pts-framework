<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# HAL server, phase 2 of 4: the standalone server and client in `pyhal` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. **Never `git add`, `git mv`, `git commit`, `git stash`
> or `git checkout`** — the user commits everything himself. Skip every "commit" step.

**Goal:** `python -m pyhal` runs a HAL server on localhost TCP; `pyhal.connect()` connects to it
or starts one; scripts use it. PyPTS still runs its devices in-process (`LocalSetup` in the
Sequencer) until phase 3.

**Architecture:** three protocol layers (typed messages, value domain, JSON-lines codec); a
server with one connection thread per client, one FIFO request queue and one request thread
that owns every `ConnectionDriver`; a client with a long connection (request lock + write lock,
a beat thread), device handles fenced by a scope counter, a log tail, and "the close" on short
connections. `connection_driver.py` stays the driver-process machinery, unchanged except where a
task says so.

**Tech Stack:** Python ≥ 3.11 standard library only in `pyhal` (`socket`, `threading`, `json`,
`subprocess`, `argparse`, `logging`, `secrets`, `hashlib`); pytest.

**Spec:** `docs/superpowers/specs/2026-11-04-hal-server-design.md` rev 5 — §5 (D15-D18, D21,
D22, D25, D27, D29, D30, D32, D36-D38, D40, D42, D44, D45, D47-D57), §6.1-§6.6, §6a, §7, §9, §11.

## Global Constraints

- `pyhal` never imports `pypts` (quality test `tests/quality_tests/test_pyhal_independence.py`).
- `pyhal/__init__.py` stays import-light: the client names are reached through a module-level
  `__getattr__` that imports `pyhal.client` on first use (§6a). A driver process importing
  `from pyhal import PSU` must not import `socket`.
- Bind `127.0.0.1` only. Windows: `SO_EXCLUSIVEADDRUSE`; Linux: `SO_REUSEADDR`. Port taken →
  the HAL exits with an error naming the port (D56).
- JSON, one UTF-8 object per line, `\n`; `allow_nan=False`; NaN/Infinity refused on input; max
  line `MAX_MESSAGE_BYTES = 16 * 1024 * 1024` (D32).
- One request outstanding per connection, no request ids (D18). One FIFO queue for all clients,
  one request thread (D52). `status` and `beat` are not queued.
- No client-side deadline on an answer (D57). The `hello` wait is bounded:
  `HAL_START_TIMEOUT_S = 15.0` on the long connection, `SHORT_CONNECT_TIMEOUT_S = 1.0` (connect
  and `hello`) on a short one.
- Client watchdog: `CLIENT_BEAT_S = 1.0`, `CLIENT_SILENCE_S = 5.0`; a client with a request
  queued or running is never silent (§7.5).
- Existing `DriverError` texts of `pyhal.md` *Failure* stay; new texts are exactly as this plan
  gives them.
- `%`-style logging through `logging.getLogger(__name__)`; technician lines keep today's text.
- Plain, old-school Python (CLAUDE.md): `match`/`case` closed with `unhandled()` for message
  handling; line length 100; `pytest tests` green at the end.
- Tests never use the default port: every test gets a free port from a fixture.

## Review Focus

1. A client that disconnects with a `close_all` sent but unread: the HAL still runs it (Task 3
   test `test_close_all_runs_after_the_client_has_gone`).
2. A slow call (> `CLIENT_SILENCE_S`) on the long connection: the client is not dropped (Task 4
   test `test_a_long_call_does_not_get_the_client_dropped`).
3. A stray thread's queued `call` after the client closed its long connection: dropped, so it
   cannot reopen a device behind a `close_all` (Task 3 test
   `test_a_gone_clients_queued_calls_are_dropped_but_its_close_all_runs`).
4. A driver call that times out: the device is torn down at once on a fresh process (D44)
   (Task 2 test `test_a_call_timeout_rescues_the_device_at_once`).
5. Two starters at once: one HAL runs, each starter knows whether it started it (Task 5 test
   `test_two_starters_get_one_hal_and_one_owner`).

---

### Task 1: The protocol — values, messages, codec

**Files:**
- Create: `src/pyhal/protocol/__init__.py` (empty docstring module), `values.py`, `messages.py`,
  `codec.py`
- Test: `tests/unit_tests/test_pyhal_protocol.py`

**Interfaces:**
- Produces `pyhal.protocol.values`: `PlainValue` (recursive type alias: `None | bool | int |
  float | str | bytes | list[PlainValue] | dict[str, PlainValue]`); `to_wire(value: Any, path:
  str = "value") -> Any` (validates and encodes tagged forms; raises `ValueError` naming the
  path); `from_wire(value: Any) -> Any` (decodes tagged forms; a tuple never comes back).
  Exact types are checked (`type(x) is float`), so `numpy.float64` and `bool` subclasses of
  other types are refused; a tuple is accepted and sent as a list.
  Tagged forms: `{"$float": "nan" | "inf" | "-inf"}`, `{"$bytes": "<base64>"}`; a dict key
  starting with `$` in a value is refused. Error text: `f"{path}: {type_name} cannot be sent"`
  (e.g. `args[0]: ndarray cannot be sent`), `f"{path}: dict key {key!r} is not a string"`,
  `f"{path}: dict key {key!r} starts with '$'"`.
- Produces `pyhal.protocol.messages`: one frozen dataclass per message, field names exactly:
  - Client → HAL (`ClientToHal` union): `Open(device: str)`, `Call(device: str, operation: str,
    args: list[Any], kwargs: dict[str, Any])`, `Recover(device: str)`, `Info(device: str)`,
    `Close(device: str)`, `CloseAll()`, `Shutdown()`, `Status()`, `Beat()`.
  - HAL → client (`HalToClient` union): `Hello(pid: int, nonce: str | None, version: str, bench:
    str, bench_sha256: str, log: str, open: list[str], clients: int)`, `Opened(device: str,
    device_type: str, operations: list[str])`, `Result(value: Any)`, `Recovered(device: str)`,
    `DeviceInfo(device: str, device_type: str, operations: list[str], is_open: bool)`,
    `Closed(device: str)`, `ClosedAll(not_torn_down: list[str])`, `Bye()`, `StatusReport(pid:
    int, version: str, bench: str, log: str, clients: int, busy: dict[str, Any] | None, queued:
    int, devices: list[dict[str, Any]])`, `Error(origin: str, message: str)` — origin one of
    `"driver"`, `"hal"`, `"protocol"`.
  - Kind strings: the snake_case of the request (`open`, `call`, `recover`, `info`, `close`,
    `close_all`, `shutdown`, `status`, `beat`) and for answers `hello`, `opened`, `result`,
    `recovered`, `info`, `closed`, `closed_all`, `bye`, `status`, `error`.
  - `CLIENT_KINDS: dict[str, type]` and `HAL_KINDS: dict[str, type]`; `kind_of(message) -> str`;
    `build(table, kind: str, **fields) -> message` (unknown kind or field → `ValueError` before
    anything is encoded, D30); `unhandled(message: Never) -> NoReturn`.
- Produces `pyhal.protocol.codec`: `MAX_MESSAGE_BYTES = 16 * 1024 * 1024`; `MAX_DEPTH = 64`;
  `encode(message) -> bytes` (one line, `\n`-terminated; values through `to_wire`; raises
  `ValueError` naming the path, or `MessageTooLarge(size: int)` over the limit);
  `decode(line: bytes, table) -> message` (raises `MalformedLine(reason: str)` for bad UTF-8,
  bad JSON, NaN/Infinity, depth over `MAX_DEPTH`, not an object, unknown kind, wrong fields);
  `read_line(stream: BinaryIO) -> bytes | None` (None at end of stream; a line over
  `MAX_MESSAGE_BYTES` raises `MalformedLine("line too long")` without reading it all into
  memory beyond the limit + 1).

- [ ] **Step 1: Write the failing tests** — names and assertions:
  - `test_plain_values_round_trip`: `from_wire(json round trip of to_wire(v)) == v` for `None,
    True, 3, 2.5, "x", [1, "a"], {"k": [1.5]}`; a tuple `(1, 2)` comes back `[1, 2]`.
  - `test_nan_inf_and_bytes_use_tagged_forms`: `to_wire(float("nan")) == {"$float": "nan"}`,
    `to_wire(float("-inf")) == {"$float": "-inf"}`, `to_wire(b"\x00\xff") == {"$bytes":
    "AP8="}`; `from_wire` of each gives back the value (`math.isnan`).
  - `test_refused_values_name_their_path`: `to_wire({"a": [object()]})` raises
    `ValueError("value['a'][0]: object cannot be sent")`; `{1: 2}` → `"value: dict key 1 is not
    a string"`; `{"$x": 1}` → `"value: dict key '$x' starts with '$'"`; a float subclass
    instance (`class F(float)`) is refused.
  - `test_every_kind_has_a_dataclass_and_every_union_member_a_kind`: `set(CLIENT_KINDS.values())
    == set(get_args(ClientToHal))`, same for HAL.
  - `test_build_refuses_a_misspelt_kind_or_field`: `build(CLIENT_KINDS, "cal")` and
    `build(CLIENT_KINDS, "open", devise="x")` raise `ValueError`.
  - `test_encode_decode_round_trip_for_every_kind`: one instance per dataclass.
  - `test_decode_refuses_malformed_lines`: `b"not json\n"`, `b'{"kind":"open"}\n'` (missing
    field), `b'{"kind":"nope"}\n'`, `b'{"kind":"result","value":NaN}\n'`, 70 nested lists,
    `b"\xff\n"` → `MalformedLine`.
  - `test_an_oversized_message_is_refused_before_sending`: a `Result` of a 17 MiB string →
    `MessageTooLarge`.
  - `test_read_line_stops_at_the_limit`: a `BytesIO` of `MAX_MESSAGE_BYTES + 10` bytes and no
    newline → `MalformedLine("line too long")`.
- [ ] **Step 2: Run** `pytest tests/unit_tests/test_pyhal_protocol.py -v` → FAIL (import error).
- [ ] **Step 3: Implement** the three modules. `decode`: `json.loads(..., parse_constant=<raise>)`,
  then a depth walk; build the dataclass with `build()`, then `from_wire` on `args`, `kwargs`,
  `value`.
- [ ] **Step 4: Run** the test file → PASS; `pytest tests/quality_tests -q` → PASS.

### Task 2: The devices — open, close, close_all, rescue at once (D44)

**Files:**
- Create: `src/pyhal/bench.py`, `src/pyhal/devices.py`
- Modify: `src/pyhal/connection_driver.py` (`_close()` returns `bool`)
- Modify: `src/pyhal/local_setup.py` (imports `split_section`, `anchor_driver_files`,
  `ini_device_sections` from `pyhal.bench` instead of defining them; drop `from_ini()` and its
  text in `get_device()`'s refusal — D12)
- Test: `tests/unit_tests/test_pyhal_devices.py`; move the `split_section` /
  `anchor_driver_files` / `ini_device_sections` tests of `test_hal.py` to it, importing from
  `pyhal.bench`; delete tests of `from_ini()`.

**Interfaces:**
- Produces `pyhal.bench`: `split_section`, `anchor_driver_files`, `ini_device_sections` (moved
  verbatim from `local_setup.py`); `read_bench(path: Path) -> tuple[dict[str, dict[str, str]],
  str]` — the anchored sections and the SHA-256 hex of the file's bytes.
- Produces `ConnectionDriver._close() -> bool`: True when teardown ran (on the live process or by
  rescue) or there was nothing to tear down; False when the ladder ended on the ERROR line.
- Produces `pyhal.devices.Devices(sections: Mapping[str, Mapping[str, str]])`, used by one
  thread only (the request thread), no lock of its own:
  - `open(name: str) -> tuple[str, list[str]]` — device type and operations; opens on first use
    or reuses; unknown name → `DriverError` with today's `No device '...' is configured...` text.
  - `call(name: str, operation: str, args: list, kwargs: dict) -> Any` — opens the device first
    if it is not open (D44's "the next request opens it again"); a `DriverError` raised while
    the device's process is gone (`not device._is_open()` after the call) → `_close()` at once
    (the rescue), the device is dropped from the open set, and the original `DriverError` is
    re-raised. A driver that merely raises leaves the device open.
  - `recover(name: str) -> None` (`device._recover()`), `info(name: str) -> tuple[str,
    list[str], bool]`, `close(name: str) -> bool`, `close_all() -> list[str]` (names not torn
    down, newest first order of closing), `open_names() -> list[str]` (in opening order),
    `snapshot() -> list[dict]` (one dict per bench device: `name`, `device_type`, `state` in
    `"configured" | "open" | "failed"`, `last_error: str | None`).
- Keeps: the call timeout path in `ConnectionDriver._read_message()` (kill, raise) — the rescue
  happens in `Devices.call()`, so the in-process `LocalSetup` keeps today's behaviour until
  phase 3.

- [ ] **Step 1: Failing tests** (loopback and `hal_test_drivers.MarkingDriver`, real driver
  processes, as `test_hal_connection.py` does):
  - `test_open_reuses_an_open_device`: `open("loop1")` twice → one driver process
    (`call(..., "process_id")` equal before/after).
  - `test_call_opens_a_closed_device`: after `close("loop1")`, `call("loop1", "echo", [5], {})
    == 5`.
  - `test_a_crashed_driver_is_rescued_at_once`: add to `tests/unit_tests/hal_test_drivers.py`
    `class CrashingMarkingDriver(MarkingDriver)` with `crash(self, exit_code)` calling
    `os._exit(exit_code)`. `call("m1", "crash", [3], {})` → `DriverError` matching `stopped
    unexpectedly`; the marks file ends `connect\nteardown\n` (the rescue ran before `call`
    returned); `open_names() == []`.
  - `test_a_call_timeout_rescues_the_device_at_once`: MarkingDriver with a 1 s call timeout
    (`Devices(..., call_timeout_s=1.0)` — add this keyword, default `CALL_TIMEOUT_S`, passed to
    `ConnectionDriver`); `call("m1", "hang", [5], {})` → `DriverError` matching `did not answer`;
    marks end with `teardown`.
  - `test_a_driver_that_raises_stays_open`: loopback `fail` → `DriverError`, `open_names() ==
    ["loop1"]`.
  - `test_close_all_closes_newest_first_and_lists_failures`: two MarkingDrivers sharing one
    marks file, second's teardown hanging forever (`.tdhang`) with `RESCUE_TIMEOUT_S`
    monkeypatched to 1 s and call timeout 1 s → `close_all() == ["m2"]`, and `m2`'s close came
    first.
  - `test_snapshot_lists_every_bench_device`.
  - `test_read_bench_returns_sections_and_hash` (tmp file; hash equals `hashlib.sha256(bytes)`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new file plus
  `test_hal.py` and `test_hal_connection.py` → PASS.

### Task 3: The server

**Files:**
- Create: `src/pyhal/server.py`, `src/pyhal/hal_log.py`
- Test: `tests/unit_tests/test_pyhal_server.py` (server in a thread of the test process; a tiny
  raw-socket test client helper in the test file that reads `hello` and sends/receives lines
  with `pyhal.protocol.codec`)

**Interfaces:**
- Consumes Task 1 (`codec`, `messages`), Task 2 (`Devices`, `read_bench`).
- Produces `pyhal.hal_log`: `LOG_FORMAT = "%(asctime)s.%(msecs)03d;%(levelname)s;%(name)s;%(message)s"`,
  `DATE_FORMAT = "%Y-%m-%d %H:%M:%S"`, `TRACE = 5` registered as `"TRACE"`;
  `RECORD_START = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3};")` (a line that does not
  match continues the previous record); `default_log_dir() -> Path` (Windows
  `%LOCALAPPDATA%\pyhal\logs`, else `$XDG_STATE_HOME` or `~/.local/state`, then `pyhal/logs`);
  `start_log_file(log_dir: Path, level: int) -> Path` (file `hal_<YYYYmmdd_HHMMSS>_<pid>.log`,
  handler on the root logger, flushed per record).
- Produces `pyhal.server.HalServer(bench_path: Path, port: int, *, nonce: str | None = None,
  log_path: str = "", call_timeout_s: float = CALL_TIMEOUT_S)`:
  - `start() -> None` — binds (port taken → `OSError`, the caller exits) and starts the accept,
    request and watchdog threads (named `HAL accept`, `HAL requests`, `HAL watchdog`; one
    `HAL client <n>` per connection); `serve_until_stopped() -> None` — blocks until the server
    has exited (after its teardown); `request_exit(reason: str) -> None` — the one exit path
    (thread-safe, idempotent): stop accepting new clients (they get `Error("hal", "The HAL
    server is shutting down.")` instead of `hello`), empty the queue except the `close_all` /
    `shutdown` that caused it, let the running request finish, then the request thread runs the
    teardown (`Devices.close_all()`), logs each device not torn down at ERROR with today's
    "may still be energised" line already logged by the ladder, closes the listener last, exits.
    If the request thread is dead, the thread calling `request_exit` runs the teardown.
  - `port` attribute (the bound port; tests pass 0 and read it back).
  - The connection thread: sends `Hello` (pid, nonce, `version` =
    `importlib.metadata.version("pts-framework")` or `"unknown"`, bench absolute path, its
    SHA-256, `log_path`, `Devices.open_names()` as last snapshotted, number of other clients);
    reads lines; `Beat` → resets the silence clock (any line does); `Status` → answered at once
    from a snapshot the request thread refreshes after each request (`busy` =
    `{"device", "operation", "since"}` of the running request or None; `queued`);
    everything else → the queue with the connection. A malformed or oversized incoming line →
    `Error("protocol", ...)` written if possible, then the connection is closed.
  - The request thread: takes `(connection, request)` FIFO; runs it on `Devices`; writes the
    answer only to that connection, and only if it is still connected; a `DriverError` → `Error`
    with origin `"hal"` when its text is the HAL's own (timeouts, stopped unexpectedly, not
    configured, could not be opened, not open) and `"driver"` when it is `Device 'x': 'op'
    failed: ...` (the driver raised); a result that `codec.encode` refuses → `Error("hal",
    f"'{operation}' ran, but its result cannot be sent: {reason}")` or `... is too large to
    send: {size} bytes.`; `Shutdown` → `close_all`, `Bye`, then `request_exit("shutdown")`;
    `CloseAll` → `ClosedAll(not_torn_down)`.
  - A client is gone (EOF, reset, write failure, or dropped by the watchdog): its queued `Open`,
    `Call`, `Recover`, `Info` are removed; its queued `Close`, `CloseAll`, `Shutdown` stay; a
    request of its that is running finishes and its answer is discarded. The bench is untouched
    (D36). Log at DEBUG.
  - The watchdog: every 0.5 s, drops a client silent for `CLIENT_SILENCE_S` that has nothing
    queued or running.
  - Any server thread dying with an exception → logged at ERROR, `request_exit("thread died")`.

- [ ] **Step 1: Failing tests** (bench = tmp INI with `loop1` = LoopbackDriver and, where
  needed, MarkingDriver devices; each test starts `HalServer(..., port=0)` and stops it with a
  `Shutdown` in teardown):
  - `test_hello_names_the_hal`: fields `pid == os.getpid()`, `nonce`, `bench`, `bench_sha256`,
    `open == []`, `clients == 0`.
  - `test_a_call_round_trip`: `open` → `Opened(device_type="Other", ...)`; `call echo [{"$float":"nan"} as NaN]`
    → `Result` NaN.
  - `test_driver_errors_and_hal_errors_carry_their_origin`: `fail "boom"` → `Error("driver",
    "Device 'loop1': 'fail' failed: RuntimeError: boom")`; `open "nope"` → origin `"hal"`, text
    starts `No device 'nope' is configured.`
  - `test_two_clients_share_a_device_fifo`: two connections, interleaved `call echo` → each gets
    its own answer; a `sleep 1` from A delays B's `echo` (B's answer arrives after A's).
  - `test_an_answer_goes_only_to_its_connection`.
  - `test_status_is_answered_while_a_call_runs`: A runs `sleep 2`; B's `status` answers within
    0.5 s with `busy["operation"] == "sleep"`.
  - `test_close_all_runs_after_the_client_has_gone` (Review Focus 1): MarkingDriver open; client
    sends `close_all`, `shutdown(SHUT_WR)`, closes at once; marks file gets `teardown` within 5 s.
  - `test_a_gone_clients_queued_calls_are_dropped_but_its_close_all_runs` (Review Focus 3): A
    runs `call sleep 2`; meanwhile B sends `call echo`, then `close_all` is impossible on the
    same connection (D18), so B sends only `call echo` and closes; C sends `close_all` and
    waits. Assert C gets `ClosedAll([])` and `server.requests_run` (an `int` attribute the
    request thread increments per request it runs — add it to `HalServer`) is 2 (A's call and
    C's `close_all`), not 3. A second variant: B sends `close_all` and closes at once → it still
    runs (the MarkingDriver's marks end `teardown`).
  - `test_a_silent_client_is_dropped_and_the_bench_is_left_alone`: monkeypatch
    `CLIENT_SILENCE_S` to 0.5; open `loop1`, stay silent; after 1.5 s the socket reads EOF and a
    new client's `hello.open == ["loop1"]`.
  - `test_a_waiting_client_is_not_dropped`: silence 0.5 s; `call sleep 2` → `Result` arrives.
  - `test_shutdown_closes_every_device_then_exits`: MarkingDriver open; `shutdown` → `Bye`;
    marks end `teardown`; `serve_until_stopped()` returns; a new connect is refused.
  - `test_a_new_client_is_refused_while_shutting_down`: MarkingDriver whose teardown takes 2 s
    (`.tdhang_once` is 60 s — add `slow_teardown_s` key support to MarkingDriver: sleep that
    many seconds in teardown); during it a new connection gets `Error("hal", "The HAL server is
    shutting down.")`.
  - `test_a_malformed_line_closes_only_that_connection`.
  - `test_an_oversized_result_is_an_error_and_the_connection_stays`: add
    `hal_test_drivers.BigResultDriver(Other)` with `big(self, megabytes)` returning
    `"x" * (megabytes * 1024 * 1024)`; `call big [17]` → `Error("hal", ...)` whose message
    matches `'big' ran, but its result is too large to send: \d+ bytes\.`; the next `call` on the
    same connection works.
  - `test_the_log_file_records_device_lines` (`start_log_file` in tmp dir, `Device 'loop1'
    connected.` present, every record line matches `RECORD_START`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS (no thread or
  driver process left behind: assert `multiprocessing.active_children() == []` in a fixture
  teardown).

### Task 4: The client — long connection, handles, scope and fence

**Files:**
- Create: `src/pyhal/client.py`
- Modify: `src/pyhal/__init__.py`: lazy `__getattr__` for `connect`, `run_scope`,
  `close_device`, `HalClient`, `DEFAULT_PORT` (imports `pyhal.client` on first use).
  **Transition dispatch until phase 3** (*Ruling:* PyPTS still runs devices in-process, and
  recipes and test code import `from pyhal import get_device`; re-pointing them now and back in
  phase 3 is churn): `pyhal.get_device(name)`, `pyhal.recover_device(device)` and
  `pyhal.device_info(device)` become small functions in a new `src/pyhal/dispatch.py`, exported
  from `__init__`. `get_device` uses the client's scope when `"pyhal.client" in sys.modules`
  and a client scope is active, else `pyhal.local_setup.get_device` (today's in-process path,
  unchanged texts). `recover_device` / `device_info` go by the handle's type (`client.Device`
  or `ConnectionDriver`). `dispatch.py` imports neither `socket` nor `pyhal.client` at module
  level. Its docstring says phase 3 removes the in-process branch.
- Test: `tests/unit_tests/test_pyhal_client.py` (server from Task 3 in a thread on a free port)

**Interfaces:**
- Consumes Tasks 1 and 3.
- Produces in `pyhal.client`:
  - `DEFAULT_PORT = 50555`; `CLIENT_BEAT_S = 1.0`; `HAL_START_TIMEOUT_S = 15.0`;
    `SHORT_CONNECT_TIMEOUT_S = 1.0`.
  - `class HalClient`: `hello: Hello`, `started_hal: bool`, `port: int`;
    `send(kind: str, **fields) -> HalToClient` (D30; builds, encodes, writes under the write
    lock, reads the answer under the request lock; `Error` answers raise `DriverError` —
    origin `"driver"`/`"hal"` verbatim, `"protocol"` as `DriverError(f"HAL protocol error:
    {message}")` logged at ERROR; a closed connection raises `DriverError(f"The HAL server
    closed the connection while {what} was running.")` where `what` is `'op' on device 'x'` for
    a call, else the kind); `close() -> None` (Task 5 fills in the close; here it only closes
    the long connection and stops the beat thread); `__enter__` / `__exit__` (calls `close()`).
  - `connect_only(port: int = DEFAULT_PORT, *, scope: bool = True) -> HalClient` — connect, read
    `hello` within `HAL_START_TIMEOUT_S`, start the beat thread (`HAL beat`, daemon), make it
    the process's client; with `scope=True` open a scope (scripts). Raises `DriverError("No HAL
    server answered on 127.0.0.1:<port>.")` when nothing listens.
  - Module state: `_client: HalClient | None`, `_scope_counter: int`, `_scope_active: bool`,
    `_scope_devices: list[str]`, one `threading.Lock` for them.
  - `class Device` (the handle): `_name`, `_device_type`, `_operations`, `_scope` (counter at
    creation); `__getattr__` as `ConnectionDriver.__getattr__` (same `AttributeError` text);
    every request checks the fence under the request lock in the same step as the send.
  - `get_device(name: str) -> Device` — outside a scope raises `DriverError("No HAL scope is
    active. get_device() works in test code PyPTS is running, or inside 'with
    pyhal.connect(...)' in a script of your own.")`; no client → `DriverError` with the D21
    reason the client remembers (`_connect_problem`), or `"Not connected to a HAL server."`.
  - `recover_device(device: Device) -> None`, `device_info(device: Device) -> DeviceInfo` (a
    round trip; `DeviceInfo` is `pyhal.device_control.DeviceInfo`), `close_device(device:
    Device) -> None` (D55).
  - `run_scope()` — context manager: on entry the slot is filled and the counter raised; on exit
    (never raises) clear the slot and raise the counter (no lock beyond the module lock), send
    `close` for each device the scope asked for, newest first, waiting for each, log a failure
    as `Device '%s' did not close: %s` at WARNING, then drain the log tail (Task 6; a no-op
    until then).
  - Stale handle: `DriverError(f"Device '{name}' belongs to a run that has ended; call
    get_device('{name}') again.")`.
- [ ] **Step 1: Failing tests:**
  - `test_get_device_calls_through_the_hal` (`echo`, `settings`).
  - `test_a_handle_refuses_unknown_operations_without_a_round_trip` (same text as today's
    `ConnectionDriver`).
  - `test_get_device_outside_a_scope_is_refused` (exact text above).
  - `test_a_stale_handle_is_refused_after_the_scope_ends` (exact text).
  - `test_the_scope_closes_its_devices_newest_first` (MarkingDriver ×2, one marks file).
  - `test_driver_and_hal_errors_reach_test_code_verbatim`.
  - `test_unsendable_arguments_are_refused_before_sending`: `echo(object())` → `DriverError`
    naming `args[0]`; the connection still works.
  - `test_a_long_call_does_not_get_the_client_dropped` (Review Focus 2): monkeypatch the
    server's `CLIENT_SILENCE_S` to 0.5 and `CLIENT_BEAT_S` to 0.1; `sleep(2)` returns normally.
  - `test_threads_take_turns_on_the_long_connection`: two threads each `echo` 50 times → every
    answer is its own value.
  - `test_the_server_going_away_fails_the_waiting_call`: `sleep(5)` in a thread, server
    `request_exit` → the call raises `DriverError` matching `closed the connection`.
  - `test_import_pyhal_stays_light`: in a subprocess, `python -I -c "import sys, pyhal;
    from pyhal import PSU; print('socket' in sys.modules, 'pyhal.client' in sys.modules)"` with
    `src` on `sys.path` → `False False`.
  - `test_top_level_get_device_uses_the_client_scope_or_the_local_setup`: inside
    `with LocalSetup(...)` and no client → a `ConnectionDriver`; inside a client scope → a
    `client.Device`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the file plus
  `test_sequencer.py`, `test_hal*.py`, `test_recipe.py` → PASS.

### Task 5: Connect or start, the close, `python -m pyhal`

**Files:**
- Create: `src/pyhal/__main__.py`
- Modify: `src/pyhal/client.py` (`connect()`, the close, `atexit`)
- Test: `tests/functional_tests/test_pyhal_standalone.py` (real detached HAL processes on free
  ports, `--log-dir` in `tmp_path`; every test ends with `python -m pyhal --stop --port N`)

**Interfaces:**
- Produces `python -m pyhal` options: `--bench FILE` (required to serve), `--port N` (default
  `DEFAULT_PORT`), `--log-dir DIR` (default `default_log_dir()`), `--log-level LEVEL` (a number
  or a level name, `TRACE` included; default `INFO`), `--nonce TEXT`, and the two client modes
  `--close-all` / `--stop` (connect only; send `close_all` or `shutdown`; wait for the answer;
  print `Not torn down: <names>` or `Every device was torn down.`; exit 0, 1 when a device was not
  torn down, 2 when no HAL answered). Serving: start the log file, `HalServer(...).start()`, on
  `OSError` while binding print `Port <N> is in use; is another HAL server running?` to stderr
  and exit 3; install exit handlers (Ctrl+C / `SIGINT`, `SIGTERM`, `SIGHUP` where they exist,
  and on Windows a console control handler via `ctypes` for close/logoff/shutdown events) that
  call `request_exit()`; then `serve_until_stopped()`.
- Produces `pyhal.client.connect(bench: str | os.PathLike[str], port: int = DEFAULT_PORT, *,
  scope: bool = True, log_sink: Callable[[int, str], None] | None = None, log_level: int | None
  = None, log_dir: str | None = None) -> HalClient`:
  1. Try `connect_only`. A `hello` → compare version and bench (path after
     `os.path.normcase(os.path.realpath())`, and `bench_sha256`): WARNING naming both on a
     difference; open devices: WARNING listing them when `hello.clients == 0`, else DEBUG.
  2. An `Error("hal", "The HAL server is shutting down.")` instead of `hello` → retry every
     0.2 s until nothing listens, bounded by `HAL_SHUTDOWN_WAIT_S = 120.0`, then start.
  3. Nothing listens → start `sys.executable -m pyhal --bench <abs> --port <port> --nonce
     <secrets.token_hex(16)> [--log-level] [--log-dir]` detached (Windows: `creationflags =
     CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`; else `start_new_session=True`), `env` with
     `PYTHONPATH` = `os.pathsep.join(sys.path)` entries that exist, stdout/stderr to
     `<log dir>/hal_startup.log` (opened in append mode), stdin `DEVNULL`; retry the connection
     every 0.2 s until `HAL_START_TIMEOUT_S`; `started_hal = (hello.nonce == our nonce)`.
     Timeout → `DriverError(f"The HAL server could not be started: {tail}")` with the last 20
     lines of the startup file.
- Produces the close, `HalClient.close()` (idempotent; the same for `with` exit, explicit close,
  `atexit`): (1) raise the scope counter, end the scope without per-device closes, close the
  long connection; (2) open a short connection (connect and `hello` within
  `SHORT_CONNECT_TIMEOUT_S`); send one request — `Shutdown` if `started_hal`, else `CloseAll`;
  `sock.shutdown(SHUT_WR)`; close without reading. Nothing answers → DEBUG line, nothing else.
  `connect()` registers `atexit.register(client.close)`; `close()` unregisters it.
- [ ] **Step 1: Failing tests:**
  - `test_connect_starts_a_hal_and_close_stops_it`: `connect(bench, port)` → `started_hal`;
    after `close()`, within 10 s nothing listens on the port.
  - `test_connect_uses_a_running_hal_and_close_leaves_it_running`: start one with
    `subprocess` + `--port`; `connect()` → `started_hal is False`; after `close()` the port
    still answers `hello`, and a MarkingDriver opened by the client was torn down
    (`close_all`).
  - `test_two_starters_get_one_hal_and_one_owner` (Review Focus 5): two `connect()` in two
    threads at once → both connected to the same `hello.pid`, exactly one `started_hal`.
  - `test_port_in_use_exits_with_code_3`: a plain socket listening on the port; `python -m pyhal
    --bench … --port N` → exit code 3, stderr names the port.
  - `test_stop_and_close_all_command_line`: `--close-all` prints `Every device was torn down.`,
    exit 0; `--stop` then the port is free; `--stop` with no HAL → exit 2.
  - `test_a_bench_mismatch_warns_and_connects` (caplog WARNING naming both files).
  - `test_atexit_closes_a_script_without_with`: a script in `tmp_path` that calls
    `pyhal.connect(...)` then `get_device("m1").hang(0)` and exits without `close()` → the
    marks file ends `teardown`, the HAL it started has exited.
  - `test_connect_waits_for_a_hal_that_is_shutting_down`: HAL with a slow-teardown MarkingDriver
    open; `--stop` sent without waiting; `connect()` right after → a new HAL (different pid).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; no `python -m
  pyhal` process left running (assert in a session fixture by probing each port used).

### Task 6: The log tail

**Files:**
- Modify: `src/pyhal/client.py`
- Test: add to `tests/unit_tests/test_pyhal_client.py`

**Interfaces:**
- Produces `pyhal.client.LogTail(path: str, sink: Callable[[int, str], None])`: `start()`
  (thread `HAL log tail`, daemon, reads new records every 0.2 s from the file's size at start),
  `drain() -> None` (reads to end of file and calls the sink for every complete record, the last
  one included, synchronously; shares one lock with the thread, so no record is passed twice or
  out of order), `stop()`. A record = a line matching `hal_log.RECORD_START` plus the following
  lines that do not; the sink gets `(levelno, message)` where `levelno` comes from the level name
  (`logging.getLevelName`, `TRACE` = 5) and `message` is the record's message text with its
  continuation lines.
- `connect(..., log_sink=...)` starts a `LogTail` on `hello.log`; `run_scope()`'s exit calls
  `drain()` after its closes; `close()` stops it.
- [ ] **Step 1: Failing tests:** `test_the_tail_passes_new_records_with_their_level` (only
  records written after start); `test_drain_passes_the_last_record_at_once`;
  `test_a_multi_line_record_arrives_whole`; `test_the_scope_drains_the_teardown_lines` (server
  with `start_log_file`; after `run_scope()` exits, the sink already holds `Device 'm1'
  disconnected.`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.

### Task 7: Documents and the full gate

**Files:**
- Modify: `src/pyhal/pyhal.md`, `docs/Usage_manuals/usage_manual.html` (the scripts passage,
  `with pyhal.connect("bench.ini"):` instead of `LocalSetup.from_ini()`, `python -m pyhal`
  with its options and exit codes), `docs/Usage_manuals/how_to_write_a_driver.html` and `.md`
  (the standalone-test section: `pyhal.connect()`), `docs/Usage_manuals/pypts_implementation_status.html`
  (entry 1.99, phase 2 of 4), `tests/quality_tests/quality_tests.md` only if a quality test
  changed.

- [ ] **Step 1: `pyhal.md`** — new sections, each describing the code as built: *The HAL server*
  (threads, the queue, who is answered, gone clients, the watchdog, the exit), *The protocol*
  (the three layers, every kind with its fields, the value domain, errors and origins, size
  limit, examples of one exchange), *The client* (connect or start, the nonce, the long
  connection and its two locks, beats, handles and the fence, the scope, the close, `atexit`,
  the log tail), *python -m pyhal* (options, exit codes), *Logs* (file name, format,
  `RECORD_START`, default folder, `hal_startup.log`); *Files* table rows for every new module;
  *Lifetime* and *Failure* updated for D44 in the server and the new texts; state plainly that
  PyPTS still runs devices in-process (`LocalSetup`) until phase 3. `from_ini()` disappears from
  every section.
- [ ] **Step 2:** the manuals and status entry, as listed.
- [ ] **Step 3: Documentation check:** every identifier `pyhal.md` names exists
  (`git grep` each new name); `git grep -n "from_ini\|LocalSetup.from_ini" -- src docs/Usage_manuals tests resources`
  → only historical status entries.
- [ ] **Step 4:** `pytest tests` → PASS (ruff and mypy included).
