# PyPTS — Development Roadmap & Plugin Architecture Proposal

*Based on branch `architecture_refactor` (read from GitLab `origin/architecture_refactor`, July 2026) and the Confluence PTS Framework specification (Framework specification, General requirements, Milestones, workflow pages, and all 12 module pages).*

---

## 1. Where the branch stands today

The `architecture_refactor` branch is a real step toward the spec: the **process skeleton and communication plumbing are built**, and the **first slice of the execution engine is in** (§1.13): the recipe data layer, the base Step lifecycle with one step type (WaitStep), and a Sequencer that really runs a sequence. Pressing "run" executes a WaitStep-only recipe end to end; every other step type still lives in `old_code/`.

### What is already done ✓

| Area | State on the branch |
|---|---|
| Package layout | Matches the system design: `core/`, `sequencer/`, `recipe/`, `step/`, `report/`, `hmi/{gui,cli}/`, `config_handler/`, `logger/`, `stream_handler/`, `hardware_layer/`, `helper_applications/{recipe_creator,recipe_verificator,example_finder}/`, `utilities/`, `launcher/`, plus `old_code/` holding the previous engine |
| Process model | **Reworked (see §1.5).** `launcher/startup.py`: argparse `--mode gui/cli/connect` (gui is the default) and `--log-level`, spawns the Logger and Core as processes and the GUI as a third; Core runs the Sequencer and the Report as **threads of its own process**. Two processes plus the Logger, exactly as agreed below |
| Typed messaging | **Reworked (see §1.1).** `pypts/messages/`: one frozen dataclass per message, one union per link, one generic `QueueWrapper` for all six links, every handler closed with `unhandled()`. The enums, the interface ABCs and the queue data-layer classes are gone, and with them the 4-step "add a message" workflow — it is two steps now. Protocol tests in `tests/unit_tests/test_messages.py` |
| Health & errors | `HeartbeatManager` ticking from Sequencer/Report/HMI, Core-side timeout detection (armed only for modules still expected to run); two decorators sending a typed `ModuleError` to Core for what nobody expected, and `report_error()`/`report_problem()` for a raise site that recognised the failure and rates it (see §1.10, §1.11). Every one names the module, the method and the exception type |
| GUI toolkit | **PySide6 migration done** (GUI skeleton + `test_pyside6_conversion.py`) — the PyQt6/LGPL conflict is resolved |
| Licensing | LGPL-2.1-or-later + CC-BY-SA-4.0, SPDX headers, `reuse.toml`, `licenses/`, `dependency_license_analysis.rst` — REUSE compliance largely in place |
| Logger | Single-writer Logger process: timestamped format (file:function, ms), file + stdout handlers, `set_stdout_logging_enabled()` toggle, and a level resolved once by the launcher from `--log-level` / config (§1.2) |
| Config handler | **Reworked (see §1.3).** `ConfigHandler` singleton in the per-user config directory (`platformdirs`), created from a commented template, versioned (a broken or mismatched file is discarded for the run — defaults in memory, launcher notice, ERROR in the log; never migrated or repaired — August 2026, see §1.3), typed access through a schema, single writer, comment-preserving writes. The launcher takes the log directory from it and Report the report directory |
| Recipe verificator | Substantial real implementation: YAML line-map extraction, faults vs warnings, per-steptype required fields, bulk folder validation, string-variable validation for the creator |
| Recipe creator | GUI application present (`recipe_creator.py`, custom GUI modules, styles) |
| Tests | `unit_tests/unit_tests/` + `functional_tests/` + `run_tests.py` (event proxy, recipe, report, steps, GUI, version…) |
| Resources | `resources/{recipes, example_commented_recipes, examples, images}` reorganization done |

### What is placeholder / not yet ported

1. **The execution engine - nine of ten step types.** The skeleton is real now (§1.13): `recipe/` parses and validates, `step/` has the base lifecycle + `WaitStep` + the registry, `execute_sequence()` runs the requested sequence and emits every run event, and Core's `LoadRecipe`/`StartSequence` handlers work. Still in **`old_code/`**: `PythonModuleStep` (and the resource-based `test_package` module loading described in `architecture.rst`), the four interactive types, `SequenceStep`/`IndexedStep` (nesting), and the SSH pair - plus the continue_on_error policy.
2. **Report module** — **first real slice in (§1.19):** one folder per run, an incremental CSV growing step by step, a simple self-contained `report.html` on `RunFinished`, and the operator told where it is (`ReportReady`; the GUI's "Open report folder" button). Still missing against `old_code/report.py` and the spec: the serial-number column (nothing asks for one yet), TDMS plots, configurable templates/`report.type`/`report.theme` (Phase 4), `ExportReport` (stub at both ends).
3. **HAL** — `hal.py` is a one-line comment.
4. **Stream handler** — `src/pypts/stream_handler/` is an empty placeholder package. The `StreamContainer` singleton and the XYGraph widget spike were moved out of the shipping package to `spikes/stream_handler/` and `spikes/GUI/XYGraph/`: neither was imported by anything, `StreamContainer` executed and printed at import, and XYGraph has undefined names that raise if reached. Phase 3 promotes them from there.
5. **GUI** — a minimal status window (status label + stop button); none of the spec's widget system, recipe preview, session persistence, etc. CLI has the interactive shell + `load_recipe`/`start_sequence` plumbing and prints the report path (§1.19), but no exit-code features yet. Neither frontend shows the message layer, and neither needs to: `--log-level DEBUG` puts every message on every link into the run log (§1.2), and the Debug Monitor renders that log live (§1.4).
6. ~~**Step construction still uses `eval(...)`**~~ **Closed (§1.13):** the new `step/registry.py` is a plain dict lookup with a clear unknown-steptype error; the `eval()` stays behind in `old_code/` and dies with it.

### Defects worth fixing early (spotted while reading the branch)

- **Broken import in the verificator:** `verify_recipe.py` does `from pypts import RECIPE_HEADER_REQUIRED_FIELDS, RECIPE_SEQUENCE_REQUIRED_FIELDS, STEP_REQUIRED_FIELDS`, but `src/pypts/__init__.py` is now minimal and defines none of these — the verificator cannot import. The schema constants need a proper home (see §3.5: make them part of the step/recipe schema layer).
- **`@catch_and_report_errors()` swallows results and errors:** *fixed (§1.10).* The `nonlocal module_name` + `inspect.stack()[1]` bug went first — the source is resolved from the decorated function at decoration time. The rest is now done too: there are **two** decorators, `catch_and_report_errors` (report and continue, for event loops) and `report_and_reraise` (report and let it through, for the execution layer), and neither assumes `self.core` exists — an object without an outbox is logged rather than having its real failure replaced by an `AttributeError` from inside the error handler.
- **Heartbeat monitoring is one-directional and always-armed:** *partially fixed.* Core now only checks modules still expected to be running, so a module that has reported itself stopped no longer produces timeout warnings for the rest of the run. **Still open:** it is warn-only, with no recovery action, and Core sends no heartbeat of its own, so an HMI cannot detect a dead Core.
- **Per-process side effects at import:** *config half fixed (§1.3).* Reading the configuration no longer writes it, and only the launcher's `bootstrap()` may create or repair the file, so the per-process `config.ini` rewrites are gone. **Still open:** per-run log directories (spec: "separate logs by test run") — the log *directory* now comes from the configuration, but it is still one timestamped file per run rather than a per-run folder with a file per process.
- **Core deps got heavier, not lighter:** `pts-framework` now hard-depends on `matplotlib`, `numpy`, `nptdms`, `nidmm`, `hightime`, `pyserial`, `paramiko`, `PySide6`. For a framework whose spec demands "lightweight" and "tests executable stand-alone," this is the strongest argument for the plugin packaging model in §3.
- Two `TODO.txt` items confirm known issues: globals stored as a list not dict; GUI refresh problems.

### 1.1 Message layer rework — **done**

> **Status: implemented.** The enum + `payload: dict` protocol was replaced by one frozen
> dataclass per message. Rationale and the topology review that led to it are recorded
> separately; what matters here is the resulting contract and what it left open.

**What changed.** `pypts/messages/` now holds one module per link (`core_hmi_communication`,
`core_sequencer_communication`, `core_report_communication`, `to_logger_communication`), plus `common_messages.py` for vocabulary two links
share and `run_events.py` for what the engine reports during a run. A single generic `QueueWrapper`
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
  `QueueWrapper.drain()` takes a bounded batch.

**New TODOs this opened:**

- [x] **DONE (§1.8):** The Sequencer runs a sequence on its own worker thread. `RunSequence`
      starts the thread and returns; the event loop keeps turning, so heartbeats continue,
      `StopSequence` is readable mid-run, and `PendingRequests.wait()` on the sequence thread is
      answered by `deliver_response()` on the loop thread. Done while `execute_sequence()` was
      still a stub, so the Phase 1 port lands in a shape that already works.
- [ ] **TODO:** Some old_code interaction steps read a *second* value off the same response
      queue after the first answer (a file path, a measured value, a `(port, baudrate, IDN)`
      triple). `UserPromptResponse` does not model this; each follow-up needs to become its own
      request when those steps are ported.
- [x] **DONE (§1.19):** Core forwards `RunStarted`/`SequenceStarted`/`StepExecuted`/
      `RunFinished` to the Report and sends `GenerateReport` right behind `RunFinished`.
- [x] **DONE (§1.9):** mypy is configured over `pypts/messages/` and the handler modules, and
      runs in CI. Note the framing in that TODO was too strong: exhaustiveness was never
      *only* a runtime check — `test_messages.py` drives every member of every union through
      the real handler and fails if one reaches `unhandled()`. mypy moves that from test time
      to edit time and adds what nothing checked before, the `QueueWrapper[X]` link types.
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
125, ~141 lines of branches in `queue_wrapper.py` / `core.py` / `startup.py`, 247 of tests) and the
one thing it did that the log did not was see the *send* side.

**What replaced it.** `QueueWrapper.send()` and `QueueWrapper.receive()` each log one DEBUG line on a
`pypts.trace` logger, naming the link and the message:

```
2026-08-12 09:32:58.056;DEBUG;Core;queue_wrapper.py:send;send core->sequencer StopSequencer()
2026-08-12 09:32:58.10?;DEBUG;Sequencer;queue_wrapper.py:receive;recv core->sequencer StopSequencer()
```

Both directions, deliberately: a message that was sent and never received is the failure
worth seeing, and it is invisible to anything that only logs on arrival. Because the trace
sits on the one object every message already passes through, no module has to remember to log
anything and no new message can escape it — the two-step "add a message" procedure in
`src/pypts/README.md` is unchanged.

