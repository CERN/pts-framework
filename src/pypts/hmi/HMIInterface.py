# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, Empty
from pypts.core.CORE_MESSAGES import CoreToHMIEvent, CoreToHMICommand
from abc import ABC, abstractmethod


class CoreToHMIInterface(ABC):
    """Core uses this interface to talk to HMI."""

    @abstractmethod
    def update_status(self, text: str):
        pass

    @abstractmethod
    def stop(self):
        pass


class CoreToHMIQueue(CoreToHMIInterface):
    """Queue-based HMI wrapper implementing HMIInterface."""

    def __init__(self, core_to_hmi_queue: Queue):
        self.core_to_hmi_queue = core_to_hmi_queue

    def update_status(self, text: str):
        event = CoreToHMIEvent(cmd=CoreToHMICommand.UPDATE_STATUS, payload={"text": text})
        self.core_to_hmi_queue.put(event)

    def stop(self):
        event = CoreToHMIEvent(cmd=CoreToHMICommand.STOP)
        self.core_to_hmi_queue.put(event)

