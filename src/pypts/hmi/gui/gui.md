<!--
SPDX-FileCopyrightText: 2025 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# The GUI — how the old one worked, and how the new one maps onto it

The context file for `src/pypts/hmi/gui/`. It records how the old GUI
(`old_code/gui.py`, 868 lines, plus `event_proxy.py`, `pts.py`, `startup.py`,
`thread_context.py`, `__main__.py`) actually worked — its screen, its pipeline,
its threading rules — and how each part maps onto the new architecture, so the
new GUI reproduces the *principle* without inheriting the implementation.
Read this before touching the module; the roadmap stays the authority on
status and plan (GUI-to-spec is Phase 3; the basic recipe-execution GUI is
groundwork laid before it).

Status of the code beside this file: **the operator screen has visual parity
with the master-branch GIF reference.** `gui.py` is the assembler;
`PtsMainWindow(QMainWindow)` owns the native menu bar, `QToolBar`, full-width
state-indicator tab bar, left/right `QSplitter`, and `QStatusBar`. Panel
contents: `top_bar.py` (`TopBarContent(QToolBar)` — SVG icons, state setters),
`step_table.py` (left stack page 1), `results_panel.py` (left stack page 2),
`center_view.py` (`CenterContent` — interaction + serial stack, `LogPanel`),
`log_tail.py` (what fills that panel — §8).
Styling: `palette.py` — **every colour the GUI uses, and the only file allowed a
hex literal** (§10) — plus `styles.py` (the light/dark QSS built from those
tokens) and `resources.py` (logo loaders). The vendored scaffold in `scaffold/` is no longer used by the
main window (§6 below). The protocol half, `hmi/hmi_client.py`, is complete and
shared with the CLI. Roadmap §1.15, §1.20, §1.21 record the rework.

---

## 1. What the old GUI looked like

One `QWidget` (`MainWindow`, "PTS", 1600×1000), a menu bar, a toolbar, and two
halves side by side:

```
┌─ menubar: File (Open Recipe, Exit) · Edit (Edit Recipe) · View · About ──────┐
├─ toolbar: [Open] [Start] [Stop]  (16px icons, text under icon) ──────────────┤
├──────────────────────────────────────┬───────────────────────────────────────┤
│ LEFT half                            │ RIGHT half                            │
│                                      │                                       │
│ recipe_label (QLabel)                │ picture_box (QLabel, ≥800×600)        │
│   "Running <name>...\n<description>" │   CERN logo, or the image a           │
│                                      │   UserInteraction step sent           │
│ step_list (QTableWidget, ≤800 wide)  │                                       │
│   3 columns:                         │ message_box (QLabel)                  │
│   Step name │ Description │ Result   │   the interaction step's question     │
│   250px bold│ 350px pt10  │ stretch  │                                       │
│                                      │ button_list_layout (QHBoxLayout)      │
│ result_list (QTreeView, ≤800×200)    │   one QPushButton per interaction     │
│   final hierarchical results         │   option, created and destroyed       │
│   (StepResultModel)                  │   per question                        │
│                                      │                                       │
│                                      │ log_text_box (QPlainTextEdit, ro,     │
│                                      │   Courier 8, whitesmoke) - live log   │
└──────────────────────────────────────┴───────────────────────────────────────┘
```

The five things an operator does with it, in order of importance: **open a
recipe, start it, watch the step table fill with results, answer the questions
a step asks, stop it.** Everything else (menus to the wiki, the recipe-creator
launcher, the serial-port dialog) hangs off those.

## 2. The old pipeline, end to end

Two threads of one process, joined by two queues and a Qt signal layer:

```
GUI thread (Qt)                          engine thread(s)
────────────────                         ────────────────
MainWindow ──("LOAD", path)──► q_in ───► command_handler_loop (pts.py)
           ──("START",)─────►                 │ LOAD: build Runtime + Recipe,
           ──("STOP",)──────►                 │       send post_load_recipe
           ──("EXIT",)──────►                 │ START: Recipe.run on a new
                                              │        daemon thread
                                              ▼
                                        Recipe.run / Step.run
                                              │ runtime.send_event(name, *data)
                                              ▼
MainWindow slots ◄── Qt signals ◄── RecipeEventProxy ◄── event_queue
(update_sequence,      (dict            (QThread; blocking      (SimpleQueue)
 update_step_result,    payloads)        get(), builds a
 show_message, ...)                      ViewModel dict,
                                         emit by name)
```

- **Commands down** were bare tuples on a plain `Queue` (`q_in`):
  `("LOAD", path)`, `("START",)`, `("STOP",)`, `("EXIT",)`. No types, no
  acknowledgements; `START` always ran `"Main"` (the sequence name was
  hardcoded in `pts.py:144`).
- **Events up** were `(event_name, data_tuple)` on a `SimpleQueue`. The
  `RecipeEventProxy` (a `QObject` moved to its own `QThread` by
  `Runtime.setup()`, `recipe.py:183-211`) blocked on `get()`, transformed each
  event into a **ViewModel dict**, and emitted the signal named
  `<event_name>_signal`. That is the thread boundary: engine threads never
  touch widgets, the GUI thread never touches the engine — the proxy's
  signal/slot hop marshals everything onto the Qt thread.
