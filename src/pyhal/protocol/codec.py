"""
The line codec: one JSON object per line, UTF-8, newline-terminated, `kind` plus the fields.

Values go through `values.to_wire` / `values.from_wire`. Limits: a message over
`MAX_MESSAGE_BYTES` is refused on both sides, nesting deeper than `MAX_DEPTH` is refused on
receipt, and NaN / Infinity literals are not valid JSON here (they travel tagged).
"""

import json
import math
from dataclasses import fields
from typing import Any, BinaryIO, NoReturn

from pyhal.protocol.messages import ClientToHal, HalToClient, build, kind_of
from pyhal.protocol.values import MAX_DEPTH, from_wire, to_wire

MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class MalformedLine(Exception):
    """A received line is not a valid message."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MessageTooLarge(Exception):
    """An encoded message is over MAX_MESSAGE_BYTES."""

    def __init__(self, size: int) -> None:
        super().__init__(f"message of {size} bytes is over the {MAX_MESSAGE_BYTES} limit")
        self.size = size


def encode(message: ClientToHal | HalToClient) -> bytes:
    """One newline-terminated line. ValueError names the bad path; MessageTooLarge over limit."""
    body: dict[str, Any] = {"kind": kind_of(message)}
    for field in fields(message):
        body[field.name] = to_wire(getattr(message, field.name), field.name, 2)
    text = json.dumps(body, separators=(",", ":"), allow_nan=False)
    data = text.encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise MessageTooLarge(len(data))
    return data + b"\n"


def _refuse_constant(name: str) -> NoReturn:
    raise ValueError(f"{name} is not allowed")


def _refuse_infinite(text: str) -> float:
    number = float(text)
    if math.isinf(number):
        raise ValueError(f"number {text} is out of range")
    return number


def _too_deep(value: Any) -> bool:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            children: Any = item.values()
        elif isinstance(item, list):
            children = item
        else:
            continue
        if depth > MAX_DEPTH:
            return True
        for child in children:
            stack.append((child, depth + 1))
    return False


def decode(line: bytes, table: dict[str, type]) -> Any:
    """Decode one line into a message of `table`; MalformedLine on anything wrong."""
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MalformedLine(f"bad UTF-8: {error}") from error
    try:
        body = json.loads(text, parse_constant=_refuse_constant, parse_float=_refuse_infinite)
    except RecursionError as error:
        raise MalformedLine("nested too deeply") from error
    except ValueError as error:
        raise MalformedLine(f"bad JSON: {error}") from error
    if _too_deep(body):
        raise MalformedLine("nested too deeply")
    if not isinstance(body, dict):
        raise MalformedLine("not a JSON object")
    kind = body.pop("kind", None)
    if type(kind) is not str:
        raise MalformedLine("missing kind")
    try:
        decoded = {name: from_wire(item) for name, item in body.items()}
        return build(table, kind, **decoded)
    except (ValueError, TypeError) as error:
        raise MalformedLine(str(error)) from error


def read_line(stream: BinaryIO) -> bytes | None:
    """
    The next line including its newline, or None at end of stream. Never reads more than
    MAX_MESSAGE_BYTES + 1 bytes of one line; a longer line raises MalformedLine("line too
    long"). The rest of that line is still in the stream, so the caller must close the
    connection after it; reading on would parse the tail of the line as a message.
    """
    line = stream.readline(MAX_MESSAGE_BYTES + 1)
    if not line:
        return None
    if len(line) > MAX_MESSAGE_BYTES and not line.endswith(b"\n"):
        raise MalformedLine("line too long")
    return line
