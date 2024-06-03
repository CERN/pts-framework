import logging
from step_result import ResultType, StepResult
import interpreter

logger = logging.getLogger(__name__)

class Step:

    def __init__(self, step_name="", skip=False, repeat_gen=None, step_parameters={}):
        self.name = step_name
        self._id = step_name
        self.skip = skip
        self.step_parameters = step_parameters
        if repeat_gen == None:
            self.__do_repeat = False
        else:
            self.__do_repeat = True
        self.repeat_gen = repeat_gen


    def _pre_step(self):
        pass

    def _step(self, variables, environments):
        return StepResult(ResultType.PASS, id=self._id)

    def _post_step(self):
        pass

    def run(self, variables, environments):
        results = list()
        if not self.skip:
            logger.debug(f"Running {self._id}:pre")
            self._pre_step()
            if not self.__do_repeat:
                logger.debug(f"Running {self._id}")
                result = self._step(variables, environments)
                results.append(result)
                logger.info(f"Test {self._id} result: {result}")
            else:
                for i in self.repeat_gen:
                    self._id = f"{self.name}#{i}"
                    logger.info(f"Running {self.name}, iteration {i}")
                    result = self._step(variables, environments)
                    results.append(result)
                    logger.info(f"Test {self._id} result: {result}")
            logger.debug(f"Running {self._id}:post")
            self._post_step()
        else:
            logger.info(f"Skipping {self.name}")
            results = [StepResult(ResultType.SKIP, id=self._id)]
        return results



class ActionStep(Step):
    
    def __init__(self, environment, action_type, action_file, method_name=None, attribute_name=None, **kwargs):
        super().__init__(**kwargs)
        self.environment = environment
        self.action_file = action_file
        self.method_name = method_name
        self.attribute_name = attribute_name
        self.action_type = action_type

    def _step(self, variables, environments):
        match self.action_type:
            case "method":
                resolved_parameters = {}
                for key, value in self.step_parameters.items():
                    match value["type"]:
                        case "direct":
                            resolved_parameters[key] = value["value"]
                        case "variable":
                            resolved_parameters[key] = variables[value["value"]]
        
                step_environment: interpreter.Interpreter = environments[self.environment]
                if not step_environment._running:
                    step_environment.start()
                result = step_environment.run_method(self.action_file, self.method_name, resolved_parameters)
                return StepResult(ResultType.PASS if result["pass"] else ResultType.FAIL, id=self._id)
            case "read_attribute":
                step_environment: interpreter.Interpreter = environments[self.environment]
                if not step_environment._running:
                    step_environment.start()
                result = step_environment.read_attribute(self.action_file, self.attribute_name)
                logger.info(f"Attribute {self.attribute_name} = {result}")
                return StepResult(ResultType.PASS if result == 6 else ResultType.FAIL, id=self._id)
