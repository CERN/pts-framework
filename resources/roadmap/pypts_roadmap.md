# PyPTS — Development Roadmap & Plugin Architecture Proposal

*Based on branch `architecture_refactor` (read from GitLab `origin/architecture_refactor`, July 2026) and the Confluence PTS Framework specification (Framework specification, General requirements, Milestones, workflow pages, and all 12 module pages).*

---

## 1. Where the branch stands today

The `architecture_refactor` branch is a real step toward the spec: the **process skeleton and communication plumbing are built**, while the **execution engine has not yet been ported into it**. It is a "walking skeleton" — everything boots, talks, and heartbeats, but pressing "run" executes nothing yet.

### What is already done ✓

| Area | State on the branch |
|---|---|
| Package layout | Matches the system design: `core/`, `sequencer/`, `recipe/`, `step/`, `report/`, `hmi/{gui,cli}/`, `config_handler/`, `logger/`, `stream_handler/`, `hardware_layer/`, `helper_applications/{recipe_creator,recipe_verificator,example_finder}/`, `utilities/`, `launcher/`, plus `old_code/` holding the previous engine |
| Process model | `launcher/startup.py`: argparse `--mode gui/cli/connect` (gui is the default) and `--log-level`, spawns Core as a process; Core spawns Sequencer and Report processes — exactly the spec's module diagram |
| Typed messaging | **Reworked (see §1.1).** `pypts/messages/`: one frozen dataclass per message, one union per link, one generic `Channel` for all six links, every handler closed with `unhandled()`. The enums, the interface ABCs and the queue data-layer classes are gone, and with them the 4-step "add a message" workflow — it is two steps now. Protocol tests in `tests/unit_tests/test_messages.py` |
| Health & errors | `HeartbeatManager` ticking from Sequencer/Report/HMI, Core-side timeout detection (armed only for modules still expected to run); `@catch_and_report_errors()` sending a typed `ModuleError` to Core, with the source resolved per function |
| GUI toolkit | **PySide6 migration done** (GUI skeleton + `test_pyside6_conversion.py`) — the PyQt6/LGPL conflict is resolved |
| Licensing | LGPL-2.1-or-later + CC-BY-SA-4.0, SPDX headers, `reuse.toml`, `licenses/`, `dependency_license_analysis.rst` — REUSE compliance largely in place |
| Logger | Single-writer Logger process: timestamped format (file:function, ms), file + stdout handlers, `set_stdout_logging_enabled()` toggle, and a level resolved once by the launcher from `--log-level` / config (§1.2) |
| Config handler | **Reworked (see §1.3).** `ConfigHandler` singleton in the per-user config directory (`platformdirs`), created from a commented template, versioned and migrated, typed access through a schema, single writer, comment-preserving writes. The launcher takes the log directory from it and Report the report directory |
| Recipe verificator | Substantial real implementation: YAML line-map extraction, faults vs warnings, per-steptype required fields, bulk folder validation, string-variable validation for the creator |
| Recipe creator | GUI application present (`recipe_creator.py`, custom GUI modules, styles) |
| Tests | `unit_tests/unit_tests/` + `functional_tests/` + `run_tests.py` (event proxy, recipe, report, steps, GUI, version…) |
| Resources | `resources/{recipes, example_commented_recipes, examples, images}` reorganization done |

### What is placeholder / not yet ported

1. **The execution engine.** `sequencer.run_sequence()` is `pass`; `recipe/recipe.py` is a one-line comment; `step/` is empty; Core's `LOAD_RECIPE` / `START_SEQUENCE` handlers are `pass`. The working engine (Recipe/Sequence/Step/Runtime/StepResult, the five step types, resource-based `test_package` module loading described in `architecture.rst`) lives in **`old_code/`** and is not reachable from the new launcher.
2. **Report module** — process shell with heartbeat exists; `generate_report()` / `export_report()` are `pass`. The CSV/HTML logic is in `old_code/report.py`.
3. **HAL** — `hal.py` is a one-line comment.
4. **Stream handler** — `StreamContainer` + an XYGraph widget spike; not integrated.
5. **GUI** — a minimal status window (status label + stop button); none of the spec's widget system, recipe preview, session persistence, etc. CLI has the interactive shell + `load_recipe`/`start_sequence` plumbing but no recipe/report/exit-code features yet. Neither frontend shows the message layer, and neither needs to: `--log-level DEBUG` puts every message on every link into the run log (§1.2).
6. **Step construction still uses `eval(step_type + "(**step_data)")`** in `old_code/recipe.py` — the closed, unsafe step factory rides along into whatever gets ported.

### Defects worth fixing early (spotted while reading the branch)

- **Broken import in the verificator:** `verify_recipe.py` does `from pypts import RECIPE_HEADER_REQUIRED_FIELDS, RECIPE_SEQUENCE_REQUIRED_FIELDS, STEP_REQUIRED_FIELDS`, but `src/pypts/__init__.py` is now minimal and defines none of these — the verificator cannot import. The schema constants need a proper home (see §3.5: make them part of the step/recipe schema layer).
- **`@catch_and_report_errors()` swallows results and errors:** *partially fixed.* The `nonlocal module_name` + `inspect.stack()[1]` bug is gone — the source is resolved from the decorated function at decoration time (`tests/unit_tests/test_utilities.py`). **Still open:** the wrapper returns `None` on an exception and does not re-raise, so a failing function silently continues, and it still assumes `self.core` exists on every decorated class. Dangerous once the sequencer executes real steps — errors must also propagate into StepResults, not only into Core events.
- **Heartbeat monitoring is one-directional and always-armed:** *partially fixed.* Core now only checks modules still expected to be running, so a module that has reported itself stopped no longer produces timeout warnings for the rest of the run. **Still open:** it is warn-only, with no recovery action, and Core sends no heartbeat of its own, so an HMI cannot detect a dead Core.
- **Per-process side effects at import:** *config half fixed (§1.3).* Reading the configuration no longer writes it, and only the launcher's `bootstrap()` may create or repair the file, so the per-process `config.ini` rewrites are gone. **Still open:** per-run log directories (spec: "separate logs by test run") — the log *directory* now comes from the configuration, but it is still one timestamped file per run rather than a per-run folder with a file per process.
- **Core deps got heavier, not lighter:** `pts-framework` now hard-depends on `matplotlib`, `numpy`, `nptdms`, `nidmm`, `hightime`, `pyserial`, `paramiko`, `PySide6`. For a framework whose spec demands "lightweight" and "tests executable stand-alone," this is the strongest argument for the plugin packaging model in §3.
- Two `TODO.txt` items confirm known issues: globals stored as a list not dict; GUI refresh problems.

