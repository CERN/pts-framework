# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
import copy
import uuid, paramiko
import queue
import time
from pathlib import Path
from importlib import import_module
import importlib.resources
from typing import List
from pypts.utilities.recipe import Step, Runtime, StepResult, ResultType, Sequence
from pypts.utilities.utils import get_package_root, find_resource_path, get_project_root, path_to_importable_module, AbortTestException

logger = logging.getLogger(__name__)


class IndexedStep(Step):
    """
    A step that wraps another step (template_step) and runs it multiple times
    based on indexed inputs. It aggregates results and outputs.
    """
    def __init__(self, step: Step, **kwargs):
        """
        Args:
            step: The template Step instance to be run multiple times.
            **kwargs: Common Step arguments (step_name, id, description, input_mapping, skip)
                      for the wrapper itself. The input_mapping here should contain
                      the potentially indexed lists.
        """
        # Initialize Step with common arguments for the wrapper
        super().__init__(**kwargs)
        if not isinstance(step, Step):
            raise TypeError(f"IndexedStep requires a valid Step instance, got {type(step)}")
        self.template_step: Step = step
        self.steps: List[Step] = [] # Stores the generated step instances for each run
        # Override output_mapping for the wrapper step itself to capture the aggregate result
        self.output_mapping = {"__result": {"type": "passthrough"}}
        # Note: Any output mappings defined in the original step_data for the wrapper
        # (like saving the aggregated result to a variable) should be added here or
        # processed by the base Step.process_outputs method using self.output_mapping.

    def check_indexing(self):
        """
        IndexedStep itself doesn't have indexed inputs; it manages the execution
        based on the template step's inputs. This method shouldn't be relevant
        after instantiation.
        """
        return False # An IndexedStep wrapper doesn't get wrapped again.

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        """
        Executes the template step multiple times based on indexed inputs.

        Args:
            runtime: The current recipe runtime environment.
            input: The dictionary of inputs resolved for *this* IndexedStep wrapper.
                   It should contain lists for inputs marked as 'indexed' in the
                   original step configuration.
            parent_step_result_uuid: The UUID of the StepResult for this IndexedStep wrapper.
                                     Sub-step results will be children of this.
        """
        # Determine which inputs of the *template* step are marked as indexed
        # from the original configuration passed during __init__.
        try:
             indexed_input_configs = {
                 name: config for name, config in self.template_step.input_mapping.items()
                 if isinstance(config, dict) and config.get("indexed", False)
             }
        except AttributeError:
             logger.error(f"Template step {getattr(self.template_step, 'name', 'Unnamed')} seems to lack input_mapping.")
             raise ValueError("Invalid template step configuration for IndexedStep.")

        indexed_list_names = list(indexed_input_configs.keys())

        # Get the actual input *values* provided to the IndexedStep wrapper
        wrapper_inputs = input

        if not indexed_list_names:
            logger.warning(f"IndexedStep '{self.name}' called, but no inputs marked 'indexed' found in template step '{self.template_step.name}'. Running template step once.")
            num_runs = 1
        else:
            # Validate that the corresponding inputs in the wrapper's resolved input values are lists
            for name in indexed_list_names:
                if name not in wrapper_inputs:
                     raise ValueError(f"Indexed input '{name}' missing in resolved inputs for IndexedStep '{self.name}'.")
                if not isinstance(wrapper_inputs[name], list):
                    raise TypeError(f"Input '{name}' for indexed step '{self.name}' must be a list, got {type(wrapper_inputs[name])}.")

            # Determine number of runs based on the shortest indexed list
            try:
                num_runs = min(len(wrapper_inputs[name]) for name in indexed_list_names)
                if num_runs == 0:
                    logger.warning(f"IndexedStep '{self.name}' has empty lists for indexed inputs. Skipping execution.")
                    return {"__result": ResultType.SKIP} # Or DONE? SKIP seems appropriate.
            except ValueError: # Handle case where indexed_list_names is empty after checks
                logger.warning(f"IndexedStep '{self.name}' inconsistency: Indexed inputs found, but failed to determine run count. Running once.")
                num_runs = 1

        logger.info(f"IndexedStep '{self.name}' will execute template '{self.template_step.name}' {num_runs} times.")
        self.steps = [] # Clear previous runs if step is somehow re-executed

        # Get names of non-indexed inputs from the wrapper's resolved inputs
        non_indexed_input_names = [name for name in wrapper_inputs if name not in indexed_list_names]

        for i in range(num_runs):
            # Create the input mapping for *this specific iteration* of the template step
            iteration_input_mapping = {}
            # Get indexed values for this iteration
            for name in indexed_list_names:
                 # Use 'direct' 'value' structure, as process_inputs expects this format
                 # when input_mapping is pre-resolved like this.
                 iteration_input_mapping[name] = {"type": "direct", "value": wrapper_inputs[name][i]}
            # Get non-indexed values (use the same value for all iterations)
            for name in non_indexed_input_names:
                 iteration_input_mapping[name] = {"type": "direct", "value": wrapper_inputs[name]}

            # Create a deep copy of the template step for this iteration
            # This ensures modifications (like changing input_mapping) don't affect other iterations.
            copied_step: Step = copy.deepcopy(self.template_step)

            # Set the specific inputs for this iteration by replacing its input_mapping
            copied_step.input_mapping = iteration_input_mapping

            # Remove local/global variable *saving* definitions from the copied step's *output* mapping.
            # We want to aggregate these values in the wrapper, not have each iteration save potentially overwriting variables.
            # Pass/Fail/Range/Equals checks on outputs should still happen per iteration.
            output_mapping_keys = list(copied_step.output_mapping.keys())
            for key in output_mapping_keys:
                output_conf = copied_step.output_mapping[key]
                if isinstance(output_conf, dict):
                    if output_conf.get("indexed", False):
                        values = output_conf.get("value", [])
                        if i < len(values):
                            copied_step.output_mapping[key]["value"] = values[i]
                        else:
                            logger.warning(f"No indexed output value for iteration {i} in '{self.name}'")
                            copied_step.output_mapping[key]["value"] = None #could also be a specified standard value.
                    elif output_conf.get("type") in ["local", "global"]:
                        logger.debug(f"Removing output mapping '{key}' (type: {output_conf.get('type')}) from iteration {i} of '{self.name}'")
                        del copied_step.output_mapping[key]

            # Modify the name for clarity in logs and results
            copied_step.name = f"{self.template_step.name} - Iteration {i+1}/{num_runs}"
            # Use a unique ID for the sub-step result? Or is the wrapper's sufficient?
            # Let StepResult handle UUID generation.
            self.steps.append(copied_step)

        # Run all the generated steps using the Step.run_steps static method
        # Pass the UUID of the *wrapper's* StepResult as the parent.
        step_results: List[StepResult] = Step.run_steps(runtime, self.steps, parent_step_result_uuid)

        # --- Aggregation ---
        # Aggregate outputs from the individual step results.
        # We only aggregate outputs that were *not* used for pass/fail/range/equals checks
        # within the iterations (i.e., likely intended as data outputs).
        aggregated_outputs = {}
        # These types imply the output was used for per-iteration result calculation.
        per_iteration_result_types = ["passthrough", "passfail", "equals", "range"]

        for result in step_results:
            # Iterate through the outputs recorded in the StepResult for this iteration
            for output_name, output_value in result.outputs.items():
                # Check the *template* step's original output mapping config for this output name.
                template_output_conf = self.template_step.output_mapping.get(output_name)

                # If the output exists in the template config AND its type was NOT a per-iteration check, aggregate it.
                if template_output_conf and isinstance(template_output_conf, dict) and template_output_conf.get("type") not in per_iteration_result_types:
                    if output_name not in aggregated_outputs:
                        aggregated_outputs[output_name] = []
                    aggregated_outputs[output_name].append(output_value)

        # Determine the overall result of the IndexedStep based on all iteration results.
        overall_result_type = StepResult.evaluate_multiple_step_results(step_results)
        # Add this overall result to the outputs dictionary under the special key "__result".
        # This is used by the wrapper's process_outputs method for the "passthrough" type.
        aggregated_outputs["__result"] = overall_result_type

        logger.info(f"IndexedStep '{self.name}' finished. Aggregated result: {overall_result_type}")
        logger.debug(f"Aggregated outputs for '{self.name}': {aggregated_outputs}")

        # Return the dictionary of aggregated outputs. This will be processed by the
        # wrapper Step's process_outputs method (e.g., to save variables).
        return aggregated_outputs


