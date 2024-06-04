from step import Step, PythonModuleStep
from typing import List, Dict
from step_result import StepResult, ResultType
import logging
import yaml
import interpreter

logger = logging.getLogger(__name__)

class Sequence:

    _setup_steps: List[Step] = []
    _steps: List[Step] = []
    _teardown_steps: List[Step] = []
    _variables: Dict[str, any] = {}
    _environments: Dict[str, interpreter.Interpreter] = {}
    _parameters: Dict[str, any] = {}
    _outputs: Dict[str, any] = {}
    _input_mapping = {}
    _output_mapping = {}

    def __init__(self, sequence_file, parameter_values={}):
        with open(sequence_file, 'r') as file:
            sequence_data = yaml.safe_load(file)
        self._sequence_name = sequence_data["sequence_name"]
        self._variables = sequence_data["variables"]
        self._parameters = sequence_data["parameters"]
        self._outputs = sequence_data["outputs"]
        
        # for each parameter defined in the sequence, override default if value is provided
        for name, value in self._parameters.items():
            if name in parameter_values:
                self._parameters[name] = parameter_values[name]

        # Create interpreter objects for each environment
        for name, path in sequence_data["environments"].items():
            self._environments[name] = interpreter.Interpreter(path, name)

        # build all steps here    
        for step_data in sequence_data["steps"]:
            self.build_step(step_data)
        # needs to load setup and teardown lists as well


    def run(self):
        logger.info(f"Starting sequence {self._sequence_name}")
        results: List[StepResult] = []
        try:
            logger.info(f"Running setup steps")
            for step in self._setup_steps:
                logger.info(f"Running step {step._id}")
                step_result = step.run(self._variables, self._parameters, self._outputs, self._environments)
                results += step_result
            
            logger.info(f"Running core steps")
            for step in self._steps:
                logger.info(f"Running step {step._id}")
                step_result = step.run(self._variables, self._parameters, self._outputs, self._environments)
                results += step_result
        except BaseException as e:
            logger.error(f"Error occured during sequence: {e.with_traceback()}")
        finally:        
            logger.info(f"Running teardown steps")
            for step in self._teardown_steps:
                logger.info(f"Running step {step._id}")
                step_result = step.run(self._variables, self._parameters, self._outputs, self._environments)
                results += step_result

        # return is too simple here, but good enough placeholder for now
        for environment in self._environments.values():
            environment.stop()
        return ResultType.FAIL if sum(result.result == ResultType.FAIL for result in results) > 0 else ResultType.PASS

    def build_step(self, step_data):
        step_type = step_data["steptype"]
        del step_data["steptype"]
        
        if "repeat_gen" not in step_data:
            step_data["repeat_gen"] = None
        elif step_data["repeat_gen"] is not None:
                repeat_eval = eval(step_data["repeat_gen"])
                step_data["repeat_gen"] = repeat_eval
        self._steps.append(eval(step_type + "(**step_data)"))
