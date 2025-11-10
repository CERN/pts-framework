from abc import ABC, abstractmethod
from queue import Queue, Empty
from pypts.hmi.HMI_MESSAGES import *
from pypts.sequencer.SEQUENCER_MESSAGES import *
from pypts.report.REPORT_MESSAGES import *


class HMIToCoreInterface(ABC):
    """Messages for usage by HMI"""
    @abstractmethod
    def start_sequence(self, sequence_name: str):
        pass

    @abstractmethod
    def load_recipe(self, recipe_path: str):
        pass

    @abstractmethod
    def stop(self):
        pass


class HMIToCoreQueue(HMIToCoreInterface):
    def __init__(self, hmi_to_core_queue: Queue):
        self.hmi_to_core_queue = hmi_to_core_queue

    def start_sequence(self, text: str):
        event = HMIToCoreEvent(cmd=HMIToCoreCommand.START_SEQUENCE, payload={"sequence_name": text})
        self.hmi_to_core_queue.put(event)

    def load_recipe(self, text: str):
        event = HMIToCoreEvent(cmd=HMIToCoreCommand.LOAD_RECIPE, payload={"recipe_path": text})
        self.hmi_to_core_queue.put(event)

    def stop(self):
        event = HMIToCoreEvent(cmd=HMIToCoreCommand.STOP)
        self.hmi_to_core_queue.put(event)


class SequencerToCoreInterface(ABC):
    """Messages for usage by Sequencer"""
    @abstractmethod
    def sequence_result(self):
        pass

    @abstractmethod
    def stop(self):
        pass

class SequencerToCoreQueue(SequencerToCoreInterface):
    def __init__(self, sequencer_to_core_queue: Queue):
        self.sequencer_to_core_queue = sequencer_to_core_queue

    def start_sequence(self, text: str):
        event = SequencerToCoreEvent(cmd=SequencerToCoreCommand.SEQUENCE_RESULT)
        self.sequencer_to_core_queue.put(event)

    def stop(self):
        event = SequencerToCoreEvent(cmd=SequencerToCoreCommand.STOP)
        self.sequencer_to_core_queue.put(event)


class ReportToCoreInterface(ABC):
    """Messages for usage by Report"""
    @abstractmethod
    def report_generated(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @report_exported
    def stop(self):
        pass


class ReportToCoreQueue(ReportToCoreInterface):
    def __init__(self, report_to_core_queue: Queue):
        self.report_to_core_queue = report_to_core_queue

    def report_generated(self,):
        event = ReportToCoreEvent(cmd=ReportToCoreCommand.REPORT_GENERATED)
        self.report_to_core_queue.put(event)

    def report_exported(self,):
        event = ReportToCoreEvent(cmd=ReportToCoreCommand.REPORT_EXPORTED)
        self.report_to_core_queue.put(event)

    def stop(self):
        event = ReportToCoreEvent(cmd=ReportToCoreCommand.STOP)
        self.report_to_core_queue.put(event)