class PythonModuleStep(Step):
    """
    Executes a method or interacts with attributes within a specified Python module.
    """
    def __init__(self, action_type: str, module: str, method_name: str = None, continue_on_error: bool = False, **kwargs):
        """
        Args:
            action_type (str): The action to perform ('method', 'read_attribute', 'write_attribute').
            module (str): The file path to the Python module.
            method_name (str, optional): The name of the method to call (required if action_type is 'method').
            **kwargs: Common Step arguments.
        """
        super().__init__(**kwargs)
        self.action_type = action_type
        self.module_path_str = module # Store path as string
        self.method_name = method_name
        self.continue_on_error = continue_on_error

        # Basic validation during init
        if self.action_type == "method" and not self.method_name:
            raise ValueError(f"method_name is required for action_type 'method' in step {self.name}")
        if not self.module_path_str:
             raise ValueError(f"Module path is required for PythonModuleStep {self.name}")

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        """
        Performs the specified action on the Python module.

        Args:
            runtime: The recipe runtime.
            input: Dictionary of resolved inputs for this step. Expected inputs depend on action_type:
                   - 'method': Passed as keyword arguments to the method.
                   - 'read_attribute': Requires 'attribute_name' in input.
                   - 'write_attribute': Requires 'attribute_name' and 'attribute_value' in input.
            parent_step_result_uuid: UUID of the parent StepResult.
        """
        step_output = {}
        runtime.continue_on_error = self.continue_on_error #Sets runtime continue on error on step
        

        try:
            # Load the module dynamically using resources
            loaded_module = self.__load_module(runtime)
        except ImportError as e:
            logger.error(f"Failed to import module '{self.module_path_str}' for step '{self.name}': {e}")
            raise # Re-raise to be caught by the main run loop and result in ERROR

        try:
            match self.action_type:
                case "method":
                    try:
                        method_to_call = getattr(loaded_module, self.method_name)
                    except AttributeError:
                        logger.error(f"Method '{self.method_name}' not found in module '{self.module_path_str}' for step '{self.name}'")
                        raise #AttributeError(f"Method '{self.method_name}' not found in module.") # Re-raise specific error

                    logger.debug(f"Calling method '{self.method_name}' in '{self.module_path_str}' with inputs: {input}")
                    # Call the method, passing the resolved 'input' dictionary as keyword arguments
                    return_value = method_to_call(**input)

                    # Ensure the output is always a dictionary for consistent processing by process_outputs
                    if isinstance(return_value, dict):
                        step_output = return_value
                    elif return_value is None:
                        step_output = {} # Explicitly empty dict if method returns None
                    else:
                        # Wrap non-dict return values under a default key 'output'
                        step_output = {"output": return_value}
                    logger.debug(f"Method '{self.method_name}' returned: {step_output}")

                case "read_attribute":
                    attribute_name = input.get("attribute_name")
                    if not attribute_name:
                        raise ValueError(f"'attribute_name' is required in inputs for action_type 'read_attribute' in step '{self.name}'")
                    try:
                        value = getattr(loaded_module, attribute_name)
                        # Store the read value in the step output dictionary using the attribute name as the key
                        step_output[attribute_name] = value
                        logger.debug(f"Read attribute '{attribute_name}' from '{self.module_path_str}': {value}")
                    except AttributeError:
                        logger.error(f"Attribute '{attribute_name}' not found in module '{self.module_path_str}' for step '{self.name}'")
                        raise AttributeError(f"Attribute '{attribute_name}' not found.")

                case "write_attribute":
                    attribute_name = input.get("attribute_name")
                    attribute_value = input.get("attribute_value")
                    # Check if both name and value are provided
                    if attribute_name is None or attribute_value is None: # Allow attribute_value to be None explicitly
                        raise ValueError(f"'attribute_name' and 'attribute_value' are required in inputs for action_type 'write_attribute' in step '{self.name}'")
                    try:
                        # Check if attribute exists before trying to set? Optional.
                        # if not hasattr(loaded_module, attribute_name):
                        #    logger.warning(f"Attribute '{attribute_name}' does not exist in module '{module_file_path.name}'. Attempting to create it.")
                        setattr(loaded_module, attribute_name, attribute_value)
                        logger.debug(f"Set attribute '{attribute_name}' in '{self.module_path_str}' to: {attribute_value}")
                        step_output = {} # Write action typically doesn't produce output data
                    except Exception as e:
                        # Catch potential errors during setattr (e.g., read-only property)
                        logger.error(f"Failed to set attribute '{attribute_name}' on module '{self.module_path_str}' for step '{self.name}': {e}")
                        raise # Re-raise to indicate step failure

                case _:
                    # Should not happen if validation occurs, but good failsafe
                    raise ValueError(f"Unknown action_type '{self.action_type}' encountered in PythonModuleStep '{self.name}'")

        except Exception as e:
             # Catch errors during attribute access or method call
             logger.error(f"Error during action '{self.action_type}' in step '{self.name}': {e}")
             import traceback
             logger.debug(traceback.format_exc()) # Log traceback for debugging
             raise # Re-raise the exception to mark the step as ERROR

        return step_output

    def __load_module(self, runtime: Runtime):
        """
        Loads a Python module dynamically from package resources.

        Args:
            runtime (Runtime): The runtime environment containing test_package information.

        Returns:
            The loaded module object.

        Raises:
            Exception: If the test module cannot be imported.
        """

        # --- 1. Figure out root ---
        if runtime.test_package:
            root = get_package_root(runtime.test_package)
        else:
            root = get_project_root()

        folder_name = None
        # --- 2. Resolve module path ---
        module_path = find_resource_path(self.module_path_str, root=root)
        try:
            #Below function is used for finding and running the pypts as an example when downloading it from wheel.
            full_module_name = path_to_importable_module(module_path)
            logger.debug(f"[DEBUG] Resolved via site-packages: {full_module_name}")

        except:
            if module_path.suffix == '.py':
                module_path = module_path.with_suffix('')

            # --- 3. Work out folder part ---
            if module_path.parent != Path(".."):
                folder_path = module_path.parent
                folder_name = ".".join(folder_path.parts)
                
                redundant_prefix = "pypts.src"
                if folder_name.startswith(redundant_prefix + "."):
                    folder_name = folder_name[len(redundant_prefix) + 1 :]
            else:
                folder_name = get_project_root().name

        
            # Build the full module name: test_package + filename only
            # e.g., "fsi_pts.tests" + "test_status" -> "fsi_pts.tests.test_status"
            module_name = module_path.name  # Just the filename part
            if runtime.test_package and folder_name == runtime.test_package:
                folder_name = None
            
            parts = [runtime.test_package, folder_name, module_name]
            full_module_name = ".".join(part for part in parts if part)
            logger.debug(f"{full_module_name}" )

        # This one above tries to include a test_package that never was found or existed as a key in the recipe.
        # --- 4. Import attempt ---
        try:
            # First check if the test package exists
            try:
                importlib.resources.files(runtime.test_package)
            except (ModuleNotFoundError, AttributeError) as e:
                logger.debug(f"Test package '{runtime.test_package}' not found or not accessible: {e}. Software will continue to dynamically find the module")
            
            # Try to import the module
            logger.debug(f"Attempting to import module '{full_module_name}'")
            module = import_module(full_module_name)
            logger.debug(f"Successfully imported module '{full_module_name}'")
            return module
            
        except ModuleNotFoundError as e:
            logger.error(f"Module '{full_module_name}' not found in package '{runtime.test_package}': {e}")
            raise ImportError(f"Failed to load module '{full_module_name}': {e}") from e
        except Exception as e:
            logger.error(f"Error loading module '{full_module_name}': {e}")
            raise ImportError(f"Failed to load module '{full_module_name}': {e}") from e


