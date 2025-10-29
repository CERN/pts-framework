# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later


from pypts.YamVIEW.verify_recipe import validate_recipe_filepath
import copy
import yaml
import logging
from typing import List, Dict, Self
from pathlib import Path
from importlib import import_module
import traceback
import queue
import time
from enum import Enum, IntEnum
import json
import uuid
import os, atexit
from pypts.event_proxy import RecipeEventProxy
from PySide6.QtCore import QTimer, QThread, QObject, Signal, Slot
from pypts.Thread_context import RuntimeContext
from threading import Timer, Event
from pypts.utils import WAIT_FOR_TERMINATION
# from pts import Runtime

logger = logging.getLogger(__name__)


class ResultType(IntEnum):
    SKIP  = 0
    DONE  = 1
    PASS  = 2
    FAIL  = 3
    ERROR = 4
    STOP = 5

    def __str__(self):
        return str(self.name)
    
class StepResult():
    def __init__(self, step=None, parent=None):
        self.step: Step = step
        self.result: ResultType = None
        self.inputs: dict = {}
        self.outputs: dict = {}
        self.error_info: str = ""
        self.subresults: List[StepResult] = []
        self.uuid: uuid.UUID = uuid.uuid4()
        self.parent: uuid.UUID = parent
        # Metadata added for reporting
        self.recipe_name: str = None
        self.recipe_file_name: str = None
        self.serial_number: str = None
        self.sequence_name: str = None
        self.pypts_version: str = "unknown" # Added pypts version
    
    def __str__(self):
        return str(self.result)
    
    def set_error(self, error_info=None, inputs={}):
        self.result = ResultType.ERROR
        self.error_info = error_info
        self.inputs = inputs

    def set_skip(self):
        self.result = ResultType.SKIP
    
    def set_stop(self,  error_info=None, inputs={}):
        self.result = ResultType.STOP
        self.error_info = error_info
        self.inputs = inputs

    def set_result(self, result_type=ResultType.DONE, inputs={}, outputs={}):
        self.result = result_type
        self.inputs = inputs
        self.outputs = outputs

    def append_subresult(self, subresult: Self):
        self.subresults.append(subresult)

    def get_result(self):
        return self.result
    
    def is_type(self, result_type: ResultType):
        return self.result == result_type
    
    @staticmethod
    def get_result_by_uuid(step_results: List[Self], uuid: uuid.UUID) -> Self:
        for result in step_results:
            if result.uuid == uuid:
                return result
            else:
                found_result = StepResult.get_result_by_uuid(result.subresults, uuid)
                if found_result is not None:
                    return found_result
        return None

    @staticmethod
    def evaluate_multiple_step_results(step_results: List[Self]) -> ResultType:
        highest_result = ResultType.SKIP
        results = [result.get_result() for result in step_results]

        for result in results:
            if result> highest_result:
                highest_result = result

        return highest_result

    def print_result(self, indent=""):
        print((indent[:-2] + "+-" if indent else "") + f"Step: {self.step.name} - ID: {self.uuid} - Result: {self.result}")
        if self.error_info:
            print(indent + f"Error: {self.error_info}")
        print(indent + f"Inputs: {self.inputs}")
        print(indent + f"Outputs: {self.outputs}")
        if self.subresults:
            print(indent + "Subresults:")
            length = len(self.subresults)
            for i, subresult in enumerate(self.subresults):
                if i == length - 1:
                    subresult.print_result(indent + "  ")
                else:
                    subresult.print_result(indent + "| ")
        # print(indent + "=====================================")