### 1.1 Message layer rework — **done**

> **Status: implemented.** The enum + `payload: dict` protocol was replaced by one frozen
> dataclass per message. Rationale and the topology review that led to it are recorded
> separately; what matters here is the resulting contract and what it left open.

**What changed.** `pypts/messages/` now holds one module per link (`hmi_link`,
`sequencer_link`, `report_link`, `logger_link`), plus `common.py` for vocabulary two links
share and `run_events.py` for what the engine reports during a run. A single generic `Channel`
replaced the six interface ABC / queue-class pairs — about 200 lines where there were 612 — and
every handler is a `match` closed with `unhandled()` instead of `case _: pass`. Adding a message
is two edits rather than four, and both ends of a link are now one file.

**Defects this closed, each of which was invisible before:**

- Core had no branch for the HMI's error message, so every failure a frontend reported through
  `@catch_and_report_errors()` was silently discarded.
- The Sequencer had no branch for `STOP_SEQUENCE`, a command Core had a method to send.
- `sequence_result(text)` packed a result string under the key `"sequence_name"`.
- `run_sequence()` took no arguments, so the sequence name the operator chose stopped at Core.
- The CLI and the GUI answered `STOP` differently — the CLI never acknowledged, so Core could
  not reach a clean shutdown in CLI mode and was only ever killed by the launcher. Both
  frontends now share one implementation of the protocol (`hmi/hmi_client.py`).
- The launcher killed Core with `terminate()` as the primary path, orphaning the Sequencer and
  the Report. It now asks first and terminates only on timeout. Verified end to end: a CLI run
  reaches "All modules stopped cleanly" and exits 0 without the fallback firing.
- `poll_queue` handled one message per 10 ms tick, capping every link at ~100 messages/second.
  `Channel.drain()` takes a bounded batch.

**New TODOs this opened:**

- [ ] **TODO:** The Sequencer must run a sequence on its own worker thread before user-prompt
      steps are ported. `PendingRequests.wait()` blocks, and if it blocks the thread that drains
      the inbox the answer can never arrive — the module deadlocks. See `messages/requests.py`.
- [ ] **TODO:** Some old_code interaction steps read a *second* value off the same response
      queue after the first answer (a file path, a measured value, a `(port, baudrate, IDN)`
      triple). `UserPromptResponse` does not model this; each follow-up needs to become its own
      request when those steps are ported.
- [ ] **TODO:** Core does not yet trigger `GenerateReport` on `RunFinished`, or forward run
      events to the Report at all. That wiring belongs with the Phase 1 engine port.
- [ ] **TODO:** No type checker is configured, so `unhandled()` currently gives runtime
      exhaustiveness only. Adding mypy or pyright over `pypts/messages/` and the handlers turns
      a forgotten `case` into a build error — which is most of the value of the rework.
- [ ] **TODO:** The CLI's main thread is parked in `input()`, so a `StopHmi` from Core is only
      noticed after the next Enter. Pre-existing, and now the only remaining asymmetry between
      the two frontends.
- [ ] **TODO:** `--mode connect` is still unimplemented. When it lands it needs event fan-out
      from Core to several HMI channels; commands stay point-to-point. A string-topic event bus
      was considered and rejected — it would erase the explicit topology.
- [ ] **TODO:** Add the `QT_QPA_PLATFORM=offscreen` CI job. `tests/unit_tests/test_hmi_gui.py`
      has real tests now and they need it on the runner.

### 1.2 Message trace in the log (`--log-level`) — **done**

> **Status: implemented.** Replaces the `--mode debug` developer console, which was
> implemented and then removed. The framework has **one build**, and everything that
> happens in it is readable from the run log.

**Why the console went.** It worked, but it meant the software had two shapes: the product,
and the product plus a tap. Anything only visible under `--mode debug` is invisible on the
machine where it matters — a test bench, a colleague's laptop, a failure someone reports
afterwards. The debug build was ~1,900 lines (`hmi/debug/` 1,401, `messages/debug_link.py`
125, ~141 lines of branches in `channel.py` / `core.py` / `startup.py`, 247 of tests) and the
one thing it did that the log did not was see the *send* side.

**What replaced it.** `Channel.send()` and `Channel.receive()` each log one DEBUG line on a
`pypts.trace` logger, naming the link and the message:

```
2026-08-12 09:32:58.056;DEBUG;Core;channel.py:send;send core->sequencer StopSequencer()
2026-08-12 09:32:58.10?;DEBUG;Sequencer;channel.py:receive;recv core->sequencer StopSequencer()
```

Both directions, deliberately: a message that was sent and never received is the failure
worth seeing, and it is invisible to anything that only logs on arrival. Because the trace
sits on the one object every message already passes through, no module has to remember to log
anything and no new message can escape it — the two-step "add a message" procedure in
`src/pypts/README.md` is unchanged.

**Why it is at the transport, not in the handlers.** Same reason the tap was: Core does not
see the messages it never receives, so a Sequencer→Core send is only visible at the
`Channel`. It also survives the thread migration unchanged — the trace does not care which
queue type the Channel wraps. The handlers' old `log.info(f"Received … message: {message}")`
lines were removed, since `receive()` now covers all four of them and adds the link name;
INFO is left carrying only the narrative (lifecycle, recipe loaded, run started, errors).

