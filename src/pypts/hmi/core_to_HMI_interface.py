# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, Empty
from pypts.core.CORE_MESSAGES import CoreToHMIEvent, CoreToHMICommand
from abc import ABC, abstractmethod

"""
Interface class that defines methods available for other modules.
All messages that are added here needs to be implemented by a data layer class (queue)
"""
class CoreToHMIInterface(ABC):
    """Core uses this interface to talk to HMI."""
    @abstractmethod
    def update_status(self, text: str):
        pass

    @abstractmethod
    def stop(self):
        pass

"""
Data layer class, that exposes the interface to be used by modules.
It implements a communication layer (queue) and payloads for the messages.
"""
class CoreToHMIQueue(CoreToHMIInterface):
    def __init__(self, core_to_hmi_queue: Queue):
        self.core_to_hmi_queue = core_to_hmi_queue

    def update_status(self, text: str):
        event = CoreToHMIEvent(cmd=CoreToHMICommand.UPDATE_STATUS, payload={"text": text})
        self.core_to_hmi_queue.put(event)

    def stop(self):
        event = CoreToHMIEvent(cmd=CoreToHMICommand.STOP)
        self.core_to_hmi_queue.put(event)

