"""
The HAL wire messages: one frozen dataclass per message, two unions, two kind tables.

Kinds are the snake_case of the request (`open`, `call`, ...) and, for answers, `hello`,
`opened`, `result`, ... Requests and answers have separate tables, so `info` names `Info` in
one and `DeviceInfo` in the other. Field names are the wire field names.
"""

import importlib.metadata
from dataclasses import dataclass, fields
from types import UnionType
from typing import Any, Never, NoReturn, get_args, get_origin

# --- Client to HAL ---------------------------------------------------------------------


@dataclass(frozen=True)
class Open:
    device: str


@dataclass(frozen=True)
class Call:
    device: str
    operation: str
    args: list[Any]
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class Recover:
    device: str


@dataclass(frozen=True)
class Info:
    device: str


@dataclass(frozen=True)
class Close:
    device: str


@dataclass(frozen=True)
class CloseAll:
    pass


@dataclass(frozen=True)
class Shutdown:
    pass


@dataclass(frozen=True)
class Status:
    pass


@dataclass(frozen=True)
class Beat:
    pass


ClientToHal = Open | Call | Recover | Info | Close | CloseAll | Shutdown | Status | Beat

# --- HAL to client ---------------------------------------------------------------------


@dataclass(frozen=True)
class Hello:
    pid: int
    nonce: str | None
    version: str
    bench: str
    bench_sha256: str
    log: str
    open: list[str]
    clients: int


@dataclass(frozen=True)
class Opened:
    device: str
    device_type: str
    operations: list[str]


@dataclass(frozen=True)
class Result:
    value: Any


@dataclass(frozen=True)
class Recovered:
    device: str


@dataclass(frozen=True)
class DeviceInfo:
    device: str
    device_type: str
    operations: list[str]
    is_open: bool


@dataclass(frozen=True)
class Closed:
    device: str


@dataclass(frozen=True)
class ClosedAll:
    not_torn_down: list[str]


@dataclass(frozen=True)
class Bye:
    pass


@dataclass(frozen=True)
class StatusReport:
    pid: int
    version: str
    bench: str
    log: str
    clients: int
    busy: dict[str, Any] | None
    queued: int
    devices: list[dict[str, Any]]


@dataclass(frozen=True)
class Error:
    #: One of "driver", "hal", "protocol".
    origin: str
    message: str


HalToClient = (
    Hello
    | Opened
    | Result
    | Recovered
    | DeviceInfo
    | Closed
    | ClosedAll
    | Bye
    | StatusReport
    | Error
)

CLIENT_KINDS: dict[str, type] = {
    "open": Open,
    "call": Call,
    "recover": Recover,
    "info": Info,
    "close": Close,
    "close_all": CloseAll,
    "shutdown": Shutdown,
    "status": Status,
    "beat": Beat,
}

HAL_KINDS: dict[str, type] = {
    "hello": Hello,
    "opened": Opened,
    "result": Result,
    "recovered": Recovered,
    "info": DeviceInfo,
    "closed": Closed,
    "closed_all": ClosedAll,
    "bye": Bye,
    "status": StatusReport,
    "error": Error,
}

_KIND_OF_CLASS: dict[type, str] = {}
for _table in (CLIENT_KINDS, HAL_KINDS):
    for _kind, _class in _table.items():
        _KIND_OF_CLASS[_class] = _kind


def kind_of(message: ClientToHal | HalToClient) -> str:
    """The wire kind string of a message."""
    kind = _KIND_OF_CLASS.get(type(message))
    if kind is None:
        raise ValueError(f"{type(message).__name__} is not a protocol message")
    return kind


def hal_version() -> str:
    """
    The version `hello` and `status` carry, and a client compares with its own: that of the
    installed `pts-framework` distribution, `unknown` when it is not installed.
    """
    try:
        return importlib.metadata.version("pts-framework")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def build(table: dict[str, type], kind: str, /, **fields_given: Any) -> Any:
    """
    Build the message of `kind` from `table`. An unknown kind, an unknown field, a missing
    field or a field of the wrong type raises ValueError, before anything is encoded.
    `table` and `kind` are positional-only, so a field may be called either.
    """
    message_class = table.get(kind)
    if message_class is None:
        raise ValueError(f"unknown message kind {kind!r}")
    wanted = {field.name for field in fields(message_class)}
    unknown = sorted(set(fields_given) - wanted)
    if unknown:
        raise ValueError(f"{kind}: unknown field(s) {unknown}")
    missing = sorted(wanted - set(fields_given))
    if missing:
        raise ValueError(f"{kind}: missing field(s) {missing}")
    for field in fields(message_class):
        if not _matches(field.type, fields_given[field.name]):
            raise ValueError(f"{kind}: field {field.name!r} has the wrong type")
    return message_class(**fields_given)


def _matches(annotation: Any, value: Any) -> bool:
    """Does `value` fit the annotation? Exact: a bool is not an int."""
    if annotation is Any:
        return True
    if annotation is type(None):
        return value is None
    origin = get_origin(annotation)
    if origin is UnionType:
        return any(_matches(member, value) for member in get_args(annotation))
    if origin is list:
        if type(value) is not list:
            return False
        (item_type,) = get_args(annotation)
        return all(_matches(item_type, item) for item in value)
    if origin is dict:
        if type(value) is not dict:
            return False
        _key_type, value_type = get_args(annotation)
        return all(type(key) is str and _matches(value_type, item) for key, item in value.items())
    return type(value) is annotation


def unhandled(message: Never) -> NoReturn:
    """Typed `Never`, so an unmatched member is a type error, and it raises here."""
    raise TypeError(f"No handler for message: {message!r}")
