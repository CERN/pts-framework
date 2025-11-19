# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, Empty
from pypts.core.CORE_MESSAGES import CoreToSequencerEvent, CoreToSequencerCommand
from abc import ABC, abstractmethod

"""
Interface class that defines methods available for other modules.
All messages added here must be implemented by a data layer class (e.g., a queue).
"""

class CoreToSequencerInterface(ABC):
    """
    Abstract base class defining the interface used by the Core module
    to communicate with the Sequencer module.
    Each method corresponds to a command the Core can send to the Sequencer.
    """

    @abstractmethod
    def run_sequence(self):
        """Command to tell the sequencer to start running a sequence."""
        pass

    @abstractmethod
    def stop_sequence(self):
        """Command to tell the sequencer to stop the ongoing sequence."""
        pass

    @abstractmethod
    def stop(self):
        """Command to stop the sequencer module entirely."""
        pass

"""
Data layer class implementing the CoreToSequencerInterface.
This class wraps a multiprocessing Queue to send commands as events to the Sequencer.
"""

class CoreToSequencerQueue(CoreToSequencerInterface):
    """
    Implements the interface by placing appropriate CoreToSequencerEvent messages
    onto the inter-process communication queue.
    """

    def __init__(self, core_to_sequencer_queue: Queue):
        """
        Initialize with the queue used for communication from Core to Sequencer.
        """
        self.core_to_sequencer_queue = core_to_sequencer_queue

    def run_sequence(self):
        """
        Send a RUN_SEQUENCE command event to the Sequencer via the queue.
        """
        event = CoreToSequencerEvent(cmd=CoreToSequencerCommand.RUN_SEQUENCE)
        self.core_to_sequencer_queue.put(event)

    def stop_sequence(self):
        """
        Send a STOP_SEQUENCE command event to stop the currently running sequence.
        """
        event = CoreToSequencerEvent(cmd=CoreToSequencerCommand.STOP_SEQUENCE)
        self.core_to_sequencer_queue.put(event)

    def stop(self):
        """
        Send a STOP command event to stop the entire Sequencer module.
        """
        event = CoreToSequencerEvent(cmd=CoreToSequencerCommand.STOP)
        self.core_to_sequencer_queue.put(event)
