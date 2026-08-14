# `pypts/messages` — the message catalogue

Context file for this module, in the sense of `CLAUDE.md` → *Module context files*.
It is the catalogue of **what each link carries**, lifted out of
`resources/internal_reports/messaging_overview.html` (which keeps the structural picture: links,
queues, transport, handlers, shutdown).

**Status: reference, not yet a contract to build on.** The structure — links, transport,
handler placement — is settled. The individual messages below are *declared*; most of them
have no sender yet, because the execution engine has not been ported. Reviewing and
reworking this list is its own task, deliberately deferred.

Every message is a **frozen slotted dataclass of plain values**. Frozen because a message is
a fact that has already happened; slotted because a typo in a field name should be an
`AttributeError`, not a silent new attribute. Each direction has a union type — that union
*is* the contract.

Legend: **CMD** an instruction to one recipient, which may be refused · **EVT** a fact that
has already happened · **STUB** declared, nothing sends or carries it out yet.

---

## Transport — `queue_wrapper.py`

One class carries every link. It wraps *anything* with `put()` and `get_nowait()`, and that
is the whole reason one class serves both kinds of boundary: the launcher hands out a
`multiprocessing.Queue` for HMI ↔ CORE, CORE hands out plain `queue.Queue` to the Sequencer
and the Report, and a future `--mode connect` can hand out a socket-backed queue-alike.
No module ever learns which one it holds.

Nothing blocks. Each module polls its inboxes from an event loop, so `receive()` takes what
is there at that moment and returns; a message sent between two ticks arrives on the next.
`DEFAULT_BATCH = 64` caps one `receive()` so a busy link cannot starve the other inboxes the
same loop tick has to service.

**The trace.** `send()` and `receive()` each log one DEBUG line, so a run log at DEBUG holds
every message twice — once where it was sent, once where it was taken off the queue. The
pair is the point: *sent but never received* is the failure worth seeing, and it is invisible
to anything that only logs on arrival. Because the trace sits on the one object every message
already passes through, no module has to remember to log and no new message can escape it.

The line names the **link**, not the sender — which is the only thing identifying the
Sequencer and the Report in the log at all, since they are threads of the Core process and
`%(processName)s` reads `Core` for their records too.

Two details that look like accidents and are not:

- `_trace` is obtained with `logging.getLogger()` rather than imported from `logger/log.py`,
  because `log.py` imports this module — importing it back would be a cycle.
- The trace line precedes the `put()`, so a message that then fails to pickle is still
  recorded; `sent` is incremented after, so a failed send is not counted as a delivery.

`sent` / `received` belong to the **holder, not the link**. A wrapper pickled into a child
process gives the child its own copy; the Sequencer and the Report are threads, so they share
CORE's object. For a whole-system view, read the trace in the run log instead.

---

## Shared vocabulary — `common_messages.py` and `run_events.py`

A type lives here when more than one link uses it: either every module sends it, or CORE
*forwards* it from one link to another. Forwarding matters — CORE relays the same object
rather than repacking it into a dict, which is how the old code lost the severity enum on
every hop.

| Type | Kind | Meaning |
|---|---|---|
| `Heartbeat(source, timestamp)` | EVT | Proof the sender's event loop is still turning. `source` travels on the message so one CORE handler serves all three links. |
| `ModuleError(source, severity, message, exception, traceback, operation, error_type)` | EVT | A failure the sender wants CORE to know about. Sent by the two decorators in `utilities/error_handling.py` for what nobody expected, and by `report_error()` / `report_problem()` from a raise site that recognised the failure itself and rated it. `operation` names the method (`"Sequencer.poll_core"`), `error_type` the exception class — strings, because this crosses the pickled link. |
| `ErrorSeverity` · `ResultType` · `StepOutcome` | — | Enums and the pickle-safe summary of one executed step. `ResultType`'s integer order is load-bearing: a group aggregates to its highest member. |
| `RecipeLoaded`, `RunStarted`, `RunFinished`, `SequenceStarted`, `SequenceFinished`, `StepStarted`, `StepFinished` | EVT · STUB | Run progress — a one-for-one port of the nine Qt signals in `old_code/event_proxy.py`. Emitted by the Sequencer, forwarded unchanged by CORE to the HMI. (`RecipeLoaded` comes from CORE itself.) |
| `UserPromptRequest/Response`, `SerialNumberRequest/Response` | EVT · STUB | The two questions the engine asks the operator, joined by a `request_id` the asker generates. |

## CORE ↔ HMI — `core_hmi_communication.py` (the only process boundary)