def serialize(obj, _seen=None):
    if _seen is None:
        _seen = set()
    obj_id = id(obj)
    if obj_id in _seen:
        return f"<Circular reference: {type(obj).__name__}>"
    _seen.add(obj_id)

    # Handle Enum
    if isinstance(obj, Enum):
        return obj.name

    # Handle dict
    if isinstance(obj, dict):
        return {serialize(k, _seen): serialize(v, _seen) for k, v in obj.items()}

    # Handle list, tuple, set
    if isinstance(obj, (list, tuple, set)):
        return [serialize(i, _seen) for i in obj]

    # Handle objects with __dict__
    try:
        return {
            k: serialize(v, _seen)
            for k, v in vars(obj).items()
            if not k.startswith("__") and not callable(v)
        }
    except Exception:
        pass

    return str(obj)

class Runtime:
    recipe_thread = None
    recipe_event_proxy = None
    stop_event = Event()
    def __init__(self, event_queue, report_queue):
        """Initializes the Runtime environment for recipe execution.

        Args:
            event_queue: Queue for sending events (e.g., to GUI).
            report_queue: Queue for sending StepResult objects to the report listener.
        """
        self.event_queue = event_queue
        self.report_queue = report_queue
        self.results: List[StepResult] = []
        self.globals = []
        self.sequences = {}
        self.local_stack = []
        
        # Metadata for reporting context
        self.recipe_name: str = None
        self.recipe_file_name: str = None
        self.serial_number: str = None
        self.current_sequence_name: str = None
        self.test_package: str = None
        self.pypts_version: str = "unknown" # Added pypts version
        self.continue_on_error: bool = False # Added continue_on_error setting
    
    @classmethod
    def setup(cls, window, api, app):
        if getattr(cls, "recipe_thread", None) is not None:
            cls._cleanup_thread()

        cls._window = window
        cls._api = api
        cls._app = app
        cls.recipe_thread = QThread()
        cls.recipe_thread.setParent(cls._app)

        cls.recipe_event_proxy = RecipeEventProxy(api.event_queue)
        cls.recipe_event_proxy.moveToThread(cls.recipe_thread)
        cls.recipe_thread.started.connect(cls.recipe_event_proxy.run)

        # Connect signals
        cls.recipe_event_proxy.pre_run_recipe_signal.connect(cls._window.update_recipe_name)
        cls.recipe_event_proxy.post_run_recipe_signal.connect(cls._window.show_results)
        cls.recipe_event_proxy.pre_run_sequence_signal.connect(cls._window.update_sequence)
        cls.recipe_event_proxy.post_run_step_signal.connect(cls._window.update_step_result)
        cls.recipe_event_proxy.pre_run_step_signal.connect(cls._window.update_running_step)
        cls.recipe_event_proxy.user_interact_signal.connect(cls._window.show_message)
        cls.recipe_event_proxy.get_serial_number_signal.connect(cls._window.get_serial_number)
        cls.recipe_event_proxy.post_load_recipe_signal.connect(cls._window.handle_post_load_recipe)
        cls.recipe_event_proxy.post_run_sequence_signal.connect(cls._window.handle_post_run_sequence)
        if not getattr(Runtime, "_cleanup_registered", False):
            atexit.register(Runtime._cleanup_thread)
            app.aboutToQuit.connect(Runtime._cleanup_thread)
            Runtime._cleanup_registered = True

    @classmethod
    def start(cls):
        if cls.recipe_thread is None:
            if not RuntimeContext.is_ready():
                logger.error("RuntimeContext not ready. Can't start.")
                return

            window = RuntimeContext.get_window()
            api = RuntimeContext.get_api()
            app = RuntimeContext.get_app()
            cls.setup(window, api, app)

        if not cls.recipe_thread.isRunning():
            cls.recipe_thread.start()
            logger.info("Started recipe execution thread.")
        else:
            logger.warning("Recipe thread already running.")

    @classmethod
    def stop(cls):
        if cls.recipe_thread and cls.recipe_thread.isRunning():
            logger.info("Stopping Runtime...")

            # Tell worker to stop
            if cls.recipe_event_proxy and hasattr(cls.recipe_event_proxy, "stop"):
                cls.recipe_event_proxy.stop()

            # Quit thread after a delay, giving worker time to exit cleanly
            def quit_and_wait():
                if cls.recipe_thread:
                    cls.recipe_thread.quit()
                    def wait_thread():
                        cls.recipe_thread.wait()
                        logger.info("Runtime thread stopped.")
                        cls._cleanup_thread()
                    Timer(0.1, wait_thread).start()
                else:
                    logger.warning("Attempted to quit recipe thread, but it was already None.")

            Timer(0.2, quit_and_wait).start()
        else:
            logger.warning("Runtime thread not running or already stopped.")

    @classmethod
    def _cleanup_thread(cls):
        if cls.recipe_thread:
            if cls.recipe_thread.isRunning():
                logger.debug("Stopping recipe event processing thread...")
                cls.recipe_thread.quit()
                cls.recipe_thread.wait(5000)
                if cls.recipe_thread.isRunning():
                    logger.warning("Thread did not stop gracefully, terminating...")
                    cls.recipe_thread.terminate()
            cls.recipe_thread = None
        else:
            logger.debug("No recipe_thread to clean up.")

        cls.recipe_event_proxy = None


    def push_locals(self, locals):
        self.local_stack.append(locals)
        logger.debug(f"Pushing locals {locals}")

    def pop_locals(self):
        popped_locals = self.local_stack.pop()
        logger.debug(f"Popping locals: {popped_locals}")
        return popped_locals
    
    def get_local(self, name):
        value = self.local_stack[-1][name]
        logger.debug(f"Getting local {name}: {value}")
        return value
    
    def set_local(self, name, value):
        logger.debug(f"Setting local {name} to {value}")
        self.local_stack[-1][name] = value
    
    def get_global(self, name):
        return self.globals[name]
    
    def get_globals(self):
        return self.globals
    
    def set_global(self, name, value):
        self.globals[name] = value

    def set_globals(self, globals):
        self.globals = globals

    def get_sequence(self, name):
        return self.sequences[name]
    
    def set_sequences(self, sequences):
        self.sequences = sequences

    def append_result(self, parent_step_id: uuid.UUID, result: StepResult):
        logger.debug(f"Appending result to parent '{parent_step_id}'")
        
        if parent_step_id is None:
            self.results.append(result)
        else:
            parent_step_result: StepResult = StepResult.get_result_by_uuid(self.results, parent_step_id)
            if parent_step_result is not None:
                parent_step_result.append_subresult(result)
            else:
                logger.warning(f"Could not find step result with uuid {parent_step_id}.")
    

    def get_results(self):
        return self.results
    
    def send_event(self, event_name:str, *event_data):
        self.event_queue.put((event_name, event_data))
        json_data = json.dumps({event_name: event_data}, default=serialize)

