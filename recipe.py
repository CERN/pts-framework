import yaml
import logging
from typing import List, Dict
from pathlib import Path
from importlib import import_module
import sys
import traceback
import threading
import queue
import time
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
    def __init__(self, event_queue):
        self.event_queue = event_queue
        self.results = []
        self.globals = []
        self.sequences = {}
        self.local_stack = []
        self.tags = {}
        
    def push_locals(self, locals):
        self.local_stack.append(locals)

    def pop_locals(self):
        return self.local_stack.pop()

    def get_local(self, name):
        return self.local_stack[-1][name]
    
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

    def set_tags(self, tags):
        self.tags = tags

    def get_tags(self):
        return self.tags
    
    def is_tag_set(self, name):
        return name in self.tags

    def get_sequence(self, name):
        return self.sequences[name]
    
    def set_sequences(self, sequences):
        self.sequences = sequences

    def append_results(self, results):
        self.results += results

    def get_results(self):
        return self.results
    
    def send_event(self, event_name:str, *event_data):
        self.event_queue.put((event_name, event_data))


class Recipe:
    def __init__(self, recipe_file_path):
        self.__load_recipe(recipe_file_path)

    def __load_recipe(self, recipe_file_path):
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
        # self.tags: dict[str, str] = recipe_main_data["tags"]
        logger.info(f"Loaded recipe {self.name} version {self.version}.")

    def __get_serial_number(self, runtime:Runtime):
        response_q = queue.SimpleQueue()
        logger.info("Asking user for serial number")
        runtime.send_event("get_serial_number", response_q)
        serial_number = response_q.get()
        del(response_q)
        logger.info(f"Serial number: {serial_number}")
        return serial_number

    def run(self, runtime:Runtime, sequence_name:str="Main", serial_number:str=None):
        runtime.set_globals(self.globals)
        runtime.set_sequences(self.sequences)
        runtime.send_event("pre_run_recipe", self.name, self.description)
        if serial_number is None:
            runtime.set_global("serial_number", self.__get_serial_number(runtime))
        else:
            runtime.set_global("serial_number", serial_number)
        # Create folder structures needed here to store all results in
        starting_sequence = runtime.get_sequence(sequence_name)
        starting_sequence.run(runtime, {})
        results = runtime.get_results()
        runtime.send_event("post_run_recipe", results)
        # self.globals = runtime.get_globals()
        return results

    
    # def parse_q_input(self, q_in):
    #     while True:
    #         input_command = q_in.get()
    #         print(f"RECEIVED SIGNAL FROM GUI: {input_command}")
    #         event:threading.Event = self.runtime["events"][input_command]
    #         event.set()
                    


def run_threaded(recipe_file, sequence_name="Main"):
    q_in = queue.Queue()
    event_queue = queue.SimpleQueue()
    runtime = Runtime(event_queue)
    recipe = Recipe(recipe_file)
    runtime.send_event("post_load_recipe", recipe)
    threading.Thread(target=recipe.run, kwargs={"runtime": runtime, "sequence_name": sequence_name}, daemon=True).start()
    # threading.Thread(target=recipe.parse_q_input, args=[q_in], daemon=True).start()
    return event_queue, q_in
        

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
        self.steps: List[Step] = []
        self.id_prefix = id_prefix

        
        def __make_id(count:int):
            if id_prefix is None:
                return str(count)
            else:
                return f"{id_prefix}.{count}"

        step_count = 0 # used for id: just an incrementing number representing the step order
        # build all steps here
        for step_data in sequence_data["setup_steps"]:
            self.steps.append(self.__build_step(step_data, __make_id(step_count)))
            step_count += 1
        for step_data in sequence_data["steps"]:
            self.steps.append(self.__build_step(step_data, __make_id(step_count)))
            step_count += 1
        self.first_teardown = len(self.steps)
        for step_data in sequence_data["teardown_steps"]:
            self.steps.append(self.__build_step(step_data, __make_id(step_count)))
            step_count += 1

    def run(self, runtime:Runtime, parameter_values:dict):
        # for each parameter defined in the sequence, override default if value is provided and store it in locals
        for parameter in self.parameters:
            if parameter in parameter_values:
                self.locals[parameter] = parameter_values[parameter]

        runtime.push_locals(self.locals)
        runtime.send_event("pre_run_sequence", self)
        logger.info(f"Starting sequence {self.name}")
        sequence_results = []
        current_step = 0
        next_step = 0
        num_sub_steps = 1
        current_sub_step = 0

        while True:
            current_step = next_step
            try:
                step = self.steps[current_step]
            except IndexError:
                logger.info("No more steps to execute")
                break

            if step.skip:
                logger.info(f"Skipping Step {current_step}: {step.name}")
                step_result = step.build_result(runtime, [], {}, ResultType.SKIP, None)
            else:
                if current_sub_step == 0:
                    input_list = step.process_inputs(runtime, step.input_mapping)
                    num_sub_steps = len(input_list)
                    current_sub_step = 1
                logger.info(f"Running Step {current_step}({current_sub_step}): {step.name}")
                step_result = step.run(runtime, input_list[current_sub_step - 1])
            
            if step_result["result"] == ResultType.ERROR:
                if current_step < self.first_teardown:
                    logger.warning("Jumping to teardown steps")
                    next_step = self.first_teardown
                    current_sub_step = 0
                else:
                    break
            else:
                if current_sub_step < num_sub_steps:
                    current_sub_step += 1
                else:
                    current_sub_step =0
                    next_step += 1
            sequence_results += step_result
        runtime.append_results(sequence_results)
        runtime.send_event("post_run_sequence", sequence_results)
        runtime.pop_locals()
        #return self.outputs

    def __build_step(self, step_data:dict, id:str):
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
        
        # integrate id into step_data
        step_data["id"] = id

        # creates the step according to the subclass type and passes all parameters   
        new_step = eval(step_type + "(**step_data)")
        return new_step

    def list_steps(self):
        for step in self.steps:
            print(step.name)


