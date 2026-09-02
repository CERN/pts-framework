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

Every message marked **STUB** here also carries a `NOT SENT YET` comment in the source, on the
dataclass and again on the branch that receives it. The marker means one specific thing:
**the receiving end is written and works; nothing constructs the message.** Five messages
are in that state today: the two prompt requests, `SetConfigParameter`, and the Report
link's export pair (`ExportReport` / `ReportExported`). Grep for it to find the set:

```bash
grep -rn "NOT SENT YET" src/pypts
```

The receivers were built ahead of the senders deliberately — the Sequencer, CORE, the CLI and
the GUI all had to agree on the contract before the engine existed — and `mypy` plus
`test_messages.py` keep every branch honest until the sender arrives. Delete the marker in the
same change that starts sending the message.

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
| `RecipeLoaded`, `RunStarted`, `RunFinished`, `SequenceStarted`, `SequenceFinished`, `StepStarted`, `StepFinished` | EVT | Run progress — a one-for-one port of the nine Qt signals in `old_code/event_proxy.py`. Live since the first engine slice: emitted by the Sequencer and the step layer on every run, forwarded unchanged by CORE to the HMI. CORE also forwards `RunStarted` and `SequenceStarted` to the Report, which needs the run brackets for its folder and its rows. `RecipeLoaded` comes from CORE itself and carries the whole pickle-safe summary of the file — `main_sequence` plus a `SequenceSummary` per sequence holding `StepSummary(step_id, step_name, description)` rows — which is what fills a frontend's sequence chooser and pre-fills its step table. |
| `StepExecuted(outcome, step_type, inputs, outputs, started_at, duration_s)` | EVT | The rich sibling of `StepFinished`, emitted by `Step.run()` right after it: everything the Report writes about one executed step, including the resolved inputs, the judged outputs and the measured duration. **Engine-internal**: it rides Sequencer→CORE and CORE→Report only, two links that never leave the Core process — it must never join the HMI unions, whose flat `StepOutcome` is the projection that crosses the boundary. |
| `UserPromptRequest/Response`, `UserTextRequest/Response` | EVT | The two questions the engine asks the operator, joined by a `request_id` the asker generates. Both are live end to end: `UserInteractionStep` asks the first (a choice between the recipe's buttons), `UserWriteStep` the second (a line of typed text). There is deliberately **no message for a particular question** — an earlier `SerialNumberRequest` hard-coded one, so the engine fetched the serial number of the unit under test whether or not the recipe wanted one. Asking is the recipe's job. |
| `RunMetadata(values)` | EVT | What the run has learned about the unit on the bench: the globals the recipe named in its `report_metadata` header, as pairs, sent by the Sequencer whenever one appears or changes. The Report cannot read globals — it is a thread fed by events, while the globals live on the sequence thread — so the Sequencer wraps the Runtime's `emit` seam and sends them. CORE relays it to the Report (which stamps it on every CSV row) and to the HMI (whose top bar shows it). |

## CORE ↔ HMI — `core_hmi_communication.py` (the only process boundary)

| `HmiToCore` (10) | Kind | Meaning |
|---|---|---|
| `LoadRecipe(recipe_path)` | CMD | Load and validate a recipe. CORE answers `RecipeLoaded` or `ModuleError`. |
| `StartSequence(sequence_name)` | CMD | Run one named sequence of the loaded recipe. |
| `StopSequence()` | CMD | Abort the running sequence; the application stays up. Defined in `run_events.py` because it rides two links: CORE relays the same object to the Sequencer, and the confirmation is the run's own `RunFinished(STOP)`. |
| `SetConfigParameter(key, value)` | CMD · STUB | CORE is the single writer of `config.ini`, so a frontend asks instead of writing. The handler currently logs that it is not implemented. |
| `ShutdownRequested()` | CMD | Shut the whole application down. The *launcher* sends this too, on the same link. |
| `HmiStopped()` | EVT | The frontend's loop has ended. CORE waits for this before it may exit. |
| `UserPromptResponse`, `UserTextResponse` | EVT | The operator's answers; CORE relays them to the Sequencer. |
| `Heartbeat`, `ModuleError` | EVT | Shared vocabulary, as above. |

| `CoreToHmi` (14) | Kind | Meaning |
|---|---|---|
| `StopHmi()` | CMD | Close the frontend. It answers `HmiStopped`. |
| `StatusChanged(text)` | EVT | One line of free text for the runtime log. Anything with structure has its own message now. |
| `ModuleErrorReported(error)` | EVT | An error CORE decided the operator should see (severity above WARNING). |
| `ReportReady(report_path, report_dir)` | EVT | The run's report is on disk. Sent by CORE when the Report answers `ReportGenerated`; the structured sibling of the `StatusChanged` sent beside it. `report_dir` is what a frontend's "open report folder" control opens. |
| the 7 progress events + `RunMetadata` + the 2 requests | EVT | Forwarded from the Sequencer, unchanged. `RunMetadata` is what the GUI's top bar shows beside the recipe name, so the operator can see which unit the bench believes is in front of them. |

Everything on this link is **pickled**: it is the one link that still crosses a process
boundary. No live queues, no Qt objects, no device handles.
`tests/unit_tests/test_messages.py` round-trips every member of both unions and fails if
that stops being true.

## CORE ↔ Sequencer — `core_sequencer_communication.py` (thread of the Core process)

| Direction | Messages |
|---|---|
| `CoreToSequencer` (6) | **CMD** `UseRecipe(recipe)` (the live, validated Recipe subsequent runs use - the one message carrying a rich object, allowed because this link never leaves the Core process) · `RunSequence(sequence_name)` · `StopSequence()` (abort the run, keep the module alive; defined in `run_events.py` - the operator sends it on HmiToCore and CORE relays the same object here) · `StopSequencer()` (shut the module down)<br>**EVT** `UserPromptResponse` · `UserTextResponse` — answers relayed back from the HMI |
| `SequencerToCore` (13) | **EVT** `SequencerStopped()` · the 6 run-progress events · `StepExecuted` (routed to the Report, never the HMI) · `RunMetadata` (routed to both) · the 2 operator requests · `Heartbeat` · `ModuleError` |

## CORE ↔ Report — `core_report_communication.py` (thread of the Core process)

| Direction | Messages |
|---|---|
| `CoreToReport` (8) | **EVT** `RunStarted` (opens the run folder and the incremental CSV, its `metadata_names` deciding the columns) · `SequenceStarted` (names the rows that follow) · `StepExecuted` (one CSV row, flushed) · `RunMetadata` (the run's metadata globals, stamped on every row when the CSV is rewritten) · `RunFinished` (closes the CSV, backfills it and renames the run folder) — all forwarded from the Sequencer<br>**CMD** `GenerateReport()` (sent by CORE right behind `RunFinished`; one queue, so the order is guaranteed) · `ExportReport()` (STUB) · `StopReport()` |
| `ReportToCore` (5) | **EVT** `ReportStopped()` · `ReportGenerated(report_path)` (answers `GenerateReport`; CORE relays it to the operator as `ReportReady`) · `ReportExported(report_path)` (STUB) · `Heartbeat` · `ModuleError`<br>The paths are absolute, and they are new: the old notifications carried nothing, so CORE learned a report existed but not where. |

## any → Logger — `to_logger_communication.py`

| `LoggerControl` (2) | Meaning |
|---|---|
| `SetStdoutEnabled(enabled)` | The Logger owns the console handler, so console echo is an application-wide message, not a local handler change. |
| `StopLogger()` | Sent last, by the launcher. Queued rather than immediate, so everything already in flight is written first. |

---

## Open items on the catalogue

These are the things to settle when the message layer is revisited — the roadmap remains the
authority on when.

- **`SetConfigParameter` is accepted and ignored.** Two questions are open: whether CORE
  answers with a confirmation or an error, and how a process that already read a value at
  startup learns that it changed.
- **A response models one answer only.** Some `old_code` interaction steps read a
  *second* value off the same response queue — a file path, a measured value, a
  (port, baudrate, IDN) triple. Each follow-up needs to become its own request rather than
  an untyped extra read. `UserWrite` did not need it (one question, one line of text);
  `UserLoadingStep` will (see `step/step.md` §2.5).
- **`PendingRequests` is only half wired.** The Sequencer owns one and calls
  `return_caller()` from `deliver_response()`, so answers coming back are handled. The
  *asking* half — `start()` and `wait()` — lands with the execution engine, and it brings a
  threading constraint with it: the thread that calls `wait()` must not be the one draining
  the inbox.
- **Now that the Sequencer is in-process**, the engine links no longer have to be
  pickle-safe. The choice was made with the first slice of the engine port: `UseRecipe`
  carries the live `Recipe`, deliberately and documented on the message — and it does not
  apply to `core_hmi_communication`, which still crosses a process boundary and stays
  pickle-tested.
