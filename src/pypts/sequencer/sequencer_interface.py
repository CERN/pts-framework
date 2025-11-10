# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, Empty
from pypts.core.CORE_MESSAGES import CoreToSequencerEvent, CoreToSequencerCommand
from abc import ABC, abstractmethod


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


class CoreToSequencerQueue(CoreToSequencerInterface):
    """Queue-based Sequencer wrapper implementing SequencerInterface."""

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

