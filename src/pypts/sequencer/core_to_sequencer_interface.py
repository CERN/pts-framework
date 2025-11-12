# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, Empty
from pypts.core.CORE_MESSAGES import CoreToSequencerEvent, CoreToSequencerCommand
from abc import ABC, abstractmethod

"""
Interface class that defines methods available for other modules.
All messages that are added here needs to be implemented by a data layer class (queue)
"""
class CoreToSequencerInterface(ABC):
    """Core uses this interface to talk to Sequencer."""
    @abstractmethod
    def run_sequence(self):
        pass

    @abstractmethod
    def stop_sequence(self):
        pass

    @abstractmethod
    def stop(self):
        pass

"""
Data layer class, that exposes the interface to be used by modules.
It implements a communication layer (queue) and payloads for the messages.
"""
class CoreToSequencerQueue(CoreToSequencerInterface):
    def __init__(self, core_to_sequencer_queue: Queue):
        self.core_to_sequencer_queue = core_to_sequencer_queue

    def run_sequence(self):
        event = CoreToSequencerEvent(cmd=CoreToSequencerCommand.RUN_SEQUENCE)
        self.core_to_sequencer_queue.put(event)

    def stop_sequence(self):
        event = CoreToSequencerEvent(cmd=CoreToSequencerCommand.STOP_SEQUENCE)
        self.core_to_sequencer_queue.put(event)

    def stop(self):
        event = CoreToSequencerEvent(cmd=CoreToSequencerCommand.STOP)
        self.core_to_sequencer_queue.put(event)

