from abc import ABC, abstractmethod

# those abstract methods have to be implemented in QueueHMI and
# can be used then within the modules that connect to the HMIInterface
class HMIInterface(ABC):
    @abstractmethod
    def send_command_to_core(self, msg: str): ...
    @abstractmethod
    def receive_command_from_core(self) -> str: ...

    # # --- Signals (All emit dictionaries) ---
    # pre_run_recipe_signal = Signal(dict)
    # """Emitted before the recipe starts. Args: {'recipe_name': str, 'recipe_description': str}"""
    # post_run_recipe_signal = Signal(dict)
    # """Emitted after the recipe finishes. Args: {'results': List[recipe.StepResult]}"""
    # pre_run_sequence_signal = Signal(dict)
    # """Emitted before a sequence starts. Args: {'sequence': recipe.Sequence}"""
    # user_interact_signal = Signal(dict)
    # """Emitted when user interaction is required. Args: {'response_q': SimpleQueue, 'message': str, 'image_path': str, 'options': list}"""
    # get_serial_number_signal = Signal(dict)
    # """Emitted when the serial number needs to be obtained. Args: {'response_q': SimpleQueue}"""
    # post_run_step_signal = Signal(dict)
    # """Emitted after a step finishes. Args: {'step_uuid': uuid, 'status_text': str, 'status_color': str}"""
    # pre_run_step_signal = Signal(dict)
    # """Emitted before a step starts. Args: {'step_uuid': uuid, 'step_name': str}"""
    # post_load_recipe_signal = Signal(dict)
    # """Emitted after a recipe is loaded. Args: {'recipe_name': str, 'recipe_version': str}"""
    # post_run_sequence_signal = Signal(dict)
    # """Emitted after a sequence finishes. Args: {'sequence_name': str, 'sequence_result': str}"""


class QueueHMI(HMIInterface):
    def __init__(self, hmi_to_core_queue, core_to_hmi_queue):
        self.hmi_to_core_queue = hmi_to_core_queue
        self.core_to_hmi_queue = core_to_hmi_queue

    def send_command_to_core(self, msg):
        self.hmi_to_core_queue.put(msg)

    def send_command_to_hmi(self, msg):
        self.core_to_hmi_queue.put(msg)

    def receive_command_from_core(self):
        return self.core_to_hmi_queue.get()

    def receive_command_from_hmi(self, timeout: float = 1.0):
        return self.hmi_to_core_queue.get(timeout=timeout)