**Why it is at the transport, not in the handlers.** Same reason the tap was: Core does not
see the messages it never receives, so a Sequencer→Core send is only visible at the
`QueueWrapper`. It also survives the thread migration unchanged — the trace does not care which
queue type the QueueWrapper wraps. The handlers' old `log.info(f"Received … message: {message}")`
lines were removed, since `receive()` now covers all four of them and adds the link name;
INFO is left carrying only the narrative (lifecycle, recipe loaded, run started, errors).

**One dial.** `--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}` overrides `[logging] level`
in `config.ini`, which **ships as `DEBUG` for the duration of the refactor** (§1.6, and the
revert TODO there); `logger.parse_log_level()` falls back
to INFO rather than raising on a name it does not know, because the config value is read
before there is anywhere to report a traceback. The launcher resolves the level **once** and
passes it to every process as an argument — children must not read the config themselves,
because `read_config_key()` writes the file, and five processes rewriting it per run is the
defect at the top of this document, not a feature. Filtering therefore happens at the sender,
which is what makes the trace free when it is off: `%`-style arguments mean the `repr()` is
only paid when a handler is actually going to emit.

**What was given up.** The live filterable trace table, the injection UI, the generated
message form, and the Modules tab. Injection needed no product code to survive: `Core.__init__`
builds every link but starts nothing, so a test constructs a Core, calls
`core.from_sequencer.send(...)` directly and drives one handler with no thread behind it —
`test_core.py::test_a_sequencer_event_is_routed_to_the_hmi` is the old injection test, rewritten
that way.

**Verified:** 9 tests in `tests/unit_tests/test_queue_wrapper_trace.py`, including that nothing is
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
      `queue_wrapper.py` import `Heartbeat` and type-test the payload, and the transport not knowing
      what a message *is* is the property that keeps it generic. Decide before Phase 1
      generates real traffic.
- [ ] **TODO:** `LOG_FORMAT` has no `%(name)s`, so a trace line is identified by the word
      `send`/`recv` and the `queue_wrapper.py:send` location field rather than by `pypts.trace`.
      Adding the logger name touches every line of every log and the `LOG_LINE` regex in
      `test_logger.py` — worth doing, but on its own.
- [ ] **TODO:** Trace payloads are not truncated (the tap capped them at 2,000 chars). A file
      does not care and a large `RunFinished` is exactly what you want whole, but revisit if a
      real Phase 1 run shows the log queue backing up.
- [x] **DONE (§1.3):** An existing `%TEMP%/pypts/config/config.ini` saying `log_level = DEBUG`
      no longer affects anything: the config moved to the per-user config directory, so the
      old file is not read at all. (The handler migrated old files for a while; migration
      and repair were removed again in August 2026 — see §1.3.) The stale file under
      `%TEMP%` is harmless and may be deleted by hand.
- [ ] **TODO:** `--mode cli` still imports PySide6, through `startup.py → hmi/gui/gui.py`.
      Removing the debug console did not fix this — deferring the GUI import into the `gui`
      branch is a one-line change nobody has made.
- [ ] **TODO:** Message-type introspection is no longer asserted anywhere. The deleted
      `test_every_message_type_can_be_built_from_the_form` was the only test proving every
      message has plain, introspectable fields. `test_messages.py` still pickles every message
      and fails on one with no example, so union coverage does not rot — but the weaker claim
      is now untested. Do not rebuild the form to get it back; a direct test would do.
- [x] **DONE (§1.4):** *"If a live developer tool is ever wanted again, it should be a
      separate distribution reading the log or subscribing through `pypts.api`, not a
      `--mode` inside the product."* One was wanted again, and it reads the log. It is a
      helper application rather than its own distribution — see §1.4 for why that is the
      same promise kept. The framework is unchanged: not one line of `src/pypts/` outside
      `helper_applications/debug_monitor/` was touched to make it work.

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
| `configuration_schema.py` | what the file contains: section → key → type, default, allowed values; `CONFIG_VERSION` |
| `template_writer.py` | writing without losing the comments |
| `config_handler.py` | the singleton: load, create, validate, get/set, dump |

**The decisions worth recording.**

- **INI stays.** A schema gives every key a type, so `get_parameter()` returns a `Path`, an
  `int` or a `bool`, not a string; dotted section names carry whatever structure the spec
  asks for, since everything before the last dot is the section.
- **The schema describes only what something reads.** `[hardware.example_device]` and the
  `SECTION_FAMILIES` prefix rule that validated `[hardware.<name>]` against it were removed:
  nothing consumed either, and shipping them committed the user's file — and Phase 5 — to a
  device shape that had not been designed. A section the schema does not know is kept
  verbatim, reported once at WARNING and returned as text, so a bench that already declares
  hardware loses nothing. `CONFIG_VERSION` was deliberately *not* bumped and no `DEPRECATED`
  entry was added: an existing `config.ini` keeps its `[hardware.example_device]` section and
  is warned about once per start until the user deletes it.
- **One instance per *process*, not per application.** Spawn gives a child no memory of its
  parent, so each process builds its own handler and reads the same file. Nothing is passed
  through `Process(args=...)`, which is what keeps the child entry points unchanged.
- **Reading is pure.** Only `bootstrap()`, called once by the launcher before anything else
  exists, may create the file. CORE is the only runtime writer.
- **No migration, no repair — discard instead (August 2026 decision).** The handler
  originally migrated old files (renamed keys moved, dead keys dropped, new keys added,
  `config.ini.v<n>.bak` kept) and refused files from a newer pypts. All of that was removed:
  an existing file is **never modified by pypts**, and keeping it correct is the user's job
  — edit it by hand, or delete it to have it recreated from the template. A file that is
  broken (a missing key, a value of the wrong type, not INI at all) **or** whose
  `config_version` does not match is **discarded whole for the run**: the template defaults
  are used in memory, `BootstrapOutcome.DISCARDED`/`bootstrap_problem` carry the verdict,
  the launcher shows a startup notice (`show_config_popup()`: QMessageBox in GUI mode,
  console banner in CLI/headless), and the reason is an ERROR in the run log. The run never
  stops for a bad config; `bootstrap()` raising is a last resort (unreadable template).
  While discarded, `set_parameter()` refuses (`ConfigWriteError`) so the user's file cannot
  be overwritten with defaults; `restore_default()` stays allowed and ends the state. Every
  process applies the same discard rule, so a run agrees with itself about the values in
  force. No CORE involvement — the notice is the launcher's. The `DEPRECATED` map and the
  migration/repair helpers are gone from the code.
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
- [ ] **TODO:** Phase 5 has to decide how a bench is described in the configuration and read
      it into a `DeviceConfig` handed to drivers by logical name. Nothing exists for this —
      the placeholder `[hardware.example_device]` section, its schema entry and the
      `SECTION_FAMILIES` mechanism were all removed, so the design is unconstrained. Whatever
      it becomes needs a `CONFIG_VERSION` bump; there is no migration mechanism any more, so
      existing files are updated by hand or recreated from the template.
- [ ] **TODO:** `report.type` / `report.theme` and the `[gui]` keys are read but not yet
      *used* — Phases 4 and 3 respectively.
- [ ] **TODO:** Move the plaintext SSH password out of
      `resources/recipes/comprehensive_recipe.yml:20` and into the configuration now that
      there is somewhere to put it. Rotate the credential if the host is live.
- [ ] **TODO:** `stdout_logging_enabled` is still derived from `--mode` rather than from the
      configuration. Probably correct — it follows from having a console, not from a
      preference — but it is the one logging decision the config does not own.
- [x] **DONE (plans/004):** an existing-but-unopenable config.ini is discarded
      with "exists but cannot be opened: <OS error>" instead of being
      misdiagnosed as "declares structure version 0" — `_read_raw` opens the
      file explicitly rather than letting configparser swallow the OSError.

---

### 1.4 Debug Monitor — **done (viewer); injection not built**

> **Status: the read-only half is implemented.** A helper application that renders the
> message trace, the heartbeats and module liveness of a run by reading its log file.
> The framework has no idea it exists.

```bash
python -m pypts --mode cli --log-level DEBUG          # any normal run
python -m pypts.helper_applications.debug_monitor     # in another shell

python -m pypts --log-level DEBUG --debug-monitor     # or both at once (see below)
```

**Why this is not the console coming back.** §1.2 removed `--mode debug` because it gave the
software two shapes: the product, and the product plus a tap. This has one shape. It is a
separate program that opens a file read-only; there is no debug build, no `--mode`, no
branch in `queue_wrapper.py` or `core.py`, and no flag that changes how a run behaves.
Starting it, or not starting it, is invisible to the framework — which is the property the
removal was protecting.

> **Amended by §1.4.1.** The launcher now has a `--debug-monitor` flag, so the original
> form of that claim — *"no branch in `startup.py`"*, and *"`git status` shows nothing
> modified under `src/pypts/` outside `helper_applications/debug_monitor/`"* — is no longer
> true as written. What the claim was protecting is: the flag starts a **program**, it does
> not import one, and no code path in the framework differs because of it. See §1.4.1 for
> the weaker property that replaced the testable one.

It lives in `helper_applications/` rather than in its own distribution, beside
`recipe_creator` and `recipe_verificator`, because that is where this repo already keeps
standalone tools that import the framework and are imported by nothing. Promoting it to its
own package is a packaging decision that can be taken later, in Phase 2 with the rest of
§3.4; nothing in its design depends on where it is installed. What matters — that it is
*outside* the product's execution path — is already true.

**What the trace being a file bought.** Two things a side channel would have had to rebuild:

- **Ordering is free.** Every process funnels its records through the single-writer Logger,
  so the order of the file *is* the order of the system. A relay taking events from four
  processes would have had to reconstruct that from four clocks.
- **Replay is free.** The same parser reads a run that finished last week, so a failure
  somebody reports afterwards is openable. This is the case §1.2 said a debug build could
  never serve, and it is now the same code path as a live tail: "now" is the last line in
  the file, not the wall clock.

**What it shows.** A filterable trace table (link checkboxes, free text, heartbeats hidden by
default, follow-tail), and a Modules tab with each module's state, last heartbeat, age, last
error, and CORE's own verdict. That last column is deliberate: the derived state and CORE's
opinion are computed from the same evidence by different code, so a disagreement between them
is a defect rather than a display glitch.

**Liveness needed no new message.** `Heartbeat` crosses a `QueueWrapper`, so it is already in the
trace; the state CORE keeps privately in `module_running` / `last_heartbeat` /
`heartbeat_lost` is reconstructible from the log without CORE sending any of it. The tool
imports `HEARTBEAT_TIMEOUT_S` from `core.py` rather than declaring its own — the deleted
console duplicated that constant, and §1.2 lists the duplication among the defects that died
with it.