class SequenceStep(Step):
    """
    Executes another sequence (defined either internally in the same recipe
    or potentially externally) as a single step within the current sequence.
    """
    def __init__(self, sequence: dict, **kwargs):
        """
        Args:
            sequence (dict): Configuration dictionary for the sequence to run.
                             Requires keys:
                             - 'type' (str): 'internal' (more types could be added).
                             - 'name' (str): Name of the sequence (for 'internal').
                             - 'path' (str): Path to sequence file (for future 'external' type).
            **kwargs: Common Step arguments.
        """
        super().__init__(**kwargs)
        # Validate sequence configuration dictionary
        if not isinstance(sequence, dict) or "type" not in sequence:
            raise ValueError(f"SequenceStep '{self.name}' requires a 'sequence' dictionary with at least a 'type' key.")
        self.sequence_config = sequence

        # Define that the primary result of this step is the pass/fail/error of the sub-sequence
        # The special output name "__result" is handled by the "passthrough" type in process_outputs.
        self.output_mapping["__result"] = {"type": "passthrough"}
        # Any other outputs defined in the YAML for SequenceStep (e.g., saving sub-sequence
        # results to variables) will be handled by process_outputs based on step_output content.

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        """
        Finds and executes the specified sub-sequence.

        Args:
            runtime: The recipe runtime, used to find internal sequences.
            input: Dictionary of resolved inputs. These will be passed as the
                   initial local variables to the sub-sequence.
            parent_step_result_uuid: UUID of the parent StepResult (this SequenceStep).
                                     Results from the sub-sequence's steps will be children of this.
        """
        seq_type = self.sequence_config["type"]
        logger.debug(f"SequenceStep '{self.name}': Running sequence (type: {seq_type})")

        sequence_to_run: Sequence = None
        sequence_name = None # For logging

        try:
            match seq_type:
                case "internal":
                    sequence_name = self.sequence_config.get("name")
                    if not sequence_name:
                         raise ValueError(f"SequenceStep '{self.name}': 'internal' sequence type requires a 'name'.")
                    try:
                        # Retrieve the pre-loaded Sequence object from the runtime
                        sequence_to_run = runtime.get_sequence(sequence_name)
                        logger.info(f"SequenceStep '{self.name}': Executing internal sequence '{sequence_name}'.")
                    except KeyError:
                        logger.error(f"Internal sequence '{sequence_name}' not found in runtime for step '{self.name}'.")
                        raise ValueError(f"Internal sequence '{sequence_name}' not found.")

                # case "external": # Example for future extension
                #     sequence_path = self.sequence_config.get("path")
                #     if not sequence_path:
                #         raise ValueError(f"SequenceStep '{self.name}': 'external' sequence type requires a 'path'.")
                #     try:
                #         # Load the sequence dynamically from its file
                #         # This assumes Sequence can be instantiated from a file path
                #         sequence_to_run = Sequence(sequence_file=sequence_path)
                #         sequence_name = sequence_to_run.name # Get name after loading
                #         logger.info(f"SequenceStep '{self.name}': Executing external sequence '{sequence_name}' from '{sequence_path}'.")
                #         # Note: Need to consider how globals/runtime interact with external sequences.
                #     except FileNotFoundError:
                #         logger.error(f"External sequence file not found: '{sequence_path}' for step '{self.name}'.")
                #         raise
                #     except Exception as e:
                #          logger.error(f"Error loading external sequence from '{sequence_path}': {e}")
                #          raise

                case _:
                    raise ValueError(f"Unsupported sequence type: '{seq_type}' in SequenceStep '{self.name}'")

            # --- Execute the Sub-Sequence ---
            # The 'input' dict for SequenceStep becomes the initial set of local variables for the sub-sequence.
            # Pass the UUID of the SequenceStep's *result* as the parent for the sub-sequence's steps.
            sub_sequence_result_type: ResultType = sequence_to_run.run(runtime, input, parent_step_result_uuid)

            # --- Collect Outputs ---
            # After the sub-sequence runs, collect its defined outputs from the (now popped) local scope.
            # We need access to the locals *before* they are popped by sequence.run().
            # This requires modifying Sequence.run() or how outputs are handled.
            #
            # Alternative: Sequence.run could return a tuple: (ResultType, dict_of_outputs)
            # Or: Outputs could be pushed to a dedicated runtime stack/dict associated with the call.
            #
            # Current approach (based on original code): Assumes Sequence.run modifies its locals
            # and SequenceStep._step tries to read them *after* run finishes, which won't work
            # correctly as the locals are popped.
            #
            # Let's assume Sequence.run is modified to return (ResultType, output_dict)
            # Or, more simply, the relevant runtime locals are accessible *somehow*.
            #
            # Revision: Sequence.run *doesn't* pop locals until the end. We need to access the locals
            # *before* the pop happens. SequenceStep._step runs *within* the context of the main
            # sequence's `run_steps` loop. The sub-sequence `run` pushes and pops its own scope.
            # How does the SequenceStep get the outputs?
            #
            # Proposal: SequenceStep needs to examine the StepResults generated by the sub-sequence
            # or the Runtime needs a way to retrieve outputs declared by a finished sequence.
            #
            # Simpler approach: The outputs defined in the Sequence object (`sequence_to_run.outputs`)
            # are keys whose values should be retrieved from the Runtime's *local* scope
            # *just before* it's popped by the Sequence.run method. Sequence.run needs modification.
            #
            # Workaround (using current structure): Assume outputs are written to *parent* locals
            # or globals by the sub-sequence steps if needed higher up. This avoids complexity here.
            # SequenceStep itself just needs to return the sub-sequence's final ResultType.

            step_output = {}
            # Add the overall result of the sub-sequence execution
            step_output["__result"] = sub_sequence_result_type

            logger.debug(f"Sequence '{sequence_name}' (called by step '{self.name}') finished with result: {sub_sequence_result_type}")
            return step_output

        except Exception as e:
             logger.error(f"Error during execution of SequenceStep '{self.name}' (running sequence '{sequence_name}'): {e}")
             import traceback
             logger.debug(traceback.format_exc())
             raise # Propagate the error


