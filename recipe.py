import yaml
import logging
from typing import List, Dict
from step_result import StepResult, ResultType
from pathlib import Path
from importlib import import_module
import sys
import traceback
import threading
import queue

logger = logging.getLogger(__name__)

class RecipeCallbacks:
    """
    This class defines the callbacks that are run at specific points of the execution
    of a recipe. Use these to plug into a UI or some other logging mechanism.
    The code calling the recipe provides an override of all these functions.
    """
    def post_load_recipe(self, recipe): pass
    def pre_run_recipe(self, recipe_name, recipe_description): pass
    def post_run_recipe(self, results): pass
    def pre_run_sequence(self, sequence): pass
    def post_run_sequence(self): pass
    def pre_run_step(self, step, inputs): pass
    def post_run_step(self, step, result): pass
    def user_interact(self, msg, image_path): pass


class ThreadCallbacks(RecipeCallbacks):
    def __init__(self, q):
        self.q:queue.Queue = q

    def post_load_recipe(self, recipe):
        self.q.put(("post_load_recipe", (recipe,)))

    def pre_run_recipe(self, recipe_name, recipe_description):
        self.q.put(("pre_run_recipe", (recipe_name, recipe_description)))
        
    def pre_run_sequence(self, sequence):
        self.q.put(("pre_run_sequence", (sequence,)))

    def post_run_step(self, step, result):
        self.q.put(("post_run_step", (step, result)))

    def post_run_recipe(self, results):
        self.q.put(("post_run_recipe", (results,)))
        print("=== TEST RESULTS ===")
        i = 0
        for result in results:
            print(f"Result {i} - Step {result['step'].id} ({result['step'].name}) with inputs {result['inputs']}: {result['result']}")
            i += 1
    
    def user_interact(self, q, message="", image_path="", options=[]):
        self.q.put(("user_interact", (q, message, image_path, options)))



class Recipe:

    def __init__(self, recipe_file_path, callback_object=RecipeCallbacks):
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
        self.callbacks = callback_object
        logger.info(f"Loaded recipe {self.name} version {self.version}.")
        self.events = {}
        self.events["continue"] = threading.Event()
        self.callbacks.post_load_recipe(self)
    

    def run(self, sequence_name="Main", single=True):
        # Create runtime variables structure here
        # This structure will be passed down throught the running functions to provide for all required data
        self.runtime = {"sequences": self.sequences,
                        "globals": self.globals,
                        "results": [],
                        "callbacks": self.callbacks,
                        "events": self.events
                        # locals will be added as soon as the sequence starts
                        }
        cb: RecipeCallbacks = self.runtime["callbacks"] # Add this to all methods that use callbacks for easy access
        cb.pre_run_recipe(self.name, self.description)
        self.sequences[sequence_name].run(self.runtime, {})
        cb.post_run_recipe(self.runtime["results"])
        return self.runtime["results"]

    
    def parse_q_input(self, q_in):
        while True:
            input_command = q_in.get()
            print(f"RECEIVED SIGNAL FROM GUI: {input_command}")
            event:threading.Event = self.runtime["events"][input_command]
            event.set()
                    


