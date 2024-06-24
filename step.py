import logging
from step_result import ResultType, StepResult
import interpreter
import sequence
from pathlib import Path
from importlib import import_module
import sys

logger = logging.getLogger(__name__)

class Step:

    def __init__(self, id, step_name, input_mapping, output_mapping, skip=False, repeat_gen=None):
        self.name = step_name
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

    def _step(self):
        return StepResult(ResultType.PASS, id=self.id)

    def _post_step(self):
        pass

    def __process_inputs(self, variables, parameters):
        self.processed_inputs = {}
        for input_name, input_config in self.input_mapping.items():
            match input_config["type"]:
                case "direct":
                    # value provided in the dictionary directly
                    self.processed_inputs[input_name] = input_config["value"]
                case "variable":
                    # go get the value in the variables
                    self.processed_inputs[input_name] = variables[input_config["variable_name"]]
                case "parameter":
                    self.processed_inputs[input_name] = parameters[input_config["parameter_name"]]
                # case "repeat_id":
                #     self.processed_inputs[input_name] = repeat_id

    def __process_outputs(self, variables, outputs, step_output):
        for output_name, output_config in self.output_mapping.items():
            match output_config["type"]:
                case "passfail":
                    # a boolean which sets pass/fail state of step
                    self.result = StepResult(ResultType.PASS if step_output[output_name] else ResultType.FAIL, id=self.id)
                case "variable":
                    # go set the value in the variables
                    variables[output_config["variable_name"]] = step_output[output_name]
                case "output":
                    # go set the value in the outputs of the step
                    outputs[output_config["output_name"]] = step_output[output_name]
                case "store":
                    # don't put in variables, but store internally in the step. Not accessible to sequence
                    pass
                case "ignore":
                    # do nothing with it. The value is discarded and the sequence won't see it
                    pass
    
    def run(self, variables, parameters, outputs):
        # not sure what this function should return: test result or data or both
        if not self.skip:
            # Should have a conditional check to see if we run this test. This would
            # allow multiple tags to be used to decide which parts run or not
            logger.debug(f"Running {self.id}:pre")
            self.__process_inputs(variables, parameters)
            self._pre_step()
            logger.debug(f"Running {self.id}")
            self.result = self._step()
            logger.debug(f"Running {self.id}:post")
            self._post_step()
            self.__process_outputs(variables, outputs, self.output)
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

    def _step(self):
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
    
    def __init__(self, sequence_file, **kwargs):
        super().__init__(**kwargs)
        self.sequence_file = sequence_file

    def _step(self):
        step_result = StepResult(ResultType.PASS, id=self.id)

        subsequence = sequence.Sequence(self.sequence_file, self.processed_inputs, self.id)
        self.output = subsequence.run()
        
        logger.info(f"Subsequence {subsequence.name} returned {self.output}")    
        return step_result