**What it costs, written down rather than discovered.** Nothing is visible unless the run was
started at DEBUG, so the window says so in words instead of showing an empty table. The
payload is `repr()` text, so the message type and the link survive and per-field structure
does not — recovering the object would mean evaluating a repr, which is the trick the §1.1
rework existed to remove.

**Verified:** 32 tests in `tests/unit_tests/test_debug_monitor.py`, most of them needing
neither Qt nor a running framework because the parser and the liveness fold are pure
functions over text. Full suite: **220 passed, 72 skipped**. Confirmed against a real
`--mode cli --log-level DEBUG` run on Windows: 93 lines, 25 messages, all seven links
present including `core->sequencer` and `core->report` which no frontend can see, zero
unparsed lines, and all three modules correctly reading *stopped* rather than *dead* after a
clean shutdown. The window itself was rendered against that log and both tabs check out.

**Not yet confirmed:** following a run that is still in progress, from a *separate* process.
The incremental read is covered by unit tests (a growing file, and a half-written trailing
line held back until it completes), but the cross-process case could not be demonstrated in
the sandboxed shell it was developed in, where a child's writes only become visible once the
child exits. It is one command to check on a normal machine: start a run at DEBUG, then start
the Monitor beside it.

One real finding from that first run, which is the sort of thing this is for: sends and
receives balanced 13/12, and the unmatched one is `StopLogger` on `any->logger`. That is
correct rather than a bug — the Logger drains its queue with a blocking `get()` and never
through `QueueWrapper.receive()`, so it is the one link that can never trace a receive. Worth
knowing before someone reads it as a lost message.

**New TODOs this opened:**

- [ ] **TODO:** Message injection is designed and **not built**. The agreed shape: a
      `[debug]` config section shipping `allow_injection = false`, a loopback
      `multiprocessing.connection.Listener` feeding a plain `queue.Queue` wrapped in a
      `QueueWrapper(link="debug->core")`, and `Core.debug_inbox` / `inject()` restored from the
      deleted console. This is the one part that puts a hole in the product, hence the gate
      and hence its being a separate change. Note it needs no `injected` flag: an injection
      arrives on a real QueueWrapper, so it traces itself as `recv debug->core InjectMessage(…)`
      immediately before the message it injects — the trace *is* the marker.
- [ ] **TODO:** The heartbeat-noise TODO above is now load-bearing for a second reason: the
      Monitor is only useful on a run at DEBUG, and such a run is ~6 heartbeat lines a
      second. It filters them client-side and is fine, but the log itself is still 170k lines
      in an 8 hour run. Unchanged deliberately — the fix would make `queue_wrapper.py` type-test
      its payload.
- [ ] **TODO:** The Monitor identifies a trace line by the `queue_wrapper.py:send` location field,
      because `LOG_FORMAT` has no `%(name)s` (the TODO above). It is a second consumer of
      that omission now, so fixing it means fixing the Monitor's parser in the same change.
- [ ] **TODO:** Attaching to a long run parses the whole file on the first tick. Acceptable
      today; revisit if a Phase 1 run makes the first paint slow.
- [ ] **TODO:** The Monitor reads `paths.logs_dir` through `ConfigHandler`, so it inherits
      §1.3's rule that reading is pure. If that ever stops being true, a debug tool would
      start writing the config of the run it is watching.
- [x] **DONE (half of the TODO below):** **CORE now bounds its shutdown.** `check_stop_status()`
      waited forever for a module that never reported itself stopped, and the only thing that
      ended such a run was the launcher terminating the process — which took the log with it,
      losing the one fact worth keeping: *which* module never answered. `Core.SHUTDOWN_TIMEOUT_S
      = 5.0` now starts when `stop_all_modules()` asks, and on expiry CORE logs an ERROR naming
      the modules it is abandoning and leaves. There is no killing to do: the Sequencer and the
      Report are daemon threads, so letting CORE leave *is* abandoning them, and the HMI is a
      process the launcher owns and CORE could not kill in any case. Five tests in
      `test_core.py`, including the previously-skipped `test_core_stops_when_all_modules_have_exited`.
- [ ] **TODO (found by the Monitor, on its first real run):** **startup races shutdown.** In
      a run where the operator asked to exit within the first few seconds, the trace shows
      CORE reaching `main_loop` at `15:20:23.174`, sending `StopSequencer` at `.176`, and the
      Sequencer process only finishing its own startup at `.284` — it starts its loop,
      immediately receives the stop it was sent before it existed, and emits exactly one
      heartbeat on its way out. Nothing is lost, because the message was queued rather than
      signalled, but a module can be told to stop before it has started and the Report
      behaves the same way. **Half answered:** the shutdown side is bounded now (the DONE item
      above). **Still open:** why reaching `main_loop` takes seconds at all. That measurement
      predates the thread migration, which removes the spawn cost for the Sequencer and the
      Report entirely — they are threads inside CORE now — so what is left to explain is
      CORE's own process start, for which the `--mode cli` still imports PySide6 TODO in §1.2
      is the obvious candidate. Re-measure before acting: the original number came from a
      sandboxed shell and from a build where both submodules were still processes. **Re-measure since §1.5:** the process-spawn half of
      that delay is gone — both modules are now threads and start in the same millisecond — but
      the race itself is unchanged, because it is about ordering, not about how long a start
      takes.

### 1.4.1 Starting the Monitor with the run (`--debug-monitor`) — **done; default flipped**

> **Status: implemented.** `startup.py` opens the Debug Monitor beside a run, instead of the
> operator starting it by hand in a second shell. **Amended: it is on by default** for the
> duration of the refactor, so a bare `startup.py` gives you both windows; `--no-debug-monitor`
> is the opt-out. The revert TODO is at the end of this section.

```bash
python -m pypts                                       # GUI mode, plus the Monitor
python -m pypts --mode cli                            # CLI mode, plus the Monitor
python -m pypts --no-debug-monitor                    # the run without it
```

**On by default, for now — amended.** It shipped as `store_true`, opt-in, on the argument
that a headless run, a test bench and CI cannot open a Qt window and should not try. That
argument still stands; what changed is the phase, exactly as in §1.6. During the refactor
nearly every run is a developer's, and an opt-in flag means the Monitor is only ever there
when someone remembered to ask - which in practice meant an IDE run configuration, a launcher
script or a hand-typed command line, i.e. a dependency on something other than plain Python
just to start the tool the refactor is being debugged with. The flag is now
`argparse.BooleanOptionalAction` with `default=True`, so **`python startup.py` with no
arguments starts the frontend and the Monitor**, and `--no-debug-monitor` is the opt-out for
the runs that cannot use it.

Nothing else about it changed: the Monitor still cannot affect a run, so the worst a default
`True` can do on a machine with no display is a child that exits on its own and a WARNING in
the log — see *It cannot stop a run* below. The automated suite never goes through
`startup.py:main()`, so CI does not spawn one either.

**Started as a program, not imported.** `start_debug_monitor()` runs
`subprocess.Popen([sys.executable, "-m", "pypts.helper_applications.debug_monitor", <log>])`.
That spelling is the whole design: `startup.py` gains a string constant naming the module and
no import of it, so the dependency still points one way only and the rule in
`debug_monitor/__init__.py` — *nothing in the framework may import this package* — holds
unchanged. A `multiprocessing.Process` would have been more consistent with the other three
children and would have broken exactly that.

**The log path is passed explicitly.** The Monitor's own default is "the newest
`pypts_*.log`", which is this run right until someone starts a second one. Being pointed at
the wrong run is the one confusion a debug tool must never create, so the launcher hands it
the path it already decided.

**It waits for the file.** The launcher only *computes* the log path; the file is created by
`logging.FileHandler` inside the **Logger process**. The Monitor exits with code 1 on a path
that is not a file, so `start_debug_monitor()` polls for up to `MONITOR_LOG_WAIT_S = 5.0` at
50 ms before giving up with a warning. Measured on Windows: ~200 ms from deciding the path to
the child being spawned.

**It cannot stop a run.** Every failure — file never appeared, interpreter unusable, PySide6
missing in the child — is a WARNING in the log and a `None` return. An `ImportError` in the
child cannot reach the launcher at all; it is the child's traceback on the child's stderr.

**It is left running.** Not stopped in the `finally` block with CORE and the Logger, because
the trace of a run is what you want to read *after* the run. The launcher logs
`Debug Monitor (pid N) left running` as one of the last lines of the file, so the log says
where its own reader went.

**Warns rather than overrides.** Asking for the Monitor on a run above DEBUG logs a WARNING
naming the level and pointing at `--log-level DEBUG`; it does not silently raise the level,
because what the operator asked to capture is not a debug tool's to change. (`config.ini`
ships `DEBUG` for the duration of the refactor, so this only bites someone who passed
`--log-level INFO` explicitly.)

**Verified:** `--mode cli --log-level DEBUG --debug-monitor` on Windows. The log shows the
Monitor started at `.053` reading this run's own file and left running at `.423`; the child
was confirmed alive by `Win32_Process` with the expected argv. Full suite: **227 passed,
71 skipped** (was 220/72 at §1.4). `ruff check` on `startup.py` reports only the `I001` that
already fails on `HEAD`.

**New TODOs this opened:**

- [ ] **TODO:** The claim §1.4 made was *testable* (`git status` after the change shows
      nothing outside `helper_applications/debug_monitor/`). What replaced it is a *reviewable*
      property — "the launcher names the module in a string and never imports it". If that is
      worth keeping honest, it wants a test: import `pypts.launcher.startup` and assert no
      `pypts.helper_applications` module is in `sys.modules`.
- [ ] **TODO (revert before v1.0):** `--debug-monitor` defaults to `True`. Put it back to
      opt-in - `default=False`, or `store_true` again - when the refactor is over and runs
      stop being developers'. The same revert as §1.6's DEBUG log level, and worth doing in
      the same change: an operator's run should open one window, not two.
- [ ] **TODO:** The child inherits the launcher's stdout. In a terminal that is right; behind
      a **pipe** it means the pipe stays open after pypts exits, because the Monitor is still
      holding it — which is how it behaved when the verification run was piped into a reader.
      Harmless interactively, surprising in a script. Fix, if wanted, is `stdout=DEVNULL` on
      the Popen, at the cost of losing the child's own error output.
- [ ] **TODO:** Ctrl+C in the launcher's console reaches the Monitor too, since no
      `CREATE_NEW_PROCESS_GROUP` is set — so the "left running" promise holds for a normal
      exit but not for an interrupted one. Deliberately not fixed: the flag would be
      Windows-only, and the normal exit path is the GUI window closing or the CLI `exit`.
- [ ] **TODO:** `pid` is the process the launcher spawned. Under a `uv`-created venv on
      Windows, `.venv\Scripts\python.exe` is a trampoline that execs the real interpreter, so
      the logged pid is the trampoline's and a *second* process shows the same argv. It costs
      nothing today — the launcher never signals the child — but it would matter to anyone who
      later decides to stop the Monitor by pid.