- The proxy also did **presentation policy**, not just transport: it computed
  the result colors, resolved image paths, and *suppressed* `pre_run_step` /
  `post_run_step` for `SequenceStep` (a nested sequence is not a row in the
  table).

### The nine signals and their slots

| Event (signal) | ViewModel payload | MainWindow slot | What the slot does |
|---|---|---|---|
| `post_load_recipe` | `{recipe_name, recipe_version}` | `handle_post_load_recipe` | log only ("Recipe 'X' (v1.0) loaded.") |
| `pre_run_recipe` | `{recipe_name, recipe_description}` | `update_recipe_name` | recipe_label + window title "PTS: <name>" |
| `get_serial_number` | `{response_q}` | `get_serial_number` | modal `QInputDialog`, retries empty input 3×, puts the text (or "CANCELLED") on the live queue |
| `pre_run_sequence` | `{sequence}` (the live `Sequence` object) | `update_sequence` | **populates the step table**: one row per step — name (bold, `step.id` stored in `UserRole`), description, Result="Pending" |
| `pre_run_step` | `{step_uuid, step_name}` | `update_running_step` | finds the row by UUID, sets Result to bold "Running...", scrolls it into view |
| `user_interact` | `{response_q, message, image_path, options}` | `show_message` | message into message_box, image into picture_box, one button per option; stores `response_q` for the button callback |
| `post_run_step` | `{step_uuid, status_text, status_color, text_color}` | `update_step_result` | finds the row by UUID, writes the verdict with its colors |
| `post_run_sequence` | `{sequence_name, sequence_result}` | `handle_post_run_sequence` | log only |
| `post_run_recipe` | `{results}` (the `StepResult` tree) | `show_results` | fills the `QTreeView` via `StepResultModel`, expands all, re-enables the buttons |

### The step table mechanic (the heart of the screen)

The one pattern everything hangs on: **rows are keyed by step id, not by
index.** `update_sequence` writes `str(step.id)` into the name item's
`Qt.ItemDataRole.UserRole`; `update_running_step` and `update_step_result`
find their row by scanning column 0 for that UUID. So the table tolerates any
event order, and a step can be updated twice (Running... → verdict) without
the GUI tracking a cursor. Result cells get the verdict's color pair
(`get_step_result_colors`, `old_code/utils.py:38`):

| Result | background | text |
|---|---|---|
| PASS | `#C8E6C9` | `#1B4F24` |
| FAIL | `#F28B82` | `#7B0000` |
| DONE | `#B2EBF2` | `#004D52` |
| SKIP | `#FFF9C4` | `#C49000` |
| ERROR | `#FFCC80` | `#BF360C` |
| STOP | `#D3D3D3` | `#4B4B4B` |

### The toolbar state machine

`Open` enabled / `Start` disabled / `Stop` disabled at startup, then:

- **Open** → file dialog → on success: `Start` enabled. (Also sent `("STOP",)`
  first, defensively.)
- **Start** → `reset_gui()` (clear table, tree, log, labels, buttons, logo
  back), repopulate the table, `("START",)` → `Stop` enabled, `Open` disabled.
- **Stop** → both disabled, `("STOP",)`, block in a nested `QEventLoop` polling
  a global `WAIT_FOR_TERMINATION` event every 100 ms until the engine confirms
  → `Open` and `Start` re-enabled.
- **Run finishes on its own** (`show_results`) → `Stop` disabled, `Open` and
  `Start` re-enabled.

### User interaction (the part that shaped the new message design)

A `UserInteractionStep` put a **live `SimpleQueue` inside the event**; the GUI
kept it (`self.response_q`), built one button per option, and the button's
callback `put()` the chosen key back. Three magic response values triggered a
*second* dialog whose answer was pushed as a *second* item on the same queue:
`file` → file-open dialog → `(path, content)`; `wrt` → text input → the typed
string; `ID` → the serial-port dialog (`SerialPortDialog`: port combo,
baudrate combo, live `*IDN?` probe on a `QThread` worker) → `(port, baudrate,
IDN)`. The serial-number prompt was the same pattern with a modal dialog.
Live queues in events are exactly what cannot cross the new process boundary —
this is why `UserPromptRequest`/`Response` joined by a `request_id` exist.

## 3. What not to reproduce (defects and debt, with locations)

- **The GUI parsed the recipe itself** (`gui.py:333-345 load_recipe()`): it
  built a *second* `Recipe` object, GUI-side, just to fill the table early —
  the engine built its own on `LOAD`. Two parses, two objects, and the
  `already_updated` flag dance to stop `pre_run_sequence` from re-filling the
  table. The new GUI must get everything from messages.
