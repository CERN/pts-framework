import logging
from step_result import ResultType, StepResult
import interpreter

logger = logging.getLogger(__name__)

class Step:

    def __init__(self, step_name="", skip=False, repeat_gen=None):
        self.name = step_name
        self._id = step_name
        self.skip = skip
        if repeat_gen == None:
            self.__do_repeat = False
        else:
            self.__do_repeat = True
        self.repeat_gen = repeat_gen


    def _pre_step(self):
        pass

    def _step(self, repeat_id, variables, parameters, outputs, environments):
        return StepResult(ResultType.PASS, id=self._id)

    def _post_step(self):
        pass

    def run(self, variables, parameters, outputs, environments):
        results = list()
        if not self.skip:
            logger.debug(f"Running {self._id}:pre")
            self._pre_step()
            if not self.__do_repeat:
                logger.debug(f"Running {self._id}")
                result = self._step(None, variables, parameters, outputs, environments)
                results.append(result)
                logger.info(f"Test {self._id} result: {result}")
            else:
                for i in self.repeat_gen:
                    self._id = f"{self.name}#{i}"
                    logger.info(f"Running {self.name}, iteration {i}")
                    result = self._step(i, variables, parameters, outputs, environments)
                    results.append(result)
                    logger.info(f"Test {self._id} result: {result}")
            logger.debug(f"Running {self._id}:post")
            self._post_step()
        else:
            logger.info(f"Skipping {self.name}")
            results = [StepResult(ResultType.SKIP, id=self._id)]
        return results



class PythonModuleStep(Step):
    
    def __init__(self, environment, action_type, action_file, input_mapping, output_mapping, method_name=None, attribute_name=None, attribute_value=None, **kwargs):
        super().__init__(**kwargs)
        self.environment = environment
        self.action_file = action_file
        self.method_name = method_name
        self.attribute_name = attribute_name
        self.attribute_value = attribute_value
        self.action_type = action_type
        self.input_mapping = input_mapping
        self.output_mapping = output_mapping

    def _step(self, repeat_id, variables, parameters, outputs, environments):
        step_result = StepResult(ResultType.PASS, id=self._id)
        match self.action_type:
            case "method":
                method_parameters = {}
                for input_name, input_config in self.input_mapping.items():
                    match input_config["type"]:
                        case "direct":
                            # value provided in the dictionary directly
                            method_parameters[input_name] = input_config["value"]
                        case "variable":
                            # go get the value in the variables
                            method_parameters[input_name] = variables[input_config["variable_name"]]
                        case "parameter":
                            method_parameters[input_name] = parameters[input_config["parameter_name"]]
                        case "repeat_id":
                            method_parameters[input_name] = repeat_id
        
                step_environment: interpreter.Interpreter = environments[self.environment]
                if not step_environment._running:
                    step_environment.start()
                method_output = step_environment.run_method(self.action_file, self.method_name, method_parameters)
                
                for output_name, output_config in self.output_mapping.items():
                    match output_config["type"]:
                        case "passfail":
                            # a boolean which sets pass/fail state of step
                            step_result = StepResult(ResultType.PASS if method_output[output_name] else ResultType.FAIL, id=self._id)
                        case "variable":
                            # go set the value in the variables
                            variables[output_config["variable_name"]] = method_output[output_name]
                        case "output":
                            # go set the value in the outputs
                            outputs[output_config["output_name"]] = method_output[output_name]
                
                logger.info(f"Method {self.method_name} returned {method_output}")    
                return step_result
            
            case "read_attribute":
                step_environment: interpreter.Interpreter = environments[self.environment]
                if not step_environment._running:
                    step_environment.start()
                method_output = step_environment.read_attribute(self.action_file, self.attribute_name)
                logger.info(f"Reading attribute {self.attribute_name}: {method_output}")
                return StepResult(ResultType.PASS if method_output == 6 else ResultType.FAIL, id=self._id)
            
            case "write_attribute":
                step_environment: interpreter.Interpreter = environments[self.environment]
                if not step_environment._running:
                    step_environment.start()
                method_output = step_environment.write_attribute(self.action_file, self.attribute_name, self.attribute_value)
                logger.info(f"Setting attribute {self.attribute_name} to {self.attribute_value}")
                return StepResult(ResultType.PASS if method_output == 6 else ResultType.FAIL, id=self._id)