### 1.5 Topology change: Sequencer and Report as threads — **done**

> **Status: implemented.** The change agreed in *"Agreed architecture change: two processes,
> threads inside the engine"* below is carried out for the two modules that exist. What that
> section describes is now what the code does; it stays as the reasoning and the remaining
> TODOs (StreamHandler, HAL as a library, the promotion rule).

**What changed.** `Core.start_submodules()` builds `threading.Thread` instead of
`multiprocessing.Process`, and `Core.__init__`'s `queue_factory` defaults to `queue.Queue`
(that argument was removed later — see §1.12; the four links are plain `queue.Queue` now).
`sequencer_main()` and `report_main()` lost their `log_queue` / `log_level` parameters and no
longer call `init_logging()` — the root logger belongs to the Core process, and a thread
reconfiguring it would tear the handler off a logger the other threads are using. `Core.start()`
gained `join_submodules()`, which waits for both threads after the loop ends. The threads are
daemons, so one that wedges cannot keep the process alive.

The process tree is now: **launcher → Logger, CORE (+ Sequencer and Report threads), and the
GUI**; in CLI mode the frontend runs in the launcher's own process, so there are three
processes in GUI mode and two in CLI mode.

**Renames in the same change** (structure only — the messages themselves are untouched):

| Was | Is | Why |
|---|---|---|
| `messages/channel.py` · `Channel` | `messages/queue_wrapper.py` · `QueueWrapper` | Says what it is: a wrapper over anything queue-shaped, now spanning a process boundary *and* a thread boundary |
| `messages/hmi_link.py` | `messages/core_hmi_communication.py` | A link module is named after **both** ends it joins, and holds both directions |
| `messages/sequencer_link.py` | `messages/core_sequencer_communication.py` | ditto |
| `messages/report_link.py` | `messages/core_report_communication.py` | ditto |
| `messages/logger_link.py` | `messages/to_logger_communication.py` | The exception, named for its single direction: nothing is ever sent back |

The message catalogue moved out of `resources/internal_reports/messaging_overview.html` §4 into
`src/pypts/messages/messages.md`, as that module's context file. Reworking the message set is
its own task and is deliberately not part of this one.

**What it bought.** The four engine links are in-process: nothing on them is pickled, and the
engine will be able to hand the Sequencer a live object — a `Recipe`, a device handle — when
the execution engine lands. Only `core_hmi_communication` still needs to be pickle-safe, and the test
that enforces that is unchanged.

**What it cost, and what is now open:**

- [ ] **TODO:** **The run log can no longer tell the two apart.** `LOG_FORMAT` uses
      `%(processName)s`, so Sequencer and Report records both read `Core`. Decided
      deliberately for now — the `filename:funcName` column and the link name in a trace line
      still identify them — but adding `%(threadName)s`, or replacing the process column with
      it, is the fix if that stops being enough. It would also change the Monitor's parser and
      every sample line in the tests.
- [ ] **TODO:** **A fault in either thread now takes CORE with it.** The mitigation the
      architecture section assumes — the GUI survives and reports it — holds, but the
      heartbeat-timeout policy TODO below is now the *only* place a stuck module gets noticed.
- [x] **DONE (plans/002):** shutdown is ordered: `StopReport` is held until
      `SequencerStopped` (or the shutdown deadline), so a run aborted by
      shutdown still gets its CSV tail and its report.html; and a sequence
      thread that outlives the 2 s join is reported to the operator as a
      CRITICAL ModuleError ("bench state unknown") instead of only an ERROR
      log line. Policy for *acting* on it stays the §1.11 TODO.
- [ ] **TODO:** `Core.__init__` still accepts `log_queue` and `log_level` and no longer needs
      to hand them anywhere. Keep them only until it is settled whether a future in-engine
      module needs them; drop them otherwise.

---

### 1.6 The message trace is on by default, for now — **done, and temporary**

> **Status: implemented, deliberately temporary.** `config.ini` ships `[logging] level =
> DEBUG` instead of `INFO`, so every run carries the full message trace without anyone having
> to ask for it, and the Debug Monitor (§1.4) always has something to read.

**This reverses a decision §1.2 took on purpose**, and the reasoning there still stands: a
trace is "the right thing to ask for deliberately and the wrong thing to get by default", and
an idle run writes about six heartbeat lines a second — roughly 170k lines in an eight-hour
run. What changed is not the argument but the phase. During the refactor nearly every run is
a developer's, the engine does not exist yet so the volume is heartbeats rather than real
traffic, and the cost of a failure that happened to be recorded at INFO is a whole run
repeated. After v1.0 the balance goes back the other way, which is why the revert is a TODO
below rather than an intention.

**Where the default lives, which is not where you would guess.** The launcher resolves
`args.log_level or config.get_parameter("logging.level")`, so the effective default is the
*config file*, not a constant in the code. Two places therefore had to change —
`configuration_schema.py` (the `Field` default) and `config_template.ini` (the shipped
literal) — and a third had to be done by hand: pypts never modifies an existing file (§1.3),
so a `config.ini` that already exists goes on saying `INFO` until someone edits that
line. That is correct behaviour for a file that belongs to the user, and it is worth knowing
before wondering why a particular machine did not pick the change up.

`logger.DEFAULT_LOG_LEVEL` was left at `INFO` on purpose. It is the fallback for a process
with no configuration — a standalone helper application calling `init_logging()` with no
arguments — and there is no reason for the Recipe Creator to start tracing.

**Verified:** `python -m pypts --mode cli` with no flags at all produces a log the Debug
Monitor reads as a trace (`trace seen: True`), across all seven links. Full suite: **227
passed, 71 skipped**.

- [ ] **TODO — revert before v1.0.** Put `[logging] level` back to `INFO` in
      `configuration_schema.py` and `config_template.ini`. This is the same shape of debt as
      the `--mode` default that pointed at the debug console for the duration of the previous
      refactor, and it is written down for the same reason: that one was only caught because
      somebody had written it down. Nothing else has to move — `--log-level` overrides the
      config in both directions, so `--log-level INFO` already quietens a single run without
      editing the file.
- [ ] **TODO:** The heartbeat-noise TODO in §1.2 is now the difference between a readable log
      and an unreadable one on *every* run, rather than only on a run where a trace was asked
      for. Still deliberately not done — the fix would make the transport type-test its
      payload — but it is no longer hypothetical.
- [ ] **TODO:** Tests that patched the shipped literal `level = INFO` broke on this change.
      `test_config_handler.py` now rewrites that line by key (`with_log_level()`), so the
      revert above will not break them a second time. A new test that needs a particular
      level should use the helper rather than a string replace.

### 1.7 Groundwork tidy-up before the engine port — **done**

> **Status: implemented.** Mechanical debt cleared while `run_sequence()` is still a stub, so
> that the Phase 1 port lands on a branch with one style, one lint baseline and no dead code
> in the shipping package. No behaviour changed; the suite stayed at 227 passing throughout.
> Sourced from `resources/internal_reports/new_code_review.html`, a file-by-file read of the
> whole new tree.

**Dead code out of the shipping package.** `stream_handler/StreamContainer.py` and
`hmi/gui/XYGraph/` were carried across the refactor and never touched: nothing imported
either, `StreamContainer` ran code and printed to stdout at import, and `XY_graph.py` has
seven undefined names that raise if reached. Both moved to `spikes/` (see §1 item 4), which
`reuse.toml` already blanket-covers. `src/pypts/stream_handler/` stays as an empty placeholder
package. This removed 22 of the tree's ruff findings without editing a line of code.

**Ruff is configured, and enforced in CI.** There was no `[tool.ruff]` anywhere, yet the
source already carried `# noqa: BLE001`, `# noqa: DTZ007` and `# noqa: B008` — suppressions
naming rules that nothing enabled. `pyproject.toml` now selects
`E,F,I,N,UP,B,BLE,DTZ,SIM,PIE,G,RUF` at `line-length = 100`, excludes `old_code/` and
`spikes/`, and silences the un-refactored helper applications wholesale (they are Phase 6).
A pinned `lint` job runs `ruff check src tests` in the `analyse` stage. The tree is clean.

Two rules are deliberately off, both because they push toward *shorter* rather than *clearer*:

- `N818` — would rename `UnhandledMessage` and the `ConfigError` family for an `Error` suffix.
- `SIM108` — would rewrite every four-line `if`/`else` as a conditional expression.

**One logging style.** `%`-style everywhere, replacing 25 f-string call sites. It is the
stdlib convention, it keeps the laziness `queue_wrapper.py` documents at length, and ruff's
`G004` now enforces it mechanically — with `logger-objects = ["pypts.logger.log.log"]` in the
config, without which the G rules see an ordinary object and check nothing.

**One lifecycle wording**, replacing five variants (`"Starting module..."` /
`"stopping module"` / `"Stopping module"` / `"exited main event loop."`):

| Event | Line |
|---|---|
| `start()` begins | `Starting module.` |
| `main_loop()` begins | `Starting main event loop.` |
| `main_loop()` ends | `Left main event loop.` |
| `stop()` handler | `Stopping module.` |
| `start()` ends | `Module stopped.` |

The CLI also announced itself twice — once in `__init__` and again in `run()`; the duplicate
is gone.

**Finished the `channel` → `QueueWrapper` rename**, which had stopped at the code: the
parameter and attribute in `HeartbeatManager` (now `outbox`), `Core.poll()`'s parameter (now
`inbox`), and roughly thirty variables plus eight *test names* across three test modules. One
comment in `logger/log.py` had been mangled by the rename into a sentence that no longer
parsed; it is rewritten.

**Three documents had drifted** and were corrected: `CLAUDE.md` said `config.ini` ships as
`INFO` (it ships `DEBUG`, §1.6); `messages/messages.md` said `PendingRequests` has no user
(the Sequencer owns one and calls `return_caller()` — the *asking* half is what is unused);
`debug_monitor/__init__.py` claimed its parser and liveness fold import no running framework
(true of the parser only — see the Phase 0 item below).

**Module renames**, filename only, for readability — no class or union type changed:
`queuewrapper.py` → `queue_wrapper.py`, `requests.py` → `blocking_messages.py`, `common.py` →
`common_messages.py`, and the four `*_link.py` modules → `*_communication.py`. The first of
those is load-bearing: the filename appears in every trace line through `%(filename)s`, so
`trace_parser.TRACE_LOCATIONS` had to move with it, and a real send/receive round trip was
checked rather than only the sample-text tests. Logs written before the rename no longer show
a trace in the Monitor; that is accepted rather than papered over with a second spelling.

