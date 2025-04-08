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
       to Qt signals for the GUI thread, transforming data into ViewModels 
       where appropriate to decouple the GUI from the core recipe logic.
    """
    # --- Raw Signals (Data directly from recipe/pts) ---
    pre_run_recipe_signal = pyqtSignal(str, str)
    post_run_recipe_signal = pyqtSignal(list) # TODO: Consider transforming to ViewModel
    pre_run_sequence_signal = pyqtSignal(recipe.Sequence) # TODO: Consider transforming to ViewModel
    user_interact_signal = pyqtSignal(SimpleQueue, str, str, list)
    get_serial_number_signal = pyqtSignal(SimpleQueue)

    # --- ViewModel Signals ---
    post_run_step_signal = pyqtSignal(dict) # Emits Step Status ViewModel

    def __init__(self, event_q: SimpleQueue):
        super().__init__()
        self.event_q = event_q

    def run(self):
        """Continuously fetches events from the queue and emits corresponding signals.
           Transforms data for specific events (like post_run_step) into ViewModels.
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