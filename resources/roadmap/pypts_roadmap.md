# PyPTS — Development Roadmap & Plugin Architecture Proposal

*Based on branch `architecture_refactor` (read from GitLab `origin/architecture_refactor`, July 2026) and the Confluence PTS Framework specification (Framework specification, General requirements, Milestones, workflow pages, and all 12 module pages).*

---

## 1. Where the branch stands today

The `architecture_refactor` branch is a real step toward the spec: the **process skeleton and communication plumbing are built**, while the **execution engine has not yet been ported into it**. It is a "walking skeleton" — everything boots, talks, and heartbeats, but pressing "run" executes nothing yet.

### What is already done ✓

| Area | State on the branch |
|---|---|
| Package layout | Matches the system design: `core/`, `sequencer/`, `recipe/`, `step/`, `report/`, `hmi/{gui,cli}/`, `config_handler/`, `logger/`, `stream_handler/`, `hardware_layer/`, `helper_applications/{recipe_creator,recipe_verificator,example_finder}/`, `utilities/`, `launcher/`, plus `old_code/` holding the previous engine |
| Process model | `launcher/startup.py`: argparse `--mode gui/cli/connect`, spawns Core as a process; Core spawns Sequencer and Report processes — exactly the spec's module diagram |
| Typed messaging | `CORE_MESSAGES` / `HMI_MESSAGES` / `SEQUENCER_MESSAGES` / `REPORT_MESSAGES` / `COMMON_MESSAGES` with enums + dataclasses; interface ABCs + queue data-layer classes (`CoreToHMIQueue`, `HMIToCoreQueue`, …); the documented 4-step "add a message" workflow in `src/pypts/README.md` |
| Health & errors | `HeartbeatManager` ticking from Sequencer/Report/HMI, Core-side timeout detection; `@catch_and_report_errors()` decorator sending `ModuleErrorEvent` to Core |
| GUI toolkit | **PySide6 migration done** (GUI skeleton + `test_pyside6_conversion.py`) — the PyQt6/LGPL conflict is resolved |
| Licensing | LGPL-2.1-or-later + CC-BY-SA-4.0, SPDX headers, `reuse.toml`, `licenses/`, `dependency_license_analysis.rst` — REUSE compliance largely in place |
| Logger | Global root-logger override: timestamped format (file:function, ms), file + stdout handlers, `set_stdout_logging_enabled()` toggle |
| Config handler | INI template copied to a per-user temp dir, auto-filled OS section, `read_config_key()` |
| Recipe verificator | Substantial real implementation: YAML line-map extraction, faults vs warnings, per-steptype required fields, bulk folder validation, string-variable validation for the creator |
| Recipe creator | GUI application present (`recipe_creator.py`, custom GUI modules, styles) |
| Tests | `unit_tests/unit_tests/` + `functional_tests/` + `run_tests.py` (event proxy, recipe, report, steps, GUI, version…) |
| Resources | `resources/{recipes, example_commented_recipes, examples, images}` reorganization done |

### What is placeholder / not yet ported

1. **The execution engine.** `sequencer.run_sequence()` is `pass`; `recipe/recipe.py` is a one-line comment; `step/` is empty; Core's `LOAD_RECIPE` / `START_SEQUENCE` handlers are `pass`. The working engine (Recipe/Sequence/Step/Runtime/StepResult, the five step types, resource-based `test_package` module loading described in `architecture.rst`) lives in **`old_code/`** and is not reachable from the new launcher.
2. **Report module** — process shell with heartbeat exists; `generate_report()` / `export_report()` are `pass`. The CSV/HTML logic is in `old_code/report.py`.
3. **HAL** — `hal.py` is a one-line comment.
4. **Stream handler** — `StreamContainer` + an XYGraph widget spike; not integrated.
5. **GUI** — a minimal status window (status label + stop button); none of the spec's widget system, recipe preview, session persistence, etc. CLI has the interactive shell + `load_recipe`/`start_sequence` plumbing but no recipe/report/exit-code features yet.
6. **Step construction still uses `eval(step_type + "(**step_data)")`** in `old_code/recipe.py` — the closed, unsafe step factory rides along into whatever gets ported.

### Defects worth fixing early (spotted while reading the branch)

