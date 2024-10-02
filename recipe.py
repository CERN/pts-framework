import yaml
import logging
from typing import List, Dict
from pathlib import Path
from importlib import import_module
import sys
import traceback
import threading
import queue
from enum import Enum

logger = logging.getLogger(__name__)


class ResultType(Enum):
    NONE  = 0
    PASS  = 1
    FAIL  = 2
    ERROR = 3
    SKIP  = 4
    DONE  = 5

    def __str__(self):
        return str(self.name)


class Runtime:
    def __init__(self, globals, event_queue, sequences={}):
        self.results = []
        self.globals = globals
        self.sequences = sequences
        self.local_stack = []
        self.event_queue = event_queue
    
    def push_locals(self, locals):
        self.local_stack.append(locals)

    def pop_locals(self):
        return self.local_stack.pop()

    def get_local(self, name):
        return self.local_stack[-1][name]
    
    def set_local(self, name, value):
        self.local_stack[-1][name] = value
    
    def get_global(self, name):
        return self.globals[name]
    
    def set_global(self, name, value):
        self.globals[name] = value

    def get_sequence(self, name):
        return self.sequences[name]

    def append_results(self, results):
        self.results += results

    def get_results(self):
        return self.results
    
    def send_event(self, event_name:str, event_data:tuple):
        self.event_queue.put((event_name, event_data))


class Recipe:
    def __init__(self, recipe_file_path):
        logger.info(f"Loading recipe file {recipe_file_path}.")
        self.sequences: dict[str, Sequence] = {} 
        with open(recipe_file_path, 'r') as file:
            recipe_data = yaml.safe_load_all(file)
            recipe_main_data = next(recipe_data)
            for sequence in recipe_data:
                self.sequences[sequence["sequence_name"]] = Sequence(sequence_data=sequence)
        self.name: str = recipe_main_data["name"]
        self.description: str = recipe_main_data["description"]
        self.version: str = recipe_main_data["version"]
        self.globals: dict[str, any] = recipe_main_data["globals"]
        self.event_queue = queue.SimpleQueue()
        logger.info(f"Loaded recipe {self.name} version {self.version}.")
        # self.callbacks.post_load_recipe(self)

    
    def __get_serial_number(self):
        response_q = queue.SimpleQueue()
        logger.info("Asking user for serial number")
        self.runtime.send_event("get_serial_number", (response_q,))
        serial_number = response_q.get()
        del(response_q)
        logger.info(f"Serial number: {serial_number}")
        return serial_number

    def run(self, sequence_name="Main"):
        # Create runtime object to hold all useful data during the run and to pass down through the run calls
        self.runtime = Runtime(self.globals, self.event_queue, self.sequences)

        self.runtime.send_event("pre_run_recipe", (self.name, self.description))
        self.runtime.set_global("serial_number", self.__get_serial_number())
        starting_sequence = self.runtime.get_sequence(sequence_name)
        starting_sequence.run(self.runtime, {})
        results = self.runtime.get_results()
        self.runtime.send_event("post_run_recipe", (results,))
        return results

    
    # def parse_q_input(self, q_in):
    #     while True:
    #         input_command = q_in.get()
    #         print(f"RECEIVED SIGNAL FROM GUI: {input_command}")
    #         event:threading.Event = self.runtime["events"][input_command]
    #         event.set()
                    


def run_threaded(sequence_file, sequence_name="Main"):
    q_in = queue.Queue()
    recipe = Recipe(sequence_file)
    threading.Thread(target=recipe.run, kwargs={"sequence_name": sequence_name}, daemon=True).start()
    # threading.Thread(target=recipe.parse_q_input, args=[q_in], daemon=True).start()
    return recipe.event_queue, q_in
        

