# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, Empty
from pypts.core.CORE_MESSAGES import CoreToReportCommand, CoreToReportEvent
from abc import ABC, abstractmethod

"""
Interface class defining methods available for use by other modules.
Each message added here must be implemented by a data layer class (using queues).
"""

class CoreToReportInterface(ABC):
    """
    Abstract interface used by the Core module to communicate with the Report module.
    Each method corresponds to a command Core can send to Report.
    """

    @abstractmethod
    def generate_report(self):
        """Command to request report generation."""
        pass

    @abstractmethod
    def export_report(self):
        """Command to request exporting the generated report."""
        pass

    @abstractmethod
    def stop(self):
        """Command to stop the report module."""
        pass

"""
Data layer class that implements CoreToReportInterface,
using a multiprocessing queue to send event messages.
"""

class CoreToReportQueue(CoreToReportInterface):
    """
    Implementation of the interface sending CoreToReportEvent messages via queue.
    """

    def __init__(self, core_to_report_queue: Queue):
        """
        Initialize instance with the communication queue from Core to Report.
        """
        self.core_to_report_queue = core_to_report_queue

    def export_report(self):
        """
        Sends an EXPORT command event to the Report module via the queue.
        """
        event = CoreToReportEvent(cmd=CoreToReportCommand.EXPORT)
        self.core_to_report_queue.put(event)

    def generate_report(self):
        """
        Sends a GENERATE command event to instruct the Report module to generate a report.
        """
        event = CoreToReportEvent(cmd=CoreToReportCommand.GENERATE)
        self.core_to_report_queue.put(event)

    def stop(self):
        """
        Sends a STOP command event to stop the Report module.
        """
        event = CoreToReportEvent(cmd=CoreToReportCommand.STOP)
        self.core_to_report_queue.put(event)
