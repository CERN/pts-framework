# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later


import copy
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
import os
import re
from threading import Event
from pypts.utils import WAIT_FOR_TERMINATION
from pypts.recipe_language import (
    CommonStepDefinition as ValidatedStepDefinition,
    DirectInput as DirectInputDefinition,
    Recipe as RecipeDefinition,
    Sequence as SequenceDefinition,
)
from pypts.recipe_parser import parse_recipe_file
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
        self.image_paths: List[str] = []  # absolute paths of images returned by the step
    
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
        self.serial_number: str = "default_serial"
        self.current_sequence_name: str = None
        self.test_package: str = None
        self.pypts_version: str = "unknown" # Added pypts version
        self.continue_on_error: bool = False # Added continue_on_error setting
        self.recipe_continue_on_error: bool | None = None
    
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
    
    def get_global(self, index):
        try:
            return self.globals[index]
        except IndexError:
            return None
    
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


class Recipe:
    """
    Represents and executes a test recipe defined in a multi-document YAML file.

    Loads the recipe structure, manages global variables, sequences, and overall
    execution flow. The detailed structure of the recipe YAML file is described
    in :doc:`yaml_format`.

    Recipe files must validate as recipe language 2.0.0 before any executable
    runtime state is constructed.
    """
    def __init__(self, recipe_file_path, event_sender=None):
        self.event_sender = event_sender or self._default_event_sender
        definition = parse_recipe_file(recipe_file_path).require_recipe()
        self._load_definition(definition, str(recipe_file_path))

    @classmethod
    def from_definition(
        cls,
        definition: RecipeDefinition,
        source_name: str = "<definition>",
        event_sender=None,
    ):
        """Construct executable state from an already validated aggregate model."""
        if not isinstance(definition, RecipeDefinition):
            raise TypeError("definition must be a validated recipe_language.Recipe")
        instance = cls.__new__(cls)
        instance.event_sender = event_sender or instance._default_event_sender
        instance._load_definition(definition, source_name)
        return instance
    
    def _default_event_sender(self, runtime, event_name, *event_data):
        """Default implementation that uses runtime's send_event"""
        runtime.send_event(event_name, *event_data)

    def _load_definition(self, definition: RecipeDefinition, source_name: str) -> None:
        """Build runtime objects only after aggregate validation has succeeded."""
        header = definition.header
        logger.info("Loading validated recipe %s.", source_name)
        self.definition = definition
        self.recipe_file_name = Path(source_name).name
        self.sequences = {
            sequence.sequence_name: Sequence(sequence)
            for sequence in definition.sequences
        }
        self.name = header.name
        self.main_sequence = header.main_sequence
        self.description = header.description
        self.version = header.version
        self.continue_on_error = header.continue_on_error
        self.report_overwrite = header.report == "overwrite"
        self.report_name_include_serial = header.report_name_include_serial
        self.globals = copy.deepcopy(header.globals)
        self.test_package = header.test_package
        logger.info("Loaded recipe %s version %s.", self.name, self.version)

    def run(self, runtime: Runtime, sequence_name: str | None = None):
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
        sent_stop_listener = False
        results = []
        try:
            runtime.set_globals(self.globals)
            runtime.set_sequences(self.sequences)
            runtime.recipe_continue_on_error = self.continue_on_error
            runtime.recipe_name = self.name             # Set recipe name in runtime
            runtime.recipe_file_name = self.recipe_file_name # Set recipe file name in runtime
            runtime.test_package = self.test_package    # Set test package in runtime
            sequence_name = self.main_sequence if sequence_name is None else sequence_name
            if sequence_name not in self.sequences:
                raise ValueError(
                    f"Sequence '{sequence_name}' does not exist; "
                    f"available sequences: {', '.join(self.sequences)}"
                )

            # Use the event sender instead of direct calls
            self.event_sender(runtime, "pre_run_recipe", self.name, self.description)

            time.sleep(1)

            # Create folder structures needed here to store all results
            # starting_sequence: Sequence = runtime.get_sequence(sequence_name)
            # final_result = starting_sequence.run(runtime, {})
            if runtime.stop_event.is_set():
                logger.info(f"Recipe run aborted before executing sequence due to stop_event. {runtime.stop_event}")
                results = []  # Ensure results is defined
                # Emit signal so GUI still updates
                return results
                
            main_step = ExecutableSequenceStep(
                sequence={"type": "internal", "name": sequence_name},
                step_name=sequence_name,
                description=f"Run top-level sequence {sequence_name}.",
                input_mapping={},
                output_mapping={},
            )
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
            sent_stop_listener = True
            logger.debug("Sent STOP_LISTENER to report queue.")

            return results
        finally:
            if not sent_stop_listener:
                try:
                    from pypts.report import STOP_LISTENER
                    runtime.report_queue.put(STOP_LISTENER)
                    logger.debug("Sent STOP_LISTENER to report queue from finally.")
                except Exception:
                    logger.exception("Failed to send STOP_LISTENER from finally.")
            #results: List[StepResult] = runtime.get_results()
            runtime.send_event("post_run_recipe", results)
            Runtime.stop_event.set()