class Sequence:

    def __init__(self, sequence_data=None, sequence_file=None, id_prefix=None):
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
        self.setup_steps: List[Step] = []
        self.steps: List[Step] = []
        self.teardown_steps: List[Step] = []
        self.id_prefix = id_prefix

        
        def make_id(count: int):
            if id_prefix is not None:
                return f"{id_prefix}.{count}"
            else:
                return str(count)

        id_count = 0
        # build all steps here
        for step_data in sequence_data["setup_steps"]:
            self.setup_steps.append(self.build_step(step_data, make_id(id_count)))
            id_count += 1
        for step_data in sequence_data["steps"]:
            self.steps.append(self.build_step(step_data, make_id(id_count)))
            id_count += 1
        for step_data in sequence_data["teardown_steps"]:
            self.teardown_steps.append(self.build_step(step_data, make_id(id_count)))
            id_count += 1

    def run(self, runtime:Runtime, parameter_values:dict):
        # runtime.update({"locals": self.locals})
        runtime.push_locals(self.locals)
        runtime.send_event("pre_run_sequence", (self,))
        # for each parameter defined in the sequence, override default if value is provided and store it in locals
        for parameter in self.parameters:
            if parameter in parameter_values:
                self.locals[parameter] = parameter_values[parameter]

        logger.info(f"Starting sequence {self.name}")
        sequence_results = []
        try:
            logger.info(f"Running setup steps")
            for step in self.setup_steps:
                logger.info(f"Step {step.id} running: {step.name}")
                step_results = step.run(runtime)
                sequence_results += step_results
                
            logger.info(f"Running core steps")
            for step in self.steps:
                logger.info(f"Step {step.id} running: {step.name}")
                step_results = step.run(runtime)
                sequence_results += step_results
                
        except Exception as e:
            logger.error(f"Error occured during sequence: {e}")
            traceback.print_exc()
        finally:        
            logger.info(f"Running teardown steps")
            for step in self.teardown_steps:
                logger.info(f"Step {step.id} running: {step.name}")
                step_results = step.run(runtime)
                sequence_results += step_results

        runtime.append_results(sequence_results)
        runtime.send_event("post_run_sequence", (sequence_results,))
        self.locals = runtime.pop_locals()
        # return self.outputs

    def build_step(self, step_data: Dict, id: str):
        """This helper function analyzes the configuration of step_data and adapts what is needed before
        creating the step.

        Args:
            step_data (Dict): the dictionary containing the keys from the sequence file

        Returns:
            Step: This is a fully configured step object
        """
        step_type = step_data["steptype"]
        # we remove this entry because it is used to determine which class to use for instantiation and
        # is not needed beyond that
        del step_data["steptype"]
        
        # integrate id into step_data
        step_data["id"] = id

        # evaluate the repeat formula to create an iterator
        if "repeat_gen" in step_data and step_data["repeat_gen"] is not None:
            step_data["repeat_gen"] = eval(step_data["repeat_gen"])
            # TODO should check validity as iterator

        # creates the step according to the subclass type and passes all parameters   
        new_step = eval(step_type + "(**step_data)")
        return new_step

    def list_steps(self):
        for step in self.setup_steps:
            print(step.name)
        for step in self.steps:
            print(step.name)
        for step in self.teardown_steps:
            print(step.name)


class Step:

    def __init__(self, id, step_name, input_mapping, output_mapping, skip=False, repeat_gen=None, description=""):
        self.name = step_name
        self.description = description
        self.id = id
        self.skip = skip
        self.input_mapping = input_mapping
        self.output_mapping = output_mapping
        self.repeat_gen = repeat_gen
        self.__do_repeat = not repeat_gen == None
        

    def __str__(self):
        return f"Step: {self.name}"

    def _pre_step(self):
        pass

    def _step_core(self, runtime, inputs):
        return ResultType.DONE

    def _post_step(self):
        pass

    def __process_inputs(self, runtime:Runtime, input_mapping:dict):
        self.processed_inputs = {}

        # We first replace all references to variables with their content. These become direct_inputs
        direct_inputs = {}
        for input_name, input_config in input_mapping.items():
            direct_inputs[input_name] = input_config
            match input_config["type"]:
                case "direct":
                    # value provided in the dictionary directly
                    pass
                case "local":
                    direct_inputs[input_name]["value"] = runtime.get_local(input_config["local_name"])
                    del direct_inputs[input_name]["local_name"]
                case "global":
                    # go get the value in the global variables
                    direct_inputs[input_name]["value"] = runtime.get_global(input_config["global_name"])
                    del direct_inputs[input_name]["global_name"]
            del direct_inputs[input_name]["type"]

        # We now process the direct_inputs to handle repetition for those inputs which are indexed
        input_list = [] # Each entry corresponds to one run of the step
        i = 0 # this index defines which position of the indexed lists we are targeting
        while True:
            processed_inputs = {} # A group of inputs to be passed to the input list
            try_next_index = False
            for input_name, input_config in direct_inputs.items():
                if input_config["indexed"]:
                    # In the indexed case we take element i from the list contained in value
                    try:
                        processed_inputs[input_name] = input_config["value"][i]
                    except IndexError:
                        # we detect that we're beyond the last index so we invalidate this pass
                        processed_inputs = {}
                        break
                    try_next_index = True
                else:
                    # In the non-indexed case, we simply use the stored value as-is
                    processed_inputs[input_name] = input_config["value"]
            if processed_inputs: # If anything is in it, we append it to input_list
                input_list.append(processed_inputs)
            if not try_next_index:
                break
            i += 1
        # If the input_list is empty, the step will run 0 times when it should run once with no arguments
        # so we add an empty dictionary so that
        if  not input_list:
            input_list.append({})
        return input_list

    def __process_outputs(self, runtime:Runtime, step_output):
        step_result = ResultType.DONE
        for output_name, output_config in self.output_mapping.items():
            match output_config["type"]:
                case "passfail":
                    # a boolean which sets pass/fail state of step
                    step_result = ResultType.PASS if step_output[output_name] else ResultType.FAIL
                case "equals":
                    step_result = ResultType.PASS if step_output[output_name] == output_config["value"] else ResultType.FAIL
                case "range":
                    step_result = ResultType.PASS if step_output[output_name] <= output_config["max"] and \
                                                     step_output[output_name] >= output_config["min"] \
                                                  else ResultType.FAIL
                case "global":
                    # go set the value in the variables
                    runtime.set_global(output_config["global_name"], step_output[output_name])
                case "local":
                    # go set the value in the variables
                    runtime.set_local(output_config["local_name"], step_output[output_name])
        return step_result
    
    def __build_result(self, runtime, step_input, step_output, step_result):
        result = {}
        result["step"] = self
        result["inputs"] = step_input
        result["outputs"] = step_output
        result["result"] = step_result
        return result

    def run(self, runtime:Runtime):
        results = []

        if not self.skip:
            # Should have a conditional check to see if we run this test. This would
            # allow multiple tags to be used to decide which parts run or not
            
            input_list = self.__process_inputs(runtime, self.input_mapping)
            pass_number = 1
            for input_set in input_list:
                logger.debug(f"Pass {pass_number} with inputs {input_set}")
                runtime.send_event("pre_run_step", (self, input_set))
                logger.debug(f"Running {self.id}:pre")
                self._pre_step()
                logger.debug(f"Running {self.id}:core")
                step_output = self._step_core(runtime, input_set)
                logger.debug(f"Running {self.id}:post")
                self._post_step()
                step_result = self.__process_outputs(runtime, step_output)
                result_data = self.__build_result(runtime, input_set, step_output, step_result)
                results.append(result_data)
                runtime.send_event("post_run_step", (self, result_data))
                logger.info(f"Pass {pass_number} result: {step_result}")
                pass_number += 1
        else:
            logger.info(f"Step {self.id} skipped")
            runtime.send_event("pre_run_step", (self, {}))
            result_data = self.__build_result(runtime, [], {}, ResultType.SKIP)
            runtime.send_event("post_run_step", (self, result_data))
            results.append(result_data)
        return results


