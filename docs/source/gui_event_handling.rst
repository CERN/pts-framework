.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

GUI Event Handling
==================

The GUI runs in a separate **HMI process**. It communicates with CORE exclusively
through typed message dataclasses on a ``QueueWrapper`` (the HMI↔CORE link). It never
sees the recipe object, step objects, or any live engine state directly.

Message flow
------------

Operator action (button, menu) → an ``HmiClient`` command method (``load_recipe()``,
``start_sequence()``, ``stop_sequence()``, ``answer_user_prompt()``, ...) → a message on
the link to CORE.

Engine event (step started, run finished) → CORE → the HMI's inbox → ``poll_core()`` →
``handle_core_message()`` → the ``show_*`` / ``ask_*`` hook the GUI overrides.

In the GUI, ``poll_core()`` runs on a ``QTimer`` on the Qt main thread (every 50 ms), so
the hooks update widgets directly - no signal hop, no extra thread. The CLI polls from a
background thread instead, because its main thread blocks on ``input()``. The routing
itself (``hmi/hmi_client.py``) is shared by both frontends and ends in ``unhandled()``, so
a new message cannot be silently dropped. The GUI does not import the ``recipe`` or
``step`` modules.

Key messages the GUI handles
-----------------------------

Inbound (CORE → HMI, the ``CoreToHmi`` union):

- ``RecipeLoaded`` — recipe name and version, main sequence, and a summary of every
  sequence and step (fills the sequence chooser and the step table)
- ``RunStarted`` — recipe name, description and version, pypts version, the names of the
  report metadata globals
- ``RunMetadata`` — current values of those globals (e.g. the serial number)
- ``SequenceStarted`` / ``SequenceFinished`` — which sequence is running, and its result
- ``StepStarted`` / ``StepFinished`` — the step's id and name; ``StepFinished`` carries its
  ``StepOutcome`` (result and error text)
- ``RunFinished`` — overall result and every step outcome
- ``ReportReady`` — ``report.html`` path and the run's report folder
- ``UserPromptRequest`` — message, button options, optional image (``UserInteraction``)
- ``UserTextRequest`` — message, optional image (``UserWrite``)
- ``UserPathRequest`` — message, ``select`` (file or folder), optional image (``UserLoading``)
- ``ModuleErrorReported`` — an error to show the operator
- ``StatusChanged`` — text for the status bar
- ``ConfigParameterResult`` — CORE's answer to a settings change
- ``StopHmi`` — shut down the frontend
- ``Heartbeat`` — CORE is alive

Outbound (HMI → CORE, the ``HmiToCore`` union):

- ``LoadRecipe`` — the recipe file the operator opened
- ``StartSequence`` — the sequence the operator started
- ``StopSequence`` — the operator pressed Stop (aborts the run; the application stays up)
- ``UserPromptResponse`` / ``UserTextResponse`` / ``UserPathResponse`` — the operator's
  answer, or ``None`` when they cancelled
- ``SetConfigParameter`` — a value changed in the settings dialog
- ``ShutdownRequested`` — the operator closed the window
- ``HmiStopped`` — the frontend has shut down cleanly
- ``Heartbeat`` / ``ModuleError`` — liveness, and failures the GUI reports about itself

For the full message list see ``src/pypts/messages/messages.md``; for the GUI itself,
``src/pypts/hmi/gui/gui.md``.

Difference from old architecture
---------------------------------

The old architecture used ``RecipeEventProxy`` (a ``QThread``) listening on a
``SimpleQueue`` and emitting Qt signals with ViewModel dictionaries, and commands went
down as bare tuples such as ``("LOAD", path)``. The new architecture replaces both with
typed messages: the GUI polls its inbox on a Qt timer and hands each message to a
presentation hook. The GUI no longer imports ``recipe.StepResult`` or
``recipe.ResultType``.