def run_threaded(sequence_file, sequence_name="Main"):
    q_out = queue.Queue()
    q_in = queue.Queue()
    recipe = Recipe(sequence_file, ThreadCallbacks(q_out))
    threading.Thread(target=recipe.run, kwargs={"sequence_name": sequence_name}, daemon=True).start()
    threading.Thread(target=recipe.parse_q_input, args=[q_in], daemon=True).start()
    return q_out, q_in
        

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

    def run(self, runtime:dict, parameter_values:dict):
        cb: RecipeCallbacks = runtime["callbacks"] # Add this to all methods that use callbacks for easy access
        runtime.update({"locals": self.locals})
        cb.pre_run_sequence(self)

        # for each parameter defined in the sequence, override default if value is provided and store it in locals
        for parameter in self.parameters:
            if parameter in parameter_values:
                self.locals[parameter] = parameter_values[parameter]

        logger.info(f"Starting sequence {self.name}")
        try:
            logger.info(f"Running setup steps")
            for step in self.setup_steps:
                logger.info(f"Running step {step.name}")
                step_data = step.run(runtime)
                runtime["results"] += step_data
            
            logger.info(f"Running core steps")
            for step in self.steps:
                logger.info(f"Running step {step.id}: {step.name}")
                step_data = step.run(runtime)
                runtime["results"] += step_data

        except Exception as e:
            logger.error(f"Error occured during sequence: {e}")
            traceback.print_exc()
        finally:        
            logger.info(f"Running teardown steps")
            for step in self.teardown_steps:
                logger.info(f"Running step {step.name}")
                step_data = step.run(runtime)
                runtime["results"] += step_data
        cb.post_run_sequence()
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

    def _step(self, runtime, inputs):
        return ResultType.DONE

    def _post_step(self):
        pass

    def __process_inputs(self, runtime, input_mapping:dict):
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
                    direct_inputs[input_name]["value"] = runtime["locals"][input_config["local_name"]]
                    del direct_inputs[input_name]["local_name"]
                case "global":
                    # go get the value in the global variables
                    direct_inputs[input_name]["value"] = runtime["globals"][input_config["global_name"]]
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

    def __process_outputs(self, runtime, step_output):
        step_result = ResultType.DONE
        for output_name, output_config in self.output_mapping.items():
            match output_config["type"]:
                case "passfail":
                    # a boolean which sets pass/fail state of step
                    step_result = ResultType.PASS if step_output[output_name] else ResultType.FAIL
                case "equals":
                    step_result = ResultType.PASS if step_output[output_name] == output_config["value"] else ResultType.FAIL
                case "global":
                    # go set the value in the variables
                    runtime["globals"][output_config["global_name"]] = step_output[output_name]
                case "local":
                    # go set the value in the variables
                    runtime["locals"][output_config["local_name"]] = step_output[output_name]
        return step_result
    
    def __build_result(self, runtime, step_input, step_output, step_result):
        result = {}
        result["step"] = self
        result["inputs"] = step_input
        result["outputs"] = step_output
        result["result"] = step_result
        return result

    def run(self, runtime):
        cb: RecipeCallbacks = runtime["callbacks"] # Add this to all methods that use callbacks for easy access
        results = []

        if not self.skip:
            # Should have a conditional check to see if we run this test. This would
            # allow multiple tags to be used to decide which parts run or not
            

            input_list = self.__process_inputs(runtime, self.input_mapping)
            for input_set in input_list:
                cb.pre_run_step(self, input_set)
                logger.debug(f"Running {self.id}:pre")
                self._pre_step()
                logger.debug(f"Running {self.id}")
                step_output = self._step(runtime, input_set)
                logger.debug(f"Running {self.id}:post")
                self._post_step()
                step_result = self.__process_outputs(runtime, step_output)
                result_data = self.__build_result(runtime, input_set, step_output, step_result)
                results.append(result_data)
                cb.post_run_step(self, result_data)
                logger.info(f"Test {self.id} result: {step_result}")
        else:
            logger.info(f"Skipping {self.name}")
            cb.pre_run_step(self, {})
            result_data = self.__build_result(runtime, [], {}, ResultType.SKIP)
            cb.post_run_step(self, result_data)
            results.append(result_data)
        return results


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
                # if not isinstance(self.output, dict):
                #     self.output = {"result", self.output}
                logger.info(f"Method {self.method_name} returned {step_output}")    
                return step_output
            
            case "read_attribute":
                module = self.__load_module(Path(self.module))
                attribute_name = inputs["attribute_name"]
                step_output[attribute_name] = getattr(module, attribute_name)
                logger.info(f"Reading attribute {attribute_name}: {step_output}")
                return step_output
            
            case "write_attribute":
                module = self.__load_module(Path(self.module))
                attribute_name = inputs["attribute_name"]
                attribute_value = inputs["attribute_value"]
                setattr(module, attribute_name, attribute_value)
                logger.info(f"Setting attribute {attribute_name} to {attribute_value}")
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

    def _step(self, runtime: dict, inputs):
        step_result = StepResult(ResultType.DONE, id=self.id)
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
        new_runtime = runtime.copy()

        # The sequence run function will insert its own locals into the runtime, but this keeps the existing runtime states
        # for when we exit the subsequence.
        self.output = subsequence.run(new_runtime, self.processed_inputs)

        logger.info(f"Subsequence {subsequence.name} returned {self.output}")    
        return step_result
    
class UserInteractionStep(Step):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _step(self, runtime:dict, inputs):
        cb: RecipeCallbacks = runtime["callbacks"] # Add this to all methods that use callbacks for easy access
        response_q = queue.SimpleQueue()
        cb.user_interact(response_q, inputs["message"], inputs["image_path"], inputs["options"])
        response = response_q.get()
        del(response_q)
        
        # runtime["events"]["continue"].wait()
        # runtime["events"]["continue"].clear()
        # Get value of output, i.e. text return of which button was pressed
        return {"output": response}
        # return StepResult(ResultType.DONE, id=self.id)



if __name__ == "__main__":

    class myCallbacks(RecipeCallbacks):
        def pre_run_recipe(self, recipe_name, recipe_description):
            print(f"Starting recipe with name {recipe_name}!!!")
    

    log_format = '%(levelname)s : %(name)s : %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format)

    recipe = Recipe("recipe1.yaml", myCallbacks())
    # recipe.sequences["Main"].list_steps()
    recipe.run()
    # recipe.sequences["Main"].run()
    # print(recipe.sequences["Subsequence"])