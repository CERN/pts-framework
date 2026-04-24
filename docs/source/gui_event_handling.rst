.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _gui_event_handling:

#################################
GUI Event Handling and Displays
#################################

This document describes how events from the recipe execution engine are processed 
and displayed in the user interface, focusing on the decoupling achieved through 
the consistent use of the ViewModel pattern via dictionary-based signals.

RecipeEventProxy: The Bridge
=============================

The `RecipeEventProxy` class (defined in `pypts.event_proxy`) acts as a crucial 
bridge between the recipe execution thread and the main GUI thread.

1.  It runs in a separate `QThread`.
2.  It listens to a `SimpleQueue` (`event_queue`) where the `recipe.Runtime` 
    puts events (like `pre_run_step`, `post_run_step`, `pre_run_recipe`, `post_run_recipe`, etc.) 
    along with their associated data.
3.  When an event is received, the proxy transforms the incoming data
    (e.g., a `recipe.StepResult` object, a `recipe.Step` object, strings)
    into a simpler **ViewModel** dictionary containing only the data relevant
    for the GUI.
4.  It dynamically finds the corresponding Qt signal (e.g., `pre_run_step_signal`,
    `post_run_step_signal`) and emits it, passing the **ViewModel dictionary**
    as the single payload.
5.  These Qt signals (all defined as `Signal(dict)`) are connected to slots
    in the `MainWindow` (`gui.py`) in the main GUI thread (`__main__.py`),
    ensuring thread-safe updates.

GUI Result Displays
===================

The runtime ``MainWindow`` is now a panelized window composed from reusable Qt
widgets. Event handling described below applies primarily to the left-side
execution/result panels and the right-side interaction panel. For the structural
layout of the window, see :doc:`gui_architecture`.

The `MainWindow` features two distinct widgets on the left side for displaying
recipe progress and results:

1. Live Step Status (`self.step_list`)
--------------------------------------

*   **Widget Type:** ``StepTable`` (internally based on ``QTableWidget``)
*   **Purpose:** Provides immediate, live feedback on the status of each step 
    as the recipe progresses.
*   **Initialization:** When a sequence starts (`pre_run_sequence` event, emitting a
    dictionary containing the `recipe.Sequence` object), the `MainWindow.update_sequence`
    slot populates this table with the names of the steps in that sequence.
    Crucially, it also stores the unique `step.id` (UUID) associated with each
    step name using `Qt.ItemDataRole.UserRole`.
*   **Update Mechanism (ViewModel Pattern):**
    1.  When a step is about to run, `recipe.Runtime` puts a `pre_run_step` event
        onto the `event_queue` containing the `recipe.Step` object.
    2.  `RecipeEventProxy` receives this, creates a ViewModel `{'step_uuid': ..., 'step_name': ...}`,
        and emits `pre_run_step_signal`.
    3.  The `MainWindow.update_running_step` slot receives the dictionary, finds the
        row using the UUID, and updates the status cell text to "Running..." and makes it bold.
    4.  When a step finishes, the `recipe.Runtime` puts a `post_run_step` event
        onto the `event_queue` containing the `recipe.StepResult` object.
    5.  `RecipeEventProxy` receives this event.
    6.  It extracts the necessary information from the `StepResult` (the *original*
        `step.id`, not the `step_result.uuid`, and result type) and creates a
        simple **ViewModel dictionary**:

        .. code-block:: python

           step_status_view_model = {
               "step_uuid": step_result.step.id, # Use original Step ID
               "status_text": str(result_type), # e.g., "PASS", "FAIL"
               "status_color": background_color # e.g., "green", "red"
           }

    7.  `RecipeEventProxy` emits the `post_run_step_signal` with this
        *dictionary* as the payload.
    8.  The `MainWindow.update_step_result` slot receives this dictionary.
    9.  The slot uses the `step_uuid` from the dictionary to find the
        corresponding row in the `QTableWidget` (by checking the stored `UserRole`
        data).
    10. It then updates the status cell in that row using the `status_text` and
        `status_color` from the dictionary, resetting the font from bold.

    **Note:** To prevent unnecessary warnings in the GUI log, the `RecipeEventProxy` explicitly filters out
    `pre_run_step` and `post_run_step` events if they originate from a `recipe.SequenceStep`.
    This is because the wrapper `SequenceStep` used to run the main sequence isn't displayed
    in the live table, and its events would otherwise cause "Could not find step with UUID" messages.

*   **Decoupling:** Because the `MainWindow` slots (`update_sequence`, `update_running_step`, `update_step_result`)
    only receive simple dictionaries, `MainWindow` does **not** need to know about
    the internal structure of `recipe.Sequence`, `recipe.Step`, `recipe.StepResult`,
    or `recipe.ResultType` for these live updates.

2. Final Hierarchical Results (`self.result_list`)
--------------------------------------------------

*   **Widget Type:** ``ResultsPanel`` containing a ``QTreeView``
*   **Purpose:** Displays the complete, detailed, and potentially nested results 
    of the entire recipe *after* it has finished execution.
*   **Initialization:** This view is populated only once when the recipe finishes.
*   **Update Mechanism (ViewModel Dictionary + Coupled Model):**
    1.  When the recipe finishes, `recipe.Runtime` puts a `post_run_recipe` 
        event onto the `event_queue` containing the final `List[recipe.StepResult]`.
    2.  `RecipeEventProxy` receives this event.
    3.  It creates a ViewModel dictionary `{'results': List[recipe.StepResult]}` and emits
        the `post_run_recipe_signal` with this dictionary as the payload.
    4.  The `MainWindow.show_results` slot receives this dictionary and extracts the raw list.
    5.  It instantiates `StepResultModel`, passing the raw list to its constructor.
    6.  `StepResultModel` (which **is** coupled to `recipe.StepResult`) 
        interprets the list, including `subresults` and parent relationships, 
        to build the hierarchical data structure required by the `QTreeView`.
*   **Coupling:** While the signal/slot communication now uses a dictionary,
    the final display mechanism via `StepResultModel` is **still coupled**
    to the `recipe.StepResult` structure. Refactoring `StepResultModel` to work
    with a pre-processed, purely hierarchical data structure (a ViewModel tailored
    for the tree view) would be necessary to fully decouple this part of the GUI.

Summary
=======

*   All communication from `RecipeEventProxy` to `MainWindow` uses Qt signals
    emitting **ViewModel dictionaries**.
*   This approach ensures a **consistent interface** and **decouples** the GUI
    slots from the specific data structures used in the recipe execution logic.
*   **`step_list` (live step table):** Live updates are fully decoupled.
*   **`result_list` (results tree):** Populated via a dictionary signal, but the
    underlying `StepResultModel` remains coupled to `recipe.StepResult`. 