class Sequence():
    def __init__(self, definition: SequenceDefinition):
        if not isinstance(definition, SequenceDefinition):
            raise TypeError("Sequence requires a validated recipe_language.Sequence")
        self.definition = definition
        self.name = definition.sequence_name
        self.description = definition.description
        self.locals = copy.deepcopy(definition.locals)
        self.parameters = copy.deepcopy(definition.parameters)
        self.outputs = copy.deepcopy(definition.outputs)
        self.steps = []
        self.teardown_steps = []

        # build all contained steps here
        for step_definition in definition.setup_steps:
            self.steps.append(Step.build_step(step_definition))

        for step_definition in definition.steps:
            self.steps.append(Step.build_step(step_definition))

        for step_definition in definition.teardown_steps:
            self.teardown_steps.append(Step.build_step(step_definition))
    def run(self, runtime: Runtime, input: dict, parent_step: uuid.UUID=None):
        logger.info(f"Starting sequence {self.name}")
        runtime.send_event("pre_run_sequence", self)
        runtime.push_locals(self.locals)
        runtime.current_sequence_name = self.name # Set current sequence name

        for variable in input:
            runtime.set_local(variable, input[variable])
        sequence_results: List[StepResult] = []
        try:
            sequence_results = Step.run_steps(runtime, self.steps, parent_step)
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
    def __init__(self, step_name, id="", description="", input_mapping=None,
                 output_mapping=None, skip=False, critical=False,
                 continue_on_error=False):
        self.name = step_name
        self.description = description
        if id:
            self.id = id
        else:
            self.id = uuid.uuid4()
        self.skip = skip
        self.critical = critical
        self.continue_on_error = continue_on_error
        self.input_mapping: dict = input_mapping or {}
        self.output_mapping: dict = output_mapping or {}

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
        verdict_types = {"passthrough", "passfail", "equals", "range"}
        configured_verdicts = [
            config["type"] for config in self.output_mapping.values()
            if config.get("type") in verdict_types
        ]
        if "passthrough" in configured_verdicts and len(configured_verdicts) != 1:
            raise ValueError(
                f"Step '{self.name}' uses passthrough with another verdict mapping; "
                "passthrough must be the sole verdict mapping"
            )

        verdicts = []

        for output_name, output_config in self.output_mapping.items():

            match output_config["type"]:
                case "passthrough": # The output is already a ResultType
                    verdicts.append(step_output[output_name])
                case "passfail":    # Output is boolean. Passes on True
                    verdicts.append(bool(step_output[output_name]))
                case "equals":      # Output is a value. Passes if equal to the target value
                    verdicts.append(step_output[output_name] == output_config["value"])
                case "range":       # Output is a numeric value. Passes if within given range
                    verdicts.append(
                        float(output_config["min"])
                        <= float(step_output[output_name])
                        <= float(output_config["max"])
                    )
                case "global":      # Output to be written to global variable
                    runtime.set_global(output_config["global_name"], step_output[output_name])
                case "local":       # Output to be written to local variable
                    if "local_name" not in output_config:
                        raise ValueError(
                            f"Output '{output_name}' in step '{self.name}' has type 'local' but is missing required field 'local_name'."
                        )
                    runtime.set_local(output_config["local_name"], step_output[output_name])
                case "image":       # Image path — handled after set_result in run(); no effect on ResultType
                    pass

        if not verdicts:
            return ResultType.DONE
        if configured_verdicts == ["passthrough"]:
            return verdicts[0]
        return ResultType.PASS if all(verdicts) else ResultType.FAIL

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
                result_type = self.process_outputs(runtime, step_output)
                step_result.set_result(result_type, step_input, step_output)
                for out_name, out_cfg in self.output_mapping.items():
                    if out_cfg.get("type") == "image":
                        image_value = step_output.get(out_name)
                        if isinstance(image_value, (list, tuple, set)):
                            for path in image_value:
                                if path:
                                    step_result.image_paths.append(str(path))
                        elif image_value:
                            step_result.image_paths.append(str(image_value))
            except:
                logger.error(f"Error occurred while running step {self.name}")
                error_info = traceback.format_exc()
                step_result.set_error(error_info, step_input)
                logger.error(error_info)
        
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
            recipe_continue_on_error = getattr(runtime, "recipe_continue_on_error", None)
            continue_on_error = (
                step.continue_on_error
                if recipe_continue_on_error is None
                else recipe_continue_on_error
            )
            runtime.continue_on_error = continue_on_error

            step_result = step.run(runtime, input, parent_step, stop_event=stop_event)
            step_results.append(step_result)
            # Check if we should stop execution due to an error
            # Stop if: ERROR occurred AND (continue_on_error is disabled OR step is critical)
            if step_result.is_type(ResultType.ERROR) and (not continue_on_error or step.is_critical()):
                logger.warning(f"Stopping execution due to error in {'critical' if step.is_critical() else 'non-critical'} step '{step.name}' (continue_on_error={'enabled' if runtime.continue_on_error else 'disabled'})")
                break
            elif step_result.is_type(ResultType.ERROR):
                logger.info(f"Continuing execution despite error in non-critical step '{step.name}' (continue_on_error enabled)")
                next_step += 1
            else:
                next_step += 1

        return step_results # aggregate_result # single pass or fail type

    @staticmethod
    def build_step(step_definition: ValidatedStepDefinition):
        """Build an executable step from a validated recipe step definition.

        This is the single boundary between declarative recipe data and
        executable runtime behavior. The definition has already passed the
        Pydantic and aggregate semantic validation performed by the parser.

        Args:
            step_definition: Validated Pydantic step definition.

        Returns:
            Fully configured executable :class:`Step`.
        """
        if not isinstance(step_definition, ValidatedStepDefinition):
            raise TypeError("Step.build_step requires a validated step definition")
        step_type = step_definition.steptype
        step_class = STEP_TYPE_REGISTRY.get(step_type)
        if step_class is None:
            supported = ", ".join(sorted(STEP_TYPE_REGISTRY))
            raise ValueError(f"Unknown step type '{step_type}'. Supported step types: {supported}")

        constructor_data = step_definition.model_dump(
            mode="python", by_alias=True, exclude={"steptype"}
        )
        new_step: Step = step_class(**constructor_data)

        has_indexed_input = any(
            isinstance(value, DirectInputDefinition) and value.indexed
            for value in step_definition.input_mapping.values()
        )
        if has_indexed_input:

            # List of keys to keep
            keys_to_keep = [
                "id", "step_name", "input_mapping", "output_mapping", "skip",
                "description", "critical", "continue_on_error",
            ]

            # Create a new dictionary excluding the keys not in keys_to_keep
            filtered_step_data = {key: value for key, value in constructor_data.items() if key in keys_to_keep}

            new_step = IndexedStep(new_step, **filtered_step_data)
        return new_step


