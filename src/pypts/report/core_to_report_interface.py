# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, Empty
from pypts.core.CORE_MESSAGES import CoreToReportCommand, CoreToReportEvent
from abc import ABC, abstractmethod

"""
Interface class that defines methods available for other modules.
All messages that are added here needs to be implemented by a data layer class (queue)
"""
class CoreToReportInterface(ABC):
    """Core uses this interface to talk to Report."""
    @abstractmethod
    def generate_report(self):
        pass

    @abstractmethod
    def export_report(self):
        pass

    @abstractmethod
    def stop(self):
        pass

"""
Data layer class, that exposes the interface to be used by modules.
It implements a communication layer (queue) and payloads for the messages.
"""
class CoreToReportQueue(CoreToReportInterface):
    def __init__(self, core_to_report_queue: Queue):
        self.core_to_report_queue = core_to_report_queue

    def export_report(self):
        event = CoreToReportEvent(cmd=CoreToReportCommand.EXPORT)
        self.core_to_report_queue.put(event)

    def generate_report(self):
        event = CoreToReportEvent(cmd=CoreToReportCommand.GENERATE)
        self.core_to_report_queue.put(event)

    def stop(self):
        event = CoreToReportEvent(cmd=CoreToReportCommand.STOP)
        self.core_to_report_queue.put(event)