**One dial.** `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}` overrides `[Application]
log_level` in `config.ini`, which now ships as `INFO`; `logger.parse_log_level()` falls back
to INFO rather than raising on a name it does not know, because the config value is read
before there is anywhere to report a traceback. The launcher resolves the level **once** and
passes it to every process as an argument — children must not read the config themselves,
because `read_config_key()` writes the file, and five processes rewriting it per run is the
defect at the top of this document, not a feature. Filtering therefore happens at the sender,
which is what makes the trace free when it is off: `%`-style arguments mean the `repr()` is
only paid when a handler is actually going to emit.

**What was given up.** The live filterable trace table, the injection UI, the generated
message form, and the Modules tab. Injection needed no product code to survive: `Core`
already takes `queue_factory`, so a test builds a Core that spawns nothing and calls
`core.from_sequencer.send(...)` directly — `test_core.py::test_a_sequencer_event_is_routed_to_the_hmi`
is the old injection test, rewritten that way.

**Verified:** 9 tests in `tests/unit_tests/test_channel_trace.py`, including that nothing is
traced above DEBUG, that a message is not even formatted when the trace is off, that a
message left on the queue is not traced as received, and that a broken log queue does not
stop the message it was tracing. Full suite: **136 passed, 77 skipped** (was 129/78).
Confirmed on Windows by running `--mode cli --log-level DEBUG` and reading the log: all six
links appear with matching send/recv pairs from four processes in one file, including
`core->sequencer` and `core->report`, which no frontend could ever see. At INFO the same run
produces zero trace lines.

- [x] **DONE — the "revert before v1.0" TODO is closed.** `--mode` defaulted to `debug` for
      the duration of the refactor; with the console gone the default is **`gui`** again, as
      Phase 3 intended. The four other console TODOs (trace export, `tuple[StepOutcome, ...]`
      editor, duplicated `HEARTBEAT_TIMEOUT_S`, injection union guard) died with it. Trace
      export in particular is now moot: the trace is a file.

**New TODOs this opened:**

- [ ] **TODO:** Heartbeat noise. Three modules × 1 Hz × two directions ≈ **6 trace lines a
      second** at DEBUG — about 170k lines in an 8-hour run. The fix is a `pypts.trace.heartbeat`
      child logger that can be silenced on its own. Deliberately not done yet: it would make
      `channel.py` import `Heartbeat` and type-test the payload, and the transport not knowing
      what a message *is* is the property that keeps it generic. Decide before Phase 1
      generates real traffic.
- [ ] **TODO:** `LOG_FORMAT` has no `%(name)s`, so a trace line is identified by the word
      `send`/`recv` and the `channel.py:send` location field rather than by `pypts.trace`.
      Adding the logger name touches every line of every log and the `LOG_LINE` regex in
      `test_logger.py` — worth doing, but on its own.
- [ ] **TODO:** Trace payloads are not truncated (the tap capped them at 2,000 chars). A file
      does not care and a large `RunFinished` is exactly what you want whole, but revisit if a
      real Phase 1 run shows the log queue backing up.
- [x] **DONE (§1.3):** An existing `%TEMP%/pypts/config/config.ini` saying `log_level = DEBUG`
      no longer affects anything: the config moved to the per-user config directory, so the
      old file is not read at all, and the handler now migrates rather than only creating.
      The stale file under `%TEMP%` is harmless and may be deleted by hand.
- [ ] **TODO:** `--mode cli` still imports PySide6, through `startup.py → hmi/gui/gui.py`.
      Removing the debug console did not fix this — deferring the GUI import into the `gui`
      branch is a one-line change nobody has made.
- [ ] **TODO:** Message-type introspection is no longer asserted anywhere. The deleted
      `test_every_message_type_can_be_built_from_the_form` was the only test proving every
      message has plain, introspectable fields. `test_messages.py` still pickles every message
      and fails on one with no example, so union coverage does not rot — but the weaker claim
      is now untested. Do not rebuild the form to get it back; a direct test would do.
- [ ] **TODO:** If a live developer tool is ever wanted again, it should be a separate
      distribution reading the log or subscribing through `pypts.api`, not a `--mode` inside
      the product.

---

### 1.3 Config handler rework — **done**

> **Status: implemented.** The four module-level functions writing an INI file into
> `%TEMP%` were replaced by a `ConfigHandler` singleton in the platform's per-user
> config directory, with a versioned structure, typed access and one writer.

**What was wrong.** Three things, all of them the same thing. `read_config_key()` called
`create_config_from_template()` first, so *every read rewrote the file*, comments and all —
five processes rewriting one file per run. The `[Paths]` section hardcoded `/tmp/pypts`,
wrong on Windows, and nothing read it: the log path was invented independently in
`utilities/local_storage.py`, and `[Application] log_level` was read for the launcher only.
And `%TEMP%` is cleaned up, so a bench's settings were one reboot from gone.

**The shape now.** Four small modules with one job each:

| File | Owns |
|---|---|
| `file_locations.py` | where the file is — `platformdirs`, and the seam tests monkeypatch |
| `configuration_schema.py` | what the file contains: section → key → type, default, allowed values; the deprecation map; `CONFIG_VERSION` |
| `template_writer.py` | writing without losing the comments |
| `config_handler.py` | the singleton: load, migrate, validate, get/set, dump |

**The decisions worth recording.**

- **INI stays.** The structure the spec asks for is carried by dotted section names —
  `[hardware.dmm1]` — and a schema that gives every key a type. `get_parameter()` returns a
  `Path`, an `int` or a `bool`, not a string.
- **One instance per *process*, not per application.** Spawn gives a child no memory of its
  parent, so each process builds its own handler and reads the same file. Nothing is passed
  through `Process(args=...)`, which is what keeps the child entry points unchanged.