- **`startup.py:34`: `time.sleep(1)` "prevents a race condition. To be
  properly fixed!!"** — the proxy thread might not be started before
  `app.exec()`. The new architecture has no such window: the QTimer poll
  starts in the constructor.
- **Abort blocked the GUI thread in a nested `QEventLoop`** (`gui.py:292-306`)
  on a **global** `threading.Event` (`WAIT_FOR_TERMINATION`) that the engine
  set in `handle_step_abort`. A stop after a *finished* run would deadlock —
  worked around by re-enabling buttons in `show_results` (`gui.py:567`).
- **The GUI attached its own handler to the root logger**
  (`TextEditLoggerHandler`, `gui.py:26-36, 113-116`) — every module's records
  went through a Qt signal into the log box. In the new architecture the root
  logger belongs to the process and the Logger owns the run log, so the panel
  reads the run log file back from the outside instead — §8.
- **Presentation state lived in the engine's objects**: `StepResultModel`
  walked live `StepResult` objects (`.step`, `.subresults`, `.output_mapping`)
  and `update_sequence` read live `Step`s. None of that pickles; the new
  boundary carries `StepOutcome` and plain values only.
- Non-GUI code in the GUI file (serial port probing — flagged by its own
  `# todo` at `gui.py:734`); `("STOP",)` sent on every Open; the recipe-editor
  launched by rglob-searching for `recipe_creator.py`; hardcoded wiki/GitLab
  URLs; `sys` used in `on_edit_clicked` without an import (dead path).

## 4. The same pipeline in the new architecture

The principle is unchanged — *commands down, events up, one hop onto the GUI
thread, a table keyed by step id*. What changed is that every ad-hoc piece now
has a typed, owned equivalent:

| Old | New |
|---|---|
| `q_in` + bare tuples `("LOAD", path)`, `("START",)`, `("STOP",)`, `("EXIT",)` | `HmiClient.load_recipe()`, `.start_sequence(name)`, `.request_shutdown()` → frozen dataclasses `LoadRecipe`, `StartSequence`, `ShutdownRequested` on the pickled HMI↔CORE link. The Stop button sends `StopSequence` (defined in `run_events.py`, riding both links; CORE relays the same object to the Sequencer). |
| `command_handler_loop` (pts.py) | CORE: `handle_hmi_message()` routes, `load_recipe()` validates and refuses bad recipes (old code had no validation gate), `start_sequence()` forwards the *chosen* sequence name (old code hardcoded "Main") |
| `event_queue` + `RecipeEventProxy` in a `QThread` (blocking `get()`) | the `CoreToHmi` `QueueWrapper` + a `QTimer` (50 ms) on the Qt thread calling `poll_core()` — non-blocking `receive()`, so no proxy thread and no sleep(1) race |
| nine `*_signal = Signal(dict)` + `getattr(self, name + "_signal")` | the `match` in `HmiClient.handle_core_message()` closed with `unhandled()` → typed `show_*` / `ask_*` hooks the GUI overrides. mypy and `test_messages.py` replace "hope the dict has the key" |
| ViewModel dicts built in the proxy | the messages *are* the view models: `StepStarted(step_id, step_name)`, `StepFinished(outcome: StepOutcome)`, `RunFinished(result, outcomes)` — plain values, already pickle-tested |
| proxy suppressing `SequenceStep` rows | not needed yet (no nested steps); when `SequenceStep` lands, the same policy belongs in the presentation layer, not the transport |
| live `response_q` in `user_interact` / `get_serial_number` events | `UserPromptRequest`/`UserPromptResponse` and `SerialNumberRequest`/`Response` joined by `request_id`; the GUI answers via `answer_user_prompt()` / `answer_serial_number()`. The hooks exist and **default to declining** so a blocked step is never stranded |
| second value pushed on the same queue (`file`/`wrt`/`ID`) | **unsolved by design** — each follow-up must become its own request/response pair when those steps are ported (roadmap §1.1 TODO) |
| `WAIT_FOR_TERMINATION` global + nested QEventLoop on abort | nothing blocks: Stop sends the command and the *events* drive the buttons — `RunFinished` (result STOP) is the "engine has stopped" confirmation the old global tried to be |
| root-logger tap into the log box | the GUI logs normally; its records go to the Logger like everyone's. The log box is fed the other way round: `log_tail.py` reads the run log file the Logger writes, so the panel shows *every* process, not just the GUI's own records (§8) |
| `StepResultModel` over live `StepResult` trees | `RunFinished.outcomes` is a **flat tuple** of `StepOutcome` (execution order). The tree returns only if a pickle-safe outcome tree is added when nesting lands |
| GUI-side `Recipe` parse to pre-fill the table | `RecipeLoaded` carries the whole pickle-safe summary — `main_sequence` plus per-sequence `StepSummary(step_id, step_name, description)` rows built by `Recipe.to_summary()` — so the table pre-fills at load time with no second parse |

What the new GUI already has for free: the whole protocol (`HmiClient`), the
heartbeat, the clean shutdown handshake (`request_shutdown` → CORE stops
everything → `StopHmi` → `on_stop()`), safe defaults for every message it does
not render yet, and the shared-protocol tests that pin all of it.