class RuntimeBridge(QObject):
    start_signal = Signal()
    stop_signal = Signal()

    def __init__(self):
        super().__init__()
        self.start_signal.connect(self.start_runtime)
        self.stop_signal.connect(self.stop_runtime)

    @Slot()
    def start_runtime(self):
        Runtime.stop_event.clear()
        Runtime.start()

    @Slot()
    def stop_runtime(self):
        logger.info("Setting stop_event from RuntimeBridge")
        Runtime.stop_event.set()
        #Runtime.stop()

# Global singleton instance
runtime_bridge = RuntimeBridge()

class Recipe:
    """
    Represents and executes a test recipe defined in a multi-document YAML file.

    Loads the recipe structure, manages global variables, sequences, and overall
    execution flow. The detailed structure of the recipe YAML file is described
    in :doc:`yaml_format`.

    Args:
        recipe_file_path (str or Path): Path to the recipe YAML file.
        file_loader (callable, optional): A function that takes a path and returns
            an iterator over loaded YAML documents. Defaults to loading from a
            local YAML file.
        event_sender (callable, optional): A function to send events during recipe
            execution. Takes `runtime`, `event_name`, and `*event_data` as arguments.
            Defaults to using `runtime.send_event`.
    """
    def __init__(self, recipe_file_path, file_loader=None, event_sender=None):
        self.file_loader = file_loader or self._default_file_loader
        self.event_sender = event_sender or self._default_event_sender
        self.__load_recipe(recipe_file_path)
        self.recipe_file_name = Path(recipe_file_path).name # Store filename

    def _default_file_loader(self, path):
        """Default implementation that loads a YAML file"""
        with open(path, 'r') as file:
            # Read the file content into memory first
            file_content = file.read()
        # Then return an iterator over the YAML documents
        return yaml.safe_load_all(file_content)
    
    def _default_event_sender(self, runtime, event_name, *event_data):
        """Default implementation that uses runtime's send_event"""
        runtime.send_event(event_name, *event_data)

    def __load_recipe(self, recipe_file_path):
        """Loads recipe data using the file_loader"""
        logger.info(f"Loading recipe file {recipe_file_path}.")
        self.sequences = {}
        
        try:
            recipe_data = self.file_loader(recipe_file_path)
            logger.debug(f"File loader returned recipe_data type: {type(recipe_data)}")
            
            recipe_main_data = next(recipe_data)
            logger.debug(f"Recipe main data keys: {recipe_main_data.keys() if isinstance(recipe_main_data, dict) else 'Not a dict'}")
            
            # Validate required fields in main data
            required_fields = ["name", "description", "version", "globals"]
            for field in required_fields:
                if field not in recipe_main_data:
                    raise KeyError(f"Missing required field '{field}' in recipe main data")

            #add verification here



            
            # The rest of the documents are all sequences
            sequence_count = 0
            for sequence in recipe_data:
                sequence_count += 1

                logger.debug(f"Processing sequence {sequence_count}: {sequence.get('sequence_name', 'UNNAMED')}")

                if "sequence_name" not in sequence:
                    logger.error(f"Sequence {sequence_count} missing 'sequence_name' field")
                    continue
                try:
                    # todo this is failing
                    self.sequences[sequence["sequence_name"]] = Sequence(sequence_data=sequence)
                except Exception as e:
                    logger.error(f"Failed to create sequence '{sequence.get('sequence_name', 'UNNAMED')}': {e}")
                    raise

            self.name: str = recipe_main_data["name"]
            self.main_sequence: str = recipe_main_data["main_sequence"]
            self.description: str = recipe_main_data["description"]
            self.version: str = recipe_main_data["version"]
            self.globals: dict[str, any] = recipe_main_data["globals"]
            self.test_package: str = recipe_main_data.get("test_package", None)
            if "." in self.test_package:
                logger.error("test_package must not contain '.' in its name. Dont include subdirectories")
                raise
            # self.tags: dict[str, str] = recipe_main_data["tags"]
            logger.info(f"Loaded recipe {self.name} version {self.version}.")
            logger.debug(f"Recipe has {len(self.sequences)} sequences: {list(self.sequences.keys())}")
            
        except Exception as e:
            logger.error(f"Failed to load recipe from {recipe_file_path}: {e}", exc_info=True)
            raise

    def __get_serial_number(self, runtime: Runtime):
        response_q = queue.SimpleQueue()
        logger.info("Asking user for serial number")
        runtime.send_event("get_serial_number", response_q)
        serial_number = response_q.get()
        del(response_q)
        logger.info(f"Serial number: {serial_number}")
        return serial_number

    def run(self, runtime: Runtime, sequence_name: str="Main", serial_number: str=None, get_serial_number_func=None):
        """Executes the main sequence of the recipe.

        Sets up the runtime, determines the serial number, runs the specified sequence,
        sends pre/post recipe events, sends the STOP_LISTENER signal to the report queue,
        and returns the collected results.

        Args:
            runtime (Runtime): The runtime environment.
            sequence_name (str, optional): The name of the sequence to start execution from. Defaults to "Main".
            serial_number (str, optional): An explicit serial number to use. If None, prompts the user.
            get_serial_number_func (callable, optional): A custom function to get the serial number.

        Returns:
            List[StepResult]: A list of the top-level StepResult objects generated during the run.
        """
        try:
            runtime.set_globals(self.globals)
            runtime.set_sequences(self.sequences)
            runtime.recipe_name = self.name             # Set recipe name in runtime
            runtime.recipe_file_name = self.recipe_file_name # Set recipe file name in runtime
            runtime.test_package = self.test_package    # Set test package in runtime
            sequence_name = self.main_sequence

            # Use the event sender instead of direct calls
            self.event_sender(runtime, "pre_run_recipe", self.name, self.description)

            if serial_number is None:
                # Allow passing a different function for getting serial numbers
                get_serial = get_serial_number_func or self.__get_serial_number
                # runtime.set_global("serial_number", get_serial(runtime))
                _serial_number = get_serial(runtime)
                runtime.set_global("serial_number", _serial_number)
                runtime.serial_number = _serial_number # Set serial number in runtime
            else:
                runtime.set_global("serial_number", serial_number)
                runtime.serial_number = serial_number # Set serial number in runtime

            # Create folder structures needed here to store all results
            # starting_sequence: Sequence = runtime.get_sequence(sequence_name)
            # final_result = starting_sequence.run(runtime, {})
            if runtime.stop_event.is_set():
                logger.info(f"Recipe run aborted before executing sequence due to stop_event. {runtime.stop_event}")
                results = []  # Ensure results is defined
                # Emit signal so GUI still updates
                return results
                
            main_step_data = {"steptype": "SequenceStep", "step_name": sequence_name, "sequence": {"type": "internal", "name": sequence_name}, "input_mapping": {}, "output_mapping": {}}
            
            main_step: Step = Step.build_step(main_step_data)
            final_result = main_step.run(runtime, {}, stop_event=runtime.stop_event)

            
            results: List[StepResult] = runtime.get_results()
            runtime.send_event("post_run_recipe", results)
            print("\n==== RESULTS ====")
            print(f"Final result: {final_result}")
            print("-----------------")
            for result in results:
                result.print_result()

            print(runtime.local_stack)
            print(runtime.globals)

            # Signal the report listener to stop
            from pypts.report import STOP_LISTENER
            runtime.report_queue.put(STOP_LISTENER)
            logger.debug("Sent STOP_LISTENER to report queue.")

            return results
        finally:
            #results: List[StepResult] = runtime.get_results()
            runtime.send_event("post_run_recipe", results)
            time.sleep(0.1)
            Runtime.stop()

            return results

    
    # def parse_q_input(self, q_in):
    #     while True:
    #         input_command = q_in.get()
    #         print(f"RECEIVED SIGNAL FROM GUI: {input_command}")
    #         event:threading.Event = self.runtime["events"][input_command]
    #         event.set()
                    



    # @staticmethod
    # def run_threaded(recipe_file, sequence_name="Main"):
    #     q_in = queue.Queue()
    #     event_queue = queue.SimpleQueue()
    #     report_queue = queue.SimpleQueue()
    #     runtime = Runtime(event_queue, report_queue)
    #     recipe = Recipe(recipe_file)
    #     runtime.send_event("post_load_recipe", recipe)
    #     threading.Thread(target=recipe.run, kwargs={"runtime": runtime, "sequence_name": sequence_name}, daemon=True).start()
    #     # threading.Thread(target=recipe.parse_q_input, args=[q_in], daemon=True).start()
    #     return event_queue, report_queue, q_in
            

