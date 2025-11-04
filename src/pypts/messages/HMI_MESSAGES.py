from dataclasses import dataclass
from enum import Enum, auto


class HMIEvent(Enum):
    INFO = auto()
    SEQUENCE_STARTED = auto()
    SEQUENCE_FINISHED = auto()
    REPORT_GENERATED = auto()
    ERROR = auto()


@dataclass
class HMIMessage:
    """Message sent from Core (and others) back to the HMI."""
    event: HMIEvent
    payload: dict | None = None
