<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Logging — the convention

The module context file for `src/pypts/logger/`. `log.py` says how the Logger *works* (one
process, single writer, the shared queue, the control messages); this file says **what a log
line is allowed to say and at which level**, for every module in the framework.

It is the authority on wording. A line anywhere in `src/pypts/` that disagrees with this file
is a defect in the line, not in the file. The roadmap stays the authority on status and plan
and wins where they overlap.

Agreed 2026-09-02; the sweep that applied it across the code is roadmap §1.23.

---

## 1. The one rule everything follows

**The GUI shows the operator everything at INFO and above.**

`hmi/gui/log_tail.py` tails this run's log file into the LOG OUTPUT panel with
`PANEL_LOG_LEVEL = logging.INFO`, and it drops every column except the level, the clock and
the message. So:

- **INFO, WARNING, ERROR and CRITICAL are written for the technician.** All four. They are
  read by someone who knows the device under test very well and the test software not at all.
- **DEBUG is written for the developer.** Everything else goes there.

If a line needs the words *queue*, *thread*, *message*, *handler*, *callback*, `None`, a class
name or a `repr()` of anything internal, it is a DEBUG line. There is no third option and no
borderline case: the question "would a technician act on this?" answers it every time.

---

## 2. The levels

| Level | Audience | What belongs there |
|---|---|---|
| `DEBUG` | developer | near-trace: call arguments and return values, branch decisions with the value that chose them, state transitions, message hops, tracebacks, heartbeat and liveness internals, internal paths, object reprs |
| `INFO` | technician | the run's story, in plain sentences — and nothing else |
| `WARNING` | technician | degraded, but the run continues: a retry, a discarded settings file, a module that stopped responding |
| `ERROR` | technician | an operation failed. A plain sentence naming *what was being done*, with the raw text appended |
| `CRITICAL` | technician | the run or the bench is in an unknown state; the operator has to fetch someone |

### 2.1 A FAIL is not an error

A step that returns `ResultType.FAIL` logs at **INFO**. A failing measurement is the normal,
expected output of testing a device — making it a WARNING or an ERROR would mean a perfectly
ordinary production unit fills the log with alarms and a real software fault stops standing
out. Only `ResultType.ERROR` — the step itself blew up — produces an `ERROR` line.

---

## 3. How a message is written

- **Sentence case, ending in a full stop.** `Recipe 'x.yml' loaded.` — not `recipe loaded: x.yml`.
  This holds at DEBUG too, so the whole file reads the same way.
- **Names in single quotes**: `'warmup'`, `'thermal_cycle.yml'`, `'read_voltage'`. A name with a
  space in it stays unambiguous, and a step can be grepped for by name.
- **ASCII only in the message text.** Write `+/-` and `->`; no `±`, no arrows, no emoji. The
  Logger pins UTF-8 when it writes precisely because a Windows console is not guaranteed to
  cope, and a `UnicodeEncodeError` inside logging is a bad way to lose a run.
- **Verdicts bare and uppercase**: `PASS`, `FAIL`, `SKIP`, `ERROR`, `DONE`, `STOP` — the
  `ResultType` members, so the log, the CSV and the HTML report all say the same word.
- **`%`-style lazy formatting, never f-strings**: `log.info("Recipe '%s' loaded.", name)`. This
  is what makes the heavy DEBUG trace cost nothing at INFO level. `ruff`'s `G004` enforces it.
- **No jargon at INFO and above** — see §1.

---

## 4. Which module is speaking

`LOG_FORMAT` is deliberately **not** changed by this convention. It stays

```
%(asctime)s.%(msecs)03d;%(levelname)s;%(processName)s;%(filename)s:%(funcName)s;%(message)s
```

so the Debug Monitor's parser and `test_logger.py`'s `LOG_LINE` regex keep working, and the
`%(processName)s` column keeps reading `Core` for the Sequencer and the Report threads — the
open TODO in roadmap §1.5, untouched here.

Identity is carried in the **message text instead**, and only where the line is *about* a
module:

```
INFO   CORE module started.            INFO   CORE module stopped.
DEBUG  CORE module starting.           DEBUG  CORE entered its main event loop.
DEBUG  CORE module stopping.           DEBUG  CORE left its main event loop.
```