class Sequence():
    def __init__(self, sequence_data=None, sequence_file=None):
        if sequence_file is not None:
            with open(sequence_file, 'r') as file:
                sequence_data = yaml.safe_load(file)
        elif sequence_data is not None:
            sequence_data = sequence_data
        else:
            raise FileNotFoundError
        
        self.name = sequence_data["sequence_name"]
        self.locals = sequence_data["locals"]
        self.parameters = sequence_data["parameters"]
        self.outputs = sequence_data["outputs"]
        self.steps = []
        self.teardown_steps = []

        # build all contained steps here
        for step_data in sequence_data["setup_steps"]:
            self.steps.append(Step.build_step(step_data))

        for step_data in sequence_data["steps"]:
            self.steps.append(Step.build_step(step_data))

        for step_data in sequence_data["teardown_steps"]:
            self.teardown_steps.append(Step.build_step(step_data))
    def run(self, runtime: Runtime, input: dict, parent_step: uuid.UUID=None):
        logger.info(f"Starting sequence {self.name}")
        runtime.send_event("pre_run_sequence", self)
        runtime.push_locals(self.locals)
        runtime.current_sequence_name = self.name # Set current sequence name

        for variable in input:
            runtime.set_local(variable, input[variable])
        try: 
            sequence_results: List[StepResult] = Step.run_steps(runtime, self.steps, parent_step)
        finally:
            stop_event = getattr(runtime, "stop_event", None)
            teardown_results: List[StepResult] = Step.run_steps(runtime, self.teardown_steps, parent_step, stop_event=stop_event.clear())

            if teardown_results:
                sequence_results += teardown_results

            sequence_result = StepResult.evaluate_multiple_step_results(sequence_results)

            runtime.pop_locals()
            runtime.send_event("post_run_sequence", self, sequence_result)
            logger.info(f"Sequence {self.name} result: {sequence_result}")

            return sequence_result


