import sys
import yaml
import logging
from pathlib import Path
from typing import NamedTuple, List, Dict
from enum import Enum
from importlib import import_module


logger = logging.getLogger("executor")


class ResultType(Enum):
    NONE  = 0
    DONE  = 1
    PASS  = 2
    FAIL  = 3
    ERROR = 4
    SKIP  = 5


class StepResult:

    def __init__(self, result=ResultType.NONE, data={}, id=""):
        self.result = result
        self.data = data
        self.id = id

    def __str__(self):
        match self.result:
            case ResultType.NONE:
                return "NONE"
            case ResultType.PASS:
                return "PASS"
            case ResultType.FAIL:
                return "FAIL"
            case ResultType.ERROR:
                return "ERROR"
            case ResultType.SKIP:
                return "SKIP"


class VariableSet(NamedTuple):
    internal: dict
    globals: dict


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
        self.globals = recipe_main_data["globals"]
        logger.info(f"Loaded recipe {self.name} version {self.version}.")
        
    def run(self):
        internals = {"sequences": self.sequences}
        self.sequences["Main"].run(self.globals, internals)


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

    def _step(self, internals):
        return StepResult(ResultType.PASS, id=self.id)

    def _post_step(self):
        pass

    def __process_inputs(self, globals, locals, parameters):
        self.processed_inputs = {}
        for input_name, input_config in self.input_mapping.items():
            match input_config["type"]:
                case "direct":
                    # value provided in the dictionary directly
                    self.processed_inputs[input_name] = input_config["value"]
                case "local":
                    # go get the value in the variables
                    self.processed_inputs[input_name] = locals[input_config["local_name"]]
                case "global":
                    # go get the value in the variables
                    self.processed_inputs[input_name] = globals[input_config["global_name"]]
                case "parameter":
                    self.processed_inputs[input_name] = parameters[input_config["parameter_name"]]
                # case "repeat_id":
                #     self.processed_inputs[input_name] = repeat_id

    def __process_outputs(self, globals, locals, outputs, step_output):
        for output_name, output_config in self.output_mapping.items():
            match output_config["type"]:
                case "passfail":
                    # a boolean which sets pass/fail state of step
                    self.result = StepResult(ResultType.PASS if step_output[output_name] else ResultType.FAIL, id=self.id)
                case "global":
                    # go set the value in the variables
                    globals[output_config["global_name"]] = step_output[output_name]
                case "local":
                    # go set the value in the variables
                    locals[output_config["local_name"]] = step_output[output_name]
                case "output":
                    # go set the value in the outputs of the step
                    outputs[output_config["output_name"]] = step_output[output_name]
                case "store":
                    # don't put in variables, but store internally in the step. Not accessible to sequence
                    pass
                case "ignore":
                    # do nothing with it. The value is discarded and the sequence won't see it
                    pass
    
    def run(self, globals, internals, locals, parameters, outputs):
        # not sure what this function should return: test result or data or both
        if not self.skip:
            # Should have a conditional check to see if we run this test. This would
            # allow multiple tags to be used to decide which parts run or not
            logger.debug(f"Running {self.id}:pre")
            self.__process_inputs(globals, locals, parameters)
            self._pre_step()
            logger.debug(f"Running {self.id}")
            self.result = self._step(globals, internals)
            logger.debug(f"Running {self.id}:post")
            self._post_step()
            self.__process_outputs(globals, locals, outputs, self.output)
            logger.info(f"Test {self.id} result: {self.result}")
        else:
            logger.info(f"Skipping {self.name}")
            self.result = StepResult(ResultType.SKIP, id=self.id)
        return self.result


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

        # for each parameter defined in the sequence, override default if value is provided
        for parameter in self.parameters:
            if parameter in parameter_values:
                self.parameters[parameter] = parameter_values[parameter]

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

    def run(self, globals, internals):
        logger.info(f"Starting sequence {self.name}")
        try:
            logger.info(f"Running setup steps")
            for step in self.setup_steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(globals, internals, self.locals, self.parameters, self.outputs)
            
            logger.info(f"Running core steps")
            for step in self.steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(globals, internals, self.locals, self.parameters, self.outputs)

        except Exception as e:
            logger.error(f"Error occured during sequence: {e}")
        finally:        
            logger.info(f"Running teardown steps")
            for step in self.teardown_steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(globals, internals, self.locals, self.parameters, self.outputs)
        return self.outputs

    def build_step(self, step_data: Dict, id: str) -> Step:
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

class PythonModuleStep(Step):
    
    def __init__(self, action_type, module, method_name=None, attribute_name=None, **kwargs):
        super().__init__(**kwargs)
        self.module = module
        self.action_type = action_type
        self.method_name = method_name
        self.attribute_name = attribute_name

    def _step(self, globals, internals):
        step_result = StepResult(ResultType.PASS, id=self.id)        
        match self.action_type:
            case "method":
                module = self.__load_module(Path(self.module))
                method = getattr(module, self.method_name)
                self.output = method(**self.processed_inputs)
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

    def _step(self, globals, internals):
        step_result = StepResult(ResultType.PASS, id=self.id)
        match self.sequence["type"]:
            case "internal":
                sequence_name = self.sequence["name"]
                sequences = internals["sequences"]
                subsequence = sequences[sequence_name]
                # need access to all internal sequences. Could save them in globals?
            case "external":
                sequence_path = self.sequence["path"]
                subsequence = Sequence(sequence_file=sequence_path)

        self.output = subsequence.run(globals, internals)
        
        logger.info(f"Subsequence {subsequence.name} returned {self.output}")    
        return step_result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    recipe = Recipe("my_sequence copy.yaml")
    # recipe.sequences["Main"].list_steps()
    recipe.run()
    # recipe.sequences["Main"].run()
    # print(recipe.sequences["Subsequence"])