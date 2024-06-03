from enum import Enum


class ResultType(Enum):
    NONE  = 0
    PASS  = 1
    FAIL  = 2
    ERROR = 3
    SKIP  = 4


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