class Step:
    def __init__(self, step_name, id="", description="", input_mapping={}, output_mapping={}, skip=False, critical=False):
        self.name = step_name
        self.description = description
        if id:
            self.id = id
        else:
            self.id = uuid.uuid4()
        self.skip = skip
        self.critical = critical
        self.input_mapping: dict = input_mapping
        self.output_mapping: dict = output_mapping

    def __str__(self):
        return f"Step: {self.__class__.__name__}: {self.name}"
    
    def check_indexing(self):
        for input_config in self.input_mapping.values():
            if "indexed" in input_config and input_config["indexed"]:
                return True
        return False
    
    def is_skipped(self):
        return self.skip

    def is_critical(self):
        return self.critical

    def _step(self, runtime, input, parent_step_result_uuid):
        # the step should be overriden by the subclass defined within steps.py
        raise NotImplementedError

    def process_inputs(self, runtime: Runtime):
        # We replace all references to variables with their content. These become direct_inputs
        direct_inputs = {}
        for input_name, input_config in self.input_mapping.items():
            direct_inputs[input_name] = input_config
            if "type" not in input_config: # if unspecified, it's a direct value
                input_config["type"] = "direct"

            if input_config.get("global_name", False):
                global_name = input_config.get("global_name")
                if not global_name:
                    raise ValueError(f"'global name' must be specified if global object is true.")
                direct_inputs[input_name] =runtime.get_global(global_name)
                continue
            match input_config["type"]:
                case "direct":
                    # value provided in the dictionary directly. Just use it
                    direct_inputs[input_name] = input_config["value"]
                case "local":
                    direct_inputs[input_name] = runtime.get_local(input_config["local_name"])
                    # del direct_inputs[input_name]["local_name"]
                case "global":
                    # go get the value in the global variables
                    direct_inputs[input_name] = runtime.get_global(input_config["global_name"])
                    # del direct_inputs[input_name]["global_name"]
                case "method":

                    direct_inputs[input_name] = input_config["value"]
            # del direct_inputs[input_name]["type"] # at this point it is always type direct so we remove the key
        return direct_inputs
    
    def process_outputs(self, runtime: Runtime, step_output: dict):
        step_result = ResultType.DONE

        for output_name, output_config in self.output_mapping.items():

            match output_config["type"]:
                case "passthrough": # The output is already a ResultType
                    step_result = step_output[output_name]
                case "passfail":    # Output is boolean. Passes on True
                    step_result = ResultType.PASS if step_output[output_name] else ResultType.FAIL
                case "equals":      # Output is a value. Passes if equal to the target value
                        step_result = (
                        ResultType.PASS
                        if step_output[output_name] == output_config["value"]
                        else ResultType.FAIL
                    )
                case "range":       # Output is a numeric value. Passes if within given range
                    step_result = (
                        ResultType.PASS
                        if (float(output_config["min"]) <= float(step_output[output_name]) <= float(output_config["max"]))
                        else ResultType.FAIL
                    )
                case "global":      # Output to be written to global variable
                    runtime.set_global(output_config["global_name"], step_output[output_name])
                case "local":       # Output to be written to local variable
                    runtime.set_local(output_config["local_name"], step_output[output_name])
        
        return step_result

    def run(self, runtime: Runtime, input, parent_step: uuid.UUID=None, stop_event = None ):
        """Executes the step, handling setup, execution, error handling, and output processing.

        Processes inputs, calls the internal `_step` method, processes outputs,
        handles potential errors, creates a StepResult, sends pre/post events,
        and sends the StepResult to the report_queue.

        Args:
            runtime (Runtime): The current execution runtime environment.
            input: The input data for the step (not used directly here, processed in `process_inputs`).
            parent_step (uuid.UUID, optional): The UUID of the parent step, if any.

        Returns:
            StepResult: An object containing the results of the step execution.
        """
        if stop_event is None:
            stop_event = getattr(runtime, "stop_event", None)
        step_result = StepResult(self, parent_step)
        # Populate metadata from runtime
        step_result.recipe_name = runtime.recipe_name
        step_result.recipe_file_name = runtime.recipe_file_name
        step_result.serial_number = runtime.serial_number
        step_result.sequence_name = runtime.current_sequence_name
        step_result.pypts_version = runtime.pypts_version # Copy version

        runtime.append_result(parent_step, step_result)

        if stop_event.is_set():
            logger.info("Recipe run stopped by button.")
            return self.handle_step_abort(step_result, runtime, input)
        
        runtime.send_event("pre_run_step", self)        
        logger.info("check before skip " + str(self.is_skipped()))
        if self.is_skipped():
            logger.info(f"Skipping step {self.name}")
            step_result.set_skip() 
        else:
            logger.info(f"Running step {self.name}")
            try:
                #define input in case it will got exception
                step_input = {}
                step_input = self.process_inputs(runtime)
                step_output = self._step(runtime, step_input, step_result.uuid)
                if stop_event.is_set():
                    logger.info("Recipe run stopped by button.")
                    return self.handle_step_abort(step_result, runtime, input)
            except:
                logger.error(f"Error occurred while running step {self.name}")
                error_info = traceback.format_exc()
                step_result.set_error(error_info, step_input)
                logger.error(error_info)
            else:
                result_type = self.process_outputs(runtime, step_output)
                step_result.set_result(result_type, step_input, step_output)
        
        runtime.send_event("post_run_step", step_result)
        # Add result to the report queue for processing by the listener
        runtime.report_queue.put(step_result)
        return step_result
    
    def handle_step_abort(self, step_result, runtime, input, reason="Stopped by user"):
        WAIT_FOR_TERMINATION.set()
        step_result.set_stop(reason, input)
        runtime.send_event("post_run_step", step_result)
        runtime.report_queue.put(step_result)
        return step_result

    @staticmethod
    def run_steps(runtime: Runtime, step_list: List[Self], parent_step: uuid.UUID, stop_event = None) -> List[StepResult]:
        step_results = []
        next_step = 0

        while next_step < len(step_list):

            step: Step = step_list[next_step]
            
            step_result = step.run(runtime, input, parent_step, stop_event=stop_event)
            step_results.append(step_result)


            try:
                runtime.continue_on_error = runtime.get_global('continue_on_error')
            except:
                pass
            # Check if we should stop execution due to an error
            # Stop if: ERROR occurred AND (continue_on_error is disabled OR step is critical)
            if step_result.is_type(ResultType.ERROR) and (not runtime.continue_on_error or step.is_critical()):
                logger.warning(f"Stopping execution due to error in {'critical' if step.is_critical() else 'non-critical'} step '{step.name}' (continue_on_error={'enabled' if runtime.continue_on_error else 'disabled'})")
                break
            elif step_result.is_type(ResultType.ERROR):
                logger.info(f"Continuing execution despite error in non-critical step '{step.name}' (continue_on_error enabled)")
                next_step += 1
            else:
                next_step += 1

        return step_results # aggregate_result # single pass or fail type

    @staticmethod
    def build_step(step_data:dict):
        """
        This helper function analyzes the configuration of step_data and adapts what is needed before
        creating the step.

        Args:
            step_data (dict): the dictionary containing the keys from the sequence file

        Returns:
            Step: This is a fully configured step object
        """
        step_type = step_data["steptype"]
        # we need to map the steptype names into the class strings.
        # it can happen that user defines waitstep instead of WaitStep and the application have to handle

        match step_type.lower():
            case "indexedstep": step_type = "IndexedStep"
            case "pythonmodulestep": step_type = "PythonModuleStep"
            case "sequencestep": step_type = "SequenceStep"
            case "userinteractionstep": step_type = "UserInteractionStep"
            case "waitstep": step_type = "WaitStep"
            case "userloadingstep": step_type = "UserLoadingStep"
            case "userrunmethodstep": step_type = "UserRunMethodStep"
            case "userwritestep": step_type = "UserWriteStep"
            case "SSHConnectStep": step_type = "SSHConnectStep"
            case "SSHCloseStep": step_type = "SSHCloseStep"

        # we remove this entry because it is used to determine which class to use for instantiation and
        # is not needed beyond that
        del step_data["steptype"]

        # creates the step according to the subclass type and passes all parameters   
        new_step: Step = eval(step_type + "(**step_data)")

        # Check if indexing is to be used, and if so, create IndexingStep to encapsulate the original step
        if new_step.check_indexing():

            # List of keys to keep
            keys_to_keep = ["id", "step_name", "input_mapping", "output_mapping", "skip", "description"]

            # Create a new dictionary excluding the keys not in keys_to_keep
            filtered_step_data = {key: value for key, value in step_data.items() if key in keys_to_keep}

            new_step = IndexedStep(new_step, **filtered_step_data)
        return new_step