- **Reading is pure.** Only `bootstrap()`, called once by the launcher before anything else
  exists, may create or repair the file. CORE is the only runtime writer.
- **Migration keeps user values.** A file from an older version has its renamed keys moved,
  its dead keys dropped and its new keys added; the previous file is kept as
  `config.ini.v<n>.bak`. A file from a *newer* pypts is refused rather than guessed at.
- **Derived paths, not shipped paths.** The template ships the path values blank; they are
  filled at creation from the platform's data directory. That is why no path in the template
  can be wrong on either platform — asserted by a test.
- **`configuration_schema.py` and `config_template.ini` are checked against each other** by
  `test_schema_and_template_agree`, which is the "config structure verification tool
  integrated into the pytest pipeline" the spec asks for. CI runs it already.

**Wired in.** `startup.py` takes the log directory from `paths.logs_dir` and the log level
from `logging.level`; `report.py` takes its output directory from `paths.reports_dir`;
`local_storage.get_log_file_path()` no longer decides a location, it is given one.

- [ ] **TODO:** `SetConfigParameter` (HMI→CORE) is **declared and not implemented** —
      CORE logs and ignores it, and nothing sends it. Two questions are open: whether CORE
      answers with a confirmation or an error, and how a process already running learns that
      a value it read at startup has changed. Until that is answered, a configuration change
      takes effect on the next start.
- [ ] **TODO:** Phase 5 should read `[hardware.<name>]` into a `DeviceConfig` and hand it to
      drivers by logical name. The section family and its validation exist; nothing consumes
      them.
- [ ] **TODO:** `report.type` / `report.theme` and the `[gui]` keys are read but not yet
      *used* — Phases 4 and 3 respectively.
- [ ] **TODO:** Move the plaintext SSH password out of
      `resources/recipes/comprehensive_recipe.yml:20` and into the configuration now that
      there is somewhere to put it. Rotate the credential if the host is live.
- [ ] **TODO:** `stdout_logging_enabled` is still derived from `--mode` rather than from the
      configuration. Probably correct — it follows from having a console, not from a
      preference — but it is the one logging decision the config does not own.

---

## TODO — Recipe format: findings and decisions

> **Status: analysed, parked.** The recipe refactoring itself is deferred — this section records
> what was found so it can be picked up later.
>
> - **`resources/roadmap/recipe_guide.md`** — full reference: what a recipe is, what the old
>   engine actually does with it, where the three rule sets disagree, 28 findings with
>   file:line evidence, and a proposed format for the new framework.
> - **`resources/roadmap/recipe_rules.html`** — the same rules condensed to one readable page
>   (open in a browser); good starting point for a review meeting.
>
> Read one of them before porting `recipe/`, `step/` or the verificator.

Recipe-format work items surfaced by that study (IDs refer to `recipe_guide.md` §16):

- [ ] **TODO:** Fix the behaviour bugs during the port, not after — F1 (header-level
  `continue_on_error` is inert), F3 (`main_sequence` overrides the requested sequence), F6
  (`output_mapping` is last-writer-wins, not all-must-pass), F8 (step-level `continue_on_error`
  leaks to later steps), F12 (mutable default `output_mapping` shared across steps), F13
  (`UserInteractionStep` swallows its own Cancel), F14 (`UserWriteStep` overwrites the typed
  value with the button key), F15 (`file_save_location: local` writes a global), F18 (teardown
  clears the abort flag), F25 (`IndexedStep` discards its output mapping).
- [ ] **TODO:** Decide and document whether `FAIL` (not just `ERROR`) stops a sequence — F7.
  Today only `ERROR` does, and it is documented nowhere.
- [ ] **TODO:** Collapse the **three** disagreeing rule sets (`recipe_rules.py`,
  `recipe_creator.py:795-800`, `yaml_format.rst`) into the one per-steptype schema described in
  §3.2 — this is the concrete form of the Phase 0 "schema module" item and closes F9/F19/F21/F23.
- [ ] **TODO:** Restore `resources/recipes/*.yml` to runnable state before the Phase 0
  characterization tests — they all reference `example_tests.py`, which is not in the repo (F24).
- [ ] **TODO (security):** `resources/recipes/comprehensive_recipe.yml:20` commits a plaintext
  SSH password; rotate the credential if the host is live, and move credentials to the Config
  Handler (F22).
- [ ] **TODO:** Answer the format decisions in the guide's §18 (subsequence
  parameters/outputs — currently parsed and never used; the magic `cancel_key`/`wrt_key`/`ID_key`
  globals; `format_version` policy; dict-vs-list for `parameters`/`outputs`) before the step
  port fixes the contract in place.

---

## TODO — Agreed architecture change: two processes, threads inside the engine

> **Status: decided in architecture review (July 2026), not yet implemented.** The spec pages and the current branch assume "every module is a process." The decisions below supersede that model; each item is a TODO so it can be transferred 1:1 into GitLab issues. Sections further down that still say "process" for Sequencer/Report should be read through this lens (marked with *→ see TODO section* where it matters).

### Target topology

```
launcher  (thin supervisor — spawns and watches BOTH processes)
├── HMI process (GUI, PySide6)              ← the ONLY process boundary
└── Engine process
    ├── CORE          (main thread — mediator + supervisor of threads)
    ├── Sequencer     (thread)  → runs Steps → calls HAL as an imported library
    ├── Report        (thread)
    └── StreamHandler (thread, ring buffer for acquisitions)
CLI mode: no HMI process at all — CLI runs in the launcher process, engine unchanged.
```

### TODO checklist

