<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# hmi — the operator frontend

Two concrete frontends (GUI and CLI) share one protocol base class.

## Files

| File | Owns |
|------|------|
| `hmi_client.py` | `HmiClient` — the protocol base class shared by GUI and CLI |
| `cli/cli.py` | `Cli` — text-based frontend, runs in the launcher process |
| `gui/` | PySide6 GUI — runs in its own process; see `gui/gui.md` |

A third subclass lives outside this folder: `pypts.api.embedding.ApiClient`, the frontend with
no presentation that `pypts.api.Pts` drives from code (`api/api.md`).

## `HmiClient` (the protocol half)

Owns:
- **Polling** — a background thread calls `poll_core()` on a tick, reads messages from
  `from_core`, dispatches to `show_*` hooks.
- **Sending** — `send(message)` wraps `self.core.send(message)`. All outbound messages
  go here.
- **Handshake** — `wait_until_stopped(grace_s)` spins until `self.running` is `False`
  (set by `stop()` when `StopHmi` is handled) or the grace period expires.
- **Default hooks** — every `show_*` method has a default that logs. A frontend that
  has not yet implemented a hook cannot crash when a new message arrives.

Subclass contract:
- Override `show_*` hooks for messages you can render.
- Never call `init_logging()` — the root logger belongs to the parent process (CLI) or
  its own process (GUI).

## CLI (`cli/cli.py`)

Minimal readline loop. Sends `LoadRecipe`, `StartSequence`, `ShutdownRequested` in
response to typed commands. Shows run events as plain log lines. No threads of its own
beyond the background poll thread inherited from `HmiClient`.

## GUI (`hmi/gui/`)

PySide6 application. Full context in `hmi/gui/gui.md`. Key points:

- Runs in a dedicated process (spawned by the launcher).
- Reads `from_core` on the background poll thread; updates UI via Qt signals to the main
  thread.
- All CORE communication uses typed message objects — the GUI never imports `recipe` or
  `step` modules.
- The pickle-safe boundary means no live queues, no Qt objects in messages.

## Key messages (HMI → CORE)

`LoadRecipe`, `StartSequence`, `ShutdownRequested`, `UserPromptResponse`, `UserTextResponse`,
`UserPathResponse` (sent by `answer_user_path()`), `HmiStopped`, `SetConfigParameter` (sent by `set_config_parameter()`; only the GUI's
Settings dialog calls it — the CLI has no command for it).

## Key messages (CORE → HMI)

`RecipeLoaded`, `RunStarted`, `SequenceStarted`, `StepStarted`, `StepFinished`,
`SequenceFinished`, `RunFinished`, `ReportReady`, `UserPromptRequest`, `UserTextRequest`,
`UserPathRequest` (hook `ask_user_path()`; the default declines with a WARNING, like
`ask_user_text()`), `ModuleErrorReported`, `StatusChanged`, `StopHmi`, `ConfigParameterResult` (hook
`show_config_parameter_result()`; the default logs at DEBUG).

Full catalogue: `messages/messages.md`.