The names are `LAUNCHER`, `LOGGER`, `CORE`, `SEQUENCER`, `REPORT`, `GUI`, `CLI` — uppercase,
exactly these spellings.

`LOGGER` is in the list but does not appear in the run log, and cannot: the Logger process is
the file's only writer and does not log through itself. Its own diagnostics go to stderr,
prefixed `[logger]`, which is the one place in the framework where a message bypasses all of
this. The launcher records the Logger's lifecycle from the outside, at DEBUG.

**Ordinary event lines carry no prefix.** `Recipe 'x.yml' loaded.` already says what happened;
a `SEQUENCER:` in front of it is noise to the person the line was written for.

### 4.1 The lifecycle phrases are fixed

These five, and no variations on them:

| Phrase | Level | When |
|---|---|---|
| `<NAME> module starting.` | DEBUG | first statement of `start()` |
| `<NAME> module started.` | INFO | once the module is up, before the event loop |
| `<NAME> entered its main event loop.` | DEBUG | first statement of the loop method |
| `<NAME> left its main event loop.` | DEBUG | after the loop method returns |
| `<NAME> module stopping.` | DEBUG | first statement of `stop()` |
| `<NAME> module stopped.` | INFO | last statement of the module's life |

INFO gets two of them, so the operator sees the system come up and go down and nothing else.

---

## 5. One fact, one INFO line

The module that **owns** a fact logs it at INFO. Every module that merely **receives** the
event afterwards logs one `DEBUG` line instead, so a message's hops through the system are
still traceable at DEBUG without the operator's panel saying the same thing three times.

| Fact | INFO owner | DEBUG hop |
|---|---|---|
| application start, operator and host, run log path, shutdown | `launcher/startup.py` | — |
| module started / stopped | each module, about itself | — |
| recipe loaded, sequences available | `core/core.py` | `sequencer`, `hmi_client`, `gui`, `cli` |
| sequence started / finished, each step started / finished | `step/step.py` — the execution layer the Sequencer drives | `core`, `hmi_client`, `gui`, `cli` |
| the run summary, the unit under test, the operator's stop | `sequencer/sequencer.py` | `core`, `hmi_client`, `gui`, `cli` |
| operator prompted, operator answered | the `User*` step types | `core`, `hmi_client`, `gui` |
| run folder, report generated | `report/report.py` | `core`, `hmi_client`, `gui`, `cli` |
| operator housekeeping (Remove Cache, clearing recents, a settings write) | `gui`, `utilities`, `config_handler` | — |
| status-bar text (`StatusUpdate`) | nobody — it is a UI channel | `hmi_client` only |
| a module lost / responding again | `core/core.py` | `core` (the raw liveness detail) |

This is safe because **the GUI panel reads the log file, not the GUI process's own records**
(`log_tail.py` explains why). A frontend that stops logging an event at INFO does not stop the
operator from seeing it — CORE or the Sequencer already wrote it to the file.

---

## 6. The run's story

What an ordinary run looks like at INFO. This is the target; a line that is not in this shape
is either a bug or a new event that belongs in this table.

```
PyPTS 0.2.2 started in GUI mode.
Started by dzbanan on PCBE12345.
Run log: C:\Users\...\logs\pypts_20260902_141201.log
CORE module started.
GUI module started.
Recipe 'thermal_cycle.yml' loaded: "Thermal cycle" v1.2, 3 sequences.
Sequences available: 'warmup', 'soak', 'teardown'.
Results will be written to: C:\...\reports\20260902_141233_warmup
Sequence 'warmup' started: 12 steps.
Step 1/12 'power_on' started.
Step 1/12 'power_on' PASS (0.8 s).
Step 3/12 'confirm_led' started.
Waiting for the operator: 'Is the status LED lit?'
The operator answered: 'Yes'.
Step 3/12 'confirm_led' PASS (6.4 s).
Step 4/12 'read_voltage' FAIL (1.1 s).
Step 5/12 'calibrate' SKIP - marked to skip in the recipe.
Sequence 'warmup' finished: FAIL - 10 passed, 1 failed, 1 skipped, 42.3 s.
Run summary: FAIL.
Run summary: 10 passed, 1 failed, 1 skipped of 12 steps in 42.3 s.
Run summary: recipe 'thermal_cycle.yml', sequence 'warmup'.
Report generated: C:\...\20260902_141233_warmup\report.html
CORE module stopped.
```