- [ ] **TODO:** Launcher stays the parent of *both* processes — the GUI is **not** spawned by Core. The supervisor must be the simplest, most stable component; the GUI must outlive an engine crash in order to report it. (`startup.py` already does this — keep it.)
- [ ] **TODO:** Change Core to spawn Sequencer and Report as **threads**, not `multiprocessing.Process` (currently in `core.py: start_submodules()`); add StreamHandler as a third thread when it lands.
- [x] **DONE (mechanism):** the **queue type is injected**, never assumed. `Channel` wraps anything with `put()`/`get_nowait()`; the launcher builds the HMI↔Core pair and `Core.__init__` takes a `queue_factory` (default `multiprocessing.Queue`) for its submodule links. Passing `queue.Queue` there is the whole change when they become threads. No module knows which it holds. *Remaining:* actually flipping it, together with the `Process` → `Thread` change above.
- [ ] **TODO:** HAL becomes a **plain library** imported by the Sequencer — no process, no event loop, no queue. Driver calls stay ordinary function calls; this also keeps the spec's "HAL usable standalone outside the framework" true by construction.
- [x] **DONE:** every HMI↔Core message type is round-tripped through `pickle.dumps`/`loads`, and a second test rejects any field that is not a plain value, a UUID, an Enum, a tuple or another message. Both are parametrised over the link unions, and a third test fails if a message exists without an example — so the coverage cannot rot. `tests/unit_tests/test_messages.py`.
- [x] **DONE (contract):** user interaction is a **request/response pair** joined by a `request_id` — `UserPromptRequest`/`Response` and `SerialNumberRequest`/`Response` in `messages/run_events.py`, with `PendingRequests` as the waiting side. The live `SimpleQueue` is gone. *Remaining:* wiring it into the steps themselves during the Phase 1 port, and the worker-thread requirement noted in §1.1.
- [ ] **TODO:** Define the heartbeat-timeout **policy** in Core (restart thread? abort run? notify HMI?) — currently it only logs a warning.
- [ ] **TODO:** Write down the **promotion rule**: a module moves from thread to its own process only in response to a concrete incident (e.g. a crash-prone C driver → wrap *that one driver* in a sidecar process; never the whole HAL).
- [ ] **TODO:** Bulk data (waveforms, acquisitions) never goes through message queues: in-engine it is passed by reference; if it must reach the GUI, use `multiprocessing.shared_memory` or a file-path handoff.

### Why threads inside the engine (instead of processes) — pros and cons

| | **Threads (chosen for the engine)** | **Processes (kept only at the GUI seam)** |
|---|---|---|
| **Memory / data channels** | ✅ Shared memory: queues pass *references*, zero-copy. Any Python object can flow — device handles, arbitrary step outputs, objects between steps ("pickling required" concern disappears in-engine) | ❌ Every message is pickled → piped → rebuilt as a *copy* (~6× slower on large arrays); device handles, Qt objects, callables cannot cross at all |
| **Crash safety** | ❌ A segfaulting C driver kills the whole engine. *Mitigation:* the GUI survives (separate process) and reports it; sidecar pattern available per rogue driver | ✅ One module can die without taking the others; the reason the GUI **stays** a process |
| **CPU parallelism** | ⚠️ GIL serializes Python bytecode on default builds — irrelevant for I/O-bound bench work (instrument I/O, waits release the GIL); free-threaded Python 3.13+/3.14 removes the limit entirely going forward | ✅ True parallelism today, but pypts has no CPU-bound path that needs it |
| **Simplicity / ops** | ✅ One import of everything: one log dir, one config load, one debugger session, instant startup | ❌ Per-process re-imports (3× log files, config rewrites — already visible on the branch), attach-to-process debugging, slower spawn on Windows |
| **State discipline** | ⚠️ Shared state needs care. *Mitigation:* the actor pattern already in the code (each module owns its state, communicates only via queues) is exactly the discipline required | ✅ Isolation by default — but bought at the price of the data-channel restrictions above |
| **Reversibility** | ✅ Thread→process is a one-line launcher change *if messages stay pickle-clean* (hence the CI pickle test) | — |

**Summary:** the requirement "solid data channels no matter what the data is" is only satisfiable inside one process — pickling is a toll gate that arbitrary objects can't pass. So the data-heavy plane (Core–Sequencer–Report–HAL–streams) lives in one engine process on threads, and the one boundary that earns its cost — operator UI that must survive an engine crash — stays a process with strictly typed, pickle-safe traffic.

---

## 2. Development roadmap (phases, no dates)

Anchors follow the wiki milestones: **v0.3.0 = structure matches the architecture, modules exist and are integrated**, **v1.0.0 = feature-complete, published, documented**. The branch has already banked a large part of Phase 0/1 groundwork (structure, messaging, licensing, PySide6); the critical path now is **porting the engine into the skeleton**.

### Phase 0 — Stabilize the skeleton

*Goal: the branch is trustworthy before the engine lands on it.*

- Fix the verificator's broken schema-constants import; give `RECIPE_*_REQUIRED_FIELDS` / `STEP_REQUIRED_FIELDS` a dedicated schema module (this becomes the programmatic recipe schema the spec asks for).
- Harden `catch_and_report_errors`: re-raise or return sentinel by policy, per-function module detection, and don't require `self.core` implicitly.
- Decide logging/config process policy. **Decided (§1.2, §1.3):** one `--log-level` for the whole run, overriding `[logging] level`, resolved once by the launcher and passed to every process as an argument, so filtering happens at the sender rather than in the Logger; and the config is created/migrated once by the launcher's `bootstrap()` and read-only everywhere else, with every process reading the file for itself. **Still open:** one log directory per *test run* with per-process log files inside it — the log directory now comes from `paths.logs_dir`, but the per-run folder does not exist yet.
- Get `run_tests.py` + unit tests green in CI on the branch; add an X-server (or `QT_QPA_PLATFORM=offscreen`) job for GUI tests (already a TODO).
- Characterization tests around `old_code`: run an example recipe end-to-end and assert on the CSV rows — this is the safety net for the port in Phase 1.
- Resolve `requirements.txt` → pyproject-only (existing TODO), REUSE check in CI (existing TODO).
- Merge strategy: get `architecture_refactor` merged to master early (it already carries the licensing work) and continue in small MRs per the Development workflow page, rather than letting the branch drift further.