### 1.8 The Sequencer runs a sequence on its own thread — **done**

> **Status: implemented.** The threading shape only, not the engine:
> `execute_sequence()` is still the stub it was. Done now precisely *because* it is a stub —
> the change is small and testable while the body is one `log.warning`, and the Phase 1 port
> then drops into a structure that already works instead of discovering the constraint half
> way through.

**What was wrong.** `main_loop → poll_core → handle_core_message → run_sequence` all ran on one
thread. Harmless today; the moment the engine lands, three things break at once:

| | Consequence |
|---|---|
| `do_periodic_tasks()` never runs | Heartbeats stop. CORE's timeout is 5 s, so **every real run** logs "Heartbeat timeout for module: sequencer" |
| The inbox is never drained | `StopSequence` sits unread — the abort path is dead exactly when it is wanted |
| The inbox is never drained | `UserPromptResponse` sits there too, so a step in `PendingRequests.wait()` waits out its five-minute timeout and gets `None` |

The third is the deadlock `messages/blocking_messages.py` has warned about since it was written:
*the thread that calls `wait()` must not be the thread that drains the inbox.*

**The shape now.** `run_sequence()` runs on the loop thread, refuses a second sequence while one
is running (a `RuntimeError`, which `@catch_and_report_errors()` turns into a `ModuleError` the
operator sees), clears `stop_requested`, starts a named daemon thread on `execute_sequence()` and
returns. `stop()` sets the flag, joins the thread with a budget deliberately below CORE's
`SHUTDOWN_TIMEOUT_S`, and only then sends `SequencerStopped` — CORE exits as soon as all three
modules have reported, so reporting while a sequence still ran would be a lie CORE acts on.

**Verified against the old shape, not just the new one.** The eight tests in
`test_sequencer.py` drive `poll_core()` by hand, so "the loop can still run" is an assertion
rather than a hope. Reverting `run_sequence()` to the synchronous call fails four of them,
including the prompt test, which takes 40 s to fail because it sits in `wait()` until timeout —
the failure mode itself, reproduced.

Left for Phase 1: `execute_sequence()` must check `stop_requested` *between* steps rather than
inside one, so a step can leave its hardware in a known state. There is a skipped placeholder
for it.

### 1.9 mypy over the message layer — **done**

> **Status: implemented.** `[tool.mypy]` in `pyproject.toml`, a `typecheck` job in the
> `analyse` stage, and `mypy` in the `dev` extra. Clean: 24 files, no issues.

**Scoped, not `strict`, and not the whole tree.** It covers `messages/`, `core/`,
`sequencer/`, `report/`, `logger/`, `utilities/` and `hmi/hmi_client.py` — where the
annotations are load-bearing. `old_code/` is frozen, `spikes/` is experiments, the helper
applications are Phase 6, and demanding an annotation on every local would bury the message
contract in noise. Widening it is cheap later.

**What it adds over the protocol tests**, which already prove no message reaches
`unhandled()`: the check happens while the code is being written rather than when the suite
runs, and the `QueueWrapper[X]` parameterisation is checked *at all* — before this,
`self.to_sequencer.send(StatusChanged("x"))` ran perfectly and put the wrong message on the
wrong link.

**What the first run actually found**, on the whole existing tree: two errors, both in the
§1.8 code written the same day — `stop_running_sequence()` calling `.join()` on a
`Thread | None` that only a helper method proved was not None. Narrowing a type checker
cannot follow, which is the class of defect this exists to catch. Fixed by binding the thread
to a local, which reads better anyway.

**What it did *not* flag is the more interesting result.** `deliver_response()` assigns
`value` inside `match` arms and reads it afterwards, which looks like a possibly-unbound
variable — and is not, because `unhandled()` is typed `NoReturn`, so the fallthrough provably
cannot reach the read. The `Never`/`NoReturn` trick in `queue_wrapper.py` was doing its job
before anything was checking it.

### 1.10 Two error decorators — **done**

> **Status: implemented.** Closes the Phase 0 item "harden `catch_and_report_errors`". The
> mechanism is in place; what a caller *does* with a step failure is still Phase 1's to decide.

`utilities/error_handling.py` now offers two decorators, and which one a piece of code uses is
a property of where it sits:

| | Behaviour | For |
|---|---|---|
| `@catch_and_report_errors()` | reports to CORE, **swallows**, returns `None` | event loops and housekeeping — a module that dies on one bad message stops answering CORE, stops heart-beating, and takes the run with it |
| `@report_and_reraise()` | reports to CORE, **re-raises** | the execution layer — a step failure has to reach a `StepResult` with `ResultType.ERROR`, and a step whose failure is only a log line is a step the report will call PASS |

Two names rather than one decorator with a `reraise=` flag: which behaviour applies should be
readable at the call site without checking an argument, and a flag would leave the default as
the dangerous one for steps.

`raise`, not `raise exc`, so the frame the failure happened in survives into the traceback the
step turns into a result. There is a test for exactly that.

**Neither assumes `self.core` any more.** An object with no outbox — a driver, a helper, a
half-built object under test — is logged instead. That was the other half of the Phase 0 item,
and it mattered more than it looks: reaching for a missing `self.core` raised `AttributeError`
*from inside the error handler*, replacing the real failure with a far less interesting one.

Nothing uses `report_and_reraise()` yet; it lands with the steps in Phase 1. The decorator is
tested on both paths in `test_utilities.py`.

*Superseded in part by §1.11: the decorators are unchanged, but they are no longer the only way
to report a failure, and the reported message now names the method and the exception type.*

### 1.11 Handling a specific error where it happens — **done**

> **Status: implemented.** Groundwork only, by decision: a raise site can now classify and
> report a failure it recognised. What CORE *does* about one is deliberately unchanged.

**The problem.** Everything reached CORE, and nothing was classified, so nothing could act on
one. Three things were missing:

- `report_error()` hard-coded `severity=ErrorSeverity.ERROR`, so `WARNING` and `CRITICAL` were
  produced by nothing at all and CORE's one severity branch was effectively dead code;
- `ModuleError.source` was `func.__module__` — the *module*. Which of a module's twenty methods
  failed was recoverable only by reading the traceback string;
- the exception type reached CORE only inside `repr(exc)`.

The decorators could not have fixed that: what a failure *means* is knowable at the raise site
and nowhere else. A decorator wrapping a whole method can only call everything an ERROR.

**The split, now three ways.** The decorators are the net for what nobody expected; the two
functions are how a method handles what it recognised:

```python
try:
    reading = self.instrument.measure()
except TimeoutError as exc:
    report_error(self, exc, severity=ErrorSeverity.WARNING)   # slow, not broken
    reading = self.retry_measurement()
```

| | For |
|---|---|
| `report_error(instance, exc, severity=…)` | a live exception the method caught and understood. Fills `error_type` and the traceback. |
| `report_problem(instance, message, severity=…)` | a failure with no exception behind it — a refused command, an instrument answering nonsense. Raising one only to catch it a frame later would attach a traceback through the module's own guard, which tells the reader nothing. |

Neither raises. The raise site keeps control of what happens next, because that decision belongs
to it and not to the error-reporting module. Anything a method does *not* recognise still falls
through to its decorator, unchanged.