class UserInteractionStep(Step):
    """
    Pauses recipe execution and sends an event to request interaction from a user
    via a UI or other external interface. Waits for a response.
    """
    def __init__(self, trigger_response: str = None, module: str = None, action_type: str = None, method_name: str = None, continue_on_error: bool = False, **kwargs):
        """
        Args:
            **kwargs: Common Step arguments. Input mapping should define:
                      - 'message' (str): Text prompt for the user.
                      - 'image_path' (str, optional): Path to an image to display.
                      - 'options' (list, optional): List of response options (e.g., button labels).
                      Output mapping should define how to store the 'user_response'.
        """
        super().__init__(**kwargs)
        self.trigger_response = trigger_response
        self.module = module
        self.action_type = action_type
        self.method_name = method_name
        self.continue_on_error = continue_on_error
        self.timeout_seconds = 0.1  # Check every 1 second
        # Example: Ensure output mapping expects the response.
        # This should be defined in the YAML, but we can add a default/check.
        if "output" not in self.output_mapping:
            logger.warning(f"UserInteractionStep '{self.name}' might need an output mapping for 'output' to store the result.")
            # Add a default? e.g., self.output_mapping["user_response"] = {"type": "local", "local_name": "user_response"}

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        """
        Sends the 'user_interact' event and waits for a response on a queue.

        Args:
            runtime: The recipe runtime, used for sending events.
            input: Dictionary of resolved inputs ('message', 'image_path', 'options').
            parent_step_result_uuid: UUID of the parent StepResult.
        """
        message = input.get("message", "User interaction required.") # Default message
        image_path = input.get("image_path") # Can be None
        options = input.get("options") # Can be None or list/dict
        runtime.continue_on_error = self.continue_on_error #Sets runtime continue on error on step


        # Create a temporary queue for this specific interaction to receive the response.
        response_q = queue.SimpleQueue()

        try:
            # Send the event to the external listener (e.g., GUI)
            # Pass the response queue so the listener knows where to send the result.
            runtime.send_event("user_interact", response_q, message, image_path, options)

            logger.info(f"Step '{self.name}': Waiting for user interaction (message: '{message[:50]}...').")

            # --- Blocking Wait for Response ---
            # This will pause the recipe execution thread until the UI puts something in the queue.
            # TODO: Consider adding a timeout mechanism here. What happens if the UI never responds?
            # Example timeout:
            # try:
            #     response = response_q.get(block=True, timeout=300) # 5-minute timeout
            # except queue.Empty:
            #     logger.error(f"Timeout waiting for user interaction in step '{self.name}'.")
            #     raise TimeoutError("User did not respond in time.")


            while True:
                if  runtime.stop_event.is_set():
                    logger.info(f"UserInteractionStep '{self.name}': Stop event set during user interaction.")
                    return {"output": None, "status": {"status": "aborted"}}

                try:
                    response = response_q.get(timeout=self.timeout_seconds)
                    break  # Got response, continue normally
                except queue.Empty:
                    continue  # No response yet, keep checking stop_event

            status = {}
            logger.info(f"Step '{self.name}': User responded.")
            logger.debug(f"Step '{self.name}': Received response: {response}")

            try:
                cancel_key = runtime.get_global('cancel_key')
                if str(response).strip().lower() == str(cancel_key).strip().lower():
                    raise AbortTestException("wrong button")
            except Exception:
                # 'cancel_key' doesn't exist or something went wrong — safely ignore
                pass
            
            if self.trigger_response and str(response).strip().lower() in ([str(v).strip().lower() for v in (self.trigger_response.keys() if isinstance(self.trigger_response, dict) else self.trigger_response)] if isinstance(self.trigger_response, (dict, list, set))else [str(self.trigger_response).strip().lower()]):
                logger.info(f"Trigger matched: '{response}' → Executing setup/calibration method.")
                
                try:
                    module_step = PythonModuleStep(
                        step_name=f"{self.name}",
                        action_type=self.action_type,
                        module=self.module,
                        method_name=self.input_mapping["method_name"]["value"],
                    )
                    if str(response).strip().lower() == runtime.get_global('loadFile_key'):
                        file = response_q.get(block=True)
                        runtime.set_global('file', file)
                    
                    # Determine input based on action_type
                    if self.action_type == 'method':
                        module_input = {}  # No inputs expected
                        file_position = runtime.get_global('file')
                        if file_position  != "None":
                            module_input["file"] = file_position
                    elif self.action_type == 'read_attribute':
                        module_input = {'attribute_name': input.get('attribute_name')}
                    elif self.action_type == 'write_attribute':
                        module_input = {
                            'attribute_name': input.get('attribute_name'),
                            'attribute_value': input.get('attribute_value')
                        }
                    else:
                        module_input = {}

                    result = module_step._step(runtime,module_input, parent_step_result_uuid=parent_step_result_uuid)

                    if result:
                        logger.info(f"Module method returned: {result}")
                    else:
                        logger.info(f"Module method returned no output (None or empty).")

                    status["status"] = "ok"
                except Exception as e:
                    logger.error(f"Module method failed: {e}")
                    status["status"] = "error"
            else:
                logger.info(f"No trigger matched. Skipping module execution.")
                status["status"] = ""

            # Return the response in a dictionary. The key should match
            # what the output mapping expects - therefore the yaml mapping is used

            # todo - dynamically resolve what is the string for output
            # but then, itr raises a question of "what if multiple outputs are processed?"
            # Maybe we shall pass whole input/output mapping instead and handle those mappings internally in the step?
            return {"output": response, "status": status}

        except Exception as e:
            # Catch potential errors during event sending or queue operations
            logger.error(f"Error during user interaction step '{self.name}': {e}")
            raise # Propagate error to mark step as ERROR
        finally:
            # Clean up queue reference (though SimpleQueue doesn't strictly need it)
            del response_q


