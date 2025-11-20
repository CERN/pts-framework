# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from abc import ABC, abstractmethod
from queue import Queue, Empty
from pypts.sequencer.SEQUENCER_MESSAGES import *
from pypts.common.COMMON_MESSAGES import *

"""
Abstract interface class defining messages that the Sequencer module sends to Core.
All messages added here must be implemented by a data layer class using queues.
"""

class SequencerToCoreInterface(ABC):
    """
    Interface used by the Sequencer module to communicate with Core.
    Defines commands to send sequence results, stop signals, and error reports.
    """

    @abstractmethod
    def sequence_result(self, text: str):
        """
        Sends the result of a sequence execution back to Core.

        Args:
            text (str): Description or summary of the sequence outcome.
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Command to stop the Sequencer module.
        """
        pass

    @abstractmethod
    def report_error(self, error: ModuleErrorEvent):
        """
        Sends an error event wrapped in ModuleErrorEvent to Core.
        """
        pass

    @abstractmethod
    def send_heartbeat(self, time: float):
        """
        Sends an heartbeat event to Core.
        """
        pass

"""
Concrete data layer class implementing SequencerToCoreInterface.
It sends appropriate SequencerToCoreEvent messages or error objects through a queue.
"""

class SequencerToCoreQueue(SequencerToCoreInterface):
    """
    Implements communication using an inter-process queue to send sequencer messages to Core.
    """

    def __init__(self, sequencer_to_core_queue: Queue):
        """
        Initialize with the queue object used to send messages from Sequencer to Core.
        """
        self.sequencer_to_core_queue = sequencer_to_core_queue

    def sequence_result(self, text: str):
        """
        Wraps the sequence result in a SequencerToCoreEvent and puts it on the queue.
        """
        event = SequencerToCoreEvent(cmd=SequencerToCoreCommand.SEQUENCE_RESULT, payload={"sequence_name": text})
        self.sequencer_to_core_queue.put(event)

    def stop(self):
        """
        Sends a STOP command event to Core via the queue.
        """
        event = SequencerToCoreEvent(cmd=SequencerToCoreCommand.STOP)
        self.sequencer_to_core_queue.put(event)

    def report_error(self, error: ModuleErrorEvent):
        # Here, encode the error as a message payload with error command
        event = SequencerToCoreEvent(cmd=SequencerToCoreCommand.ERROR, payload={
            "source": error.source,
            "severity": error.severity.name,
            "message": error.message,
            "exception": error.exception,
            "traceback": error.traceback,
        })
        self.sequencer_to_core_queue.put(event)

    def send_heartbeat(self, time: float):
        # Construct heartbeat event and send to Core
        heartbeat_event = SequencerToCoreEvent(
            cmd=SequencerToCoreCommand.HEARTBEAT,
            payload={"timestamp": time}
        )
        self.sequencer_to_core_queue.put(heartbeat_event)