class Step:

    def __init__(self, id, step_name, input_mapping, output_mapping, skip=False, description=""):
        self.name = step_name
        self.description = description
        self.id = id
        self.skip = skip
        self.input_mapping = input_mapping
        self.output_mapping = output_mapping

    def __str__(self):
        return f"Step: {self.name}"

    def _step(self, runtime, inputs):
        return ResultType.DONE

    def process_inputs(self, runtime:Runtime, input_mapping:dict):
        self.processed_inputs = {}

        # We first replace all references to variables with their content. These become direct_inputs
        direct_inputs = {}
        for input_name, input_config in input_mapping.items():
            direct_inputs[input_name] = input_config
            if "type" not in input_config: # if unspecified, it's a direct value
                input_config["type"] = "direct"
            match input_config["type"]:
                case "direct":
                    # value provided in the dictionary directly. Nothing to do
                    pass
                case "local":
                    direct_inputs[input_name]["value"] = runtime.get_local(input_config["local_name"])
                    del direct_inputs[input_name]["local_name"]
                case "global":
                    # go get the value in the global variables
                    direct_inputs[input_name]["value"] = runtime.get_global(input_config["global_name"])
                    del direct_inputs[input_name]["global_name"]
            del direct_inputs[input_name]["type"] # at this point it is always type direct so we remove the key

        # We now process the direct_inputs to handle repetition for those inputs which are indexed
        input_list = [] # Each entry corresponds to one run of the step
        i = 0 # this index defines which position of the indexed lists we are targeting
        while True:
            processed_inputs = {} # A group of inputs to be passed to the input list
            try_next_index = False
            for input_name, input_config in direct_inputs.items():
                if "indexed" in input_config and input_config["indexed"]: # using lazy evaluation so that if absent, it doesn't raise exception
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
        # we add an empty dictionary to input list
        if  not input_list:
            input_list.append({})
        return input_list

    def process_outputs(self, runtime:Runtime, step_output:dict):
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
    
    def build_result(self, runtime, step_input, step_output, step_result, error_info):
        result = {}
        result["step"] = self
        result["inputs"] = step_input
        result["outputs"] = step_output
        result["result"] = step_result
        result["error"] = error_info
        return result

    def run(self, runtime:Runtime, input_set):
        # results = []
        
        # input_list = self.process_inputs(runtime, self.input_mapping)
        # pass_number = 1
        # for input_set in input_list:
        error_info = None
            # logger.debug(f"Pass {pass_number} with inputs {input_set}")
        runtime.send_event("pre_run_step", self, input_set)
        try:
            step_output = self._step(runtime, input_set)
            step_result = self.process_outputs(runtime, step_output)
        except:
            step_output = {}
            step_result = ResultType.ERROR
            error_info = traceback.format_exc()
            logger.error(error_info)

        result_data = self.build_result(runtime, input_set, step_output, step_result, error_info)
        # results.append(result_data)
        runtime.send_event("post_run_step", self, result_data)
        # logger.info(f"Pass {pass_number} result: {step_result}")
        # pass_number += 1
        return result_data


class PythonModuleStep(Step):
    
    def __init__(self, action_type, module, method_name=None, **kwargs):
        super().__init__(**kwargs)
        self.module = module
        self.action_type = action_type
        self.method_name = method_name

    def _step(self, runtime, inputs):
        step_output = {}
        match self.action_type:
            case "method":
                module = self.__load_module(Path(self.module))
                method = getattr(module, self.method_name)
                step_output = method(**inputs)
                if not isinstance(step_output, dict):
                    step_output = {"output": step_output}
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

    def _step(self, runtime:Runtime, inputs):
        # step_result = StepResult(ResultType.DONE, id=self.id)
        match self.sequence["type"]:
            case "internal":
                sequence_name = self.sequence["name"]
                subsequence = runtime.get_sequence(sequence_name)
            # case "external":
            #     sequence_path = self.sequence["path"]
            #     subsequence = Sequence(sequence_file=sequence_path)

        step_output = subsequence.run(runtime, inputs)

        logger.info(f"Subsequence {subsequence.name} returned {step_output}")    
        return step_output
    
class UserInteractionStep(Step):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _step(self, runtime:Runtime, inputs):
        response_q = queue.SimpleQueue()
        runtime.send_event("user_interact", response_q, inputs["message"], inputs["image_path"], inputs["options"])
        logger.info("Waiting for user interaction...")
        response = response_q.get()
        del(response_q)
        return {"output": response}

class WaitStep(Step):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _step(self, runtime:Runtime, inputs):
        logger.info(f"Waiting for {inputs['wait_time']}s")
        time.sleep(inputs["wait_time"])

# if __name__ == "__main__":
#     log_format = '%(levelname)s : %(name)s : %(message)s'
#     logging.basicConfig(level=logging.INFO, format=log_format)

#     recipe = Recipe("recipe1.yaml")
#     # recipe.sequences["Main"].list_steps()
#     recipe.run()
#     # recipe.sequences["Main"].run()
#     # print(recipe.sequences["Subsequence"])