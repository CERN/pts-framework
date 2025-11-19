# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from abc import ABC, abstractmethod
from queue import Queue, Empty
from pypts.hmi.HMI_MESSAGES import *
from pypts.common.COMMON_MESSAGES import *

"""
Interface class defining methods that HMI modules use to communicate with Core.
Each method corresponds to a message that HMI can send.
All messages must also be implemented by a data layer class using queues.
"""

class HMIToCoreInterface(ABC):
    """
    Abstract interface used by HMI to send commands or events to Core.
    """

    @abstractmethod
    def start_sequence(self, sequence_name: str):
        """
        Command to start running a sequence identified by sequence_name.
        """
        pass

    @abstractmethod
    def load_recipe(self, recipe_path: str):
        """
        Command to load a recipe from the specified recipe_path.
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Command to stop the HMI module or its current operation.
        """
        pass

    @abstractmethod
    def report_error(self, error: ModuleErrorEvent):
        """
        Sends an error event to Core, encapsulated by ModuleErrorEvent.
        """
        pass

    @abstractmethod
    def exit(self):
        """
        Command to exit the HMI application or module.
        """
        pass

"""
Data layer class that implements HMIToCoreInterface.
Handles sending messages asynchronously via a multiprocessing queue.
"""

class HMIToCoreQueue(HMIToCoreInterface):
    """
    Concrete implementation of the HMI-to-Core interface, wrapping a queue.
    """

    def __init__(self, hmi_to_core_queue: Queue):
        """
        Initialize with the queue used for sending messages from HMI to Core.
        """
        self.hmi_to_core_queue = hmi_to_core_queue

    def start_sequence(self, sequence_name: str):
        """
        Sends a START_SEQUENCE event with the sequence name as payload.
        """
        event = HMIToCoreEvent(cmd=HMIToCoreCommand.START_SEQUENCE, payload={"sequence_name": sequence_name})
        self.hmi_to_core_queue.put(event)

    def load_recipe(self, recipe_path: str):
        """
        Sends a LOAD_RECIPE event with the recipe path as payload.
        """
        event = HMIToCoreEvent(cmd=HMIToCoreCommand.LOAD_RECIPE, payload={"recipe_path": recipe_path})
        self.hmi_to_core_queue.put(event)

    def stop(self):
        """
        Sends a STOP command event to Core.
        """
        event = HMIToCoreEvent(cmd=HMIToCoreCommand.STOP)
        self.hmi_to_core_queue.put(event)

    def exit(self):
        """
        Sends an EXIT command event to Core.
        """
        event = HMIToCoreEvent(cmd=HMIToCoreCommand.EXIT)
        self.hmi_to_core_queue.put(event)

    def report_error(self, error: ModuleErrorEvent):
        """
        Sends a ModuleErrorEvent instance directly to Core for error reporting.
        """
        self.hmi_to_core_queue.put(error)
