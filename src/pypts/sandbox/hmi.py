# hmi.py
from abc import ABC, abstractmethod
from multiprocessing import Queue

class HMIInterface(ABC):
    @abstractmethod
    def load_recipe(self, path: str):
        pass


class QueueHMI(HMIInterface):
    def __init__(self, HMI_to_core: Queue, core_to_HMI: Queue):
        self.HMI_to_core = HMI_to_core
        self.core_to_HMI = core_to_HMI

    def send_command_to_core(self, message: str):
        self.HMI_to_core.put(message)

    def receive_core_command(self):
        return self.core_to_HMI.get()

    def load_recipe(self, path: str):
        # Implemented to satisfy the abstract method
        print(f"Loading recipe from {path} (stub)")