**`ModuleError` gained two fields** — `operation` (the failing method's qualname) and
`error_type` (the exception class name). Plain strings, for the same reason `exception` is a
repr: the message crosses the pickled HMI link. The decorators fill both in from the function
they wrap, resolved at decoration time next to `source`, so an *unexpected* failure names its
method too. Both decorators also take `severity=`, so a method whose failure is routine can say
so once, where it is decorated, instead of at every raise site inside it.

**CORE's authority is unchanged, on purpose.** `handle_module_error()` still logs and still
forwards anything above `WARNING` to the frontend. What changed is that the log line names the
method and the exception type before the message, and the *level* now follows the severity
(`WARNING`/`ERROR`/`CRITICAL`) — which is the first time `ErrorSeverity` has meant anything. No
policy table, no run control: see the open TODOs below.

**First real use:** `Sequencer.run_sequence()` refusing a second sequence. It used to
`raise RuntimeError(...)` and let the decorator convert it; the module knows exactly what that
is — the operator asked for something it cannot do — so it reports it and returns. Same
`ModuleError` to CORE, same line to the operator, without a traceback through the guard that
produced it.

Six tests in `test_utilities.py` cover the new half, including the no-outbox fallback for both
functions.

- [ ] **TODO (Phase 1):** decide what CORE *does* about an error beyond recording it — stop the
  running sequence, abort the run, contribute to the run's `ResultType`. Needs the engine to
  exist first; this is the same open item as the `FAIL`-vs-`ERROR` question below.
- [ ] **TODO:** revisit whether a `PyptsError` base + family is wanted once the steps and the HAL
  are ported. It was deliberately *not* introduced here — a raise site matches on the concrete
  exception it already knows about, and a taxonomy with one user is a guess.
- [ ] **TODO:** the heartbeat-timeout policy (`core.py: do_periodic_tasks()`) is still only a
  warning. It is the other half of "what CORE does about a module in trouble".

---

### 1.12 `Core.__init__` no longer takes a `queue_factory` — **done**

> **Status: implemented.** A parameter removal, nothing else. No behaviour changed: every
> caller in the repo was already getting `queue.Queue` out of it.

**What it was.** §1.5 turned the Sequencer and the Report into threads and, in the same
change, left `Core.__init__` a `queue_factory=Queue` parameter that built the four submodule
links. Three reasons were recorded for keeping it. On inspection during the CORE refactor,
none of them held:

- *"What tests use to build a CORE that starts nothing."* They don't. Both call sites passed
  `queue.Queue`, which was the default. What makes a constructed `Core` start nothing is that
  `__init__` builds queues and `start_submodules()` starts threads — the argument had no part
  in it.
- *"The seam a future `--mode connect` turns."* Wrong seam. Connect mode needs event fan-out
  from CORE to several **HMI** channels (the TODO in §1.1's list), and the HMI↔Core pair is
  built by `startup.py` and handed to CORE as `to_hmi`/`from_hmi`. It never went through
  `queue_factory`. What `queue_factory` did build — Core↔Sequencer, Core↔Report — stays inside
  the Core process in every planned topology; StreamHandler joins them as a third *thread*.
- *"The queue type is injected, never assumed."* That is `QueueWrapper`'s doing, not the
  argument's: it wraps anything with `put()`/`get_nowait()`, and the launcher already exercises
  both transports. Removing the argument leaves that property exactly as it was.

So it was a variation point with no variation, and — being unannotated in a module that is
inside mypy's scope — an implicit-`Any` in the signature of the class we are refactoring.

**What changed.** The parameter is gone; `core.py` constructs the four links with `Queue()`
directly, the comment above them now says *why* a plain `queue.Queue` is the right thing there,
and the two test fixtures dropped the keyword. `from queue import Queue` stays.

Should a submodule ever need a different transport, the honest change is to pass that module's
built link in, the way the launcher already passes the HMI pair — not to re-add a factory that
guesses which links are affected.

**Verified:** the full suite unchanged at 248 passed / 69 skipped, `ruff check src tests` and
`mypy` clean.

---

### 1.13 Engine skeleton: recipe / step / sequencer, WaitStep end-to-end — **done**

> **Status: implemented.** The first slice of the Phase 1 engine port. `--mode cli` loads
> `resources/recipes/wait_recipe.yml` and runs it: `load_recipe` → `RecipeLoaded`,
> `start_sequence Main` → both WaitSteps execute on the sequence thread, every run event
> reaches the frontend, and the DEBUG trace shows the whole conversation. One step type;
> the structure is the deliverable.

**The layout.** `recipe/` is pure data — parse + validate, no queues, no Sequencer import
(pinned by a test that imports it in a fresh interpreter). `step/` is the execution unit:
`step.py` (base `Step` lifecycle, `StepResult`, `run_steps()`, `run_sequence()` — the
sequence body a future `SequenceStep` reuses), one module per concrete step type
(`wait_step.py`, `python_module_step.py` — the schema every newly ported type follows),
`registry.py` (the
`eval()` replacement: a dict `steptype -> class`, unknown names get an error listing what
exists — F11 closed), `runtime.py` (globals + the locals stack + two callable seams).
`sequencer/execute_sequence()` looks the sequence up, builds a `Runtime`, and brackets the
run with `RunStarted`/`RunFinished`.

**The emission model.** `Runtime` carries `emit` (the Sequencer passes its outbox's
`send`) and `should_stop` (a lambda over `stop_requested`). `Step.run()` emits
`StepStarted`/`StepFinished` itself; `run_sequence()` emits the sequence pair; the
Sequencer only the run pair. Chosen over "the sequencer loop emits" because a nested
sequence inside a future `SequenceStep` then reports through the same channel it already
holds — no rework when nesting lands. `step/` imports message *dataclasses* only, never
`QueueWrapper`; a bare `Runtime()` is a complete fake context, which is what keeps steps
testable stand-alone.

**The recipe handoff.** CORE loads and validates (`Recipe.from_file`, every failure a
`RecipeError`), stores the recipe, answers `RecipeLoaded` to the HMI — and hands the **live
`Recipe` object** to the Sequencer in the new `UseRecipe` message on the internal link.
That is the design choice §1.5 left open ("whether to allow live objects on the engine
links"), now taken deliberately: this link never leaves the Core process, nothing is
pickled, and the message's docstring says so. The boundary link stays pickle-tested and
carries only `StepOutcome`, the flat projection of the rich, engine-internal `StepResult`.
An invalid recipe never reaches the Sequencer — CORE reports the `RecipeError` through
`report_own_error()` (CORE has no outbox to itself, so it builds the `ModuleError` by hand
and feeds its own `handle_module_error`) and sends nothing.

**Old defects fixed by construction during the port:** F3 (`execute_sequence` runs the
*requested* sequence; `main_sequence` is only the frontend's default), F11 (`eval` → the
registry), F12 (mutable-default mappings), F16 (sequence locals pushed as a copy, so a
re-run starts clean), the `global_name` short-circuit that made `case "global"` dead code,
the silent skip of unnamed sequence documents and silent last-wins of duplicate names
(both are `RecipeError`s now), the caller's step dict being mutated, and teardown's
accidental `stop_event.clear()` (teardown now runs with the stop check suppressed,
explicitly). The run invariant an HMI depends on is pinned by test: **`RunStarted` is
answered by exactly one `RunFinished`**, whatever happens in between.

**Deliberately kept / deferred, each with the reasoning:**

- **F6 kept for parity (decided):** when several `output_mapping` entries judge, the last
  one wins, exactly as the old engine did. Documented in `process_outputs()` and pinned by
  a test that says so.
- **continue_on_error is not ported.** The old engine had three disagreeing sources of
  truth (runtime attribute, global variable, per-step YAML key — F8 leaked one step's
  setting onto the next). Current policy is minimal and explicit: a step ERROR stops the
  sequence, FAIL never does, `skip` is honoured, `critical` is parsed and stored but not
  consulted. The real policy design is a Phase 1 decision.
- **WaitStep sleeps in one piece.** The framework contract is a stop at the *step
  boundary* (pinned by `test_stop_requested_is_checked_between_steps_not_inside_one`); a
  stop-aware sliced sleep is a courtesy for later.
- **`id:` must now be a valid UUID string when given.** The typed events
  (`StepStarted.step_id: UUID`) force it; no existing recipe sets one.

**Verified:** 305 passed / 52 skipped (was 248 / 69 — the recipe, step, sequencer-engine
and core-orchestration placeholders are real tests now), `ruff check src tests` and `mypy`
clean, and the end-to-end CLI run confirmed on Windows: `--mode cli --log-level DEBUG`,
`load_recipe resources/recipes/wait_recipe.yml` → `RecipeLoaded`, `start_sequence Main` →
both steps DONE, `Run finished: DONE (2 steps)`, clean shutdown, exit 0 — and the run log
carries the full send/recv trace including `UseRecipe` on `core->sequencer`.

**New TODOs this opened:**

- [ ] **TODO:** revisit F6 - should every judging `output_mapping` entry have to pass
      (worst verdict wins), as the old documentation claimed? One-line change in
      `process_outputs()` plus the pinning test; a behaviour change, so decide it, don't
      slip it in.
- [ ] **TODO:** design the continue_on_error policy (per-recipe? per-step? `critical`
      re-arming the stop?) before porting the step types that used it - one source of
      truth this time.
- [ ] **TODO:** `WaitStep`: sleep in slices and honour `should_stop()`, so a long wait
      does not hold up an abort.
- [ ] **TODO:** stable step ids - the old code accepted arbitrary strings for `id:`; the
      typed events force UUIDs. Decide a policy (hash of name? explicit UUIDs in the
      Creator?) before the Report and the Creator need stable identity across runs.
- [ ] **TODO:** the `"method"` input type (identical to `direct` in the old code) returns
      with `PythonModuleStep`.
- [x] **DONE (§1.19):** `Core` triggers `GenerateReport` on `RunFinished`, and forwards the
      run events the Report records.
- [ ] **TODO:** the CI `typecheck` job installs only mypy, so `[[tool.mypy.overrides]]`
      silences the missing PyYAML; install `types-PyYAML` (or the package) in that job and
      drop the override.
- [ ] **TODO:** `resources/recipes/*.yml` other than `wait_recipe.yml` still target the
      old engine's step types and a missing `example_tests.py` (F24);
      `test_every_example_recipe_in_resources_parses` stays skipped until the registry
      grows. Unskip it steptype by steptype.

---

### 1.14 GUI groundwork: old GUI studied, scaffold vendored as PySide6 — **done**

> **Status: two preparation steps for the GUI rebuild are in; the GUI itself is
> unchanged (still the minimal status window).** The plan for the rebuild lives in
> `src/pypts/hmi/gui/gui.md` — the module context file — not here.

**The study.** `old_code/gui.py` (868 lines) plus its event proxy, command loop and
assembly were read end to end and written up in `hmi/gui/gui.md`: the screen anatomy, the
nine-signal pipeline, the UUID-keyed step table mechanic, the toolbar state machine, the
interaction pattern, the result color table — and the defects not to reproduce (the GUI
parsing the recipe itself, the `sleep(1)` startup race, the nested-QEventLoop abort, the
root-logger tap, live engine objects in the view). Section 4 of that file maps every old
mechanism onto its typed equivalent in the new architecture; section 5 lists what the
basic-execution GUI still needs decided.

**The scaffold.** The GUI's layout will come from `pyrade_gui_scaffold` 1.3.0 (CERN RADE's
four-panel QSplitter main window). Upstream is PyQt6 — the GPL licensing the PySide6
migration removed — so it is **vendored as a PySide6 port** in `src/pypts/hmi/gui/scaffold/`
(same class names, same public API, upstream's test suite ported alongside:
18 tests in `tests/unit_tests/test_gui_scaffold.py`), with provenance in the package
docstring. Reviewed against the old GUI's features first: everything fits the four regions;
the mapping and the one API trap (`set_content()` deletes, so it is assembly-time only) are
recorded in `gui.md` §6.

**Verified:** 323 passed / 52 skipped, `ruff` and `mypy` clean.

**New TODOs this opened:**

- [ ] **TODO (license):** the template repo carries **no license** (no LICENSE file, no
      SPDX, no pyproject `license` field). The port proceeded on the user's decision with
      full attribution; get written clearance from its author (or a LICENSE upstream) and
      record the license in the vendored package **before any release**.
- [x] **DONE (§1.15):** fit the basic-execution GUI into the scaffold per `gui.md` §5-§6:
      the panel content widgets, `GUI(HmiClient)` as the assembler, and the two protocol
      gaps (the recipe summary and the HMI→CORE stop-the-run message).

---

### 1.15 The four-panel operator GUI, and the two protocol additions it needed — **done**

> **Status: implemented.** `python -m pypts` now opens the real operator screen: open a
> recipe → the step table pre-fills "Pending" and the sequence chooser offers every
> sequence (main selected) → Start → rows go "Running..." then take the old color table's
> verdicts live → Stop aborts at the step boundary → the status line narrates. The CLI
> gained the same abort (`stop_sequence`). Design record: `hmi/gui/gui.md` §5 (each of the
> five open points, settled) and §6.

**Protocol addition 1 — the operator's abort.** `StopSequence` moved from
`core_sequencer_communication.py` to `run_events.py` and joined `HmiToCore`: it rides two
links and CORE relays the same object (the shared-message rule in `src/pypts/README.md`,
the `UserPromptResponse` precedent — also what keeps `recipe/`+`yaml` out of the HMI
process's import graph). `HmiClient.stop_sequence()` sends it; the confirmation is the
run's own `RunFinished(STOP)`, so nothing waits. CLI verb: `stop_sequence` (`stop` was
already an exit alias).

**Protocol addition 2 — the recipe summary.** `RecipeLoaded` now carries `main_sequence`
and `sequences: tuple[SequenceSummary, ...]`, each a tuple of
`StepSummary(step_id, step_name, description)` built by `Recipe.to_summary()` /
`Sequence.to_summary()` (mirroring `StepResult.to_outcome()`). The summary includes the
**teardown steps** — they run through the same lifecycle and emit the same events, so they
need table rows. This closes the old GUI's ugliest habit: parsing the recipe a second time
GUI-side just to fill the table (`gui.md` §3). The `show_recipe_loaded` hook now takes the
whole event.

**The GUI itself.** `gui.py` is the assembler (`GUI(HmiClient)` builds the scaffold
window, one content per panel, one `set_content()` each); the contents are pure views:
`top_bar.py` (Open/dropdown/Start/Stop + the event-driven state machine — every transition
caused by a message, nothing blocks), `step_table.py` (the UUID-in-UserRole row mechanic,
verdicts in `result_colors.py`'s old table, error_info as tooltip), `center_view.py` (a
QStackedWidget: CERN-logo idle page — the logo is package data under `hmi/gui/images/` —
a prompt page and a serial-number page, with an exactly-once answer guard: a new request
declines the unanswered one, RunFinished cancels whatever is pending, and the pair is
cleared before the callback fires). The serial form is a page, not the old modal dialog —
no nested event loop. `PtsMainWindow` subclasses the scaffold (scaffold untouched) to turn
the first [X] into `ShutdownRequested`; the real close happens on `StopHmi`, so closing
the window can no longer orphan the engine.

**Verified:** 341 passed / 51 skipped (18 GUI tests, was 8), `ruff` and `mypy` clean, and
a CLI end-to-end on Windows that exercised load → start → a *refused* second start
("already running", shown to the operator) → `stop_sequence` mid-run →
`Run finished: STOP (1 steps)` → clean exit 0.

**New TODOs this opened:**

- [ ] **TODO:** the interactive prompt pages have no sender yet — the `User*` step types
      are the next engine port, and the GUI side of them is now already built and tested.
- [ ] **TODO:** the old GUI's File/About menus (wiki, GitLab, recipe-creator launcher) and
      the live log box were deliberately left out of the basic screen — Phase 3, with the
      widget system. Same for dark mode: `force_light_mode()` pins the light scheme because
      the verdict colors are designed light; a dark palette is a Phase 3 design task, not a
      toggle.
- [ ] **TODO:** `StepStarted` for a sequence the table is not showing logs a warning and
      is dropped; revisit when `SequenceStep` nesting lands (the display policy for nested
      rows lives in the presentation layer now, not the transport).

---

### 1.16 PythonModuleStep, minimal — **done**

> **Status: implemented.** The second step type: call one Python function with the
> recipe's resolved inputs as keyword arguments and judge what comes back. Demo:
> `resources/recipes/python_demo.yml` + `example_tests.py` beside it — four function tests
> (equals, range, a deliberate passfail FAIL, a wrapped scalar) and a 2 s wait; verified
> end to end in the CLI: PASS/PASS/DONE/FAIL/PASS → `Run finished: FAIL (5 steps)`.

**What was ported and what deliberately was not.** `action_type: method` only —
`read_attribute`/`write_attribute` stay in old_code, refused with a clear error. Module
resolution replaced the old project-wide rglob heuristic (bare `except` at its heart,
`old_code/steps.py __load_module`): a recipe's `module:` is either **a file next to the
recipe** (`example_tests.py` or `example_tests`; `Recipe.from_file` records `base_dir`,
the Sequencer hands it to the `Runtime`, absolute paths work too) or **a dotted import
name** (stdlib/installed code). File-loaded modules are executed without touching
`sys.modules`.

**Verified:** 350 passed / 51 skipped, `ruff` and `mypy` clean, plus the CLI run above.

**New TODOs this opened:**

- [ ] **TODO:** the module-loading *design* is still the recorded open question — this
      port is the minimal contract (beside-the-recipe or importable), and the old
      `test_package` header key is still tolerated-and-ignored. Decide the final shape
      before the verificator learns to check `module:`/`method_name:` resolution.
- [ ] **TODO:** `resources/recipes/simple_recipe.yml` steps 2-9 now *almost* run (they
      use PythonModuleStep + WaitStep) but reference the still-missing `example_tests.py`
      module with different function names (F24) and a `UserInteractionStep` first step.
      Revisit when the User* types land.

---

### 1.17 Recipe format simplified: rules as code, one validator, `PythonModule`/`Wait` — **done**

> **Status: implemented.** The recipe format for the two ported step types is now defined in
> one importable place and enforced by one validator, and a recipe states **only what it
> needs**: every optional field left out is assumed empty. No `{}`/`[]` boilerplate ever again.
> Reference recipe: `resources/recipes/python_demo.yml`; readable rules page:
> `resources/internal_reports/recipe_format.html`.

**The pieces.**

- **`recipe/rules.py`** — the format rules as data: required fields, optional fields and their
  defaults, per-steptype required keys (`STEP_TYPE_REQUIRED`) — definitions only, the code
  that acts on them lives in the parser and the validator. A
  header needs only `name`; a sequence only `sequence_name` and `steps`; a step `steptype`,
  `step_name` and what its type requires. A bare `locals:` line (YAML None) counts as absent.
  An omitted `main_sequence` means *the first sequence in the file*. This is the beginning of
  the "one per-steptype schema" the format study asked for (F9/F19/F21/F23) — the old
  verificator's tables and `Step.REQUIRED_INPUTS` (now removed) are superseded by it.
- **`recipe/validator.py`** — parsed YAML in, a list of problems out. The parser runs it before
  building anything and raises **one `RecipeError` naming every problem at once**, so a bad
  file is fixed in one round trip.
- **Steptype names drop the `Step` suffix in YAML**: `steptype: PythonModule`, `steptype: Wait`
  (case-insensitive, only these spellings — the class names keep the suffix). A `Wait` carries
  `wait_time` directly on the step — no `input_mapping` nesting, no `output_mapping` — because
  a fixed wait has no inputs to resolve and nothing to judge.
- **The recipe language is case-insensitive** (`recipe_parser.py`'s normalize functions,
  applied once in the parser so everything downstream stays strict): keys, `steptype`,
  mapping `type`/`action_type` values, and the `main_sequence` lookup ignore case; sequence
  names must therefore be unique without case. `module`, `method_name`, variable names,
  mapping entry names and compared values keep their case — they name the user's code and
  data, which are case-sensitive.
- The demo and fixture recipes (`python_demo.yml`, both `wait_recipe.yml`) were trimmed to the
  new format and double as its showcase.

**Verified:** 358 passed / 31 skipped, `ruff` clean on everything touched, `mypy` clean.

**New TODOs this opened:**

- [ ] **TODO:** `helper_applications/recipe_verificator/` still carries its own (older,
      disagreeing, broken-import) rule tables — when it is refactored it must import
      `recipe/rules.py` + `recipe/validator.py` and delete its own copies. Its remaining
      added value over `Recipe.from_file` is YAML line numbers in the messages.
- [ ] **TODO:** the unported example recipes still spell steptypes with the `Step` suffix;
      rename them as their types are ported (they do not parse today either way).

---

### 1.18 Recipe package layered: `recipe_parser.py`, warn-only `format_version` — **done**

> **Status: implemented.** The final cut of the recipe package's separation of concerns:
> `rules.py` defines → `validator.py` checks → **`recipe_parser.py` does the work** (read,
> YAML-parse, normalize case, validate, version-check, apply defaults, build) →
> `recipe.py` is pure data: the `Recipe`/`Sequence` objects the Sequencer executes.

`Recipe.from_file()` / `Recipe.from_yaml_text()` stay as thin facades delegating to
`recipe_parser.load_recipe()` / `parse_recipe()` (parser imported inside the method body -
the module-level dependency runs one way, parser → data), so CORE and the existing tests
needed no changes; the untouched suite is the proof the move broke nothing.

New with the layer: the **`format_version` check, warn-only** for the duration of the
refactor. The optional header key declares which format the recipe was written for; absent
means "the current one"; a mismatch against `rules.RECIPE_FORMAT_VERSION` is one ERROR log
line ("… - loading anyway") and the recipe still loads. The hard refusal and the
supported-versions window come with the compatibility policy, ~v1.0 (§4 risk entry).

**Verified:** 365 passed / 30 skipped (the reserved `format_version` placeholder became two
real tests), `ruff` and `mypy` clean.

---

### 1.19 The Report is real: incremental CSV + HTML per run — **done (first slice)**

> **Status: implemented.** The first half of Phase 1 step 4. A run now leaves artefacts:
> one folder per run under `paths.reports_dir`, a `report.csv` that grows step by step
> while the run is going, a self-contained `report.html` built when it finishes, and the
> operator told where it all is — the CLI prints the path, the GUI's new
> **"Open report folder"** button opens the folder.

**The message flow, following the architecture rather than working around it:**

1. `Step.run()` now also emits **`StepExecuted`** (new, in `run_events.py`), right after
   `StepFinished`: the rich per-step record — `StepOutcome` plus `step_type`, the resolved
   `inputs`, the judged `outputs`, `started_at` and a `duration_s` measured with a
   monotonic clock around the whole lifecycle. **Engine-internal by contract**: it rides
   Sequencer→CORE and CORE→Report only, never the HMI boundary — the flat `StepOutcome`
   remains the pickled projection, exactly the split its docstring always promised.
2. CORE forwards `RunStarted` and `SequenceStarted` to the Report as well as the HMI,
   routes `StepExecuted` to the Report alone, and on `RunFinished` forwards it and sends
   `GenerateReport` right behind it — one queue, so the Report closes the CSV before it is
   asked to generate. This closes the §1.1 wiring TODO.
3. The Report opens `<timestamp>_<recipe name>/report.csv` on `RunStarted` (a collision
   gets a numeric suffix), appends **and flushes** one row per `StepExecuted` — a run that
   dies mid-sequence still leaves the results it produced — closes it on `RunFinished`,
   writes `report.html` from the recorded rows on `GenerateReport`, and answers
   `ReportGenerated(report_path)`.
4. CORE relays that to the operator as `StatusChanged` plus the new structured
   **`ReportReady(report_path, report_dir)`** (`core_hmi_communication.py`); the shared
   `show_report_ready()` hook lands in `hmi_client.py`, the CLI prints the path, the GUI
   enables the button (dead until the first report of the session).

**The CSV** mirrors the old engine's report where a column existed there
(`old_code/report.py`): recipe/sequence/step names, step id and type, result, inputs and
outputs as JSON, error info — plus `started_at` and `duration_s`, which the old report did
not have. **The HTML** is deliberately plain: run context, summary counts, one colored row
per step, inline CSS, opens from disk.

**Verified:** 387 passed / 45 skipped (test_report.py's five placeholders are ten real
tests; routing tests in test_core.py, emission tests in test_step.py, one presentation
test per frontend), `mypy` clean, `ruff` clean on everything this change touched (it
reports two E501 and a BLE001 in `logger/log.py`, pre-existing from commit ee4dc1c and
deliberately not fixed here), and the end-to-end CLI run confirmed on
Windows: `load_recipe` → `start_sequence Main` → `Run finished: DONE (2 steps)` →
`Report: …\reports\20260820_183324_Wait_demo\report.html`, with the CSV's two rows
carrying real durations (~0.5 s each).

**New TODOs this opened:**

- [ ] **TODO:** the `serial_number` column returns when something sends
      `SerialNumberRequest` (the four `User*` step types, Phase 1 step 2), and the
      `pypts_version` column with it — stamped by the Report, not carried on every event.
- [ ] **TODO:** `ExportReport`/`ReportExported` are now the Report link's only stubs. They
      wait for Phase 4's format work (`report.type`/`report.theme` are still read and
      unused, §1.3), which is also where the old TDMS plot generation gets rethought.
- [ ] **TODO:** the Report keeps the run's rows in memory for the HTML pass. Fine for
      bench-sized runs; the old code re-read the CSV instead, which is the fallback if a
      soak test ever makes this matter.
- [ ] **TODO:** the run folder solves "artifacts organized per run folder" for *reports*;
      the log file still lives in one flat `logs/` directory (the per-run-folder item in
      Phase 0's logging decision). Deciding whether the log joins the report folder is
      part of that open item.
- [x] **DONE (plans/001):** `start_run()` resets the run state *before*
      creating the run folder, so a failed `make_run_dir` (long name, unwritable
      directory) leaves the Report in the "no run open" state instead of
      silently rewriting the previous run's report.html; run-folder names are
      capped at 60 chars and never empty.

---

## TODO — Recipe format: findings and decisions

> **Status: analysed; the format itself now exists for the ported types (§1.17), the rest is
> still parked.** This section records what the study found so it can be picked up later.
>
> - **`resources/roadmap/recipe_guide.md`** — full reference: what a recipe is, what the old
>   engine actually does with it, where the three rule sets disagree, 28 findings with
>   file:line evidence, and a proposed format for the new framework.
> - **`resources/internal_reports/recipe_rules.html`** — the same rules condensed to one readable page
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
  **Started (§1.17):** `recipe/rules.py` is that schema for the two ported types; the old copies
  still exist in the unrefactored helper applications and docs.
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
- [x] **DONE (see §1.5):** Core runs Sequencer and Report as **threads**, not `multiprocessing.Process` (`core.py: start_submodules()`). StreamHandler joins them as a third thread when it lands.
- [x] **DONE (mechanism):** the **transport is not baked into any module**. `QueueWrapper` wraps anything with `put()`/`get_nowait()`, which is the whole mechanism: the launcher builds the HMI↔Core pair out of `multiprocessing.Queue` because that link crosses a process boundary, and `Core.__init__` builds its four submodule links out of `queue.Queue` because the Sequencer and the Report are threads of its own process. No module knows which of the two it is holding. See §1.12 for why the `queue_factory` argument that used to sit on `Core.__init__` is gone: `--mode connect` (TODO above) changes the *HMI* boundary, which the launcher owns, not the submodule links.
- [ ] **TODO:** HAL becomes a **plain library** imported by the Sequencer — no process, no event loop, no queue. Driver calls stay ordinary function calls; this also keeps the spec's "HAL usable standalone outside the framework" true by construction.
- [x] **DONE:** every HMI↔Core message type is round-tripped through `pickle.dumps`/`loads`, and a second test rejects any field that is not a plain value, a UUID, an Enum, a tuple or another message. Both are parametrised over the link unions, and a third test fails if a message exists without an example — so the coverage cannot rot. `tests/unit_tests/test_messages.py`.
- [x] **DONE (contract):** user interaction is a **request/response pair** joined by a `request_id` — `UserPromptRequest`/`Response` and `SerialNumberRequest`/`Response` in `messages/run_events.py`, with `PendingRequests` as the waiting side. The live `SimpleQueue` is gone. *Remaining:* wiring it into the steps themselves during the Phase 1 port, and the worker-thread requirement noted in §1.1.
- [ ] **TODO:** Define the heartbeat-timeout **policy** in Core (restart thread? abort run? notify HMI?) — currently it only logs a warning.
- [ ] **TODO:** Write down the **promotion rule**: a module moves from thread to its own process only in response to a concrete incident (e.g. a crash-prone C driver → wrap *that one driver* in a sidecar process; never the whole HAL).
- [ ] **TODO:** Bulk data (waveforms, acquisitions) never goes through message queues: in-engine it is passed by reference; if it must reach the GUI, use `multiprocessing.shared_memory` or a file-path handoff.
- [x] **DONE (plans/005):** the launcher pins `set_start_method("spawn")` on
      every platform, first thing in `main()`. Closes the Linux fork hazard
      (the bootstrap notice can create a QApplication in the launcher before
      the children exist), and makes Linux exercise the same spawn semantics
      Windows always had. Cost accepted: slower child startup on Linux.
      Linux end-to-end run still owed - see the verification note in the plan.

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
- ~~Harden `catch_and_report_errors`: re-raise or return sentinel by policy, per-function module detection, and don't require `self.core` implicitly.~~ **Done — §1.10.**
- Decide logging/config process policy. **Decided (§1.2, §1.3):** one `--log-level` for the whole run, overriding `[logging] level`, resolved once by the launcher and passed to every process as an argument, so filtering happens at the sender rather than in the Logger; and the config is created once by the launcher's `bootstrap()` (never migrated — see §1.3) and read-only everywhere else, with every process reading the file for itself. **Still open:** one log directory per *test run* with per-process log files inside it — the log directory now comes from `paths.logs_dir`, but the per-run folder does not exist yet.
- Get `run_tests.py` + unit tests green in CI on the branch; add an X-server (or `QT_QPA_PLATFORM=offscreen`) job for GUI tests (already a TODO).
- Characterization tests around `old_code`: run an example recipe end-to-end and assert on the CSV rows — this is the safety net for the port in Phase 1.
- Resolve `requirements.txt` → pyproject-only (existing TODO), REUSE check in CI (existing TODO).
- Merge strategy: get `architecture_refactor` merged to master early (it already carries the licensing work) and continue in small MRs per the Development workflow page, rather than letting the branch drift further.
- ~~Unit-test net under shutdown/abort/exit paths~~ **Done (plans/003):** Core
  fan-out + poison survival, mid-run abort partial outcomes, the HMI exit
  handshake both ways, and the launcher's `stop_core()`/monitor-wait bounds
  are asserted; two `test_core.py` placeholders became real tests.

**Exit criteria:** CI green on the branch; skeleton boots in GUI and CLI mode on Windows and Linux; characterization baseline recorded.

### Phase 1 — Port the engine into the skeleton → v0.3.0

*Goal: `pypts --mode cli`/`gui` actually loads and runs a recipe through Core → Sequencer.*

> **TODO — topology change applies here** (*→ see TODO section above*): the port targets Sequencer/Report as **threads inside the engine process**, not separate processes. Wherever this phase or the spec pages say "process" for those modules, implement a thread with the identical interface classes; only the GUI keeps its process boundary.

Recommended porting order (each step is one reviewable MR):

1. **Recipe (data layer):** ~~move loading/parsing/validation from `old_code/recipe.py` into `recipe/recipe.py`, stripped of all execution logic~~ **done (§1.13)** - every load failure is a loud `RecipeError` and an invalid recipe never reaches the Sequencer. Still open here: the verificator integration (it has its own broken-import problem, Phase 0), and `test_package` handling, which lands with `PythonModuleStep`.
2. **Step & Sequencer (execution):** **skeleton done (§1.13)** - the base `Step` lifecycle, `StepResult`, `Runtime` and `execute_sequence()` are in and all seven run events are produced on every run. What remains of this item is porting the other nine step types onto that base, one reviewable MR each, in dependency order: `PythonModuleStep` (module loading design) → the four `User*` types (the request/response prompt wiring) → `SequenceStep`/`IndexedStep` (nesting - `run_sequence()` and `StepResult.subresults` are already shaped for it) → the SSH pair (credentials move to the Config Handler first, F22).
3. **Core orchestration:** implement `LOAD_RECIPE`/`START_SEQUENCE` handlers, runtime metadata (recipe info, DUT serials, timing, machine info), result aggregation, and forwarding to HMI + Report.
4. **Report:** ~~port incremental CSV writing + HTML generation behind `GENERATE`/`EXPORT`; intermediate result file (YAML/CSV) per spec; artifacts organized per run folder~~ **first slice done (§1.19)** - incremental CSV, HTML on `GenerateReport`, one folder per run. Still open: `ExportReport`, the serial-number column, TDMS plots, and the template/theme work of Phase 4.
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
- Stream handler: promote `StreamContainer` + XYGraph — now in `spikes/stream_handler/` and `spikes/GUI/XYGraph/` — into the spec'd singleton stream layer (CSV first), fed by an acquisition logger channel. Both need rewriting rather than moving back: see §1 item 4.

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
- **Error-handling policy.** *Mechanism complete (§1.10, §1.11); policy still open.* `report_and_reraise` for the execution layer, `catch_and_report_errors` for event loops, and `report_error()`/`report_problem()` for a raise site that recognised the failure and rates it itself — so a failure now reaches its caller, carrying which method raised it and what type it was. What is still undecided is what anyone *does* with one: StepResult(ERROR) is agreed, continue-or-abort per recipe config is not, and CORE deliberately still only logs and notifies.
- **Core busy-loop & heartbeats.** 100 Hz polling in every module is fine for now; when Core gains real work, consider `Queue.get(timeout=...)`-driven loops. Heartbeat timeout currently only logs a warning — define the recovery action (restart module? abort run? notify HMI?).
- ~~**Config in the temp directory.**~~ **Closed (§1.3):** moved to the `platformdirs` per-user config directory, single writer, versioned structure (migration was later removed — see §1.3), and dotted section names for structure. It is still INI — deliberately, because the type information lives in `configuration_schema.py` and the file stays hand-editable on a bench. What remains open is *changing* configuration at runtime: `SetConfigParameter` is declared but not implemented, and there is no mechanism for telling a running process that a value changed.
- **PyPI name.** The pyproject rename to `pts-framework` needs an early availability check on PyPI (v1.0.0 requirement), and alignment with the import name `pypts`.
- **Recipe format versioning.** Before the Creator and third-party step plugins ship, the compatibility policy must get teeth. What exists (§1.18): `recipe/rules.py: RECIPE_FORMAT_VERSION = "0.1.0"` (bumped in the same change that alters a rule), the optional `format_version` header key, and a **warn-only** check in the parser — a mismatch is an ERROR in the log, the recipe still loads. Still open: the hard refusal and the supported-versions window, ~v1.0.
- **`pypts.api` stability.** Freezing the step/driver contract is the highest-leverage design decision left; review it with the module owners (per the Milestones page, each module has an assigned owner) before Phase 2 ends.
