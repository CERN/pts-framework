.. _gui_event_handling:

#################################
GUI Event Handling and Displays
#################################

This document describes how events from the recipe execution engine are processed 
and displayed in the user interface, focusing on the decoupling achieved through 
the ViewModel pattern for live updates.

RecipeEventProxy: The Bridge
=============================

The `RecipeEventProxy` class (defined in `pypts.event_proxy`) acts as a crucial 
bridge between the recipe execution thread and the main GUI thread.

1.  It runs in a separate `QThread`.
2.  It listens to a `SimpleQueue` (`event_queue`) where the `recipe.Runtime` 
    puts events (like `pre_run_step`, `post_run_step`, `post_run_recipe`, etc.) 
    along with their associated data.
3.  When an event is received, the proxy determines the appropriate action:
    *   For most events, it dynamically finds a corresponding Qt signal 
        (e.g., `pre_run_recipe_signal`) and emits it with the original data.
    *   For specific events (currently `post_run_step`), it transforms the 
        incoming data (e.g., a `recipe.StepResult` object) into a simpler 
        **ViewModel** dictionary before emitting a dedicated signal 
        (e.g., `post_run_step_signal`).
4.  These Qt signals are connected to slots in the `MainWindow` (`gui.py`) in 
    the main GUI thread (`__main__.py`), ensuring thread-safe updates.

GUI Result Displays
===================

The `MainWindow` features two distinct widgets on the left side for displaying 
recipe progress and results:

1. Live Step Status (`self.step_list`)
--------------------------------------

*   **Widget Type:** `QTableWidget`
*   **Purpose:** Provides immediate, live feedback on the status of each step 
    as the recipe progresses.
*   **Initialization:** When a sequence starts (`pre_run_sequence` event), the 
    `MainWindow.update_sequence` slot populates this table with the names 
    of the steps in that sequence. Crucially, it also stores the unique 
    `step.id` (UUID) associated with each step name using `Qt.ItemDataRole.UserRole`.
*   **Update Mechanism (ViewModel Pattern):**
    1.  When a step finishes, the `recipe.Runtime` puts a `post_run_step` event 
        onto the `event_queue` containing the `recipe.StepResult` object.
    2.  `RecipeEventProxy` receives this event.
    3.  It extracts the necessary information from the `StepResult` (UUID, result 
        type) and creates a simple **ViewModel dictionary**:
        
        .. code-block:: python

           step_status_view_model = {
               "step_uuid": step_result.uuid, 
               "status_text": str(result_type), # e.g., "PASS", "FAIL"
               "status_color": background_color # e.g., "green", "red"
           }

    4.  `RecipeEventProxy` emits the `post_run_step_signal` with this 
        *dictionary* as the payload.
    5.  The `MainWindow.update_step_result` slot receives this dictionary.
    6.  The slot uses the `step_uuid` from the dictionary to find the 
        corresponding row in the `QTableWidget` (by checking the stored `UserRole` 
        data).
    7.  It then updates the status cell in that row using the `status_text` and 
        `status_color` from the dictionary.
*   **Decoupling:** Because `update_step_result` receives a simple dictionary, 
    `MainWindow` does **not** need to know about the internal structure of 
    `recipe.StepResult` or `recipe.ResultType` for these live updates.

2. Final Hierarchical Results (`self.result_list`)
--------------------------------------------------

*   **Widget Type:** `QTreeView`
*   **Purpose:** Displays the complete, detailed, and potentially nested results 
    of the entire recipe *after* it has finished execution.
*   **Initialization:** This view is populated only once when the recipe finishes.
*   **Update Mechanism (Direct Data Binding):**
    1.  When the recipe finishes, `recipe.Runtime` puts a `post_run_recipe` 
        event onto the `event_queue` containing the final `List[recipe.StepResult]`.
    2.  `RecipeEventProxy` receives this event.
    3.  It emits the `post_run_recipe_signal` directly with the *original* 
        `List[recipe.StepResult]` as the payload. **(Note: No ViewModel transformation 
        is currently applied here).**
    4.  The `MainWindow.show_results` slot receives this raw list.
    5.  It instantiates `StepResultModel`, passing the raw list to its constructor.
    6.  `StepResultModel` (which **is** coupled to `recipe.StepResult`) 
        interprets the list, including `subresults` and parent relationships, 
        to build the hierarchical data structure required by the `QTreeView`.
*   **Coupling:** This display mechanism is **still coupled** to the `recipe.StepResult` 
    structure via the `StepResultModel`. Refactoring `StepResultModel` to use a 
    hierarchical ViewModel would be necessary to fully decouple this part of the GUI.

Summary
=======

*   **`step_list` (Top Table):** Live, step-by-step status updates. Uses a **ViewModel** dictionary. Decoupled from `recipe.StepResult`.
*   **`result_list` (Bottom Tree):** Final, hierarchical results display. Uses **raw `recipe.StepResult` objects** via `StepResultModel`. Currently coupled. 