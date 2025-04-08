# src/pypts/event_proxy.py
import logging
from PyQt6.QtCore import QObject, pyqtSignal
from queue import SimpleQueue
from contextlib import suppress
from pypts import recipe
import uuid

logger = logging.getLogger(__name__)

class RecipeEventProxy(QObject):
    """Proxies events from the recipe execution thread's event queue 
       to Qt signals for the GUI thread. 

       It transforms data into ViewModels (dictionaries) for all signals
       to decouple the GUI from the core recipe logic.
    """
    # --- Signals (All emit dictionaries) ---
    pre_run_recipe_signal = pyqtSignal(dict)
    """Emitted before the recipe starts. Args: {'recipe_name': str, 'recipe_description': str}"""
    post_run_recipe_signal = pyqtSignal(dict)
    """Emitted after the recipe finishes. Args: {'results': List[recipe.StepResult]}"""
    pre_run_sequence_signal = pyqtSignal(dict)
    """Emitted before a sequence starts. Args: {'sequence': recipe.Sequence}"""
    user_interact_signal = pyqtSignal(dict)
    """Emitted when user interaction is required. Args: {'response_q': SimpleQueue, 'message': str, 'image_path': str, 'options': list}"""
    get_serial_number_signal = pyqtSignal(dict)
    """Emitted when the serial number needs to be obtained. Args: {'response_q': SimpleQueue}"""
    post_run_step_signal = pyqtSignal(dict)
    """Emitted after a step finishes. Args: {'step_uuid': uuid, 'status_text': str, 'status_color': str}"""
    pre_run_step_signal = pyqtSignal(dict)
    """Emitted before a step starts. Args: {'step_uuid': uuid, 'step_name': str}"""
    post_load_recipe_signal = pyqtSignal(dict)
    """Emitted after a recipe is loaded. Args: {'recipe_name': str, 'recipe_version': str}"""
    post_run_sequence_signal = pyqtSignal(dict)
    """Emitted after a sequence finishes. Args: {'sequence_name': str, 'sequence_result': str}"""

    def __init__(self, event_q: SimpleQueue):
        """Initializes the proxy with the event queue to listen to."""
        super().__init__()
        self.event_q = event_q

    def run(self):
        """Continuously fetches events from the queue, transforms data for 
           `post_run_step` into a ViewModel, and emits the corresponding Qt signal.
        """
        logger.info("RecipeEventProxy started.")
        while True:
            try:
                event_name, event_data = self.event_q.get()
                logger.debug(f"Event Proxy received: {event_name}")

                # --- Data Transformation / ViewModel Creation ---
                event_dict = {}
                if event_name == "post_run_step":
                    step_result: recipe.StepResult = event_data[0] # event_data is a tuple
                    result_type = step_result.get_result()
                    match result_type:
                        case recipe.ResultType.PASS: background_color = "green"
                        case recipe.ResultType.FAIL: background_color = "red"
                        case recipe.ResultType.DONE: background_color = "cyan"
                        case recipe.ResultType.SKIP: background_color = "yellow"
                        case recipe.ResultType.ERROR: background_color = "red"
                        case _: background_color = "white"
                            
                    event_dict = {
                        "step_uuid": step_result.uuid,
                        "status_text": str(result_type),
                        "status_color": background_color
                    }
                elif event_name == "pre_run_recipe":
                    event_dict = {
                        "recipe_name": event_data[0], 
                        "recipe_description": event_data[1]
                    }
                elif event_name == "post_run_recipe":
                    event_dict = {"results": event_data[0]}
                elif event_name == "pre_run_sequence":
                    event_dict = {"sequence": event_data[0]}
                elif event_name == "user_interact":
                    event_dict = {
                        "response_q": event_data[0], 
                        "message": event_data[1], 
                        "image_path": event_data[2], 
                        "options": event_data[3]
                    }
                elif event_name == "get_serial_number":
                    event_dict = {"response_q": event_data[0]}
                elif event_name == "pre_run_step":
                    step_object: recipe.Step = event_data[0] # event_data is a tuple (step,)
                    event_dict = {
                        "step_uuid": step_object.id,
                        "step_name": step_object.name
                        # Add other step attributes if needed later
                    }
                elif event_name == "post_load_recipe":
                    recipe_object: recipe.Recipe = event_data[0]
                    event_dict = {
                        "recipe_name": recipe_object.name,
                        "recipe_version": recipe_object.version
                    }
                elif event_name == "post_run_sequence":
                    sequence_object: recipe.Sequence = event_data[0]
                    sequence_result: recipe.ResultType = event_data[1]
                    event_dict = {
                        "sequence_name": sequence_object.name,
                        "sequence_result": str(sequence_result) # Convert enum to string
                    }
                # Add other event types and their dictionary mappings here if needed

                # --- Signal Emission ---
                if event_dict: # Check if a dictionary was created for the event
                    with suppress(AttributeError):
                        signal_name = event_name + "_signal"
                        signal = getattr(self, signal_name)
                        signal.emit(event_dict)
                    # else: # Optional: Log if no matching signal found (shouldn't happen if event_dict is populated)
                    #    logger.warning(f"No signal found for event: {event_name}")
                else:
                    logger.warning(f"No dictionary created for event: {event_name}")

            except Exception as e:
                logger.error(f"Error in RecipeEventProxy loop: {e}", exc_info=True)
                # Depending on desired behavior, you might want to break or continue
                # For robustness, we'll continue here