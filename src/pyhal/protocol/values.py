"""
Plain values: what may cross the wire, and how the awkward ones are tagged.

JSON cannot carry NaN, infinity or bytes, so those travel as one-key tagged dicts:
`{"$float": "nan" | "inf" | "-inf"}` and `{"$bytes": "<base64>"}`. A dict key that starts
with `$` is therefore refused in a value. Types are checked exactly (`type(x) is float`), so
numpy scalars and subclasses are refused instead of being sent as something else.
"""

import base64
import binascii
import math
from typing import Any, TypeAlias

PlainValue: TypeAlias = (
    bool | int | float | str | bytes | list["PlainValue"] | dict[str, "PlainValue"] | None
)

#: Deepest nesting of lists and dicts in a message, the message body itself being level 1.
MAX_DEPTH = 64

_FLOAT_TAG = "$float"
_BYTES_TAG = "$bytes"
_FLOAT_WORDS = {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf")}


def to_wire(value: Any, path: str = "value", depth: int = 1) -> Any:
    """
    Validate a value and encode it into JSON-safe form; ValueError names the path.
    `depth` is the nesting level of `value` itself (the message body is level 1); a list or
    dict nested deeper than MAX_DEPTH is refused, which also stops a circular value.
    """
    kind = type(value)
    if value is None or kind is bool or kind is int or kind is str:
        return value
    if kind is float:
        if math.isnan(value):
            return {_FLOAT_TAG: "nan"}
        if math.isinf(value):
            if value > 0:
                return {_FLOAT_TAG: "inf"}
            return {_FLOAT_TAG: "-inf"}
        return value
    if kind is bytes:
        return {_BYTES_TAG: base64.b64encode(value).decode("ascii")}
    if (kind is list or kind is tuple or kind is dict) and depth > MAX_DEPTH:
        raise ValueError(f"{path}: nested deeper than {MAX_DEPTH} levels")
    if kind is list or kind is tuple:
        return [to_wire(item, f"{path}[{index}]", depth + 1) for index, item in enumerate(value)]
    if kind is dict:
        encoded: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path}: dict key {key!r} is not a string")
            if key.startswith("$"):
                raise ValueError(f"{path}: dict key {key!r} starts with '$'")
            encoded[key] = to_wire(item, f"{path}[{key!r}]", depth + 1)
        return encoded
    raise ValueError(f"{path}: {kind.__name__} cannot be sent")


def from_wire(value: Any) -> Any:
    """Decode the tagged forms; a tuple never comes back. ValueError on a bad tag."""
    if isinstance(value, list):
        return [from_wire(item) for item in value]
    if isinstance(value, dict):
        if len(value) == 1:
            for key, item in value.items():
                if key == _FLOAT_TAG:
                    return _decode_float(item)
                if key == _BYTES_TAG:
                    return _decode_bytes(item)
        return {key: from_wire(item) for key, item in value.items()}
    return value


def _decode_float(word: Any) -> float:
    if type(word) is not str or word not in _FLOAT_WORDS:
        raise ValueError(f"bad {_FLOAT_TAG} tag: {word!r}")
    return _FLOAT_WORDS[word]


def _decode_bytes(text: Any) -> bytes:
    if type(text) is not str:
        raise ValueError(f"bad {_BYTES_TAG} tag: {text!r}")
    try:
        return base64.b64decode(text, validate=True)
    except binascii.Error as error:
        raise ValueError(f"bad {_BYTES_TAG} tag: {error}") from error
