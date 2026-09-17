<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# `pypts/messages` — the message catalogue

Context file for this module, in the sense of `CLAUDE.md` → *Module context files*.
It is the catalogue of **what each link carries**, plus the transport and the helpers beside
it. The communication model itself (who talks to whom, why only CORE routes) is summarised in
`CLAUDE.md` → *Communication model*; the shutdown choreography is in `core/core.md`.

**Status: live contract.** Every message below has a sender and a receiver, except the
Report link's export pair (`ExportReport` / `ReportExported`, marked **STUB**). Changing a
message, a union or a field means changing this file in the same commit.

## Files

| File | Owns |
|------|------|
| `__init__.py` | Re-exports only `QueueWrapper`, `UnhandledMessage`, `unhandled`. Import a message from the link module that owns it. |
| `queue_wrapper.py` | `QueueWrapper[Msg]`, `unhandled()`, `UnhandledMessage` — see *Transport* |
| `links.py` | The link names used in trace lines: `HMI_TO_CORE`, `CORE_TO_HMI`, `CORE_TO_SEQUENCER`, `SEQUENCER_TO_CORE`, `CORE_TO_REPORT`, `REPORT_TO_CORE`, `ANY_TO_LOGGER`. Imports nothing. |
| `common_messages.py` | `ModuleError`, `Heartbeat` and the payloads `ErrorSeverity`, `ResultType`, `StepOutcome` |
| `run_events.py` | Run progress, operator commands about a run, the three operator questions, and the payloads `StepSummary`, `SequenceSummary` |
| `core_hmi_communication.py` | `HmiToCore` / `CoreToHmi` and the messages only that link carries |
| `core_sequencer_communication.py` | `CoreToSequencer` / `SequencerToCore`, `RunSequence`, `StopSequencer`, `SequencerStopped` |
| `core_report_communication.py` | `CoreToReport` / `ReportToCore`, `GenerateReport`, `ExportReport`, `StopReport`, `ReportStopped`, `ReportGenerated`, `ReportExported` |
| `to_logger_communication.py` | `LoggerControl`: `SetStdoutEnabled`, `StopLogger` |
| `blocking_messages.py` | `PendingRequests` — the waiting half of a request/response pair; see *Waiting for an answer* |

Every message is a plain **dataclass of plain values**. Each direction has a union type — that
union *is* the contract.

They were `frozen=True, slots=True` until September 2026, so that a message could not be
edited in flight and a typo in a field name was an error rather than a silent new attribute.
Both were dropped deliberately: the framework is the only thing that builds and forwards a
message, so that is now a rule the code keeps rather than one the type enforces. Two
consequences worth knowing — a message is no longer hashable (nothing puts one in a set or
uses one as a dict key today), and Core forwards the *same object* on the two in-process
links, so a handler that mutated one would change what the other recipient sees.

Legend: **CMD** an instruction to one recipient, which may be refused · **EVT** a fact that
has already happened · **STUB** declared, nothing sends or carries it out yet.

Every message marked **STUB** here also carries a `NOT SENT YET` comment in the source, on the
dataclass and again on the branch that receives it. The marker means one specific thing:
**the receiving end is written and works; nothing constructs the message.** Only the Report
link's export pair (`ExportReport` / `ReportExported`) is in that state today —
`SetConfigParameter` left it in September 2026, when the GUI's Settings dialog started
sending it. Grep for it to find the set:

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
`multiprocessing.Queue` for HMI ↔ CORE, and CORE hands out plain `queue.Queue` to the
Sequencer and the Report. No module ever learns which one it holds.

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

### Messages and payloads

Both files hold two kinds of type, and the **Kind** column below is where they part:

- **`CMD` / `EVT` — a message.** A member of a link union. `QueueWrapper.send()` takes it,
  a handler answers it with a `case`, `mypy` counts it towards exhaustiveness, and
  `EXAMPLES` in `test_messages.py` must have one.
- **`—` — a payload.** Only ever a *field* of a message. It reaches no union, no handler
  and no `EXAMPLES` entry. `StepOutcome` is the clearest case: it is not a message, it is
  what `StepFinished`, `StepExecuted` and `RunFinished` are made of.

Nothing in the syntax separates them — both are plain dataclasses sitting in the same file
— so each file carries a `# --- Payloads: … ---` banner over its payload block and each
payload's docstring opens by naming the messages that carry it. Five types are payloads:
`ErrorSeverity`, `ResultType`, `StepOutcome` (`common_messages.py`) and `StepSummary`,
`SequenceSummary` (`run_events.py`). `test_no_payload_is_on_a_union` fails if one ever
reaches a union, which is what stops those comments from quietly going stale.