# Import step implementations from steps module
from pypts.steps import IndexedStep, PythonModuleStep, SequenceStep, UserInteractionStep, WaitStep, UserLoadingStep, UserRunMethodStep, UserWriteStep, SSHConnectStep, SSHCloseStep



if __name__ == "__main__":
    log_format = '%(levelname)s : %(name)s : %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format)

    yaml_dir = os.path.join(os.path.dirname(__file__), 'recipes')
    yaml_path = os.path.join(yaml_dir, 'simple_recipe.yml')
    validate_recipe_filepath(yaml_path)
    # give time to print to stdout
    time.sleep(0.1)
    recipe = Recipe(yaml_path)
    
    recipe.sequences["Main"].list_steps()
    recipe.run()
    # recipe.sequences["Main"].run()
    # print(recipe.sequences["Subsequence"])
    # step = WaitStep(id="1", step_name="Wait Step", input_mapping={"wait_time": {"type": "direct", "value": 5}}, output_mapping={})
    # step1 = IndexedStep(step, id="1", step_name="Test Step", input_mapping={"a": {"type": "direct", "value": [1, 2, 3], "indexed": True}, "b": {"type": "direct", "value": [4, 5, 6], "indexed": True}, "c": {"type": "direct", "value": 6}}, output_mapping={"output": {"type": "direct"}})
    # print(step1._step())