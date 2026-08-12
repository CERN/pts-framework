# pypts

## Overview

This framework orchestrates automation and monitoring tasks by running separate modules as
independent processes. It is built for extensibility, reliability, and clear communication
between modules using well-structured message patterns.

## Architecture

### Launcher

- `launcher/startup.py`. Creates the HMI ↔ CORE channels and the log queue, and starts the
  Logger, CORE and — in GUI mode — the frontend. It is the parent of all of them, and it must
  stay the simplest component in the system.

### CORE

- The mediator. Spawns the Sequencer and the Report, routes every message between modules, and
  supervises their heartbeats. It is the only module that talks to more than one other.

### HMI (GUI/CLI)

- The operator's view. Both frontends share one implementation of the protocol
  (`hmi/hmi_client.py`) and differ only in presentation.

### Sequencer

- Runs the sequences of a loaded recipe and reports progress. Execution is still to be ported
  from `old_code/`.

### Report

- Builds and exports the artefacts of a run. Also still to be ported.

### Logger

- The single writer of the run log file. Every process reaches it through one shared queue.

## Communication model

Modules never touch a queue directly and never call each other. Every link is wrapped in a
`Channel`, and everything that travels on it is a frozen dataclass declared in
`pypts/messages/`.

```
launcher ──ShutdownRequested──► CORE
   HMI  ◄────────────────────► CORE ◄───────────► Sequencer
                                 ▲  ◄───────────► Report
                                 │
  every process ─ LogRecord + control messages ─► Logger   (not CORE-mediated)
```

Three rules hold the model together:

- **One transport.** `Channel` wraps anything with `put()` and `get_nowait()`. The launcher
  decides whether that is a `multiprocessing.Queue` or a `queue.Queue`; no module knows which
  it holds, which is what keeps the planned move of the Sequencer and the Report to threads a
  change to the launcher alone.
- **The owner builds the handle.** Whoever owns a link constructs both of its channels and
  passes them to the module that needs them. A module cannot invent a channel to somebody it
  has no business talking to, so the topology is enforced by construction.
- **No silent messages.** Every handler is a `match` closed with `unhandled()`, which a type
  checker rejects unless every member of the link's union is matched, and which raises at run
  time otherwise. There is no `case _: pass` anywhere.
- **One trace.** `Channel.send()` and `Channel.receive()` each log a DEBUG line naming the
  link and the message, so `--log-level DEBUG` writes every message in the system to the run
  log twice — once from the process that sent it, once from the process that took it. A send
  with no matching receive is a lost message, and that is the point of tracing both. Because
  it sits on the transport, no module has to remember to log anything, and the two edits below
  are still the whole procedure for adding a message.

Anything crossing the HMI ↔ CORE boundary is pickled, so it must stay a frozen dataclass of
plain values. `tests/unit_tests/test_messages.py` round-trips every one of them and fails if
that stops being true.

## Adding a message

Two edits:

1. **Declare it** in the link module under `pypts/messages/`, and add it to that link's union.

   ```python
   @dataclass(frozen=True, slots=True)
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
`messages/common.py` or `messages/run_events.py` so both ends refer to the same class.

## Layout of `pypts/messages/`

| File | Contents |
|---|---|
| `channel.py` | `Channel`, its DEBUG trace, `unhandled()`, `UnhandledMessage` |
| `links.py` | the name of each direction, as it appears in the trace |
| `common.py` | vocabulary shared by more than one link: `ModuleError`, `Heartbeat`, `ResultType`, `StepOutcome` |
| `run_events.py` | what the engine reports during a run, and the two questions it asks the operator |
| `hmi_link.py` | HMI ↔ CORE |
| `sequencer_link.py` | CORE ↔ Sequencer |
| `report_link.py` | CORE ↔ Report |
| `logger_link.py` | any → Logger |
| `requests.py` | `PendingRequests`, the waiting half of a request/response pair |

## Key features

- All inter-module traffic is typed and explicitly modelled; a missing handler is an error
  rather than silence.
- One process boundary, chosen deliberately: the operator's UI survives an engine crash.
- Flexible frontend: CLI or GUI, sharing one implementation of the protocol.
- The transport is swappable without touching a single module.

## License

Copyright CERN, 2025
Licensed under LGPL-2.1-or-later
