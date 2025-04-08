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

       It transforms data into ViewModels for specific signals (like 
       `post_run_step_signal`) to decouple the GUI from the core recipe logic,
       while passing raw data for others.
    """
    # --- Raw Signals (Data directly from recipe/pts) ---
    pre_run_recipe_signal = pyqtSignal(str, str)
    """Emitted before the recipe starts. Args: recipe_name (str), recipe_description (str)"""
    post_run_recipe_signal = pyqtSignal(list)
    """Emitted after the recipe finishes. Args: results (List[recipe.StepResult])"""
    pre_run_sequence_signal = pyqtSignal(recipe.Sequence)
    """Emitted before a sequence starts. Args: sequence (recipe.Sequence)"""
    user_interact_signal = pyqtSignal(SimpleQueue, str, str, list)
    """Emitted when user interaction is required. Args: response_q, message, image_path, options"""
    get_serial_number_signal = pyqtSignal(SimpleQueue)
    """Emitted when the serial number needs to be obtained. Args: response_q"""

    # --- ViewModel Signals ---
    post_run_step_signal = pyqtSignal(dict)
    """Emitted after a step finishes. Args: step_status_vm (dict) - A ViewModel 
       containing keys like 'step_uuid', 'status_text', 'status_color'.
    """

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
                if event_name == "post_run_step":
                    step_result: recipe.StepResult = event_data[0] # event_data is a tuple
                    
                    # Determine color based on result type
                    result_type = step_result.get_result()
                    match result_type:
                        case recipe.ResultType.PASS:
                            background_color = "green"
                        case recipe.ResultType.FAIL:
                            background_color = "red"
                        case recipe.ResultType.DONE:
                            background_color = "cyan"
                        case recipe.ResultType.SKIP:
                            background_color = "yellow"
                        case recipe.ResultType.ERROR:
                            background_color = "red" # Or maybe orange/purple?
                        case _: # Should not happen
                            background_color = "white"
                            
                    # Create the ViewModel dictionary
                    step_status_view_model = {
                        "step_uuid": step_result.uuid,
                        "status_text": str(result_type),
                        "status_color": background_color
                    }
                    
                    # Emit the specific signal with the ViewModel
                    self.post_run_step_signal.emit(step_status_view_model)

                # --- Direct Signal Emission for other events ---
                else:
                    with suppress(AttributeError):
                        # Dynamically find the corresponding signal and emit
                        signal_name = event_name + "_signal"
                        signal = getattr(self, signal_name)
                        signal.emit(*event_data)
                    # else: # Optional: Log if no matching signal found
                    #    logger.warning(f"No signal found for event: {event_name}")

            except Exception as e:
                logger.error(f"Error in RecipeEventProxy loop: {e}", exc_info=True)
                # Depending on desired behavior, you might want to break or continue
                # For robustness, we'll continue here