from dataclasses import dataclass
from enum import Enum, auto


class ReportCommand(Enum):
    EXIT = auto()
    REPORT_GENERATED = auto()


@dataclass
class ReportMessage:
    """Message sent from Report to Core."""
    cmd: ReportCommand
    payload: dict | None = None