class WaitStep(Step):
    """
    Pauses recipe execution for a specified duration.
    """
    def __init__(self, **kwargs):
        """
        Args:
            **kwargs: Common Step arguments. Input mapping should define:
                      - 'wait_time' (float or int): Duration to wait in seconds.
        """
        super().__init__(**kwargs)

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        """
        Performs the time.sleep operation.

        Args:
            runtime: The recipe runtime (not used directly but part of signature).
            input: Dictionary of resolved inputs, must contain 'wait_time'.
            parent_step_result_uuid: UUID of the parent StepResult.
        """
        wait_time = float(input.get("wait_time"))

        # Validate wait_time
        if not isinstance(wait_time, (int, float)):
            raise TypeError(f"Invalid wait_time type '{type(wait_time)}' for WaitStep '{self.name}'. Must be number.")
        if wait_time < 0:
            raise ValueError(f"Invalid wait_time '{wait_time}' for WaitStep '{self.name}'. Must be non-negative.")

        logger.info(f"Step '{self.name}': Waiting for {wait_time:.2f} seconds...")
        try:
            time.sleep(wait_time)
            logger.info(f"Step '{self.name}': Wait finished.")
        except Exception as e:
             # Catch potential errors during sleep (e.g., interrupted?)
             logger.error(f"Error during wait step '{self.name}': {e}")
             raise # Propagate error

        # Wait step typically doesn't produce data output
        return {} 



