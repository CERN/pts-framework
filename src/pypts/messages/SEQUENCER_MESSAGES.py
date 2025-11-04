from dataclasses import dataclass
from enum import Enum, auto


class SequencerCommand(Enum):
    EXIT = auto()
    SEQUENCE_RESULT = auto()


@dataclass
class SequencerMessage:
    """Message sent from Sequencer to Core."""
    cmd: SequencerCommand
    payload: dict | None = None