# Import step implementations from steps module
from pypts.steps import (
    IndexedStep,
    PythonModuleStep as ExecutablePythonModuleStep,
    SequenceStep as ExecutableSequenceStep,
    UserInteractionStep as ExecutableUserInteractionStep,
    WaitStep as ExecutableWaitStep,
    UserLoadingStep as ExecutableUserLoadingStep,
    UserRunMethodStep as ExecutableUserRunMethodStep,
    UserWriteStep as ExecutableUserWriteStep,
    SerialNumberStep as ExecutableSerialNumberStep,
    SSHConnectStep as ExecutableSSHConnectStep,
    SSHCloseStep as ExecutableSSHCloseStep,
    SSHUploadStep as ExecutableSSHUploadStep,
)

# Runtime behavior dispatch belongs beside Step.build_step(), the sole typed
# factory. This registry does not define fields or supported recipe structures:
# those come exclusively from recipe_language.StepDefinition's discriminated
# union. It only binds each already-validated canonical discriminator to the
# concrete class in steps.py that implements its behavior. Keeping the mapping
# here also preserves the dependency direction because steps.py depends on
# runtime types defined in this module.
STEP_TYPE_REGISTRY = {
    "PythonModuleStep": ExecutablePythonModuleStep,
    "SequenceStep": ExecutableSequenceStep,
    "UserInteractionStep": ExecutableUserInteractionStep,
    "WaitStep": ExecutableWaitStep,
    "UserLoadingStep": ExecutableUserLoadingStep,
    "UserRunMethodStep": ExecutableUserRunMethodStep,
    "UserWriteStep": ExecutableUserWriteStep,
    "SerialNumberStep": ExecutableSerialNumberStep,
    "SSHConnectStep": ExecutableSSHConnectStep,
    "SSHCloseStep": ExecutableSSHCloseStep,
    "SSHUploadStep": ExecutableSSHUploadStep,
}