class UserLoadingStep(Step):
    """
    Pauses recipe execution and sends an event to request interaction from a user
    via a UI or other external interface. Waits for a response.
    """
    def __init__(self, continue_on_error: bool = False, file_save_location: dict = None, **kwargs):
        """
        Args:
            **kwargs: Common Step arguments. Input mapping should define:
                      - 'message' (str): Text prompt for the user.
                      - 'image_path' (str, optional): Path to an image to display.
                      - 'options' (list, optional): List of response options (e.g., button labels).
                      Output mapping should define how to store the 'user_response'.
        """
        super().__init__(**kwargs)
        self.continue_on_error = continue_on_error
        self.file_save_location = file_save_location
        self.timeout_seconds = 1 
        if "output" not in self.output_mapping:
            logger.warning(f"UserLoadingStep '{self.name}' might need an output mapping for 'output' to store the result.")
            # Add a default? e.g., self.output_mapping["user_response"] = {"type": "local", "local_name": "user_response"}

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        """
        Sends the 'user_interact' event and waits for a response on a queue.

        Args:
            runtime: The recipe runtime, used for sending events.
            input: Dictionary of resolved inputs ('message', 'image_path', 'options').
            parent_step_result_uuid: UUID of the parent StepResult.
        """
        message = input.get("message", "User interaction required.") # Default message
        image_path = input.get("image_path") # Can be None
        options = input.get("options") # Can be None or list/dict
        runtime.continue_on_error = self.continue_on_error #Sets runtime continue on error on step

        response_q = queue.SimpleQueue()

        try:
            runtime.send_event("user_interact", response_q, message, image_path, options)
            logger.info(f"Step '{self.name}': Waiting for user interaction (message: '{message[:50]}...').")

            while True:
                if  runtime.stop_event.is_set():
                    logger.info(f"UserInteractionStep '{self.name}': Stop event set during user interaction.")
                    return {"output": None, "status": {"status": "aborted"}}

                try:
                    response = response_q.get(timeout=self.timeout_seconds)
                    break  # Got response, continue normally
                except queue.Empty:
                    continue  # No response yet, keep checking stop_event

            logger.info(f"Step '{self.name}': User responded.")
            logger.debug(f"Step '{self.name}': Received response: {response}")

            if str(response).strip().lower() == runtime.get_global('loadFile_key'):
                        file = response_q.get(block=True)
                        if self.file_save_location and self.file_save_location.get("type") == "global":
                            runtime.set_global(self.file_save_location.get("variable"), file)
                        elif self.file_save_location and self.file_save_location.get("type") == "local":
                            runtime.set_global(self.file_save_location.get("variable"),file) 
                        else:
                            runtime.set_global('file', file)
            if str(response).strip().lower() == runtime.get_global('cancel_key'):
                        raise AbortTestException(f"wrong button")
            else:
                logger.info(f"No trigger matched. Skipping module execution.")

            return {"output": response}

        except Exception as e:
            # Catch potential errors during event sending or queue operations
            logger.error(f"Error during user interaction step '{self.name}': {e}")
            raise # Propagate error to mark step as ERROR
        finally:
            # Clean up queue reference (though SimpleQueue doesn't strictly need it)
            del response_q



