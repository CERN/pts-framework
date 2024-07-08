import step
from typing import List, Dict
from step_result import StepResult, ResultType
import logging
import yaml

logger = logging.getLogger(__name__)

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
        self.setup_steps: List[step.Step] = []
        self.steps: List[step.Step] = []
        self.teardown_steps: List[step.Step] = []
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

    def build_step(self, step_data: Dict, id: str) -> step.Step:
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
        new_step = eval("step." + step_type + "(**step_data)")
        return new_step

    def list_steps(self):
        for step in self.setup_steps:
            print(step.name)
        for step in self.steps:
            print(step.name)
        for step in self.teardown_steps:
            print(step.name)