**Exit criteria:** CI green on the branch; skeleton boots in GUI and CLI mode on Windows and Linux; characterization baseline recorded.

### Phase 1 — Port the engine into the skeleton → v0.3.0

*Goal: `pypts --mode cli`/`gui` actually loads and runs a recipe through Core → Sequencer.*

> **TODO — topology change applies here** (*→ see TODO section above*): the port targets Sequencer/Report as **threads inside the engine process**, not separate processes. Wherever this phase or the spec pages say "process" for those modules, implement a thread with the identical interface classes; only the GUI keeps its process boundary.

Recommended porting order (each step is one reviewable MR):

1. **Recipe (data layer):** move loading/parsing/validation from `old_code/recipe.py` into `recipe/recipe.py`, stripped of all execution logic. Keep the consolidated `steps.py` implementations and resource-based `test_package` loading (`architecture.rst`). Integrate the verificator: a recipe that fails validation is never handed to the Sequencer.
2. **Step & Sequencer (execution):** move `Step`/`Sequence`/`Runtime`/`StepResult` execution into `sequencer/` + `step/`; implement `run_sequence(sequence_name)` behind the existing `RunSequence` command. The events it has to emit already exist — `RunStarted`, `SequenceStarted`, `StepStarted`, `StepFinished`, `SequenceFinished`, `RunFinished` in `messages/run_events.py`, ported one-for-one from the nine signals in `old_code/event_proxy.py` — so this step is about producing them, not designing them.
3. **Core orchestration:** implement `LOAD_RECIPE`/`START_SEQUENCE` handlers, runtime metadata (recipe info, DUT serials, timing, machine info), result aggregation, and forwarding to HMI + Report.
4. **Report:** port incremental CSV writing + HTML generation behind `GENERATE`/`EXPORT`; intermediate result file (YAML/CSV) per spec; artifacts organized per run folder.
5. **HMI:** CLI first — recipe load/validate/run, sequence selection, prompts (serial number, user interaction now crossing a process boundary — see pickling risk in §4), report/log locations, exit codes `0/1/2/3`, `--version`. Then grow the GUI beyond the status window (recipe preview, runtime log, results table).
6. **Delete `old_code/`** once parity is proven by the Phase 0 characterization tests. v0.3.0 is tagged here.

The design decision this phase used to carry — defining the step / user-interaction / result **payload contracts** — was taken up front instead (§1.1). The dataclasses exist and are pickle-tested; what remains is producing and consuming them.

### Phase 2 — Plugin infrastructure

*Goal: the extension mechanism of §3, applied where the spec demands openness.*

- Introduce `pypts.api` (stable contracts) + `PluginRegistry` with entry-point discovery.
- Replace the `eval()` step factory with the registry as the step code is ported (cheapest moment: during Phase 1 step 2, latest here); built-in step types self-register through the same mechanism.
- Recipe schema (per steptype) comes from each step plugin → verificator rules, docs, and Recipe Creator toolbar all derive from one source.
- Add spec-required step features on the new API: serial-registration step type, conditional execution, timeouts for predefined types.

**Exit criteria:** a step type in a separately pip-installed package runs from a recipe with zero core changes.

### Phase 3 — Frontends to spec

- CLI feature-complete per the CLI module page (already started in Phase 1.5).
- GUI: modular widget system (input prompt, image/buttons, XYGraph, result widget) as **widget plugins** keyed by step/stream type; 1280×720–1920×1200 scaling; session persistence; helper-app quick access; runtime notifications from the Logger's runtime handler. Fix the known GUI refresh bug (TODO.txt) while rebuilding.
- Stream handler: promote `StreamContainer` + XYGraph into the spec'd singleton stream layer (CSV first), fed by an acquisition logger channel.

### Phase 4 — Reporting to spec

- Configurable HTML templates (template/generator plugin interface — HTML now, PDF/JSON later without core changes).
- Full artifact packaging (report + logs + raw data per run, single traceable folder), report path/type/theme from Config Handler.
- Move generated HTML out of the repo (existing TODO).

### Phase 5 — Hardware Abstraction Layer

- `pypts.api.hal`: `Device` base (connect/teardown/recover, uniform logging/errors), family bases (`PowerSupply`, `DAQ`, `Load`) with the spec's standard verbs.
- Config Handler supplies per-device communication parameters; recipes reference devices by logical name.
- **Drivers as pip-installable plugin packages** rather than git sub-repositories (§3.6) — and this is where `nidmm`, `hightime`, `nptdms`, `pyserial`, `paramiko` leave the core dependency list.
- Driver docs template + tutorial; optional TCP server mode stays future work.

### Phase 6 — Helper applications to 1.0

- Verificator: cross-reference checks (undefined sequences/variables), rule engine fed by the plugin schemas, "see wiki X" hints, exception-free user-facing messages (largely structured already).
- Recipe Creator: interactive ⇄ text mode parity, undo/history, step toolbar generated from the step registry, integrated verification on save.
- Example Finder: promote from helper_applications stub/spike to the NI-style browser, indexing `resources/examples` and driver-plugin examples.

### Phase 7 — v1.0.0 hardening & release

- Docs complete (quick-start field-tested with another MTA engineer, per Milestones page; `architecture.rst` updated to describe the *process* architecture, since its current text describes the old_code consolidation).
- Demo project (recipe + test package + fake driver plugin).
- PyPI publication (`pip install` for users, git clone for devs), alongside the acc-py index; note the project was renamed `pts-framework` in pyproject — check the name is free on PyPI early.
- Cross-platform CI (Windows + Linux), REUSE check, coverage thresholds, error-path tests for full fault traceability.

### Continuous tracks

Unit tests per module as they're ported; GitLab flow per the Development workflow page (task → branch → MR with impact description → test → close, bi-weekly reporting); TODO.txt items folded into GitLab issues.

---

## 3. Plugin-based modules — proposal

