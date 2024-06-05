from step import Step, PythonModuleStep, SubSequenceStep
from typing import List, Dict
from step_result import StepResult, ResultType
import logging
import yaml
import interpreter

logger = logging.getLogger(__name__)

class Sequence:

    def __init__(self, sequence_file, parameter_values={}, id_prefix=None):
        with open(sequence_file, 'r') as file:
            sequence_data = yaml.safe_load(file)
        self.name = sequence_data["sequence_name"]
        self.variables = sequence_data["variables"]
        self.parameters = sequence_data["parameters"]
        self.outputs = sequence_data["outputs"]
        self.environments: Dict[str, interpreter.Interpreter] = {}
        self.setup_steps: List[Step] = []
        self.steps: List[Step] = []
        self.teardown_steps: List[Step] = []
        self.id_prefix = id_prefix

        # for each parameter defined in the sequence, override default if value is provided
        for parameter in self.parameters:
            if parameter in parameter_values:
                self.parameters[parameter] = parameter_values[parameter]

        # Create interpreter objects for each environment
        for environment, path in sequence_data["environments"].items():
            self.environments[environment] = interpreter.Interpreter(path, environment)


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

    def run(self):
        logger.info(f"Starting sequence {self.name}")
        try:
            logger.info(f"Running setup steps")
            for step in self.setup_steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(self.variables, self.parameters, self.outputs)
            
            logger.info(f"Running core steps")
            for step in self.steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(self.variables, self.parameters, self.outputs)

        except Exception as e:
            logger.error(f"Error occured during sequence: {e}")
        finally:        
            logger.info(f"Running teardown steps")
            for step in self.teardown_steps:
                logger.info(f"Running step {step.id}")
                step_result = step.run(self.variables, self.parameters, self.outputs)
            for environment in self.environments.values():
                environment.stop()
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

        # provide the step's interpreter name with the created interpreter
        if "environment" in step_data and step_data["environment"] is not None:
            step_data["environment"] = self.environments[step_data["environment"]]

        # evaluate the repeat formula to create an iterator
        if "repeat_gen" in step_data and step_data["repeat_gen"] is not None:
            step_data["repeat_gen"] = eval(step_data["repeat_gen"])
            # TODO should check validity as iterator

        # creates the step according to the subclass type and passes all parameters   
        new_step = eval(step_type + "(**step_data)")
        return new_step
