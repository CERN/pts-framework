# XY Graph + Stream Container Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test code registers a named live data stream, the CORE side writes it to a CSV in the run folder, and the GUI draws it in an XY graph in the right column while a step with `graph: <name>` runs.

**Architecture:** A new zero-pypts-import stream container fills `src/pypts/stream_handler/` (one active `StreamSession` per process, the `LocalSetup` pattern). The Sequencer opens one session per run. The CSV file is the whole contract between CORE and the GUI: the GUI derives the path from `RunStarted.run_dir` and the step's `graph:` name, tails the file, and plots it with the copied `pyrade_xy_graph` plot widget. No new message.

**Tech Stack:** Python ≥ 3.11, PySide6 6.9.2, pyqtgraph (new), numpy, Pydantic v2, pytest + pytest-qt.

**Spec:** `resources/internal_reports/xy_graph_stream_design_2026-10-19.html` (every decision, with the review IDs B1–B4, H1–H6, M1–M6, Q1–Q8). Background: `resources/internal_reports/xy_graph_stream_design_review_2026-10-19.html`. Read the spec before your task.

## Global Constraints

- **No git commits or staging.** The user commits everything themselves. Where a task ends, stop and report; do not run `git add` / `git commit`.
- **Read the module's context file before touching a module** (table in `CLAUDE.md`). Documentation moves with the code in the same task — a task is not done until the docs it names describe the code as it now is.
- Quality gates per task: `pytest tests`, `ruff check src tests`, `mypy` all pass.
- Code style: plain, old-school Python; `if`/`else` over conditional expressions; logging is `%`-style, never f-strings (`G004`). Wording and levels per `src/pypts/logger/logging_rules.md` (INFO+ for the technician, developer detail DEBUG).
- `src/pypts/stream_handler/` imports **nothing** from the rest of `pypts` (stdlib and numpy only). Its log lines use `logging.getLogger(__name__)` (precedent: `hal/drivers/loopback.py`).
- Stream file path: `<folder>/streams/<safe name>.csv`. Safe name = alphanumerics kept, every other character `_`, at most 60 characters — the rule of `utilities.local_storage.safe_name_part()`, written out again in the container.
- CSV dialect: `csv.writer` on a file opened `mode="a", newline="", encoding="utf-8"`. Header row written only when the file is new: `x,y [<unit>]`, or `x,y` with no unit.
- `graph:` is a step-common recipe key like `image_path`, Sequence steps included; Indexed wrapper value propagates like `image_path`.
- The graph lives exactly while its step runs (pops on `StepFinished` like a picture); a step's own graph wins over its own `image_path`; an open question with its own picture takes the area until answered; `RunFinished` tears the graph down and the verdict picture shows.
- New dependency `pyqtgraph>=0.13`; `matplotlib` removed from `[project].dependencies` (unused in `src/`).
- New files under `src/pypts/**/*.py` and `tests/**/*.py` need no SPDX header (`reuse.toml`). New files under `resources/` need an inline SPDX header (`LGPL-2.1-or-later` for `.py`/`.yml`, copyright `2026 CERN <home.cern>`).
- `CONFIG_VERSION` is not touched.

## Review Focus