### 3.1 Design goals

From the spec: loose coupling ("tests executable stand-alone"), lightweight core, open-source contributions, and the explicit extensibility asks in the module pages (custom drivers "without modifying the core HAL", GUI "widgets can be expanded, but GUI implementation stays the same", reports with "extensible and customizable templates"). The branch's own README already commits to "built for extensibility… easy to swap out or refactor parts of the system" — the plugin layer is the missing half of that promise.

**Principle: the core is a kernel** — recipe parsing, sequencing, event routing, plugin management. Everything hardware-, presentation-, or format-specific is a plugin. The core must run with zero plugins installed.

The branch's typed-interface pattern and the plugin system are complementary, not competing: **interfaces + messages govern how *processes* talk (Core ↔ Sequencer ↔ Report ↔ HMI); plugins govern how *capabilities* are added inside a process** (a new step type inside the Sequencer, a new widget inside the GUI, a new report format inside Report, a new driver inside the HAL).

### 3.2 The stable contract: `pypts.api`

A small subpackage (eventually its own distribution `pypts-api`) containing only ABCs, dataclasses, and enums — no Qt, no drivers, no multiprocessing:

```python
# pypts/api/step.py
class StepPlugin(ABC):
    steptype: ClassVar[str]           # name used in recipe YAML
    input_schema: ClassVar[dict]      # feeds verificator + Recipe Creator
    output_schema: ClassVar[dict]
    required_fields: ClassVar[tuple]  # today's STEP_REQUIRED_FIELDS, per steptype, owned by the step itself

    @abstractmethod
    def execute(self, ctx: StepContext, inputs: dict) -> dict: ...

# pypts/api/hal.py
class Device(ABC):
    @abstractmethod
    def connect(self, config: DeviceConfig) -> None: ...
    @abstractmethod
    def teardown(self) -> None: ...
    def recover(self) -> None: ...    # default: disconnect+connect

class PowerSupply(Device):
    @abstractmethod
    def set_voltage(self, value: float) -> None: ...

# pypts/api/report.py
class ReportGenerator(ABC):
    format_name: ClassVar[str]        # "html", "pdf", ...
    @abstractmethod
    def generate(self, intermediate_file: Path, out_dir: Path, template: Path | None) -> Path: ...
```

Rules that keep coupling loose:

- **Plugins import only `pypts.api`** — never `pypts.core`, never each other.
- **Core never imports plugins by name**; it discovers them and talks through the ABCs.
- Everything a step needs arrives through `StepContext` (variable get/set, logger, config namespace, event emission, HAL device lookup, stream channels). No singleton imports inside plugins — that is what makes steps unit-testable stand-alone with a fake context, satisfying the "tests executable independently" requirement.
- This also fixes the schema-constants problem cleanly: `RECIPE_HEADER_REQUIRED_FIELDS` etc. stop being loose constants in `__init__.py` and become *derived from the registered step plugins* — the verificator asks the registry, not a hardcoded dict.
- `pypts.api` is semver-stable; each plugin declares `requires_api = ">=1,<2"` and the plugin manager rejects incompatible plugins with a clear message at load time.

### 3.3 Discovery: entry points + registry

Use standard Python **entry points** (`importlib.metadata.entry_points`) — the mechanism pytest and Sphinx use; works with pip/venvs/acc-py; no homegrown scanning. One group per extension kind:

| Entry-point group | Extension |
|---|---|
| `pypts.steps` | step types |
| `pypts.drivers` | HAL device drivers |
| `pypts.report_formats` | report generators |
| `pypts.gui_widgets` | step/stream presentation widgets |
| `pypts.stream_formats` | stream storage backends (CSV now, TDMS/HDF5 later — `nptdms` and the `hdf_support` branch both point here) |
| `pypts.verification_rules` | extra recipe-verificator rules |

A plugin package declares its contributions in its own `pyproject.toml`:

```toml
# pypts-driver-ni-dmm/pyproject.toml
[project]
name = "pypts-driver-ni-dmm"
dependencies = ["pypts-api>=1,<2", "nidmm==1.4.8", "hightime==0.2.2"]

[project.entry-points."pypts.drivers"]
ni_dmm = "pypts_driver_ni_dmm:NiDmm"
```

Core side — one small registry class reused for every group:

```python
class PluginRegistry:
    def __init__(self, group: str, base: type):
        self._group, self._base = group, base
        self._factories: dict[str, Callable] = {}   # name -> lazy loader
        self._loaded: dict[str, type] = {}

    def register(self, name, cls): self._loaded[name] = cls          # built-ins
    def discover(self):                                              # metadata only, cheap
        for ep in entry_points(group=self._group):
            self._factories.setdefault(ep.name, ep.load)             # NOT imported yet
    def get(self, name) -> type:                                     # lazy import on first use
        if name not in self._loaded:
            if name not in self._factories:
                raise UnknownPluginError(name, available=self.names())
            cls = self._factories[name]()
            self._check(cls)                                         # base class + api version
            self._loaded[name] = cls
        return self._loaded[name]
```

`build_step` then becomes `STEPS.get(step_data.pop("steptype"))` — which **kills the `eval()`** (arbitrary code execution via recipe file), opens the step set to third parties, and yields good errors ("Unknown steptype 'PythonModulStep'. Available: …").

**Lazy loading keeps startup light:** `discover()` reads installed-package metadata only; a plugin module is imported the first time a recipe references it. A broken plugin fails at *validation* time for the recipes that use it, not at framework startup. One process-model note: each module process (Sequencer, Report, GUI) runs `discover()` for the groups *it* owns — steps in the Sequencer, widgets in the GUI, formats in Report — so plugin loading never crosses process boundaries and never needs pickling.

### 3.4 Packaging model

