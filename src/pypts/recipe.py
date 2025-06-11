# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import copy
import yaml
import logging
from typing import List, Dict, Self
from pathlib import Path
from importlib import import_module
import sys
import traceback
import threading
import queue
import time
from enum import Enum
import json
import uuid
# from pts import Runtime

logger = logging.getLogger(__name__)


class ResultType(Enum):
    SKIP  = 0
    DONE  = 1
    PASS  = 2
    FAIL  = 3
    ERROR = 4

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
            if result.value > highest_result.value:
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

def serialize(obj):
    if isinstance(obj, Enum):
        return obj.name
    else:
        try:
            filtered_dict = {
                k: v
                for k, v in obj.__dict__.items()
                if not k.startswith("__")
            }
            return filtered_dict
        
        except AttributeError:
            return str(obj)

class Runtime:
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
        logger.debug(f"Setting global {name} to {value}")
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
            
            # The rest of the documents are all sequences
            sequence_count = 0
            for sequence in recipe_data:
                sequence_count += 1
                logger.debug(f"Processing sequence {sequence_count}: {sequence.get('sequence_name', 'UNNAMED')}")
                if "sequence_name" not in sequence:
                    logger.error(f"Sequence {sequence_count} missing 'sequence_name' field")
                    continue
                try:
                    self.sequences[sequence["sequence_name"]] = Sequence(sequence_data=sequence)
                except Exception as e:
                    logger.error(f"Failed to create sequence '{sequence.get('sequence_name', 'UNNAMED')}': {e}")
                    raise

            self.name: str = recipe_main_data["name"]
            self.description: str = recipe_main_data["description"]
            self.version: str = recipe_main_data["version"]
            self.globals: dict[str, any] = recipe_main_data["globals"]
            self.test_package: str = recipe_main_data.get("test_package", None)
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
        runtime.set_globals(self.globals)
        runtime.set_sequences(self.sequences)
        runtime.recipe_name = self.name             # Set recipe name in runtime
        runtime.recipe_file_name = self.recipe_file_name # Set recipe file name in runtime
        runtime.test_package = self.test_package    # Set test package in runtime

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

        main_step_data = {"steptype": "SequenceStep", "step_name": sequence_name, "sequence": {"type": "internal", "name": sequence_name}, "input_mapping": {}, "output_mapping": {}}
        main_step: Step = Step.build_step(main_step_data)
        final_result = main_step.run(runtime, {})
        
        results: List[StepResult] = runtime.get_results()
        runtime.send_event("post_run_recipe", results)
        
        print("\n==== RESULTS ====")
        # print(f"Final result: {final_result}")
        # print("-----------------")
        # for result in results:
        #     result.print_result()

        # print(runtime.local_stack)
        # print(runtime.globals)

        # Signal the report listener to stop
        from pypts.report import STOP_LISTENER
        runtime.report_queue.put(STOP_LISTENER)
        logger.debug("Sent STOP_LISTENER to report queue.")

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

        sequence_results: List[StepResult] = Step.run_steps(runtime, self.steps, parent_step)
        teardown_results: List[StepResult] = Step.run_steps(runtime, self.teardown_steps, parent_step)
        if teardown_results:
            sequence_results += teardown_results

        sequence_result = StepResult.evaluate_multiple_step_results(sequence_results)

        runtime.pop_locals()
        runtime.send_event("post_run_sequence", self, sequence_result)
        logger.info(f"Sequence {self.name} result: {sequence_result}")

        return sequence_result


class Step:
    def __init__(self, step_name, id="", description="", input_mapping={}, output_mapping={}, skip=False):
        self.name = step_name
        self.description = description
        if id:
            self.id = id
        else:
            self.id = uuid.uuid4()
        self.skip = skip
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

    def _step(self, runtime, input, parent_step_result_uuid):
        raise NotImplementedError

    def process_inputs(self, runtime: Runtime):
        # We replace all references to variables with their content. These become direct_inputs
        direct_inputs = {}
        for input_name, input_config in self.input_mapping.items():
            direct_inputs[input_name] = input_config
            if "type" not in input_config: # if unspecified, it's a direct value
                input_config["type"] = "direct"
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
                case "range":       # Output is a numberic value. Passes if within given range
                    step_result = (
                        ResultType.PASS
                        if (output_config["min"] <= step_output[output_name] <= output_config["max"])
                        else ResultType.FAIL
                    )
                case "global":      # Output to be written to global variable
                    runtime.set_global(output_config["global_name"], step_output[output_name])
                case "local":       # Output to be written to local variable
                    runtime.set_local(output_config["local_name"], step_output[output_name])
        
        return step_result

    def run(self, runtime: Runtime, input, parent_step: uuid.UUID=None):
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
        step_result = StepResult(self, parent_step)
        # Populate metadata from runtime
        step_result.recipe_name = runtime.recipe_name
        step_result.recipe_file_name = runtime.recipe_file_name
        step_result.serial_number = runtime.serial_number
        step_result.sequence_name = runtime.current_sequence_name
        step_result.pypts_version = runtime.pypts_version # Copy version

        runtime.append_result(parent_step, step_result)
        runtime.send_event("pre_run_step", self)

        if self.is_skipped():
            logger.info(f"Skipping step {self.name}")
            step_result.set_skip() 
        else:
            logger.info(f"Running step {self.name}")
            step_input = self.process_inputs(runtime)

            try:
                step_output = self._step(runtime, step_input, step_result.uuid)
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

    @staticmethod
    def run_steps(runtime: Runtime, step_list: List[Self], parent_step: uuid.UUID) -> List[StepResult]:
        step_results = []
        next_step = 0

        while next_step < len(step_list):
            step: Step = step_list[next_step]
            
            step_result = step.run(runtime, input, parent_step)
            
            step_results.append(step_result)

            if step_result.is_type(ResultType.ERROR):
                break
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
from pypts.steps import IndexedStep, PythonModuleStep, SequenceStep, UserInteractionStep, WaitStep




if __name__ == "__main__":
    log_format = '%(levelname)s : %(name)s : %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format)

    # recipe = Recipe("recipe1.yaml")
    # recipe.sequences["Main"].list_steps()
    # recipe.run()
    # recipe.sequences["Main"].run()
    # print(recipe.sequences["Subsequence"])
    # step = WaitStep(id="1", step_name="Wait Step", input_mapping={"wait_time": {"type": "direct", "value": 5}}, output_mapping={})
    # step1 = IndexedStep(step, id="1", step_name="Test Step", input_mapping={"a": {"type": "direct", "value": [1, 2, 3], "indexed": True}, "b": {"type": "direct", "value": [4, 5, 6], "indexed": True}, "c": {"type": "direct", "value": 6}}, output_mapping={"output": {"type": "direct"}})
    # print(step1._step())