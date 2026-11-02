<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# pypts

## Overview

A Python test-automation framework: it runs YAML "recipes" (sequences of steps) against the
hardware on a bench and produces CSV + HTML reports. Three modes: GUI (the default), CLI and
headless (`python -m pypts --mode headless --recipe x.yml`); a fourth way in is the Python
API (`pypts.api.Pts`), which drives the same engine from code. The engine and the GUI are
separate processes; the Sequencer and the Report are threads inside the engine; the CLI and
headless mode run inside the launcher process.

## Architecture

| Module | Role |
|---|---|
| `launcher/` | entry point (`python -m pypts`): pins spawn, parses the arguments, builds the HMI ↔ CORE links and the log queue, and starts the Logger, CORE and — in GUI mode — the frontend process. The CLI runs in the launcher process itself. |
| `core/` | the mediator and the engine process: routes every message between modules, runs the Sequencer and the Report as its threads, watches heartbeats, orchestrates shutdown. The only module that talks to more than one other. |
| `sequencer/` | the event loop that executes a loaded recipe; `execute_sequence()` runs each sequence on a worker thread of its own |
| `recipe/` | the recipe data layer: parser, schema (Pydantic models), validation |
| `step/` | the six registered step types — PythonModule, UserInteraction, UserWrite, UserLoading, Wait, Sequence — plus Indexed, expanded into generated steps at load time; the Runtime seams; `run_sequence()`, the body the Sequencer runs |
| `report/` | writes an incremental `report.csv` during the run and the HTML at the end, in the run's folder; the report files are named `<board id>_<start time>` |
| `hmi/` | the operator's view: `hmi_client.py` is the protocol half every frontend shares; `cli/` and `gui/` (PySide6) differ only in presentation |
| `api/` | embedding: `Pts` (the engine driven from code), `open_gui()`, and headless mode |
| `messages/` | the typed message dataclasses, one module per link, and `QueueWrapper` |
| `config_handler/` | the per-user `config.ini`, and `bench.ini` beside it — the bench's devices, one bare-named section each (`bench_config.py`) |
| `logger/` | the Logger process: the single writer of the run log. Every process reaches it through one shared queue. |
| `utilities/` | error handling, heartbeats, local storage, recent recipes |
| `hal/` | the hardware layer: devices by logical name, one driver process each; an SSH driver ships |
| `stream_handler/` | the stream container: test code registers named (x, y) streams and pushes samples; each is written to `<run folder>/streams/<name>.csv`, which the GUI draws as a live graph |
| `helper_applications/` | the Recipe Creator (with the recipe verificator) and the Recipe Editor v2 — separate programs with their own entry points |

## Communication model

Modules never touch a queue directly and never call each other. Every link is wrapped in a
`QueueWrapper`, and everything that travels on it is a plain dataclass declared in
`pypts/messages/`.

```
launcher ──ShutdownRequested──► CORE
   HMI  ◄────────────────────► CORE ◄───────────► Sequencer   ┐ threads of
     (process boundary)          ▲  ◄───────────► Report      ┘ the CORE process
                                 │
  every process ─ LogRecord + control messages ─► Logger   (not CORE-mediated)
```

Four rules hold the model together:

- **One transport.** `QueueWrapper` wraps anything with `put()` and `get_nowait()`. The
  HMI ↔ CORE pair is a `multiprocessing.Queue` because it crosses a process boundary; CORE's
  four engine links are plain `queue.Queue`, because the Sequencer and the Report are its own
  threads. No module knows which it holds.
- **The owner builds the handle.** Whoever owns a link constructs both of its wrappers and
  passes them to the module that needs them. A module cannot invent a link to somebody it
  has no business talking to, so the topology is enforced by construction.
- **No silent messages.** Every handler is a `match` closed with `unhandled()`, which a type
  checker rejects unless every member of the link's union is matched, and which raises at run
  time otherwise. There is no `case _: pass` anywhere.
- **One trace.** `QueueWrapper.send()` and `QueueWrapper.receive()` each log a TRACE line
  (custom level 5, `logger/levels.py`), so `--log-level TRACE` writes every message in the
  system to the run log twice — once where it was sent, once where it was taken off the
  queue. A send with no matching receive is a lost message, and that is the point of tracing
  both. Because it sits on the transport, no module has to remember to log anything, and the
  two edits below are still the whole procedure for adding a message. The link name is also
  what identifies the Sequencer and the Report in the log at all: the format names the
  process, and theirs is `Core`.

Anything crossing the HMI ↔ CORE boundary is pickled, so it must stay a plain dataclass of
pickle-friendly values — no queues, Qt objects or device handles. Engine-internal messages
never cross that boundary and may carry richer values: `StepExecuted` deliberately carries
`dict[str, Any]`, and must never join the HMI unions. `tests/unit_tests/test_messages.py`
round-trips every boundary message and fails if that stops being true.

## Adding a message

Two edits:

1. **Declare it** in the link module under `pypts/messages/`, and add it to that link's union.

   ```python
   @dataclass
   class StartSequence:
       sequence_name: str

   HmiToCore = LoadRecipe | StartSequence | ...
   ```

2. **Handle it** in the recipient's handler.

   ```python
   case StartSequence(sequence_name=name):
       self.start_sequence(name)
   ```

Everything else is found for you: the type checker flags every `match` that is now incomplete,
and `test_messages.py` fails until the message has an example and a branch.

A message shared by two links — anything CORE forwards rather than repacks — belongs in
`messages/common_messages.py` or `messages/run_events.py` so both ends refer to the same class.

## Layout of `pypts/messages/`

| File | Contents |
|---|---|
| `queue_wrapper.py` | `QueueWrapper`, its TRACE-level message trace, `unhandled()`, `UnhandledMessage` |
| `links.py` | the name of each direction, as it appears in the trace |
| `common_messages.py` | vocabulary shared by more than one link: `ModuleError`, `Heartbeat`, `ResultType`, `StepOutcome` |
| `run_events.py` | what the engine reports during a run, and the three questions it asks the operator |
| `core_hmi_communication.py` | CORE ↔ HMI |
| `core_sequencer_communication.py` | CORE ↔ Sequencer |
| `core_report_communication.py` | CORE ↔ Report |
| `to_logger_communication.py` | any → Logger |
| `blocking_messages.py` | `PendingRequests`, the waiting half of a request/response pair |
| `messages.md` | module context: the catalogue of what each link carries |

A link module is named after the two ends it joins and holds *both* directions. The Logger is
the exception — `to_logger_communication.py` — because nothing is ever sent back.

## Key features

- All inter-module traffic is typed and explicitly modelled; a missing handler is an error
  rather than silence.
- One process boundary, chosen deliberately: the operator's UI survives an engine crash.
  Everything else runs in the engine process, so nothing else pays to pickle.
- Flexible frontend: CLI or GUI, sharing one implementation of the protocol — and no frontend
  at all in headless mode.
- The transport is swappable without touching a single module — the same `QueueWrapper`
  serves a process boundary and a thread boundary.

## License

Copyright CERN, 2025
Licensed under LGPL-2.1-or-later
