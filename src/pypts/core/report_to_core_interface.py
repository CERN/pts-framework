# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from abc import ABC, abstractmethod
from queue import Queue, Empty
from pypts.report.REPORT_MESSAGES import *
from pypts.common.COMMON_MESSAGES import *

"""
Abstract interface class defining messages the Report module sends to Core.
All messages defined here must be implemented by a data layer class utilizing a communication queue.
"""

class ReportToCoreInterface(ABC):
    """
    Interface used by the Report module to send events or commands to the Core module.
    Each method corresponds to a specific message the Report module can send.
    """

    @abstractmethod
    def report_generated(self):
        """
        Notify Core that a report has been generated successfully.
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Command to stop the Report module.
        """
        pass

    @abstractmethod
    def report_exported(self):
        """
        Notify Core that a report has been successfully exported.
        """
        pass

    @abstractmethod
    def report_error(self, error: ModuleErrorEvent):
        """
        Send an error event encapsulated by ModuleErrorEvent to Core.
        """
        pass

"""
Concrete data layer class implementing ReportToCoreInterface.
This class sends the appropriate ReportToCoreEvent messages or error events
to the Core module over an inter-process queue.
"""

class ReportToCoreQueue(ReportToCoreInterface):
    """
    Implements the report-to-core communication interface using a queue.
    """

    def __init__(self, report_to_core_queue: Queue):
        """
        Initialize with the queue used for report-to-core communication.
        """
        self.report_to_core_queue = report_to_core_queue

    def report_generated(self):
        """
        Sends a REPORT_GENERATED event to notify core of successful report generation.
        """
        event = ReportToCoreEvent(cmd=ReportToCoreCommand.REPORT_GENERATED)
        self.report_to_core_queue.put(event)

    def report_exported(self):
        """
        Sends a REPORT_EXPORTED event notifying core of successful report export.
        """
        event = ReportToCoreEvent(cmd=ReportToCoreCommand.REPORT_EXPORTED)
        self.report_to_core_queue.put(event)

    def stop(self):
        """
        Sends a STOP command event to stop the Report module.
        """
        event = ReportToCoreEvent(cmd=ReportToCoreCommand.STOP)
        self.report_to_core_queue.put(event)

    def report_error(self, error: ModuleErrorEvent):
        """
        Sends a ModuleErrorEvent instance directly to Core for error reporting.
        """
        self.report_to_core_queue.put(error)