- **Core:** `pts-framework` → depends on `PyYAML` (+ `ruamel.yaml` if kept for the creator's round-tripping) and stdlib. That's the lightweight framework.
- **Extras** for first-party optional pieces: `pip install pts-framework[gui]` (PySide6), `[all]`.
- **Separate distributions** for heavy/licensed stacks: `pypts-driver-ni-dmm` (nidmm, hightime), `pypts-driver-scpi` (pyserial), `pypts-remote-ssh` (paramiko), `pypts-stream-tdms` (nptdms), plotting widgets (matplotlib) with the GUI extra. Today all of these are unconditional core deps — every CLI-only bench installs Qt, matplotlib, and NI drivers to parse YAML.
- Built-in steps/report formats stay in the core package but register through the same registry — one mechanism, no special cases.
- A `pypts plugins list` CLI command + `pypts-plugin-template` cookiecutter give discoverability and enforce the driver documentation template the HAL spec requires.

### 3.5 How each spec module maps to the plugin system

- **Steps:** recipe `steptype:` = registry name. A step plugin's schemas feed (a) the verificator, (b) auto-generated docs ("fully programmatic recipe structure"), (c) the Recipe Creator's step toolbar. New step type ⇒ automatically creatable, verifiable, documented.
- **HAL:** family bases in `pypts.api.hal`; drivers as plugins grouped by family; Config Handler supplies `DeviceConfig` by logical device name; drivers stay usable standalone because they depend only on `pypts-api`.
- **GUI widgets:** widget factory resolved from `pypts.gui_widgets` by step/stream type, generic fallback — exactly "widgets can be expanded, but GUI implementation stays the same."
- **Report:** generators from `pypts.report_formats`; the CLI page's future `--report-type` option becomes real with zero core changes.
- **Verificator rules:** core rules ship with the verificator; step/driver packages contribute additional rules via `pypts.verification_rules`.
- **Stream handler:** storage backends via `pypts.stream_formats` (CSV → TDMS → HDF5).

### 3.6 Recommendation: plugin packages instead of driver git-submodules

The HAL wiki page proposes drivers as sub-repositories. Suggest revisiting: submodules couple checkout state to the framework repo, complicate CI, and make versioning painful. Pip-installable driver plugins give the same contribution model (separate repos, separate owners under a `pypts-drivers` GitLab group) plus independent release cycles, dependency isolation, and plain `pip install` UX — better serving the wiki's own goals (easy contribution/sharing, docs, versioning).

### 3.7 Communication stays Core-mediated

Plugins never talk to each other. A step reaches HAL via `ctx.hal(...)`, streams via `ctx.stream(...)`, logs via `ctx.log` — all mediated by objects the host process provides behind `pypts.api` protocols. The spec's "modules do not speak to each other, they speak through CORE" survives intact, and the typed message files remain an internal detail that can evolve without breaking any plugin.

### 3.8 Alternatives considered

- **pluggy** (pytest's hook library): great for *hook-style* extension (many listeners per event — e.g. a future `pypts_step_finished` hook for a Grafana exporter). It doesn't model *named factories* (steptype → class) as naturally as a registry; the two compose well. Start with entry points + registry; add pluggy hooks later if lifecycle extensions are wanted.
- **stevedore**: thin wrapper over entry points; extra dependency for little gain at this scale.
- **Namespace-package scanning:** implicit, import-order-sensitive, no metadata — entry points are strictly better.
- **Config-file plugin lists:** rejected as the primary mechanism, but the Config Handler can offer an allow/deny list for locked-down production benches.

### 3.9 First increment (fits Phase 2, partially even Phase 1)

1. `pypts/api/` with `StepPlugin` + `StepContext` (typed façade over the ported Runtime).
2. `PluginRegistry`; register the five existing step types; replace `eval()`.
3. "Unknown steptype" error path + a test that pip-installs a dummy step plugin from `unit_tests/fixtures/`.
4. Split heavy deps out of `pts-framework` into extras/driver packages.
5. Publish the cookiecutter template.

Steps 1–3 are naturally done *while porting steps into the sequencer* — doing the port and the registry together avoids touching the same code twice.

---

## 4. Risks & open questions

- **Pickling across process boundaries.** *(→ resolved.)* Only the HMI↔Core boundary remains a process boundary; user prompts are a request/response pair, and the pickle round-trip test guards every message on both unions permanently (§1.1). Step-to-step object passing and device handles stay in-engine and are unaffected.
- **`old_code` divergence.** The branch's `old_code` is *newer* than master (consolidated steps, `test_package` resource loading). Freeze master, do the port from `old_code` only, and delete it at v0.3.0 — three coexisting engines (master, old_code, new modules) is the biggest confusion risk for the team.
- **Error-handling policy.** `catch_and_report_errors` currently reports and *continues*. Define per-layer behavior: step errors → StepResult(ERROR) + report + continue/abort per recipe config; module errors → Core event + heartbeat-driven recovery; never both silent.
- **Core busy-loop & heartbeats.** 100 Hz polling in every module is fine for now; when Core gains real work, consider `Queue.get(timeout=...)`-driven loops. Heartbeat timeout currently only logs a warning — define the recovery action (restart module? abort run? notify HMI?).
- ~~**Config in the temp directory.**~~ **Closed (§1.3):** moved to the `platformdirs` per-user config directory, single writer, versioned structure with migration, and structured data through dotted section families. It is still INI — deliberately, because the type information lives in `configuration_schema.py` and the file stays hand-editable on a bench. What remains open is *changing* configuration at runtime: `SetConfigParameter` is declared but not implemented, and there is no mechanism for telling a running process that a value changed.
- **PyPI name.** The pyproject rename to `pts-framework` needs an early availability check on PyPI (v1.0.0 requirement), and alignment with the import name `pypts`.
- **Recipe format versioning.** Before the Creator and third-party step plugins ship, add `format_version` to the recipe header and a compatibility policy — cheap now, expensive later.
- **`pypts.api` stability.** Freezing the step/driver contract is the highest-leverage design decision left; review it with the module owners (per the Milestones page, each module has an assigned owner) before Phase 2 ends.