## 5. The five open points, and how each was settled

1. **Pre-filling the step table — solved with the summary.** `RecipeLoaded`
   now carries `main_sequence` and a `SequenceSummary` per sequence, each a
   tuple of `StepSummary(step_id, step_name, description)` rows built by
   `Recipe.to_summary()` — including the teardown steps, which run through
   the same lifecycle and emit the same events. The table fills at load time
   like the old one, with no GUI-side parse.
2. **The Stop button — `StopSequence` rides both links.** The dataclass moved
   to `run_events.py` (the shared-message rule in `src/pypts/README.md`); a
   frontend sends it, CORE relays the same object to the Sequencer, and the
   confirmation is the run's own `RunFinished(STOP)`. The CLI's verb is
   `stop_sequence` (plain `stop` was already an exit alias).
3. **Which sequence runs — the dropdown.** Filled from the summary, defaulted
   to `main_sequence`; Start sends `StartSequence(selected)`. Changing the
   selection re-fills the table from local data.
4. **Button states — event-driven, exactly as proposed.** `RecipeLoaded`
   enables Start; `RunStarted` disables Open/Start/combo and enables Stop;
   `RunFinished` (any result) restores. Nothing blocks; the old nested
   QEventLoop has no successor. The window's [X] follows the same principle:
   the first close is a `ShutdownRequested`, the real close happens on
   `StopHmi`.
5. **Colors — kept.** `result_colors.py`, the §2 table verbatim, keyed by
   `ResultType`.

## 6. The scaffold — why it was abandoned

The vendored `pyrade_gui_scaffold` (v1.3.0, PySide6 port in `scaffold/`) provided
a four-panel `MainWindow` (TopBar / LeftSidebar / CenterView / BottomBar) via
nested `QSplitter`s. It was the basis of §1.20 visual parity work.

**Why it was replaced (§1.21):** the scaffold's four-panel geometry cannot
produce the master-branch layout: the state-indicator tab bar must span the full
window width *above* the left/right splitter, and `TopBarContent` must be a
native `QToolBar` (so the OS can render it correctly, add separators, etc.).
Fitting those requirements inside the scaffold's fixed four-region grid would
have required removing the scaffold anyway, so it was replaced outright with
`PtsMainWindow(QMainWindow)`.

The scaffold code remains in `scaffold/` and its tests in
`test_gui_scaffold.py` are preserved. The license question (no SPDX on the
upstream template) is still an open roadmap TODO before v1.0.

**Current `PtsMainWindow` layout:**

| Qt element | Content |
|---|---|
| `addToolBar(top_bar)` | `TopBarContent(QToolBar)` — Open / Start / Pause / Stop, sequence combo, and (far right) the report button: always enabled — opens this run's report folder once `ReportReady` names one, the `paths.reports_dir` root before that |
| `setMenuBar` (built in `_build_menu()`) | File (Open Recipe, Open Recent → §9, Exit) / Edit (Edit Recipe, Remove Cache → §10) / View (dark mode toggle) / About stubs |
| `screen_tab_bar` (`QTabBar`, CERN Blue bg) | Full-width state indicator: Idle \| Running \| Prompt \| Results; click snaps back unless `_browsable=True` (pause mode) |
| `recipe_label` (`QLabel`) | "Loaded…" / "Running…" below the tab bar |
| `QSplitter` 52/48 | left: `left_stack` (`QStackedWidget`, 3 pages); right: `CenterContent` |
| `left_stack` page 0 | idle placeholder (CERN logo + "Open a YAML recipe…") |
| `left_stack` page 1 | `StepTableContent` |
| `left_stack` page 2 | `ResultsPanel` (badges + `QTreeView`) |
| `QStatusBar` | status label (stretch=1) |

---

## 7. The master-branch GUI — the visual reference for refining this module

Between the old code (§1–§2) and the current `architecture_refactor` branch,
a new GUI was built on the `master` branch that is **the visual design target**.
A verbatim copy lives at **`src/pypts/old_code/hmi/`** (copied 2026-08-31).
Read that code before touching any widget in this folder.

### Layout (master, 1600×1000, splitter 52/48)