Notes on that shape:

- **Every step gets a `started` line and a result line.** A step that takes thirty seconds
  must not leave the panel silent, and the operator counts progress off `n/total`.
- **Durations** come from `StepOutcome.duration_s`, which `step.py` already measures. The
  sequence duration is wall clock, measured in the Sequencer.
- **The run summary is three separate records**, not one multi-line record. Each then carries
  its own timestamp, and neither `log_tail` nor the Debug Monitor has to treat the second and
  third lines as traceback continuations.
- **Paths at INFO are only the ones the operator needs**: the run log, the run folder, the
  report. Config directories, cache directories and module search paths are DEBUG.

### 6.1 The reason on a FAIL line

There is none yet, and the line does not invent one. `StepResult` carries `error_info`, but
that is only set when a step *raises* — so it appears on an `ERROR` verdict, not on a `FAIL`.
Where it is present it is appended (`FAIL (1.1 s) - <error_info>`); where it is not, the line
stops after the duration.

A proper operator-facing `reason` on `StepResult`, filled in by whatever judged the step, is
the fix. It is a TODO in the roadmap, not part of this convention.

---

## 7. Errors

`utilities/error_handling.py` writes **two** records for one failure:

```
ERROR  Step 'read_voltage' could not run: [WinError 2] The system cannot find the file specified.
DEBUG  Traceback for the failure in 'PythonModuleStep.execute':
       Traceback (most recent call last):
         ...
```

The ERROR line is a generic operator-facing frame — *what was being done* — with `str(exc)`
appended. The technician always learns **what** failed, even when **why** stays technical.
There is deliberately no table mapping exception types to friendly sentences: it would have to
be maintained forever and would still miss the case in front of you.

The traceback never appears above DEBUG. A Python traceback in the operator's panel tells them
nothing and hides the line that did.

The §1.11 split still holds and is unchanged by any of this: `@catch_and_report_errors()`
reports and continues, `@report_and_reraise()` reports and re-raises, `report_error()` and
`report_problem()` are for a failure the method recognised.

### 7.1 Liveness

The whole heartbeat vocabulary is **DEBUG** — the word "heartbeat" never appears at INFO or
above. It is an internal health mechanism and the operator cannot act on it.

The single exception is a module that is actually lost, because otherwise the application goes
quiet with nothing in the panel to explain it:

```
WARNING  The GUI has stopped responding.
INFO     The GUI is responding again.
```

Plain language, no mechanism, no numbers. The source, the age of the last beat and the timeout
value go on the DEBUG line beside it.

---

## 8. DEBUG — heavy near-tracing

DEBUG is meant to be nearly a trace of execution: arguments and return values of every
non-trivial function, per-iteration lines in loops that mean something, every branch decision
together with the value that decided it, every state transition, every caught exception with
its traceback, and the receiver hop lines of §5.

**Except on hot paths, which are excluded.** These are the ones that run on a timer or once per
poll iteration:

- a module's event-loop poll when it found nothing,
- the GUI's 200 ms log-tail timer,
- Qt paint and repaint,
- per-beat heartbeat emission.

The log-tail exclusion is not style, it is a feedback loop: that timer reads the very file the
process is writing to. Everything those paths actually *decide* is still logged; only the empty
ticks are not.

**The cost is real.** A normal DEBUG run already produces a six-figure line count, because
`QueueWrapper` traces every message twice — once sent, once received (roadmap §1.2), and
`config.ini` ships DEBUG for the duration of the refactor (§1.6). Heavy tracing multiplies
that, and the Debug Monitor has to parse all of it. That is the accepted price of being able to
reconstruct a run from its log.

---

## 9. Where this is enforced

Nothing checks the wording automatically. `ruff`'s `G004` catches an f-string in a log call and
that is the only mechanical guard there is. The rest is this file, and reading it before adding
a log line.

Tests that assert on log text (`test_config_handler.py` does, in about fifteen places) pin the
wording of the lines they cover. Changing one of those lines means changing its test in the
same commit — which is the intended friction.