- **A background thread pushing after its run ended** (the demo's `start_sine()` thread, an early-stopped run): no exception on the bare thread, nothing written into the next run's folder. Test in Task 1 (`test_push_after_session_close_is_dropped`, `test_stale_handle_never_writes_into_next_session`) and Task 3 (`test_background_pusher_outliving_run_writes_nothing_into_next_run`).
- **The GUI reading a CSV while it is being written** — a torn last line, or `\r\n` endings: no garbage points, no half-row parsed as a float. Test in Task 5 (`test_reader_holds_back_torn_row`, `test_reader_handles_crlf`).
- **A stream name that is not a legal file name** (`ch?1`, `a/b`, `V:out`, `..\report`) — the file stays inside `streams/`, and the GUI looks in the same place. Test in Task 1 (`test_unsafe_names_stay_inside_streams`) and Task 7 (`test_gui_graph_path_matches_container_for_unsafe_name`).
- **A long soak** (100 Hz for hours): memory stays bounded and each timer tick reads only new bytes. Test in Task 6 (`test_store_is_bounded_by_max_points`, `test_switching_back_to_a_stream_does_not_reread`).
- **An engineering retest (no run folder) on a recipe with `graph:` keys**: test code runs unchanged, one WARNING, graph steps show no picture area. Test in Task 1 (`test_session_without_folder_writes_nothing`), Task 3 (`test_no_folder_run_registers_without_error`), Task 7 (`test_graph_step_without_run_dir_shows_no_picture`).

---

### Task 1: The stream container

**Files:**
- Create: `src/pypts/stream_handler/stream_file.py` — path rule, header format, `Stream`
- Create: `src/pypts/stream_handler/stream_session.py` — `StreamSession`, the active slot, `register_stream()`, `abandon_active_session()`, `StreamError`
- Modify: `src/pypts/stream_handler/__init__.py` — public API
- Rewrite: `src/pypts/stream_handler/stream_handler.md` — from placeholder to module doc (files, the interface, lifetime rules, the CSV format as the CORE↔GUI contract, why it imports nothing of pypts); drop the spike pointers
- Test: `tests/unit_tests/test_stream_handler.py`

**Interfaces:**
- Produces (all exported from `pypts.stream_handler`):
  - `STREAMS_FOLDER = "streams"`
  - `stream_csv_path(folder: str | os.PathLike[str], name: str) -> pathlib.Path`
  - `unit_from_header(fields: list[str]) -> str | None` — `["x", "y [V]"]` → `"V"`; `["x", "y"]` → `None`
  - `class Stream` — `name: str`, `path: Path | None` (None: streams off), `unit: str | None`; `push(x, y) -> None`; `close() -> None`; `closed: bool` (property)
  - `class StreamSession(folder: str | os.PathLike[str] | None)` — `register(name: str, unit: str | None = None) -> Stream`; `has_stream(name: str) -> bool`; `records_streams: bool` (property: folder is not None); `close() -> None` (never raises); `abandon() -> None`; context manager that activates/deactivates
  - `register_stream(name: str, unit: str | None = None) -> Stream` — on the active session; raises `StreamError` when none is active
  - `abandon_active_session() -> None` — never raises
  - `class StreamError(RuntimeError)`

- [ ] **Step 1: Write the failing tests** in `tests/unit_tests/test_stream_handler.py` (use `tmp_path`):
  - `test_stream_csv_path_is_inside_streams`: `stream_csv_path(tmp_path, "sine") == tmp_path / "streams" / "sine.csv"`
  - `test_unsafe_names_stay_inside_streams`: for each of `"ch?1"`, `"a/b"`, `"V:out"`, `"..\\report"`: `stream_csv_path(tmp_path, n).parent == tmp_path / "streams"`, and `stream_csv_path(tmp_path, "ch?1").name == "ch_1.csv"`; a 100-char name gives a 60-char stem
  - `test_header_with_and_without_unit`: register `"a"` with `unit="V"` and `"b"` with none; first lines are `x,y [V]` and `x,y`; `unit_from_header(["x", "y [V]"]) == "V"`, `unit_from_header(["x", "y"]) is None`
  - `test_push_scalar_and_arrays`: `push(0.0, 1.0)` then `push([0.1, 0.2], [2.0, 3.0])` → file has header + 3 rows, read back with `csv.reader` as floats `[(0.0,1.0),(0.1,2.0),(0.2,3.0)]`; raw bytes end in `b"\r\n"` and contain no `b"\r\r\n"`
  - `test_push_unequal_lengths_raises`: `push([1, 2], [1])` raises `ValueError`
  - `test_reregister_appends_to_same_file`: register, push, close, register same name again, push → one header, both rows
  - `test_push_after_close_is_dropped`: `close()` then `push(1, 1)` does not raise, file unchanged; `close()` twice does not raise; exactly one DEBUG record for the stream (`caplog`) across two dropped pushes
  - `test_push_after_session_close_is_dropped`: stream from a session; `session.close()`; `push` does not raise; `stream.closed is True`
  - `test_stale_handle_never_writes_into_next_session`: stream from session A (folder A), A exits; session B (folder B) active; old handle `push` → nothing under folder B
  - `test_push_from_thread`: a `threading.Thread` pushes 1000 rows while the main thread pushes 1000 → 2000 rows, every row parses as two floats
  - `test_register_without_active_session_raises`: `pytest.raises(StreamError)`
  - `test_session_without_folder_writes_nothing`: `with StreamSession(None):` register `"sine"` and push → returns a `Stream` with `path is None`, nothing written anywhere (cwd untouched: run with `monkeypatch.chdir(tmp_path)` and assert `tmp_path` empty), exactly one WARNING whose message contains `"sine"` and `"no run folder"`, and a second registration logs no second WARNING
  - `test_has_stream`: false before, true after `register("x")`, in both folder and no-folder sessions
  - `test_closing_another_session_does_not_clear_active`: inside `with outer:`, a second `StreamSession(tmp_path / "b")` that is closed without ever being entered leaves the slot alone — `register_stream("x")` still writes under `outer`'s folder (the identity-checked `_deactivate` of `hal/local_setup.py:250-254`)
  - `test_abandon_active_session`: `abandon_active_session()` with a session active closes its streams and clears the slot (`register_stream` then raises); with none active, does nothing

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/unit_tests/test_stream_handler.py -v`
Expected: FAIL — `ImportError` on `pypts.stream_handler` names.

- [ ] **Step 3: Implement `stream_file.py`**

`Stream.__init__(self, name: str, path: Path | None, unit: str | None)`: when `path` is set, `path.parent.mkdir(parents=True, exist_ok=True)`, open per the CSV dialect constraint, write the header row only if the file did not exist or was empty. One `threading.Lock` guards the handle; `push` and `close` both take it. `push`: a pair of numbers is one row; otherwise both sides must have equal `len()` (`ValueError` if not); write all rows, then one `flush()`. A push on a closed stream, or on a stream with `path is None`, writes nothing; on a *closed* stream log one DEBUG line per stream (`"Stream '%s' is closed; samples pushed after close are dropped."`), not one per push.

- [ ] **Step 4: Implement `stream_session.py`**

Copy the shape of `hal/local_setup.py:230-292` (module slot `_active_session`, `_active_lock`, `_activate`, identity-checked `_deactivate`, `abandon_active_session` taking the slot then calling `abandon()`). `StreamSession` keeps `{name: Stream}`; `register` closes nothing — re-registering a name opens a new `Stream` on the same path (append). With `folder is None`, `register` returns `Stream(name, None, unit)` and logs once per session at WARNING: `"Stream '%s' is not recorded: this run has no run folder."`. `close()` closes every stream (each under its own lock), never raises. `abandon()` = `close()` plus refusing further `register` with `StreamError("This run was abandoned; its streams are closed.")`. `__exit__` calls `close()` then `_deactivate(self)` in a `finally`.

- [ ] **Step 5: Export the API from `__init__.py`** (the names in Interfaces, with `__all__`).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/unit_tests/test_stream_handler.py -v`
Expected: all PASS.

- [ ] **Step 7: Rewrite `stream_handler.md`** as listed under Files; add the two new WARNING/DEBUG lines' wording to `logger/logging_rules.md` where it catalogues lines.

- [ ] **Step 8: Gates** — `pytest tests`, `ruff check src tests`, `mypy` pass. Stop; report.

---

### Task 2: The `graph:` recipe key

**Files:**
- Modify: `src/pypts/recipe/recipe_schema.py` — `STEP_COMMON_DEFAULTS` (~line 157) gains `"graph": None`; `_StepFields` (~line 398) gains `graph`
- Modify: `src/pypts/step/step.py:375-391` — `Step.__init__(..., graph: str | None = None)`, stored as `self.graph`
- Modify: `src/pypts/step/sequence_step.py:74-91` — `graph: str | None = None` parameter, passed to `super().__init__`
- Modify: `src/pypts/step/indexed_step.py:119-122` — propagate `graph` exactly like `image_path`
- Modify: `src/pypts/messages/run_events.py:64` — `StepSummary.graph: str | None = None`
- Modify: `src/pypts/recipe/recipe.py:73-85` — `summary_rows()` passes `graph=step.graph`
- Docs: `recipe/recipe.md`, `step/step.md`, `messages/messages.md` (the field), `recipe_guide.html` (the key on every step type, Sequence and Indexed rules, "quote a numeric name: `graph: \"07\"`"). Check the sync rule in `helper_applications/recipe_creator/recipe_creator.md` §"The sync rule" and do what it says for a new common key.
- Test: `tests/unit_tests/test_recipe_schema.py`, `tests/unit_tests/test_recipe.py`, `tests/unit_tests/test_messages.py`

**Interfaces:**
- Produces: `Step.graph: str | None`; `StepSummary.graph: str | None` (default `None`, pickle-safe).

- [ ] **Step 1: Write the failing tests**
  - `test_recipe_schema.py::test_graph_is_a_common_step_key`: `STEP_COMMON_DEFAULTS["graph"] is None`; a PythonModule step dict with `graph: "sine"` validates
  - `test_recipe.py::test_graph_on_every_step_type_loads`: a recipe file (written to `tmp_path`) with `graph: sine` on a PythonModule, UserInteraction, UserWrite, UserLoading, Wait, Sequence and Indexed step loads without error and every built step has `.graph == "sine"`; the Indexed wrapper's generated steps carry it, and a template with its own `graph: other` keeps `"other"`
  - `test_recipe.py::test_summary_rows_carry_graph`: `sequence.to_summary().steps` rows have `.graph == "sine"` for those steps and `None` for a step without the key
  - `test_messages.py`: add `graph="sine"` to the `StepSummary` used in the EXAMPLES so the pickle round-trip covers it (follow how `image_path` is exercised there)

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit_tests/test_recipe_schema.py tests/unit_tests/test_recipe.py tests/unit_tests/test_messages.py -v`
Expected: FAIL (`graph` rejected by `extra="forbid"`, or `TypeError` from `SequenceStep.__init__`).

- [ ] **Step 3: Implement** the six source changes under Files. `_StepFields.graph`: `str | None = Field(default=None, description="The name of a live data stream to show as a graph on the right while this step runs, instead of its picture.", examples=["sine"])`.

- [ ] **Step 4: Run to verify they pass** — same command; all PASS.

- [ ] **Step 5: Docs** as listed. **Step 6: Gates.** Stop; report.

---

### Task 3: The Sequencer opens a session per run

**Files:**
- Modify: `src/pypts/sequencer/sequencer.py` — `execute_sequence()` (297-414), `make_metadata_watcher()` (539-560), `tear_down_abandoned_devices()` (778-798)
- Docs: `sequencer/sequencer.md`, `logger/logging_rules.md` (the typo WARNING)
- Test: `tests/unit_tests/test_sequencer.py`

**Interfaces:**
- Consumes: Task 1 (`StreamSession`, `abandon_active_session`), Task 2 (`StepSummary.graph`).

- [ ] **Step 1: Write the failing tests** (follow the file's existing run helpers; PythonModule test code in `tmp_path` that imports `from pypts.stream_handler import register_stream`):
  - `test_run_writes_stream_into_run_folder`: a step registers `"sine"` and pushes 3 rows → `<run_dir>/streams/sine.csv` exists with header + 3 rows after the run
  - `test_streams_closed_before_run_finished`: by the time the `RunFinished` event is sent, a stream handle kept by test code reports `.closed is True`
  - `test_typo_graph_logs_warning`: a step with `graph: bg_sien` and no such registration → exactly one WARNING `"Step '<name>' shows graph 'bg_sien', but no stream of that name was registered."`; a step with `graph: sine` that registered `sine` → no WARNING
  - `test_no_folder_run_registers_without_error`: `write_report=False` run whose step registers and pushes → step passes, no file written, one WARNING containing `"no run folder"`, and no typo WARNING for its `graph:` step
  - `test_background_pusher_outliving_run_writes_nothing_into_next_run`: run 1's step starts a thread that keeps the handle and pushes after run 1 ends; run 2 runs; run 2's `streams/` has no file from run 1's name, and no exception reached `threading.excepthook` (patch it to record)
  - `test_abandoned_run_abandons_session`: `tear_down_abandoned_devices()` also leaves no active stream session (`register_stream` raises `StreamError`)

- [ ] **Step 2: Run to verify they fail** — `pytest tests/unit_tests/test_sequencer.py -v -k "stream or graph or folder or pusher or abandoned_run_abandons"`; expected FAIL.

- [ ] **Step 3: Implement**
  - In `execute_sequence()`, after `start_run_folder()`: `session = StreamSession(run_dir or None)` — `None` when `run_dir == ""`. Activate it for the run (`with session:` or explicit enter) so that its streams are closed and the slot cleared **before** `end_run_log()` and before `RunFinished` is sent, and a failure inside the run still closes it (`close()` never raises). The session opens in `execute_sequence()`, not `run_body()` (review M2).
  - Build `graph_by_step: dict[UUID, str]` from `sequence.to_summary().steps` (rows whose `.graph` is set) and pass it and the session into `make_metadata_watcher()`, so the `Runtime` is built after the session.
  - In the `emit` closure: after forwarding, if the event is a `StepFinished` whose `outcome.step_id` is in `graph_by_step`, and `session.records_streams`, and not `session.has_stream(name)`: `log.warning("Step '%s' shows graph '%s', but no stream of that name was registered.", outcome.step_name, name)`.
  - `tear_down_abandoned_devices()`: call `abandon_active_session()` as well.

- [ ] **Step 4: Run to verify they pass.** **Step 5: Docs.** **Step 6: Gates** (`test_sequencer.py` whole file must still pass). Stop; report.

---

### Task 4: Copy `pyrade_xy_graph` and wire packaging

**Precondition:** upstream clone at `C:/git/pyrade_xy_graph`, HEAD `af9e4b0`. If HEAD differs, stop and report.

**Files:**
- Create: `src/pyrade_xy_graph/` — copy of upstream `pyrade_xy_graph/` (`__init__.py`, `main.py`, `core/`, `ui/`). Not copied: `old_graph/`, `tests/`, `.DS_Store`, `*.pyc`, upstream `pyproject.toml`, the PNGs.
- Create: `src/pyrade_xy_graph/DEVIATIONS.md` (inline SPDX header, `CC-BY-SA-4.0`): upstream URL (`gitlab.cern.ch` `pyrade/hmi/gui/pyrade_xy_graph`), commit `af9e4b0`, and the two deviations below with the original lines quoted; plus "reported upstream: `requires-python >=3.9` is wrong (3.10+ syntax), `pymeasure` is stale, no licence file"
- Modify: `src/pyrade_xy_graph/ui/plot_widget.py` — deviation 1: delete the line `from pyrade_xy_graph.ui import tdms_exporter  # noqa: F401 ...` (line 11). Deviation 2: delete the import-time `pg.setConfigOptions(antialias=False, useOpenGL=False)` and the two `pg.setConfigOption(...)` lines (18-20) and their comment; nothing replaces them globally.
- Modify: `reuse.toml` — add `"src/pyrade_xy_graph/**/*.py"` to the first annotation's `path` list (`2025 CERN <home.cern>`, `LGPL-2.1-or-later`)
- Modify: `pyproject.toml` — `[tool.setuptools.packages.find] include` gains `"pyrade_xy_graph", "pyrade_xy_graph.*"`; dependencies: add `"pyqtgraph>=0.13"`, remove `"matplotlib"` (first confirm `grep -rn matplotlib src tests` finds nothing); `[tool.ruff] exclude` gains `"src/pyrade_xy_graph"` with a one-line comment (copied upstream code, not held to this style). mypy needs nothing.
- Docs: `CLAUDE.md` — architecture tree gains `src/pyrade_xy_graph/` (copied plot package, later a dependency), the `reuse.toml`-globs sentence names the new glob
- Test: `tests/unit_tests/test_pyrade_copy.py`

- [ ] **Step 1: Install pyqtgraph** into the venv: `.venv/Scripts/python.exe -m pip install "pyqtgraph>=0.13"`; confirm `python -c "import pyqtgraph"` works.

- [ ] **Step 2: Write the failing tests** in `test_pyrade_copy.py`:
  - `test_plot_path_imports`: `from pyrade_xy_graph.ui.plot_widget import ScopePlotWidget` and `from pyrade_xy_graph.core.data_store import DataStore` succeed
  - `test_no_tdms_exporter_registered`: after importing `plot_widget`, `"pyrade_xy_graph.ui.tdms_exporter" not in sys.modules`
  - `test_import_leaves_pyqtgraph_config_alone`: record `pyqtgraph.getConfigOption("background")` and `("foreground")` before importing `plot_widget` (in a fresh interpreter via `subprocess` with `sys.executable -c`, so import order in the test session cannot hide it) and assert unchanged after
  - `test_heavy_deps_not_pulled_in`: in the same subprocess, after importing the two plot-path modules, none of `h5py`, `nptdms`, `pandas` is in `sys.modules`

- [ ] **Step 3: Run to verify they fail** — `pytest tests/unit_tests/test_pyrade_copy.py -v`; expected FAIL (`ModuleNotFoundError: pyrade_xy_graph`).

- [ ] **Step 4: Copy and apply the two deviations; write `DEVIATIONS.md`; edit `reuse.toml`, `pyproject.toml`; `pip install -e .` again so the new package is found.**

- [ ] **Step 5: Run to verify they pass.** **Step 6: Docs** (`CLAUDE.md`). **Step 7: Gates** — plus `reuse lint` if the `reuse` tool is installed (report if it is not). Stop; report.

---

### Task 5: One line tailer, and the stream CSV reader

**Files:**
- Create: `src/pypts/hmi/gui/line_tail.py` — `LineTail`, the whole-line reading `LogTail` does today
- Modify: `src/pypts/hmi/gui/log_tail.py` — `LogTail` keeps its public API (`open`, `new_lines`, `close`, `path`, `min_level`) and delegates reading to a `LineTail`
- Create: `src/pypts/hmi/gui/stream_reader.py` — Qt-free reader of one stream CSV
- Docs: `hmi/gui/gui.md` (the two new modules)
- Test: `tests/unit_tests/test_line_tail.py`, `tests/unit_tests/test_stream_reader.py`; existing `tests/unit_tests/test_log_follower.py` must keep passing unchanged

**Interfaces:**
- Consumes: Task 1 (`unit_from_header`).
- Produces:
  - `class LineTail(path: str | os.PathLike[str])` — `open() -> None` (raises `OSError`), `whole_lines() -> list[str]` (complete lines since the last call, terminators stripped incl. `\r`; a trailing partial line held back), `close() -> None` (idempotent), `is_open: bool`
  - `class StreamReader(path: Path)` — `poll() -> tuple[np.ndarray, np.ndarray]` (the new complete rows as float arrays, both empty when none; opens the file on the first poll that finds it); `exists: bool` (property: the file has been opened); `unit: str | None` (from the header, `None` until read); `close() -> None`
  - `read_whole_stream(path: Path) -> tuple[str | None, np.ndarray, np.ndarray] | None` — the static read for a look-back; `None` when the file does not exist

- [ ] **Step 1: Write the failing tests**
  - `test_line_tail.py`: `test_whole_lines_holds_back_partial` (write `"a\nb"`, get `["a"]`; append `"c\n"`, get `["bc"]`); `test_strips_crlf`; `test_close_twice_and_before_open`
  - `test_stream_reader.py` (write files with `csv.writer(newline="")` the way Task 1 does):
    - `test_reader_waits_for_file`: missing file → `poll()` returns empty arrays, `exists is False`; file created → next `poll()` returns its rows, `exists is True`
    - `test_reader_reads_unit_and_rows`: header `x,y [V]` + 2 rows → `unit == "V"`, arrays `[0.0, 0.1]`, `[1.0, 2.0]`
    - `test_reader_returns_only_new_rows`: second `poll()` after appending 1 row returns exactly that row
    - `test_reader_holds_back_torn_row`: file ends `"0.2,3."` without newline → not returned; after `"5\r\n"` appended → `(0.2, 3.5)` returned
    - `test_reader_handles_crlf`: no row yields `nan` or raises
    - `test_reader_skips_unparsable_row`: a row `"x,oops"` mid-file is skipped (DEBUG line), rows around it returned
    - `test_read_whole_stream_static` and `test_read_whole_stream_missing_returns_none`

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement `LineTail`** by moving the open/read/partial-line logic out of `LogTail` (`log_tail.py:113-155`): open `"r", encoding="utf-8", errors="replace"`, keep the handle open between calls (that is the per-stream offset — no re-read from 0). **Then make `LogTail` use it** without changing its behaviour.

- [ ] **Step 4: Implement `StreamReader` / `read_whole_stream`** on `LineTail`: first whole line is the header (`csv.reader` on it → `unit_from_header`); each further line split on `,` into two floats.

- [ ] **Step 5: Run to verify they pass** (and `test_log_follower.py`). **Step 6: Docs. Step 7: Gates.** Stop; report.

---

### Task 6: The `StreamGraph` widget

**Files:**
- Create: `src/pypts/hmi/gui/stream_graph.py`
- Docs: `hmi/gui/gui.md`
- Test: `tests/unit_tests/test_stream_graph.py` (pytest-qt, `qtbot`)

**Interfaces:**
- Consumes: Task 4 (`ScopePlotWidget`, `DataStore`), Task 5 (`StreamReader`, `read_whole_stream`).
- Produces: `class StreamGraph(QWidget)` with
  - `MAX_POINTS = 100_000`, `POLL_INTERVAL_MS = 250` (module constants)
  - `show_live(name: str, csv_path: Path) -> None` — shows stream `name`, polling on its `QTimer`
  - `show_static(name: str, csv_path: Path) -> bool` — draws the whole file once, no polling; `False` when the file does not exist
  - `stop() -> None` — timer off, nothing shown; per-stream state kept
  - `forget_run() -> None` — `stop()` and drop every per-stream reader and store
  - `is_waiting() -> bool`, `shown_name() -> str | None`, `set_dark(dark: bool) -> None`

- [ ] **Step 1: Write the failing tests**
  - `test_live_waits_then_draws`: `show_live("sine", missing_path)` → `is_waiting()`; the waiting label text is `"Waiting for stream sine"`; create the file with rows; `qtbot.waitUntil(lambda: not graph.is_waiting())`; the plot's curve for `"sine"` has the rows' points
  - `test_live_appends_new_rows`: append rows after the first draw → curve length grows
  - `test_store_is_bounded_by_max_points`: monkeypatch `MAX_POINTS` to 50; 200 rows → curve holds ≤ 50 points, the last 50
  - `test_switching_back_to_a_stream_does_not_reread`: show `a`, then `b`, then `a` again — `a`'s `StreamReader` is the same object (spy `poll` call count / offsets) and its earlier points are still there
  - `test_static_draws_whole_file_once`: `show_static` returns `True`, curve has all rows, timer inactive; `False` for a missing file
  - `test_forget_run_drops_state`
  - `test_axis_label_carries_unit`: header `x,y [V]` → left axis label includes `V`

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Per stream name keep a `StreamReader` and a `DataStore(max_len=MAX_POINTS)` with `set_x_key(name, "x")`. The glue upstream keeps in `graph_widget.py` is re-created here: the shown store's `data_updated` → `get_signal(name)` → `plot.update_signal(name, x, y)`. Each tick: one `poll()` on the shown stream's reader, its rows appended as **one** `DataStore.append({"x": xs, name: ys})` (one repaint per tick), then `plot.autoscale()` (upstream disables pyqtgraph auto-range). On switching stream: `plot.clear_signals()`, connect the new store, draw what it already holds. Colours: light/dark from `pypts.hmi.gui.palette.get_palette(dark)` (background, text), applied to the `ScopePlotWidget` in `set_dark` — not via global `pg.setConfigOption`.

- [ ] **Step 4: Run to verify they pass. Step 5: Docs. Step 6: Gates.** Stop; report.

---

### Task 7: The graph in the right column

**Files:**
- Modify: `src/pypts/hmi/gui/run_display.py` — `_Running.graph`, `_Seen.graph`, `StepReview.graph`, `graph` property
- Modify: `src/pypts/hmi/gui/interaction_panel.py` — hosts a `StreamGraph` under `image_label`
- Modify: `src/pypts/hmi/gui/center_view.py` — `run_started(run_dir)`, `_show_run_view()`, `run_finished()`, `set_recipe()`, `review_step()`
- Modify: `src/pypts/hmi/gui/gui.py:1185` — `self.center.run_started(event.run_dir)`
- Docs: `hmi/gui/gui.md` §18 (graph as one more state of the one decider; precedence: own graph over own picture, question picture over graph, verdict over graph at run end; no run folder → no picture area) and §19 (static look-back)
- Test: `tests/unit_tests/test_run_display.py`, `tests/unit_tests/test_hmi_gui.py`

**Interfaces:**
- Consumes: Task 1 (`stream_csv_path`), Task 2 (`StepSummary.graph`), Task 6 (`StreamGraph`).
- Produces:
  - `RunDisplay.graph -> str | None` (property): the innermost running-stack entry that has a graph **or** a picture decides; if it has a graph, that graph; else `None`. `RunDisplay.image_path` keeps its contract but returns `None` when that deciding entry is a graph. Sequence entries never carry a graph.
  - `StepReview.graph: str | None = None` — the graph on screen when the step started (inherited group graph included); pending review: the step's own `graph`.
  - `InteractionPanel.show_graph(name: str, csv_path: Path) -> None`, `show_static_graph(name: str, csv_path: Path) -> bool`, `is_showing_graph() -> bool`, `stream_graph: StreamGraph` (attribute). `_set_image_from_path()` and `show_no_picture()` stop and hide the graph; `show_graph` hides `image_label` and the missing-image text.
  - `InteractionPanel.show_review(review: StepReview, graph_path: Path | None = None) -> None` — a review with `graph`: static graph if `graph_path` exists, else `show_no_picture()`.
  - `CenterContent.run_started(run_dir: str) -> None`

- [ ] **Step 1: Write the failing tests**
  - `test_run_display.py`:
    - `test_graph_is_innermost_and_pops`: step with `graph="sine"` started → `graph == "sine"`, `image_path is None`; `step_finished` → `graph is None`
    - `test_own_graph_wins_over_own_picture`: a step with both → `graph == "sine"`, `image_path is None`
    - `test_group_graph_shows_under_inner_step_without_one`, and an inner step with its own `image_path` shows that, the group graph returning after it
    - `test_review_records_graph`: finished step's `review().graph == "sine"`; pending step's review carries its own `graph`
  - `test_hmi_gui.py` (CenterContent with real widgets; write CSVs under a `tmp_path` run dir):
    - `test_graph_step_shows_graph_then_pops`: `run_started(str(run_dir))`, `step_started` for a graph step → `interaction.is_showing_graph()`; `step_finished` → not
    - `test_graph_step_without_run_dir_shows_no_picture`: `run_started("")` → graph step → `not is_showing_graph()` and `not is_showing_picture_area()`
    - `test_question_picture_wins_then_graph_returns`: during a graph step, `show_prompt` with an `image_path` → picture shown, not the graph; answer it → `is_showing_graph()` again
    - `test_question_without_picture_keeps_graph`
    - `test_run_finished_tears_graph_down_and_shows_verdict`: `run_finished(ResultType.PASS)` → `not is_showing_graph()`, `run_result_shown() == RUN_PASSED_IMAGE`
    - `test_look_back_at_graph_step_draws_static_graph`: after the run, `review_step(id)` → static graph shown; with the CSV deleted → no picture area
    - `test_gui_graph_path_matches_container_for_unsafe_name`: `graph: "ch?1"`; file written by a `StreamSession(run_dir)` registration of `"ch?1"` is the one the GUI shows

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement** per Interfaces. `CenterContent` keeps `_run_dir` from `run_started` until the next `run_started` or `set_recipe` (look-backs after the run need it). In `_show_run_view()`, after the existing review and pending-question-with-picture returns: if `run_display.graph` is set → `show_graph(graph, stream_csv_path(run_dir, graph))` when `_run_dir`, else `show_no_picture()`; otherwise the existing picture/no-picture branch. `run_started` calls `interaction.stream_graph.forget_run()`. `run_finished` stops the graph before the existing idle/verdict lines. `review_step` passes `stream_csv_path(_run_dir, review.graph)` when both are set.

- [ ] **Step 4: Run to verify they pass** (whole `test_hmi_gui.py` and `test_run_display.py`). **Step 5: Docs. Step 6: Gates.** Stop; report.

---

### Task 8: Demo recipe, spikes, and the remaining documents

**Files:**
- Create: `resources/recipes/stepgraph_recipes/stepgraph_demo.yml` and `resources/recipes/stepgraph_recipes/sine_tests.py` — inline SPDX headers; mirror the layout and header comment style of `resources/recipes/stepimage_recipes/stepimage_demo.yml`
- Delete: `spikes/stream_handler/` and `spikes/GUI/XYGraph/` (superseded reference material)
- Docs: `usage_manual.html` (the graph in the right column; streams CSVs in the run folder's `streams/`), `pypts_implementation_status.html` (stream_handler implemented; new section for this change), `src/pypts/README.md:35` ("stream_handler | stub" row), `CLAUDE.md` (drop "Still a stub: `stream_handler/`"; recipes enumeration gains `stepgraph_recipes/`), `recipe_guide.html` (link the demo)
- Test: `tests/functional_tests/test_stepgraph_demo.py`

**Interfaces:**
- Consumes: everything above. `sine_tests.py`: `run_sine() -> None` registers `"sine"` (`unit="V"`), pushes ~100 samples/s for 10 s in batches of 10, closes; `start_sine() -> None` starts a daemon thread that registers `"bg_sine"`, pushes for 10 s, closes itself, and returns at once.

- [ ] **Step 1: Write the failing functional test** `test_stepgraph_demo_writes_both_streams`: run the demo's main sequence in-process (pattern: `run_to_report()` in `tests/functional_tests/test_engine_in_process.py`), with the push duration monkeypatched short (e.g. a module constant `DURATION_S` in `sine_tests.py` set to 0.3); assert `<run_dir>/streams/sine.csv` and `bg_sine.csv` exist with header `x,y [V]` and at least one row, and the run log has no typo WARNING.

- [ ] **Step 2: Run to verify it fails. Step 3: Write the recipe and test code.** Steps: "Blocking sine" (PythonModule, `graph: sine`, `run_sine`); "Start background sine" (PythonModule, `start_sine`); "Watch it" (Wait 12 s, `graph: bg_sine`).

- [ ] **Step 4: Run to verify it passes. Step 5: Delete the spikes; update the docs listed.**

- [ ] **Step 6: Manual check (report what you saw, do not claim it):** `python run_pypts.py`, load the demo, run: the sine draws live during step 1, the right column follows the stack during step 2, `bg_sine` shows whole-then-live during step 3, the verdict picture after; click step 1 afterwards → static graph.

- [ ] **Step 7: Gates, then the documentation check** — re-read every document touched across Tasks 1–8 against the final code (CLAUDE.md quality gate 4). Stop; report.
