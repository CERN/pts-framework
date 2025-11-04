from dataclasses import dataclass
from enum import Enum, auto


class CoreCommand(Enum):
    EXIT = auto()
    RUN_SEQUENCE = auto()
    GENERATE_REPORT = auto()


@dataclass
class CoreMessage:
    """Message sent from HMI to Core."""
    cmd: CoreCommand
    payload: dict | None = None