```
┌─ MenuBar: File · Edit · View (Toggle Dark Mode) · About ──────────────────┐
├─ PtsToolBar: [Open] [Start] [Pause] [Stop]  ······················ pypts ─┤
├─ Tab bar (state indicator): Idle | Running | Prompt | Results ────────────┤
│  recipe label  ("Running XYZ..." / "Loaded recipe\nReady to start")       │
├────────────────────────────────┬──────────────────────────────────────────┤
│  LEFT (52%)  QStackedWidget    │  RIGHT (48%)                             │
│   page 0 = idle placeholder    │  InteractionPanel (QFrame)               │
│     CERN logo centred          │    image_label (≥220px, CERN logo idle)  │
│     "Open a YAML recipe…"      │    message_label (word-wrap, hidden idle)│
│   page 1 = StepTable           │    button_row (HBox, hidden idle)        │
│     cols: Name(260)|Desc|Result│    keyboard nav: ←→↑↓ + Enter           │
│     status badge delegate      ├──────────────────────────────────────────┤
│     row highlight on Running   │  "Log Output" section label              │
│   page 2 = ResultsPanel        │  LogPanel (Courier 9, 160px fixed height)│
│     PASS/FAIL/TOTAL badges     │    coloured level prefixes               │
│     QTreeView (StepResultModel)│    2000-line rolling buffer              │
├────────────────────────────────┴──────────────────────────────────────────┤
│  QStatusBar  ("Ready" / "Recipe running" / "Waiting for user input" / …)  │
└────────────────────────────────────────────────────────────────────────────┘
```

### Styling tokens (from `old_code/hmi/gui_components/styles.py`)

- CERN Blue `#0033A0` — tab bar background, primary buttons
- MTA Blue `#005BAC` — selected tab, header text
- Full light QSS + full dark QSS; `detect_system_dark_mode()` + OS live-sync
  (`install_system_theme_sync` via `styleHints().colorSchemeChanged`)
- Toolbar icons: inline SVG, colour-coded (green play, red stop, orange pause)
- Log level colours: INFO `#6abf69`, DEBUG `#6897bb`, WARNING `#FFCC80`, ERROR
  `#F28B82`, CRITICAL `#ff7c9c`
- StepTable status colours: same as §2 table, plus RUNNING `#DBEAFE`/`#1D4ED8`

### Browse (pause) mode

Pause locks the real screen index but lets the operator click tabs to browse
the left stack (step table ↔ results) without disturbing the running recipe.
Start resumes and restores the locked tab. `_paused` flag + tab click handler.

### File layout in `old_code/hmi/` (master reference copy)

| File | Owns |
|---|---|
| `gui.py` | `MainWindow` — assembler, screen FSM, all toolbar/menu wiring |
| `gui_theme.py` | `detect_system_dark_mode`, `install_system_theme_sync`, `get_theme_colors`, `get_yamview_stylesheet` |
| `gui_components/styles.py` | Color tokens, `LIGHT_QSS`, `DARK_QSS`, `get_stylesheet`, `STATUS_COLORS`, `LOG_LEVEL_COLORS` |
| `gui_components/toolbar.py` | `PtsToolBar` — SVG icon helpers + state setters |
| `gui_components/step_table.py` | `StepTable`, `StatusBadgeDelegate` — rounded pill badges |
| `gui_components/log_panel.py` | `LogPanel` — coloured-prefix append, rolling buffer |
| `gui_components/interaction_panel.py` | `InteractionPanel` — image/logo, message, button row, keyboard nav |
| `gui_components/results_panel.py` | `ResultsPanel`, `SummaryBadge`, `StepResultModel` |
| `gui_components/resources.py` | `load_cern_logo_pixmap`, `load_app_logo_pixmap`, `make_placeholder_pixmap` |
| `XYGraph/XY_graph.py` | `PlotWindow`, `SignalSpawner` (pyqtgraph-based live plot) |
| `XYGraph/StreamContainer.py` | `GlobalContainer`, `Stream` singleton registry |
| `XYGraph/simulated_signals.py` | `Simulated_sine_wave` thread |

### Gap analysis — master vs. current `hmi/gui/`

| Feature | Current `hmi/gui/` | Master reference |
|---|---|---|
| `PtsMainWindow(QMainWindow)` GIF layout | ✓ (§1.21) | ✓ |
| `PtsToolBar` with SVG icons + state | ✓ ported (§1.20) | ✓ full |
| `StepTable` with badge delegate | verdict colours render (§9); the rounded-pill delegate is still open | ✓ full |
| `LogPanel` (coloured prefixes) | ✓ ported (§1.20), fed from the run log (§8) | ✓ |
| `InteractionPanel` (image/buttons/kbd) | ✓ ported (§1.20) | ✓ |
| `ResultsPanel` (badges + tree) | ✓ ported (§1.20) | ✓ |
| Light/dark QSS + OS theme sync | ✓ ported (§1.20) | ✓ |
| `styles.py` colour tokens | ✓ ported (§1.20) | ✓ |
| `resources.py` logo loader | ✓ ported (§1.20) | ✓ |
| Browse/pause mode | ✓ ported (§1.20) | ✓ |
| XYGraph live plot | **missing** | ✓ (spike) |

Note: master's `StepResultModel` walked live `recipe.StepResult` objects —
those can't cross the process boundary. The port adapted it to work from
`StepOutcome` (plain values, pickle-safe) sent in `RunFinished`.

## 8. The LOG OUTPUT panel — where its lines come from

The panel shows **the run log file**, not the GUI's own log records.

The old GUI put a handler on the root logger and pushed records into the box
through a Qt signal (§3). That cannot work here: the root logger belongs to the
process, so a GUI-side handler would see GUI records only — and the interesting
part of a run happens in CORE and the engine. The Logger process is the single
writer of one file that already has *everyone's* records in it, so the panel
reads that file back from the outside.