class UserRunMethodStep(Step):
    """
    Pauses recipe execution and sends an event to request interaction from a user
    via a UI or other external interface. Waits for a response.
    """
    def __init__(self, trigger_response: str = None, module: str = None, action_type: str = None, method_name: str = None, continue_on_error: bool = False, **kwargs):
        """
        Args:
            **kwargs: Common Step arguments. Input mapping should define:
                      - 'message' (str): Text prompt for the user.
                      - 'image_path' (str, optional): Path to an image to display.
                      - 'options' (list, optional): List of response options (e.g., button labels).
                      Output mapping should define how to store the 'user_response'.
        """
        super().__init__(**kwargs)
        self.trigger_response = trigger_response
        self.module = module
        self.action_type = action_type
        self.method_name = method_name
        self.continue_on_error = continue_on_error
        self.timeout_seconds = 1
        if "output" not in self.output_mapping:
            logger.warning(f"UserRunMethodStep '{self.name}' might need an output mapping for 'output' to store the result.")
            # Add a default? e.g., self.output_mapping["user_response"] = {"type": "local", "local_name": "user_response"}

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        """
        Sends the 'user_interact' event and waits for a response on a queue.

        Args:
            runtime: The recipe runtime, used for sending events.
            input: Dictionary of resolved inputs ('message', 'image_path', 'options').
            parent_step_result_uuid: UUID of the parent StepResult.
        """
        message = input.get("message", "User interaction required.") # Default message
        image_path = input.get("image_path") # Can be None
        options = input.get("options") # Can be None or list/dict

        other_keys = [key for key in input.keys() if key not in {"message", "image_path", "options"}]
        runtime.continue_on_error = self.continue_on_error

        response_q = queue.SimpleQueue()

        try:
            runtime.send_event("user_interact", response_q, message, image_path, options)
            logger.info(f"Step '{self.name}': Waiting for user interaction (message: '{message[:50]}...').")

            while True:
                if  runtime.stop_event.is_set():
                    logger.info(f"UserInteractionStep '{self.name}': Stop event set during user interaction.")
                    return {"output": None, "status": {"status": "aborted"}}

                try:
                    response = response_q.get(timeout=self.timeout_seconds)
                    break  # Got response, continue normally
                except queue.Empty:
                    continue  # No response yet, keep checking stop_event

            status = {}
            logger.info(f"Step '{self.name}': User responded.")
            logger.debug(f"Step '{self.name}': Received response: {response}")
            
            if str(response).strip().lower() == runtime.get_global('cancel_key'):
                        raise AbortTestException(f"wrong button")
            
            if self.trigger_response and str(response).strip().lower() in ([str(v).strip().lower() for v in (self.trigger_response.keys() if isinstance(self.trigger_response, dict) else self.trigger_response)] if isinstance(self.trigger_response, (dict, list, set))else [str(self.trigger_response).strip().lower()]):
                logger.info(f"Trigger matched: '{response}' → Executing setup/calibration method.")
            
                try:
                    module_step = PythonModuleStep(
                        step_name=f"{self.name}",
                        action_type=self.action_type,
                        module=self.module,
                        method_name=self.input_mapping["method_name"]["value"],
                    )
                    
                    # Determine input based on action_type
                    if self.action_type == 'method':
                        module_input = {}  # No inputs expected
                        if other_keys:
                            for key in other_keys:
                                key_input = input.get(key)
                                input_type = key_input.get("type")
                                
                                if input_type == "global":
                                    specified_value = runtime.get_global("global_name")
                                elif input_type == "local":
                                    specified_value = runtime.get_local("local_name")
                                else:
                                    specified_value = key_input.get("value")
                                
                                module_input[key] = specified_value
                    elif self.action_type == 'read_attribute':
                        module_input = {'attribute_name': input.get('attribute_name')}
                    elif self.action_type == 'write_attribute':
                        module_input = {
                            'attribute_name': input.get('attribute_name'),
                            'attribute_value': input.get('attribute_value')
                        }
                    else:
                        module_input = {}

                    result = module_step._step(runtime,module_input, parent_step_result_uuid=parent_step_result_uuid)

                    if result:
                        logger.info(f"Module method returned: {result}")
                    else:
                        logger.info(f"Module method returned no output (None or empty).")
                    status["status"] = "ok"
                except Exception as e:
                    logger.error(f"Module method failed: {e}")
                    status["status"] = "error"
                    response = "error"
            else:
                logger.info(f"No trigger matched. Skipping module execution.")
                status["status"] = ""

            return {"output": response, "status": status}

        except Exception as e:
            # Catch potential errors during event sending or queue operations
            logger.error(f"Error during user interaction step '{self.name}': {e}")
            raise # Propagate error to mark step as ERROR
        finally:
            # Clean up queue reference (though SimpleQueue doesn't strictly need it)
            del response_q




class UserWriteStep(Step):
    """
    Pauses recipe execution and sends an event to request interaction from a user
    via a UI or other external interface. Waits for a response.
    """
    def __init__(self, trigger_response: str = None, continue_on_error: bool = False, **kwargs):
        """
        Args:
            **kwargs: Common Step arguments. Input mapping should define:
                      - 'message' (str): Text prompt for the user.
                      - 'image_path' (str, optional): Path to an image to display.
                      - 'options' (list, optional): List of response options (e.g., button labels).
                      Output mapping should define how to store the 'user_response'.
        """
        super().__init__(**kwargs)
        self.trigger_response = trigger_response
        self.continue_on_error = continue_on_error
        self.timeout_seconds = 1
        if "output" not in self.output_mapping:
            logger.warning(f"UserLoadingStep '{self.name}' might need an output mapping for 'output' to store the result.")
            # Add a default? e.g., self.output_mapping["user_response"] = {"type": "local", "local_name": "user_response"}

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        """
        Sends the 'user_interact' event and waits for a response on a queue.

        Args:
            runtime: The recipe runtime, used for sending events.
            input: Dictionary of resolved inputs ('message', 'image_path', 'options').
            parent_step_result_uuid: UUID of the parent StepResult.
        """
        message = input.get("message", "User interaction required.") # Default message
        image_path = input.get("image_path") # Can be None
        options = input.get("options") # Can be None or list/dict
        runtime.continue_on_error = self.continue_on_error #Sets runtime continue on error on step

        response_q = queue.SimpleQueue()

        try:

            runtime.send_event("user_interact", response_q, message, image_path, options)
            logger.info(f"Step '{self.name}': Waiting for user interaction (message: '{message[:50]}...').")

            while True:
                if  runtime.stop_event.is_set():
                    logger.info(f"UserInteractionStep '{self.name}': Stop event set during user interaction.")
                    return {"output": None, "status": {"status": "aborted"}}

                try:
                    response = response_q.get(timeout=self.timeout_seconds)
                    break  # Got response, continue normally
                except queue.Empty:
                    continue  # No response yet, keep checking stop_event

            logger.info(f"Step '{self.name}': User responded.")
            logger.debug(f"Step '{self.name}': Received response: {response}")

            if str(response).strip().lower() == runtime.get_global('cancel_key'):
                        raise AbortTestException(f"wrong button")
            
            if str(response).strip() == runtime.get_global('wrt_key'):
                        Value = response_q.get(block=True)
                        if self.output_mapping["output"]["type"] == "local":
                            runtime.set_local(self.output_mapping["output"]["local_name"], Value)
                        elif self.output_mapping["output"]["type"] == "global":
                            runtime.set_global(self.output_mapping["output"]["global_name"], Value)

            
            if str(response).strip() == runtime.get_global('ID_key'):
                        port, baudrate, IDN = response_q.get(block=True)
                        print(IDN)
                        runtime.set_local('serial_ID', IDN)
                        runtime.set_local('serialport', port)
                        runtime.set_local('baudrate', baudrate)


            else:
                logger.info(f"No trigger matched. Skipping module execution.")

            return {"output": response}

        except Exception as e:
            # Catch potential errors during event sending or queue operations
            logger.error(f"Error during user interaction step '{self.name}': {e}")
            raise # Propagate error to mark step as ERROR
        finally:
            # Clean up queue reference (though SimpleQueue doesn't strictly need it)
            del response_q