class PythonModuleStep(Step):
    
    def __init__(self, action_type, module, method_name=None, **kwargs):
        super().__init__(**kwargs)
        self.module = module
        self.action_type = action_type
        self.method_name = method_name

    def _step_core(self, runtime, inputs):
        step_output = {}
        match self.action_type:
            case "method":
                module = self.__load_module(Path(self.module))
                method = getattr(module, self.method_name)
                step_output = method(**inputs)
                # if not isinstance(self.output, dict):
                #     self.output = {"result", self.output}
                logger.debug(f"Method {self.method_name} returned {step_output}")    
                return step_output
            
            case "read_attribute":
                module = self.__load_module(Path(self.module))
                attribute_name = inputs["attribute_name"]
                step_output[attribute_name] = getattr(module, attribute_name)
                logger.debug(f"Reading attribute {attribute_name}: {step_output}")
                return step_output
            
            case "write_attribute":
                module = self.__load_module(Path(self.module))
                attribute_name = inputs["attribute_name"]
                attribute_value = inputs["attribute_value"]
                setattr(module, attribute_name, attribute_value)
                logger.debug(f"Setting attribute {attribute_name} to {attribute_value}")
                return {}
            
    def __load_module(self, module_full_path: Path):
        module_path = str(module_full_path.parent)
        module_filename = module_full_path.stem
        if module_path not in sys.path:
            sys.path.append(module_path)
        module = import_module(module_filename)
        return module


class SubSequenceStep(Step):
    
    def __init__(self, sequence, **kwargs):
        super().__init__(**kwargs)
        self.sequence = sequence

    def _step_core(self, runtime: dict, inputs):
        # step_result = StepResult(ResultType.DONE, id=self.id)
        match self.sequence["type"]:
            case "internal":
                sequence_name = self.sequence["name"]
                sequences = runtime["sequences"]
                subsequence = sequences[sequence_name]
            case "external":
                sequence_path = self.sequence["path"]
                subsequence = Sequence(sequence_file=sequence_path)

        # We want the subsequence to refer to the same global runtime objects, but have locals defined by the current sequence.
        # We make a shallow copy of the runtime dictionary. This will allow us to replace the locals item while maintaining
        # the locals in the current scope once the subsequence is done
        # new_runtime = runtime.copy()

        # The sequence run function will insert its own locals into the runtime, but this keeps the existing runtime states
        # for when we exit the subsequence.
        self.output = subsequence.run(runtime, inputs)

        logger.info(f"Subsequence {subsequence.name} returned {self.output}")    
        return self.output
    
class UserInteractionStep(Step):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _step_core(self, runtime:Runtime, inputs):
        response_q = queue.SimpleQueue()
        runtime.send_event("user_interact", (response_q, inputs["message"], inputs["image_path"], inputs["options"]))
        logger.info("Waiting for user interaction...")
        response = response_q.get()
        del(response_q)
        return {"output": response}


# if __name__ == "__main__":
#     log_format = '%(levelname)s : %(name)s : %(message)s'
#     logging.basicConfig(level=logging.INFO, format=log_format)

#     recipe = Recipe("recipe1.yaml")
#     # recipe.sequences["Main"].list_steps()
#     recipe.run()
#     # recipe.sequences["Main"].run()
#     # print(recipe.sequences["Subsequence"])