- **Broken import in the verificator:** `verify_recipe.py` does `from pypts import RECIPE_HEADER_REQUIRED_FIELDS, RECIPE_SEQUENCE_REQUIRED_FIELDS, STEP_REQUIRED_FIELDS`, but `src/pypts/__init__.py` is now minimal and defines none of these — the verificator cannot import. The schema constants need a proper home (see §3.5: make them part of the step/recipe schema layer).
- **`@catch_and_report_errors()` swallows results and errors:** the wrapper returns `None` on success-path exceptions *and* doesn't re-raise, so a failing function silently continues; it also assumes `self.core.report_error` exists on every decorated class, and the `nonlocal module_name` + `inspect.stack()[1]` combination captures the *first caller's* module and reuses it forever. Fine for a skeleton, dangerous once the sequencer executes real steps — errors must also propagate into StepResults, not only into Core events.
- **Heartbeat monitoring is one-directional and always-armed:** Core warns on timeout even before/without submodules being expected to run, and HMI heartbeat is only sent by CLI/GUI loops that also block on `input()` (CLI's input thread blocks, but heartbeats tick in the polling thread — OK; still, warn-only with no recovery action).
- **Per-process side effects at import:** `logger/log.py` and the config handler run at import time in every spawned process — each process opens its own timestamped log file and rewrites `config.ini`. Decide per-run log directories (spec: "separate logs by test run") and a single config writer before this multiplies.
- **Core deps got heavier, not lighter:** `pts-framework` now hard-depends on `matplotlib`, `numpy`, `nptdms`, `nidmm`, `hightime`, `pyserial`, `paramiko`, `PySide6`. For a framework whose spec demands "lightweight" and "tests executable stand-alone," this is the strongest argument for the plugin packaging model in §3.
- Two `TODO.txt` items confirm known issues: globals stored as a list not dict; GUI refresh problems.

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
- [ ] **TODO:** Interface/message classes stay exactly as they are; the **launcher injects the queue type** — `multiprocessing.Queue` for GUI↔Core, plain `queue.Queue` inside the engine. No module may ever know which one it holds.
- [ ] **TODO:** HAL becomes a **plain library** imported by the Sequencer — no process, no event loop, no queue. Driver calls stay ordinary function calls; this also keeps the spec's "HAL usable standalone outside the framework" true by construction.
- [ ] **TODO:** Add a CI unit test that round-trips **every** HMI↔Core message type through `pickle.dumps`/`loads` — mechanically enforces that only pickle-safe dataclasses ever cross the process boundary.
- [ ] **TODO:** Rework user-interaction steps as a **request/response message pair** across the HMI boundary (today an event carries a live `SimpleQueue` — cannot cross a process).
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
- Decide logging/config process policy: one log directory per *test run*, per-process log files inside it; config written once by the launcher, read-only elsewhere.
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
2. **Step & Sequencer (execution):** move `Step`/`Sequence`/`Runtime`/`StepResult` execution into `sequencer/` + `step/`; implement `run_sequence()` behind the existing `RUN_SEQUENCE` command; results stream back via `SEQUENCE_RESULT` (define a per-step result event too — `STEP_RESULT` — so HMIs update live, replacing the old event-proxy strings).
3. **Core orchestration:** implement `LOAD_RECIPE`/`START_SEQUENCE` handlers, runtime metadata (recipe info, DUT serials, timing, machine info), result aggregation, and forwarding to HMI + Report.
4. **Report:** port incremental CSV writing + HTML generation behind `GENERATE`/`EXPORT`; intermediate result file (YAML/CSV) per spec; artifacts organized per run folder.
5. **HMI:** CLI first — recipe load/validate/run, sequence selection, prompts (serial number, user interaction now crossing a process boundary — see pickling risk in §4), report/log locations, exit codes `0/1/2/3`, `--version`. Then grow the GUI beyond the status window (recipe preview, runtime log, results table).
6. **Delete `old_code/`** once parity is proven by the Phase 0 characterization tests. v0.3.0 is tagged here.

Design decision to make *during* this phase, not after: define step/user-interaction/result **payload contracts** (dataclasses in the message files) — inter-process queues mean everything must be picklable; the old in-thread trick of passing a `SimpleQueue` inside an event for user prompts will not survive process boundaries and needs a request/response message pair instead.

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

- **Pickling across process boundaries.** *(→ largely resolved by the TODO topology: only the HMI↔Core boundary remains a process boundary.)* Remaining work: user prompts become a request/response *message pair* over that boundary (TODO above), and the CI pickle round-trip test guards it permanently. Step-to-step object passing and device handles stay in-engine and are unaffected.
- **`old_code` divergence.** The branch's `old_code` is *newer* than master (consolidated steps, `test_package` resource loading). Freeze master, do the port from `old_code` only, and delete it at v0.3.0 — three coexisting engines (master, old_code, new modules) is the biggest confusion risk for the team.
- **Error-handling policy.** `catch_and_report_errors` currently reports and *continues*. Define per-layer behavior: step errors → StepResult(ERROR) + report + continue/abort per recipe config; module errors → Core event + heartbeat-driven recovery; never both silent.
- **Core busy-loop & heartbeats.** 100 Hz polling in every module is fine for now; when Core gains real work, consider `Queue.get(timeout=...)`-driven loops. Heartbeat timeout currently only logs a warning — define the recovery action (restart module? abort run? notify HMI?).
- **Config in the temp directory.** `%TEMP%/pypts/config/config.ini` is easy to lose on cleanup and awkward for benches with fixed configs — consider `platformdirs` user-config location, and a single writer (launcher) with readers elsewhere. Also still INI; spec mentions structured data and versioned config schema.
- **PyPI name.** The pyproject rename to `pts-framework` needs an early availability check on PyPI (v1.0.0 requirement), and alignment with the import name `pypts`.
- **Recipe format versioning.** Before the Creator and third-party step plugins ship, add `format_version` to the recipe header and a compatibility policy — cheap now, expensive later.
- **`pypts.api` stability.** Freezing the step/driver contract is the highest-leverage design decision left; review it with the module owners (per the Milestones page, each module has an assigned owner) before Phase 2 ends.
