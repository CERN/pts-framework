
# [ GUI Process ]                     [ CORE Process ]
#     gui.py                               core.py
#        │                                    │
#        ▼                                    ▼
#    QueueHMI  ---------------------------> QueueHMI
#        │                                    │
#        ▼                                    ▼
#     uses HMIInterface                uses HMIInterface


# hmi.py
from abc import ABC, abstractmethod
from multiprocessing import Queue

# the interface defines what actions are possible, not how those are implemented
class HMIInterface(ABC):
    @abstractmethod
    def load_recipe(self, action: str, path: str):
        """Tell the core to load a recipe."""
        pass

# the queueHMI class implements the way of communication between the modules - like data layer
class QueueHMI(HMIInterface):
    def __init__(self, HMI_to_core: Queue, core_to_HMI: Queue):
        self.HMI_to_core = HMI_to_core
        self.core_to_HMI = core_to_HMI

    def send_command_to_core(self, message: str):
        self.HMI_to_core.put(message)

    def receive_core_command(self):
        return self.core_to_HMI.get()

    def load_recipe(self, acxtion: str, path: str):
        """Actual action of sending the command understandable by the core."""
        self.send_command_to_core({"action": "load_recipe", "path": path})