class SSHConnectStep(Step):
    """
    Attempts an SSH connection to the given host and returns connection status.
    """

    def __init__(self, continue_on_error=False, **kwargs):
        """
        Args:
            **kwargs: Common Step arguments.
                      Global inputs required:
                          - 'host' (str): The SSH hostname or IP address.
                          - 'private_key' (str) The path to key file. important if no password is given.
                          - 'user' (str): The SSH username.
                          - 'port' (int, optional): SSH port (default: 22).
                          - 'password' (str, optional): Password for SSH auth.
                          - 'connect_timeout' (int, optional): Timeout for SSH connect (seconds).
                      Output mapping will store:
                          - 'status' (str): "connected" or "error".
                          - 'message' (str): Optional message or error reason.
        """
        super().__init__(**kwargs)
        self.continue_on_error = continue_on_error
        self.timeout_seconds = 1

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        host = runtime.get_global("host")
        private_key = runtime.get_global("private_key")
        user = runtime.get_global("user")
        password = runtime.get_global("password")
        raw_port =runtime.get_global("port")
        port = int(raw_port) if raw_port not in (None, "None", "") else 22
        connect_timeout = input.get("connect_timeout", 5)
        runtime.continue_on_error = self.continue_on_error #Sets runtime continue on error on step
        try:

            if not ((user and host and password) or (user and host and private_key)):
                    raise ValueError("Missing required SSH connection parameters.")

            logger.debug(f"[{self.name}] Attempting SSH connection to {host}:{port} as {user}")

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            logger.debug(f"[DEBUG] SSH connect to host='{host}' port='{port}' user='{user}'")
            if private_key and user:
                private_key = paramiko.RSAKey.from_private_key_file(private_key)
                client.connect(hostname=host, username=user, pkey=private_key,port=port, timeout=connect_timeout)
            elif password and user:
                client.connect(hostname=host, username=user, password=password,port=port, timeout=connect_timeout)

            result = client.exec_command("whoami")
            logger.debug(f"[{self.name}] SSH command output: {result[1].read().decode().strip()}")

            if host:
                try:
                    stdin, stdout, stderr = client.exec_command(f"nc -zv {host} {port}")
                    
                    # Wait for command to complete and get exit code
                    exit_status = stdout.channel.recv_exit_status()

                    if exit_status == 0:
                        logger.info(f"[{self.name}] Successfully connected to {host}:{port}")
                    else:
                        logger.warning(f"[{self.name}] Cannot connect to service at {host}:{port}")
                        
                except Exception as e:
                    logger.error(f"[{self.name}] SSH command execution failed: {e}")
            runtime.set_global("ssh_client",client)
            return {
                "status": "connected",
                "message": f"SSH connection to {host} successful."
            }

        except (paramiko.ssh_exception.AuthenticationException, paramiko.ssh_exception.SSHException, Exception) as e:
            logger.error(f"[{self.name}] SSH connection failed: {e}", exc_info=True)

            # Raise or return based on error policy
            if not self.continue_on_error:
                raise

            return {
                "status": "error",
                "message": str(e)
            }
        

class SSHCloseStep(Step):
    """
    Closes an existing Paramiko SSH connection.
    """

    def __init__(self, continue_on_error=False, **kwargs):
        """
        Args:
            continue_on_error (bool): If True, step won't raise on error.
            **kwargs: Common Step arguments.
        """
        super().__init__(**kwargs)
        self.continue_on_error = continue_on_error
        self.timeout_seconds = 1

    def _step(self, runtime: Runtime, input: dict, parent_step_result_uuid: uuid.UUID):
        host = runtime.get_global("host") or "<unknown>"
        runtime.continue_on_error = self.continue_on_error #Sets runtime continue on error on step
        
        try:
            client = runtime.get_global("ssh_client")
            if client:
                if client.get_transport() and client.get_transport().is_active():
                    client.close()
                    logger.info(f"[{self.name}] Closed SSH connection to {host}")
                else:
                    logger.info(f"[{self.name}] SSH connection was already inactive.")
            runtime.set_global("ssh_client", None)
            return {
                "status": "closed",
                "message": f"SSH connection to {host} closed."
            }
        except Exception as e:
            logger.error(f"[{self.name}] Failed to close SSH connection: {e}", exc_info=True)

            if not self.continue_on_error:
                raise
            return {
                "status": "error",
                "message": str(e)
            }
