from abc import ABC, abstractmethod
from queue import Queue, Empty
from pypts.messages.CORE_MESSAGES import CoreMessage
from pypts.messages.HMI_MESSAGES import HMIMessage


class HMIInterface(ABC):
    @abstractmethod
    def send_command_to_core(self, msg: CoreMessage): ...
    @abstractmethod
    def receive_command_from_core(self, timeout: float = 1.0) -> HMIMessage | None: ...


class QueueHMI(HMIInterface):
    """Implements HMI <-> Core communication via message queues."""

    def __init__(self, hmi_to_core_queue: Queue, core_to_hmi_queue: Queue):
        self.hmi_to_core_queue = hmi_to_core_queue
        self.core_to_hmi_queue = core_to_hmi_queue

    def send_command_to_core(self, msg: CoreMessage):
        self.hmi_to_core_queue.put(msg)

    def send_command_to_hmi(self, msg: HMIMessage):
        self.core_to_hmi_queue.put(msg)

    def receive_command_from_core(self, timeout: float = 1.0) -> HMIMessage | None:
        try:
            return self.core_to_hmi_queue.get(timeout=timeout)
        except Empty:
            return None

    def receive_command_from_hmi(self, timeout: float = 1.0) -> CoreMessage | None:
        try:
            return self.hmi_to_core_queue.get(timeout=timeout)
        except Empty:
            return None
