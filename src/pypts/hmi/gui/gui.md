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

Status of the code beside this file: **the four-panel operator screen is
built.** `gui.py` is the assembler; the panel contents are `top_bar.py`,
`step_table.py`, `center_view.py` with `result_colors.py`, on the vendored
scaffold in `scaffold/`. The protocol half it builds on, `hmi/hmi_client.py`,
is complete and shared with the CLI. Roadmap section 1.15 records the rework.

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
  logger belongs to the process and the Logger owns the run log; a GUI log
  view is a display of *its own* process's records (or, later, a reader of the
  run log file like the Debug Monitor).
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
| root-logger tap into the log box | the GUI logs normally; its records go to the Logger like everyone's. A live log box, if wanted, shows GUI-process records only |
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

## 6. Fitting the pyrade scaffold

The new GUI's layout comes from `pyrade_gui_scaffold` (v1.3.0, CERN RADE,
https://gitlab.cern.ch/rade/rade-core/utils/gui_template - the vendored port in
`scaffold/` is the complete in-repo copy; the framework references the upstream
repo nowhere): a
`MainWindow(QMainWindow)` holding four `BasePanel(QFrame)` regions in nested
drag-resizable `QSplitter`s — TopBar, LeftSidebar, CenterView, BottomBar —
each filled once via `panel.set_content(widget)`. `BoxStyle` / `LayoutConfig`
dataclasses configure borders and proportions. It is layout-only: no menus,
toolbars, dialogs, threading or event plumbing, by design.

**The two review blockers, and how they were resolved:**

- **It is PyQt6; pypts is PySide6** — deliberately (the PyQt6 GPL/LGPL
  conflict is why the PySide6 migration happened). **Resolved: the scaffold
  is vendored as a PySide6 port in `scaffold/` beside this file** — same
  class names, same public API, upstream's test suite ported with it
  (`tests/unit_tests/test_gui_scaffold.py`), full provenance in the package
  docstring. The only structural change: upstream's five single-class
  component files are one `panels.py`. No pip dependency on the PyQt6
  package, ever.
- **The template has no license** (no LICENSE, no SPDX, no pyproject license
  field). The port went ahead on the user's decision, with attribution;
  **clearance from the author is an open roadmap TODO** and must be settled
  before a release.

**The region mapping (cross-checked against §1-§2):**

| Panel | Content |
|---|---|
| TopBar | recipe controls: Open, sequence dropdown, Start, Stop, recipe name label (the §2 toolbar state machine, event-driven per §5.4) |
| LeftSidebar | the step table - UUID-keyed rows, §2 colors (`LayoutConfig` widens it; default 1:4 stretch is too narrow for it) |
| CenterView | a `QStackedWidget` with three pages: idle (logo) → prompt (message + image + option buttons) → results |
| BottomBar | status line (`StatusChanged`, errors) + the "Open report folder" button (dead until the first `ReportReady`, then opens `report_dir` via `QDesktopServices`); a log view later |
| native `QMainWindow.setMenuBar()` | File/About menus - the scaffold leaves it free |

**Integration shape:** the template's `GUIAssembler` example is exactly our
architecture - `GUI(HmiClient)` plays the assembler: it builds the scaffold
`MainWindow`, builds one pure-view content widget per panel (callbacks in via
constructor, update methods out), calls `set_content()` once per panel, and
the `show_*` hooks drive the update methods while button callbacks call
`load_recipe()` / `start_sequence()`. The 50 ms `QTimer` poll is unchanged.

**The one trap:** `set_content()` *deletes* the previous widget
(`deleteLater()`). It is an assembly-time hand-over, not a page switcher -
page switching happens inside our own container (the `QStackedWidget`), never
by repeated `set_content()` calls. Also keep, when porting: the `showEvent` +
`QTimer.singleShot(0, ...)` initial-sizing pass, and
`setChildrenCollapsible(False)` (all four regions always visible - the old
"result tree appears at the end" becomes a CenterView page swap).

---

*Update this file the way the roadmap is updated: in the same change that
changes the module.*
