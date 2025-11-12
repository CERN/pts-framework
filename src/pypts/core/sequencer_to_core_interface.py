# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from abc import ABC, abstractmethod
from queue import Queue, Empty
from pypts.sequencer.SEQUENCER_MESSAGES import *
from pypts.common.COMMON_MESSAGES import *

"""
Interface class that defines methods available for other modules.
All messages that are added here needs to be implemented by a data layer class (queue)
"""
class SequencerToCoreInterface(ABC):
    """Sequencer uses this interface to talk to Core."""
    @abstractmethod
    def sequence_result(self, text: str):
        pass

    @abstractmethod
    def stop(self):
        pass

    @abstractmethod
    def report_error(self, error: ModuleErrorEvent):
        pass

"""
Data layer class, that exposes the interface to be used by modules.
It implements a communication layer (queue) and payloads for the messages.
"""
class SequencerToCoreQueue(SequencerToCoreInterface):
    def __init__(self, sequencer_to_core_queue: Queue):
        self.sequencer_to_core_queue = sequencer_to_core_queue

    def sequence_result(self, text: str):
        event = SequencerToCoreEvent(cmd=SequencerToCoreCommand.SEQUENCE_RESULT, payload={"sequence_name": text})
        self.sequencer_to_core_queue.put(event)

    def stop(self):
        event = SequencerToCoreEvent(cmd=SequencerToCoreCommand.STOP)
        self.sequencer_to_core_queue.put(event)

    def report_error(self, error: ModuleErrorEvent):
        self.sequencer_to_core_queue.put(error)