The chain, launcher first:

| Where | What |
|---|---|
| `startup.py` | decides the run log path once (`get_log_file_path()`), and passes it to `gui_main` alongside the log queue |
| `gui_main()` | hands it to `init_logging(log_queue, log_level, log_file_path)` |
| `logger/log.py` | remembers it; `get_log_path()` hands it back to whoever in this process wants to read the log |
| `GUI.start_log_tail()` | opens a `LogTail` on that path and starts a second `QTimer` at `LOG_POLL_INTERVAL_MS` (200 ms) |
| `GUI.poll_log()` | appends what `LogTail.new_lines()` returns to `CenterContent.log_panel` |

`log_tail.py` owns the reading and the presentation of a record:

- **Read-only, and safe while the Logger writes.** `logging.FileHandler(mode="a")`
  leaves the default Windows share mode in place, so a second reader is allowed.
  Nothing here writes, locks or truncates.
- **A torn record is never shown.** A read can land between the Logger's `write()`
  and its flush; anything not ending in a newline is held back until the rest
  arrives.
- **Filtered to `PANEL_LOG_LEVEL` (INFO).** `config.ini` ships DEBUG for the
  refactor, so the file carries the full message trace — every message twice,
  sent and received. That is the Debug Monitor's job; the operator's panel would
  be nothing but `QueueWrapper` traces. Traceback lines are shown or dropped with
  the record they hang under.
- **Rendered `LEVEL     HH:MM:SS  message`.** Level first because that is what
  `LogPanel.append_line()` colours on. Process name and `file:func` are dropped —
  again, the Monitor is where you go for those.

Two things follow from the path being *passed in* rather than looked up:

- A GUI built without one — a test, or a frontend started by hand — has no log to
  follow. It says `No run log to follow.` in the panel and starts no timer. The
  window is otherwise unaffected.
- Nothing here imports `helper_applications/debug_monitor/`, which has a similar
  follower of its own. The dependency rule is one-way, and the Monitor is
  temporary; the duplication is deliberate and dies with it.

A `DEBUG`-level toggle for this panel is not implemented. If it is ever wanted,
it is `LogTail.min_level` plus a checkable item in the View menu — nothing else.

---

## 9. Open Recent — and where pypts keeps state

`File → Open Recent` lists the last 10 recipes that **loaded successfully**.
Roadmap §1.24 records the decision; this is what a reader of this folder needs.

**The store is not in this module, and not in the config.** It is
`utilities/recent_recipes.py` — plain Python, no Qt, no messages — so the CLI
could use it too, and so it is testable without a `QApplication`. It is not in
`config.ini` because that file is the *user's*: one writer, never modified, a
version mismatch discards it (§1.3). A list rewritten on every load is the
inverse of that.

**It is state, not a cache.** A cache is a disposable copy of something that can
be recomputed; nothing can recompute which recipes somebody opened last week. So
the file lives in `file_locations.state_dir()` (`platformdirs.user_state_dir`),
not in a cache directory that OS cleanup tools treat as free to wipe. It stores
**paths, not copies of the YAML** — opening a recent recipe re-reads the file, so
the operator always runs the current version of it.

**How an entry is recorded, with no new messages.** `RecipeLoaded` carries no
path, and does not need to: the HMI is the side that sent `LoadRecipe`.

```
top bar Open button  -+
File > Open Recipe   -+-> GUI.open_recipe(path) -> stash path -> load_recipe()
File > Open Recent   -+                                               |
                                                                      v
                                                       CORE parses and validates
                                                                      |
 recent_recipes.remember(stashed path, event.recipe_name) <- show_recipe_loaded()
```

A recipe that fails to parse never reaches `show_recipe_loaded()`, so it never
enters the list. `HmiClient` is untouched by all of this.

**Two decisions worth not undoing:**

- The submenu is rebuilt on `aboutToShow`, not kept in step with the store. It
  therefore cannot show a stale list.
- The menu **never `stat()`s the entries when it opens.** Ten `stat()` calls
  against a dead `\\bench\recipes` share would freeze the window for seconds every time
  somebody touched the File menu. The existence check is on the **click**
  instead — one `stat()`, on a file the operator explicitly asked for — and a
  missing file is forgotten and reported as a WARNING.

---

## 9. The step table: sizing, wrapping, and the `::item` trap

`step_table.py`. Three columns, and each is sized by a different policy because
each has a different job:

| Column | Policy | Why |
|---|---|---|
| Step name | `Interactive`, `_NAME_WIDTH` (220) | wide enough for a generated name like `Add numbers [a=100, b=250]`, and draggable — how much a name needs is the operator's call |
| Description | `Stretch` | the only column with prose in it, so it gets every pixel the other two do not |
| Result | `Fixed`, `_RESULT_WIDTH` (90) | it only ever holds `Pending`, `Running...` or a verdict |

