# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, Empty
from pypts.core.CORE_MESSAGES import CoreToHMIEvent, CoreToHMICommand
from abc import ABC, abstractmethod

"""
Interface class defining method contracts for modules communicating with HMI.
Each message added here must be implemented in a data layer class using queues.
"""

class CoreToHMIInterface(ABC):
    """
    Abstract interface used by Core to send commands or updates to HMI modules.
    """

    @abstractmethod
    def update_status(self, text: str):
        """
        Command to update the status display text on the HMI.
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Command to stop the HMI module.
        """
        pass

"""
Data layer class implementing CoreToHMIInterface.
This class uses a multiprocessing queue to send CoreToHMIEvent messages.
"""

class CoreToHMIQueue(CoreToHMIInterface):
    """
    Concrete implementation of CoreToHMIInterface using a communication queue.
    """

    def __init__(self, core_to_hmi_queue: Queue):
        """
        Initialize with the queue used for Core-to-HMI communication.
        """
        self.core_to_hmi_queue = core_to_hmi_queue

    def update_status(self, text: str):
        """
        Sends an UPDATE_STATUS command event to HMI with provided text payload.
        """
        event = CoreToHMIEvent(cmd=CoreToHMICommand.UPDATE_STATUS, payload={"text": text})
        self.core_to_hmi_queue.put(event)

    def stop(self):
        """
        Sends a STOP command event to stop the HMI module.
        """
        event = CoreToHMIEvent(cmd=CoreToHMICommand.STOP)
        self.core_to_hmi_queue.put(event)