| Type | Kind | Meaning |
|---|---|---|
| `Heartbeat(source, timestamp)` | EVT | Proof the sender's event loop is still turning. `source` travels on the message so one CORE handler serves all three links. It also travels **one way back**, CORE→HMI, which is why it is on four unions and not three: the HMI is the only module in a process of its own, so it is the only one that can still be running with nothing at the other end of its link. The Sequencer and the Report are threads of CORE's process and die with it, so neither is sent one — a second and third reverse direction would watch for something that cannot happen and double the trace traffic doing it. |
| `ModuleError(source, severity, message, exception, traceback, operation, error_type)` | EVT | A failure the sender wants CORE to know about. Sent by the two decorators in `utilities/error_handling.py` for what nobody expected, and by `report_error()` / `report_problem()` from a raise site that recognised the failure itself and rated it. `operation` names the method (`"Sequencer.poll_core"`), `error_type` the exception class — strings, because this crosses the pickled link. |
| `ErrorSeverity` · `ResultType` · `StepOutcome` | — | **Payloads.** Enums and the pickle-safe summary of one executed step. `ErrorSeverity` is a field of `ModuleError`; `ResultType` of `RunFinished`, `SequenceFinished` and `StepOutcome`; `StepOutcome` of `StepFinished`, `StepExecuted` and `RunFinished`. `StepOutcome` carries the step's `inputs`, `outputs` and `expectations` as tuples of `(name, text)` pairs (M-3, `step/step.md` §3.6): text, so it stays pickle-safe whatever a step returned, and pairs rather than a dict because a message is built from plain values, tuples and dataclasses only. `ResultType`'s integer order is load-bearing: a group aggregates to its highest member. |
| `StepSummary(step_id, step_name, description, depth=0, is_group=False)` · `SequenceSummary(sequence_name, steps)` | — | **Payloads**, in `run_events.py`. The rows a frontend draws before a run: `StepSummary` is a field of `SequenceSummary`, which is a field of `RecipeLoaded`. Rows are depth-first over called sequences: a row with `is_group` stands for a `Sequence` step and its own rows follow at `depth + 1`. Summaries, not the live `Step` and `Sequence` — those must never cross the HMI boundary. |
| `RecipeLoaded`, `RunStarted`, `RunFinished`, `SequenceStarted`, `SequenceFinished`, `StepStarted`, `StepFinished` | EVT | Run progress — a one-for-one port of the nine Qt signals in `old_code/event_proxy.py`. Live since the first engine slice: emitted by the Sequencer and the step layer on every run, forwarded unchanged by CORE to the HMI. CORE also forwards `RunStarted` and `SequenceStarted` to the Report, which needs the run brackets for its folder and its rows. `RecipeLoaded` comes from CORE itself and carries the whole pickle-safe summary of the file — `main_sequence` plus a `SequenceSummary` per sequence holding `StepSummary(step_id, step_name, description)` rows — which is what fills a frontend's sequence chooser and pre-fills its step table. |
| `StepExecuted(outcome, step_type, inputs, outputs, started_at, duration_s, group_path="")` | EVT | The rich sibling of `StepFinished`, emitted by `Step.run()` right after it: everything the Report writes about one executed step, including the resolved inputs, the judged outputs, the measured duration and `group_path` — the sequences it ran inside, `Main/PowerCycle`. **Engine-internal**: it rides Sequencer→CORE and CORE→Report only, two links that never leave the Core process — it must never join the HMI unions, whose flat `StepOutcome` is the projection that crosses the boundary. |
| `UserPromptRequest/Response`, `UserTextRequest/Response`, `UserPathRequest/Response` | EVT | The three questions the engine asks the operator, joined by a `request_id` the asker generates. All three are live end to end: `UserInteractionStep` asks the first (a choice between the recipe's buttons), `UserWriteStep` the second (a line of typed text), `UserLoadingStep` the third — `UserPathRequest(request_id, message, select, image_path)` with `select` `"file"` or `"folder"` (always lowercase), answered by `UserPathResponse(request_id, path)`, `path` None if declined. The frontend hooks are `HmiClient.ask_user_path()` (the default declines with a WARNING) and `answer_user_path()`. There is deliberately **no message for a particular question** — an earlier `SerialNumberRequest` hard-coded one, so the engine fetched the serial number of the unit under test whether or not the recipe wanted one. Asking is the recipe's job. |
| `RunPaused(step_name, position, total)` · `RunResumed()` | EVT | The operator's hold, confirmed. `RunPaused` is sent by the Sequencer when the hold actually **begins** — after the step that was running when Pause was pressed has finished — and names the main step the run is held before (`position`/`total` count main steps, 1-based). `RunResumed` is sent when a hold ends, by `ResumeSequence` or by `StopSequence`; never without a `RunPaused` before it. Never sent for teardown, which always runs straight through. CORE relays both to the HMI only — the Report does not record holds. |
| `RunMetadata(values)` | EVT | What the run has learned about the unit on the bench: the globals the recipe named in its `report_metadata` header, as pairs, sent by the Sequencer whenever one appears or changes. The Report cannot read globals — it is a thread fed by events, while the globals live on the sequence thread — so the Sequencer wraps the Runtime's `emit` seam and sends them. CORE relays it to the Report (which stamps it on every CSV row) and to the HMI (whose top bar shows it). |

## CORE ↔ HMI — `core_hmi_communication.py` (the only process boundary)

| `HmiToCore` (13) | Kind | Meaning |
|---|---|---|
| `LoadRecipe(recipe_path)` | CMD | Load and validate a recipe. CORE answers `RecipeLoaded` or `ModuleError`. |
| `StartSequence(sequence_name)` | CMD | Run one named sequence of the loaded recipe. |
| `StopSequence()` | CMD | Abort the running sequence; the application stays up. Defined in `run_events.py` because it rides two links: CORE relays the same object to the Sequencer, and the confirmation is the run's own `RunFinished(STOP)`. |
| `PauseSequence()` · `ResumeSequence()` | CMD | Hold the run before its next main step / end the hold (or cancel a pause whose hold has not begun). Defined in `run_events.py` and relayed unchanged, like `StopSequence`. Confirmed by `RunPaused` / `RunResumed`. If no main step is left the pause lapses — teardown is never held. **GUI only**: the CLI and the API do not send them. |
| `SetConfigParameter(key, value)` | CMD | Change one value in `config.ini`. CORE is the single runtime writer, so a frontend asks instead of writing; `value` is the text as the file spells it. Sent by the GUI's Edit → Settings dialog, one per changed key. CORE answers `ConfigParameterResult`. In force from the next start. |
| `ShutdownRequested()` | CMD | Shut the whole application down. The *launcher* sends this too, on the same link. |
| `HmiStopped()` | EVT | The frontend's loop has ended. CORE waits for this before it may exit. |
| `UserPromptResponse`, `UserTextResponse`, `UserPathResponse` | EVT | The operator's answers; CORE relays them to the Sequencer. |
| `Heartbeat`, `ModuleError` | EVT | Shared vocabulary, as above. |

| `CoreToHmi` (19) | Kind | Meaning |
|---|---|---|
| `StopHmi()` | CMD | Close the frontend. It answers `HmiStopped`. |
| `ConfigParameterResult(key, value, accepted, reason)` | EVT | CORE's answer to one `SetConfigParameter`. `accepted` means the value is in the file now; otherwise nothing was written and `reason` says why (wrong type, unknown key, a read-only section, a file discarded at startup). `key`/`value` repeat the request so a frontend waiting on several answers can tell them apart. |
| `StatusChanged(text)` | EVT | One line of free text for the frontend's status bar. Anything with structure has its own message now. **Not logged above DEBUG**: the fact behind it was already written to the run log by whichever module owns it, so logging the status text too would say it twice - see `logger/logging_rules.md` section 5. |
| `ModuleErrorReported(error)` | EVT | An error CORE decided the operator should see (severity above WARNING). |
| `ReportReady(report_path, report_dir)` | EVT | The run's report is on disk. Sent by CORE when the Report answers `ReportGenerated`; the structured sibling of the `StatusChanged` sent beside it. `report_dir` is what a frontend's "open report folder" control opens. |
| the 7 progress events + `RunPaused` + `RunResumed` + `RunMetadata` + the 3 requests | EVT | Forwarded from the Sequencer, unchanged. `RunMetadata` is what the GUI's top bar shows beside the recipe name, so the operator can see which unit the bench believes is in front of them. |
| `Heartbeat` | EVT | CORE's own, at 1 Hz, and the only message that travels this way for the frontend's benefit rather than the operator's. `HmiClient.check_core_is_alive()` watches it: quiet for 5 s is a WARNING, quiet for 15 s closes the window. Without it a CORE killed outright — or one whose event loop has wedged while the process stays up — leaves the frontend showing a run that stopped long ago, with nobody left to send it `StopHmi`. CORE keeps beating all through a shutdown for the same reason: the HMI is being stopped then, and must not read the silence as an engine that died under it. |

Everything on this link is **pickled**: it is the one link that still crosses a process
boundary. No live queues, no Qt objects, no device handles.
`tests/unit_tests/test_messages.py` round-trips every member of both unions and fails if
that stops being true.

## CORE ↔ Sequencer — `core_sequencer_communication.py` (thread of the Core process)

| Direction | Messages |
|---|---|
| `CoreToSequencer` (8) | **CMD** `RunSequence(recipe, sequence_name)` (the live, validated Recipe *and* the sequence to run - the one message carrying a rich object, allowed because this link never leaves the Core process; CORE owns the loaded recipe and hands it over per run, so the Sequencer holds none between runs) · `StopSequence()` (abort the run, keep the module alive; defined in `run_events.py` - the operator sends it on HmiToCore and CORE relays the same object here) · `PauseSequence()` · `ResumeSequence()` (hold the run before its next main step / end the hold; relayed the same way) · `StopSequencer()` (shut the module down)<br>**EVT** `UserPromptResponse` · `UserTextResponse` · `UserPathResponse` — answers relayed back from the HMI |
| `SequencerToCore` (16) | **EVT** `SequencerStopped()` · the 6 run-progress events · `RunPaused` · `RunResumed` (routed to the HMI only) · `StepExecuted` (routed to the Report, never the HMI) · `RunMetadata` (routed to both) · the 3 operator requests · `Heartbeat` · `ModuleError` |

## CORE ↔ Report — `core_report_communication.py` (thread of the Core process)

| Direction | Messages |
|---|---|
| `CoreToReport` (8) | **EVT** `RunStarted` (opens the run folder and the incremental CSV, its `metadata_names` deciding the columns) · `SequenceStarted` (names the rows that follow) · `StepExecuted` (one CSV row, flushed) · `RunMetadata` (the run's metadata globals, stamped on every row when the CSV is rewritten) · `RunFinished` (closes the CSV, backfills it and renames the run folder) — all forwarded from the Sequencer<br>**CMD** `GenerateReport()` (sent by CORE right behind `RunFinished`; one queue, so the order is guaranteed) · `ExportReport()` (STUB) · `StopReport()` |
| `ReportToCore` (5) | **EVT** `ReportStopped()` · `ReportGenerated(report_path)` (answers `GenerateReport`; CORE relays it to the operator as `ReportReady`) · `ReportExported(report_path)` (STUB) · `Heartbeat` · `ModuleError`<br>The paths are absolute, and they are new: the old notifications carried nothing, so CORE learned a report existed but not where. |

## Waiting for an answer — `blocking_messages.py`

`PendingRequests` joins a `User*Request` to its `User*Response` by `request_id`. Fully wired
in the Sequencer:

- **Asking** — `Sequencer.ask_operator()` (the step layer's `Runtime.ask` seam) runs on the
  *sequence worker thread*: `pending.start(request_id)` **before** sending the request (so a
  fast answer cannot be lost), then `pending.wait(request_id, should_abort=...)`.
- **Answering** — `Sequencer.deliver_response()` runs on the *event-loop thread* and calls
  `pending.return_caller(request_id, value)`; `False` means nobody was waiting and is logged.

`wait()` polls every `POLL_INTERVAL_S` (0.1 s) so an operator's Stop is honoured while a
question is on screen, gives up after `DEFAULT_TIMEOUT_S` (300 s), and always cancels its slot.
A timeout, an abort and a declined question all return `None` — deliberately the same to the
asker. **The thread that calls `wait()` must never be the one draining the inbox**, or the
answer cannot arrive.

## any → Logger — `to_logger_communication.py`

| `LoggerControl` (2) | Meaning |
|---|---|
| `SetStdoutEnabled(enabled)` | The Logger owns the console handler, so console echo is an application-wide message, not a local handler change. |
| `StopLogger()` | Sent last, by the launcher. Queued rather than immediate, so everything already in flight is written first. |

---

## Open items on the catalogue

These are the things to settle when the message layer is revisited — the roadmap remains the
authority on when.

- **A configuration change is not propagated.** `SetConfigParameter` is answered with
  `ConfigParameterResult`; a process that already read a value keeps it until the next
  start, by decision.
- **A response models one answer only — settled.** Some `old_code` interaction steps read
  a *second* value off the same response queue — a file path, a measured value, a
  (port, baudrate, IDN) triple. The rule is that each follow-up becomes its own request
  rather than an untyped extra read. `UserLoadingStep` was the case that needed it, and it
  follows the rule: the old "button, then path" pair is one `UserPathRequest` answered by
  one `UserPathResponse` carrying the path (see `step/step.md` §2.5). The IDN triple went
  with `UserWrite`'s dropped `ID` mode.
- **Now that the Sequencer is in-process**, the engine links no longer have to be
  pickle-safe. The choice was made with the first slice of the engine port: `RunSequence`
  carries the live `Recipe`, deliberately and documented on the message — and it does not
  apply to `core_hmi_communication`, which still crosses a process boundary and stays
  pickle-tested.
