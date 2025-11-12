# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from abc import ABC, abstractmethod
from queue import Queue, Empty
from pypts.report.REPORT_MESSAGES import *
from pypts.common.COMMON_MESSAGES import *

"""
Interface class that defines methods available for other modules.
All messages that are added here needs to be implemented by a data layer class (queue)
"""
class ReportToCoreInterface(ABC):
    """Report uses this interface to talk to Core."""
    @abstractmethod
    def report_generated(self):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def report_exported(self):
        pass

    @abstractmethod
    def report_error(self, error: ModuleErrorEvent):
        pass

"""
Data layer class, that exposes the interface to be used by modules.
It implements a communication layer (queue) and payloads for the messages.
"""
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

    def report_error(self, error: ModuleErrorEvent):
        self.report_to_core_queue.put(error)