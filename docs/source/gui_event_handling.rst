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

Operator action (button, menu) → ``HmiClient.send()`` → CORE inbox.

Engine event (step started, run finished) → CORE → ``HmiClient`` inbox → polled by a
background thread in the GUI → Qt signal → main thread slot.

The Qt signal carries a typed message object (e.g. ``StepStarted``, ``StepFinished``,
``RunFinished``). The GUI slot reads the fields it needs; it does not import ``recipe``
or ``step`` modules.

Key messages the GUI handles
-----------------------------

Inbound (CORE → HMI):

- ``RunStarted`` — recipe name, description, sequence list
- ``SequenceStarted`` / ``SequenceFinished`` — which sequence is running
- ``StepStarted`` / ``StepFinished`` — step name, result, outcome
- ``RunFinished`` — overall result
- ``ReportReady`` — path to ``report.html``
- ``UserInteractionRequest`` — message, image path, button options
- ``UserWriteRequest`` — prompt text
- ``ModuleErrorReported`` — error text for the log panel (WARNING and above)
- ``StopHmi`` — shut down the frontend

Outbound (HMI → CORE):

- ``ShutdownRequested`` — operator clicked Stop / closed window
- ``RunSequence`` — operator selected a sequence and clicked Run
- ``UseRecipe`` — recipe loaded from disk
- ``UserInteractionResponse`` / ``UserWriteResponse`` — operator replied to a prompt
- ``HmiStopped`` — frontend has shut down cleanly

For the full message list see ``src/pypts/messages/messages.md``.

Difference from old architecture
---------------------------------

The old architecture used ``RecipeEventProxy`` (a ``QThread``) listening on a
``SimpleQueue`` and emitting Qt signals with ViewModel dictionaries. The new
architecture replaces this with a polling background thread in ``HmiClient`` that
reads typed messages from the ``QueueWrapper`` and emits Qt signals directly. The
GUI no longer imports ``recipe.StepResult`` or ``recipe.ResultType``.