| `HmiToCore` (9) | Kind | Meaning |
|---|---|---|
| `LoadRecipe(recipe_path)` | CMD | Load and validate a recipe. CORE answers `RecipeLoaded` or `ModuleError`. |
| `StartSequence(sequence_name)` | CMD | Run one named sequence of the loaded recipe. |
| `SetConfigParameter(key, value)` | CMD · STUB | CORE is the single writer of `config.ini`, so a frontend asks instead of writing. The handler currently logs that it is not implemented. |
| `ShutdownRequested()` | CMD | Shut the whole application down. The *launcher* sends this too, on the same link. |
| `HmiStopped()` | EVT | The frontend's loop has ended. CORE waits for this before it may exit. |
| `UserPromptResponse`, `SerialNumberResponse` | EVT | The operator's answers; CORE relays them to the Sequencer. |
| `Heartbeat`, `ModuleError` | EVT | Shared vocabulary, as above. |

| `CoreToHmi` (12) | Kind | Meaning |
|---|---|---|
| `StopHmi()` | CMD | Close the frontend. It answers `HmiStopped`. |
| `StatusChanged(text)` | EVT | One line of free text for the runtime log. Anything with structure has its own message now. |
| `ModuleErrorReported(error)` | EVT | An error CORE decided the operator should see (severity above WARNING). |
| the 7 progress events + the 2 requests | EVT | Forwarded from the Sequencer, unchanged. |

Everything on this link is **pickled**: it is the one link that still crosses a process
boundary. No live queues, no Qt objects, no device handles.
`tests/unit_tests/test_messages.py` round-trips every member of both unions and fails if
that stops being true.

## CORE ↔ Sequencer — `core_sequencer_communication.py` (thread of the Core process)

| Direction | Messages |
|---|---|
| `CoreToSequencer` (5) | **CMD** `RunSequence(sequence_name)` · `StopSequence()` (abort the run, keep the module alive) · `StopSequencer()` (shut the module down)<br>**EVT** `UserPromptResponse` · `SerialNumberResponse` — answers relayed back from the HMI |
| `SequencerToCore` (11) | **EVT** `SequencerStopped()` · the 6 run-progress events · the 2 operator requests · `Heartbeat` · `ModuleError` |

## CORE ↔ Report — `core_report_communication.py` (thread of the Core process)

| Direction | Messages |
|---|---|
| `CoreToReport` (3) | **CMD** `GenerateReport()` · `ExportReport()` · `StopReport()` |
| `ReportToCore` (5) | **EVT** `ReportStopped()` · `ReportGenerated(report_path)` · `ReportExported(report_path)` · `Heartbeat` · `ModuleError`<br>The paths are absolute, and they are new: the old notifications carried nothing, so CORE learned a report existed but not where. |

## any → Logger — `to_logger_communication.py`

| `LoggerControl` (2) | Meaning |
|---|---|
| `SetStdoutEnabled(enabled)` | The Logger owns the console handler, so console echo is an application-wide message, not a local handler change. |
| `StopLogger()` | Sent last, by the launcher. Queued rather than immediate, so everything already in flight is written first. |

---

## Open items on the catalogue

These are the things to settle when the message layer is revisited — the roadmap remains the
authority on when.

- **Nothing emits the run-progress events yet.** `Sequencer.run_sequence()` is a stub, so
  that half of the contract is currently write-only. They were declared early on purpose:
  the CLI, the GUI and the Report all have to agree on them.
- **`RecipeLoaded` is never sent.** `Core.load_recipe()` answers `StatusChanged` saying the
  recipe layer is not ported.
- **`SetConfigParameter` is accepted and ignored.** Two questions are open: whether CORE
  answers with a confirmation or an error, and how a process that already read a value at
  startup learns that it changed.
- **`UserPromptResponse` models one answer only.** Some `old_code` interaction steps read a
  *second* value off the same response queue — a file path, a measured value, a
  (port, baudrate, IDN) triple. Each follow-up needs to become its own request rather than
  an untyped extra read.
- **`PendingRequests` is only half wired.** The Sequencer owns one and calls
  `return_caller()` from `deliver_response()`, so answers coming back are handled. The
  *asking* half — `start()` and `wait()` — lands with the execution engine, and it brings a
  threading constraint with it: the thread that calls `wait()` must not be the one draining
  the inbox.
- **Now that the Sequencer is in-process**, the engine links no longer have to be
  pickle-safe. Whether to allow live objects (a `Recipe`, a device handle) on
  `core_sequencer_communication` is a real design choice, not an oversight — and it does not apply to
  `core_hmi_communication`, which still crosses a process boundary.