# Preserve direct concrete runtime construction from this long-standing module.
PythonModuleStep = ExecutablePythonModuleStep
SequenceStep = ExecutableSequenceStep
UserInteractionStep = ExecutableUserInteractionStep
WaitStep = ExecutableWaitStep
UserLoadingStep = ExecutableUserLoadingStep
UserRunMethodStep = ExecutableUserRunMethodStep
UserWriteStep = ExecutableUserWriteStep
SerialNumberStep = ExecutableSerialNumberStep
SSHConnectStep = ExecutableSSHConnectStep
SSHCloseStep = ExecutableSSHCloseStep
SSHUploadStep = ExecutableSSHUploadStep



if __name__ == "__main__":
    log_format = '%(levelname)s : %(name)s : %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format)

    yaml_dir = os.path.join(os.path.dirname(__file__), 'recipes')
    yaml_path = os.path.join(yaml_dir, 'simple_recipe.yml')
    recipe = Recipe(yaml_path)
    
    recipe.sequences["Main"].list_steps()
    recipe.run()
    # recipe.sequences["Main"].run()
    # print(recipe.sequences["Subsequence"])
    # step = WaitStep(id="1", step_name="Wait Step", input_mapping={"wait_time": {"type": "direct", "value": 5}}, output_mapping={})
    # step1 = IndexedStep(step, id="1", step_name="Test Step", input_mapping={"a": {"type": "direct", "value": [1, 2, 3], "indexed": True}, "b": {"type": "direct", "value": [4, 5, 6], "indexed": True}, "c": {"type": "direct", "value": 6}}, output_mapping={"output": {"type": "direct"}})
    # print(step1._step())