`setStretchLastSection(False)` is what makes that possible: with it on, the
*Result* column absorbed the slack and the description was squeezed.

**Rows grow to fit.** `setWordWrap(True)` plus `setTextElideMode(ElideNone)` so a
long description wraps instead of ending in an ellipsis, and the vertical header
is `ResizeToContents` so the row is re-measured whenever the wrap changes — which
is on every window resize, because the description column stretches. The explicit
`resizeRowsToContents()` after filling is for the first paint only, before the
table has been laid out.

### The `::item` trap — do not put one back

**A `QTableWidget::item` rule in the stylesheet silently kills every verdict
colour.** Qt hands item painting to `QStyleSheetStyle` as soon as an `::item`
rule exists, and the model's background brush — everything
`show_outcome()`/`_pending_item()` set through `setBackground()` — is then never
consulted. The symptom is a table where PASS and FAIL are ordinary text on white,
which is exactly what "still plain text verdicts" in the roadmap's gap table
meant: not a missing feature, a stylesheet rule cancelling one.

So `styles.py` carries **no** `QTableWidget::item` rule in either palette, and
says why at the point where one would go. The step table is the only
`QTableWidget` in the GUI (`ResultsPanel` is a `QTreeView`, which that selector
does not match), so dropping it costs nothing elsewhere. Cell spacing comes from
the font size and the row height instead of `padding:`.

If a future `::item` rule is genuinely wanted, the verdict badges have to move
into a `QStyledItemDelegate` first — which is the rounded-pill badge delegate the
roadmap already has as a TODO, and would then own both the shape and the colour.

---

## 10. `palette.py` — every colour, in one file

**No file in `hmi/gui/` may contain a hex literal except `palette.py`.** A unit
test enforces it (`test_no_colour_literal_lives_outside_the_palette`), because the
rule is only worth having if it cannot quietly decay. Changing how the GUI looks
is an edit to that one file.

What lives there, and why it is split three ways:

| | What | Theme-dependent? |
|---|---|---|
| `Palette` (`LIGHT`, `DARK`) | ~40 named tokens: surfaces, text, lines, grid, interaction, scrollbars, brand, toolbar icons, `logo_tint` | **yes** — `get_palette(dark)` picks one |
| `Palette.verdicts` (`LIGHT_VERDICTS` / `DARK_VERDICTS`) | the PASS/FAIL/DONE/SKIP/ERROR/STOP chips, plus PENDING and RUNNING | **yes**, but see below |
| `LOG_LEVEL_COLORS`, `PLACEHOLDER_*` | log level prefixes, the image placeholder | **no** |

**The verdict chips keep their hue and change their value.** An operator reads a
bench screen by colour, so green is PASS and red is FAIL in both themes — that
part is not negotiable, and it is the same set the old GUI used
(`old_code/utils.py get_step_result_colors`). What could not stay was the *value*:
a pastel fill that reads as a soft chip on white glares on charcoal. So the dark
theme inverts the relationship — the fill goes dark and the text carries the
colour. Same for the toolbar: `#1B5E20` reads as "go" on white and vanishes on
charcoal, so `icon_start` is themed too.

### Per-item colour is the part a stylesheet cannot reach

Three things colour themselves item by item, and each therefore needs an explicit
repaint when the theme changes — a stylesheet swap does nothing for them:

| Widget | What it repaints | How |
|---|---|---|
| `StepTableContent` | the Result column | `set_dark()` re-reads each cell's own text (`Pending` / `Running...` / the verdict name — each is a chip key) and rebuilds the item |
| `ResultsPanel` | the tree's Result column and the three badges | the model carries `dark`; `set_dark()` flips it, recolours the badges and invalidates the viewport |
| `LogPanel` | its whole backlog | lines already on screen keep the `QTextCharFormat` they were written with, so the panel remembers its lines and re-appends them |

That last one was a real bug, not a precaution: a run that started in light and
switched to dark left every log line already written in the light theme's grey,
which on `#1e1e1e` is barely readable.

The CERN logo is the fourth: it is artwork, not a stylesheet colour, so
`load_cern_logo_pixmap(tint)` recolours it through `resources.tint_pixmap()` —
`SourceIn` over the alpha, so the outline keeps every edge — and `gui.py` and
`interaction_panel.py` reload it on a theme change.

`Palette` is a frozen dataclass, so `LIGHT` and `DARK` cannot drift: a token added
to one is a `TypeError` until the other has it too.

### Seeing it

```bash
python -m pypts.hmi.gui.palette
```

opens a two-tab window — Light and Dark — with every token as a swatch labelled
with its name and its hex, then the verdict chips as the step table paints them,
then the log/icon/placeholder colours. Everything under
`# --- the showcase ---` in that file exists only for this and is imported by
nothing; it may import PySide6 freely because it only runs when someone asks to
look.

### What `styles.py` is now

Structure only: the two stylesheets, built from tokens, with **no colour literal
of their own**. Light and dark are still two texts rather than one template
applied twice — they are nearly identical but not quite (light styles a `QTabBar`
that dark does not), and merging them would change how one of the two themes
looks. That is a job of its own, not a side effect of moving the colours out.

