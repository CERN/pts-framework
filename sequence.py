from step import Step, PythonModuleStep, SubSequenceStep
from typing import List, Dict
from step_result import StepResult, ResultType
import logging
import yaml
import interpreter

logger = logging.getLogger(__name__)

class Sequence:

    # _setup_steps: List[Step] = []
    # _steps: List[Step] = []
    # _teardown_steps: List[Step] = []
    # _variables: Dict[str, any] = {}
    # _environments: Dict[str, interpreter.Interpreter] = {}
    # _parameters: Dict[str, any] = {}
    # _outputs: Dict[str, any] = {}
    # _input_mapping = {}
    # _output_mapping = {}

    def __init__(self, sequence_file, parameter_values={}):
        logger.info(f"Parsing sequence file {sequence_file}.")
        with open(sequence_file, 'r') as file:
            sequence_data = yaml.safe_load(file)
        self._name = sequence_data["sequence_name"]
        self._variables = sequence_data["variables"]
        self._parameters = sequence_data["parameters"]
        self._outputs = sequence_data["outputs"]

        self._environments: Dict[str, interpreter.Interpreter] = {}
        # for each parameter defined in the sequence, override default if value is provided
        for parameter in self._parameters:
            if parameter in parameter_values:
                self._parameters[parameter] = parameter_values[parameter]

        # Create interpreter objects for each environment
        for parameter, path in sequence_data["environments"].items():
            self._environments[parameter] = interpreter.Interpreter(path, parameter)

        self._setup_steps: List[Step] = []
        self._steps: List[Step] = []
        self._teardown_steps: List[Step] = []
        # build all steps here    
        for step_data in sequence_data["setup_steps"]:
            self._setup_steps.append(self.build_step(step_data))
        for step_data in sequence_data["steps"]:
            self._steps.append(self.build_step(step_data))
        for step_data in sequence_data["teardown_steps"]:
            self._teardown_steps.append(self.build_step(step_data))

    def run(self):
        logger.info(f"Starting sequence {self._name}")
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
            for environment in self._environments.values():
                environment.stop()
        return self._outputs

    def build_step(self, step_data):
        step_type = step_data["steptype"]
        del step_data["steptype"]
        # we remove this entry because it is used to determine which class to use for instantiation and
        # is not needed beyond that
        
        if "repeat_gen" not in step_data:
            step_data["repeat_gen"] = None
        elif step_data["repeat_gen"] is not None:
                repeat_eval = eval(step_data["repeat_gen"])
                step_data["repeat_gen"] = repeat_eval
        return eval(step_type + "(**step_data)")
