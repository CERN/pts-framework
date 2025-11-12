# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from abc import ABC, abstractmethod
from queue import Queue, Empty
from pypts.hmi.HMI_MESSAGES import *
from pypts.common.COMMON_MESSAGES import *

"""
Interface class that defines methods available for other modules.
All messages that are added here needs to be implemented by a data layer class (queue)
"""
class HMIToCoreInterface(ABC):
    """HMI uses this interface to talk to Core."""
    @abstractmethod
    def start_sequence(self, sequence_name: str):
        pass

    @abstractmethod
    def load_recipe(self, recipe_path: str):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def report_error(self, error: ModuleErrorEvent):
        pass

    @abstractmethod
    def exit(self):
        pass
"""
Data layer class, that exposes the interface to be used by modules.
It implements a communication layer (queue) and payloads for the messages.
"""
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

    def exit(self):
        event = HMIToCoreEvent(cmd=HMIToCoreCommand.EXIT)
        self.hmi_to_core_queue.put(event)

    def report_error(self, error: ModuleErrorEvent):
        self.hmi_to_core_queue.put(error)