`STATUS_COLORS` (which `styles.py` used to hold) and `result_colors.py` were the
*same table said twice*, in two shapes, plus a third copy of PENDING/RUNNING
inside `step_table.py`. All three are gone; `Palette.verdicts` replaced them.

`grid_line` is separate from `border` on purpose: `border` is the frame around a
table and may be quiet, but a grid that cannot be seen has stopped being a grid.
The light theme's value is Qt's own default (`#d8d8d8`), kept exactly — making
the grid a token was a dark-theme fix and the light theme was not asked to
change.

---

## 10. Remove Cache — a dialog that deletes things

`Edit → Remove Cache` clears what pypts writes on this machine: the recents
list, `config.ini`, every report and every run log. Roadmap §1.25 records the
decision; this is what a reader of this folder needs.

**One checkbox per category, and the defaults carry the meaning.** Only the
recents list is a cache; reports and run logs are *test records* — a report is
the evidence that a unit passed. So `state` and `config` are **ticked** when the
dialog opens and `reports` and `logs` are **not** (`DEFAULT_SELECTION`): removing
records is one deliberate extra click, and the defaults say which is which
without a warning banner. A category with nothing in it has a disabled box.
`Cancel` is the **default** button, so Return dismisses rather than deletes.

The total and the confirm button follow the ticks (`_selection_changed`), and
`selected_items()` is what removal and the result page both act on. The boxes are
connected to that handler only **after** the whole page is built — `setChecked()`
during row construction would otherwise emit `toggled` before the total label and
the button exist.

**The split.** `utilities/data_removal.py` decides *what* (no Qt);
`hmi/gui/remove_cache_dialog.py` shows it (no deleting). The dialog is handed a
survey and a `remover` callable, so the tests drive the whole thing without a
single file being deleted — which is why there is a callable at all.

```
Edit > Remove Cache -> GUI._remove_cache()
                          |
                          +-> data_removal.survey()   what is there, and how big
                          |
                          +-> RemoveCacheDialog       page 1: this is what goes
                                   | operator says yes
                                   v
                              data_removal.remove()   deletes exactly the survey
                                   |
                                   v
                              page 2: what went, what could not
```

**Four decisions worth not undoing:**

- **Greyed out during a run**, with the reason on hover (the Edit menu therefore
  needs `setToolTipsVisible(True)`). Emptying the reports folder while the Report
  thread writes into it would take the run down.
- **This run's log is never offered.** The Logger holds an open handler on it for
  as long as pypts is up, so on Windows it cannot be deleted at all. It is
  excluded from the survey rather than attempted and reported as a failure, and
  both pages say why it is staying.
- **Named files and directory *contents*, never a directory.** On Windows
  `state_dir()`, `config_dir()` and the default `base_dir` are all
  `%LOCALAPPDATA%\\pypts` — deleting a directory would take all four categories at
  once. `data_removal` also refuses a `reports_dir` or `logs_dir` that resolves to
  a filesystem root or the user's home, because those are values in an INI file
  somebody may edit.
- **The GUI rebuilds `RecentRecipes` afterwards.** The old store still held the
  list in memory and would have written it straight back on the next load.

**One page, not two popups.** The confirm view is replaced in the layout by the
result view — not a `QStackedWidget`, whose `sizeHint` is its tallest page
whatever the size policies say, which left the short result view floating in the
confirm view's height.

---

## 11. Why the toolbar answers its own tooltips

Every control in `TopBarContent` carries a description — `describe()` sets the
tooltip (rich text: the action name bold, what it does under it) *and*
`accessibleName` / `accessibleDescription` with the same words in plain text, so
a sighted operator and a screen reader are told the same thing.

**The wording is state-driven, not fixed.** `_refresh_descriptions()` runs from
`_refresh_controls()` on every transition, and a disabled control says *why*:
`Start` reads "Open a recipe first." before a recipe is loaded and "A run is
already in progress." during one; `Pause` becomes **Resume** while the run is
held (`set_paused()`, called from `GUI._toggle_pause`). A greyed button that
does not explain itself is the one that gets filed as a bug.

**And the trap that made all of this invisible.** Qt shows **no tooltip for a
disabled widget** — a disabled widget receives no mouse events at all, so it
never gets the `ToolTip` event. Start, Pause and Stop are all disabled when the
window opens, which is exactly when their descriptions are most useful. The
event falls through to the toolbar instead, so `TopBarContent.event()` catches
`QEvent.Type.ToolTip`, finds the child under the cursor with `tooltip_at()`, and
shows that child's text itself. An *enabled* child handles its own tooltip and
the toolbar never sees the event.

`tooltip_at()` is split out because `event()` cannot be asserted on: the base
`QWidget` implementation accepts a `ToolTip` event whichever branch ran, so its
return value proves nothing.

---

*Update this file the way the roadmap is updated: in the same change that
changes the module.*
