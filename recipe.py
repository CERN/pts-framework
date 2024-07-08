import yaml
import logging
from typing import List, Dict
from step_result import StepResult, ResultType
from pathlib import Path
from importlib import import_module
import sys
import traceback

logger = logging.getLogger(__name__)


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
        logger.info(f"Loaded recipe {self.name} version {self.version}.")
        
    def run(self, sequence_name="Main"):
        # Create runtime variables structure here
        # This structure will be passed down throught the running functions to provide for all required data
        runtime = {"sequences": self.sequences,
                   "globals": self.globals,
                   "results": [],
                  # locals will be added as soon as the sequence starts
                   }

        self.sequences[sequence_name].run(runtime, {"target_value": 44})

        

class Sequence:

    def __init__(self, sequence_data=None, sequence_file=None, parameter_values={}, id_prefix=None):
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
        runtime.update({"locals": self.locals})
        
        # for each parameter defined in the sequence, override default if value is provided and store it in locals
        for parameter in self.parameters:
            if parameter in parameter_values:
                self.locals[parameter] = parameter_values[parameter]

        print(runtime)
        logger.info(f"Starting sequence {self.name}")
        try:
            logger.info(f"Running setup steps")
            for step in self.setup_steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(runtime)
            
            logger.info(f"Running core steps")
            for step in self.steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(runtime)

        except Exception as e:
            logger.error(f"Error occured during sequence: {e}")
            traceback.print_exc()
        finally:        
            logger.info(f"Running teardown steps")
            for step in self.teardown_steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(runtime)
        return self.outputs

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
        self.output = {}
        self.result = None
        

    def _pre_step(self):
        pass

    def _step(self, runtime, inputs):
        return StepResult(ResultType.PASS, id=self.id)

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
        
        input_list = []
        remaining_iterations = True
        i = 0
        while remaining_iterations:
            processed_inputs = {}
            for input_name, input_config in direct_inputs.items():
                #processed_inputs = direct_inputs
                if input_config["indexed"]:
                    try:
                        processed_inputs[input_name] = input_config["value"][i]

                    except IndexError:
                        remaining_iterations = False
                        break
                else:
                    processed_inputs[input_name] = input_config["value"]
            if remaining_iterations:
                input_list.append(processed_inputs)
                i += 1
        print(input_list)
        return input_list

    def __process_outputs(self, runtime, step_output):
        for output_name, output_config in self.output_mapping.items():
            match output_config["type"]:
                case "passfail":
                    # a boolean which sets pass/fail state of step
                    self.result = StepResult(ResultType.PASS if step_output[output_name] else ResultType.FAIL, id=self.id)
                case "equals":
                    self.result = StepResult(ResultType.PASS if step_output[output_name] == output_config["value"] else ResultType.FAIL, id=self.id)
                case "global":
                    # go set the value in the variables
                    runtime["globals"][output_config["global_name"]] = step_output[output_name]
                case "local":
                    # go set the value in the variables
                    runtime["locals"][output_config["local_name"]] = step_output[output_name]
    
    def __evaluate_repetition(self):
        repeat = False
        indexed_inputs = {}
        for input_name, input_config in self.input_mapping.items():
            if input_config["indexed"]:
                repeat = True
                indexed_inputs[input_name] = eval(input_config["value"])
        
        return indexed_inputs

    def run(self, runtime):
        # not sure what this function should return: test result or data or both
        if not self.skip:
            # Should have a conditional check to see if we run this test. This would
            # allow multiple tags to be used to decide which parts run or not
            
            # indexed_inputs = self.__evaluate_repetition()
            
            logger.debug(f"Running {self.id}:pre")
            input_list = self.__process_inputs(runtime, self.input_mapping)
            for input_set in input_list:
                self._pre_step()
                logger.debug(f"Running {self.id}")
                self.result = self._step(runtime, input_set)
                logger.debug(f"Running {self.id}:post")
                self._post_step()
                self.__process_outputs(runtime, self.output)
                logger.info(f"Test {self.id} result: {self.result}")
        else:
            logger.info(f"Skipping {self.name}")
            self.result = StepResult(ResultType.SKIP, id=self.id)
        return self.result


class PythonModuleStep(Step):
    
    def __init__(self, action_type, module, method_name=None, attribute_name=None, **kwargs):
        super().__init__(**kwargs)
        self.module = module
        self.action_type = action_type
        self.method_name = method_name
        self.attribute_name = attribute_name

    def _step(self, runtime, inputs):
        step_result = StepResult(ResultType.DONE, id=self.id)        
        match self.action_type:
            case "method":
                module = self.__load_module(Path(self.module))
                method = getattr(module, self.method_name)
                self.output = method(**inputs)
                # if not isinstance(self.output, dict):
                #     self.output = {"result", self.output}
                logger.info(f"Method {self.method_name} returned {self.output}")    
                return step_result
            
            case "read_attribute":
                module = self.__load_module(Path(self.module))
                self.output[self.attribute_name] = getattr(module, self.attribute_name)
                logger.info(f"Reading attribute {self.attribute_name}: {self.output}")
                return step_result
            
            case "write_attribute":
                module = self.__load_module(Path(self.module))
                attribute_value = self.processed_inputs[self.attribute_name]
                setattr(module, self.attribute_name, attribute_value)
                logger.info(f"Setting attribute {self.attribute_name} to {attribute_value}")
                return step_result
            
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

    def _step(self, runtime: dict):
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
    

if __name__ == "__main__":
    log_format = '%(levelname)s : %(name)s : %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format)
    recipe = Recipe("recipe2.yaml")
    recipe.sequences["Main"].list_steps()
    recipe.run()
    # recipe.sequences["Main"].run()
    # print(recipe.sequences["Subsequence"])