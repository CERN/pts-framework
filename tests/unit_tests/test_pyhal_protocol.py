"""Tests for the pyhal wire protocol: values, messages, codec."""

import io
import json
import math
from typing import Any, get_args

import pytest

from pyhal.protocol import codec, messages, values
from pyhal.protocol.codec import MalformedLine, MessageTooLarge
from pyhal.protocol.messages import CLIENT_KINDS, HAL_KINDS, ClientToHal, HalToClient


def _round_trip(value: Any) -> Any:
    return values.from_wire(json.loads(json.dumps(values.to_wire(value))))


def test_plain_values_round_trip() -> None:
    for value in (None, True, 3, 2.5, "x", [1, "a"], {"k": [1.5]}):
        assert _round_trip(value) == value
    result = _round_trip((1, 2))
    assert result == [1, 2]
    assert type(result) is list


def test_nan_inf_and_bytes_use_tagged_forms() -> None:
    assert values.to_wire(float("nan")) == {"$float": "nan"}
    assert values.to_wire(float("inf")) == {"$float": "inf"}
    assert values.to_wire(float("-inf")) == {"$float": "-inf"}
    assert values.to_wire(b"\x00\xff") == {"$bytes": "AP8="}
    assert math.isnan(values.from_wire({"$float": "nan"}))
    assert values.from_wire({"$float": "inf"}) == float("inf")
    assert values.from_wire({"$float": "-inf"}) == float("-inf")
    assert values.from_wire({"$bytes": "AP8="}) == b"\x00\xff"


def test_refused_values_name_their_path() -> None:
    with pytest.raises(ValueError) as error:
        values.to_wire({"a": [object()]})
    assert str(error.value) == "value['a'][0]: object cannot be sent"
    with pytest.raises(ValueError) as error:
        values.to_wire({1: 2})
    assert str(error.value) == "value: dict key 1 is not a string"
    with pytest.raises(ValueError) as error:
        values.to_wire({"$x": 1})
    assert str(error.value) == "value: dict key '$x' starts with '$'"

    class F(float):
        pass

    with pytest.raises(ValueError):
        values.to_wire(F(1.0))


def test_every_kind_has_a_dataclass_and_every_union_member_a_kind() -> None:
    assert set(CLIENT_KINDS.values()) == set(get_args(ClientToHal))
    assert set(HAL_KINDS.values()) == set(get_args(HalToClient))


def test_build_refuses_a_misspelt_kind_or_field() -> None:
    with pytest.raises(ValueError):
        messages.build(CLIENT_KINDS, "cal")
    with pytest.raises(ValueError):
        messages.build(CLIENT_KINDS, "open", devise="x")


def _samples() -> list[Any]:
    return [
        messages.Open("d"),
        messages.Call("d", "op", [1, b"\x01", float("inf")], {"k": [2.5]}),
        messages.Recover("d"),
        messages.Info("d"),
        messages.Close("d"),
        messages.CloseAll(),
        messages.Shutdown(),
        messages.Status(),
        messages.Beat(),
        messages.Hello(1, None, "1.0", "bench", "abc", "log.txt", ["d"], 2),
        messages.Opened("d", "type", ["op"]),
        messages.Result({"a": [1, None]}),
        messages.Recovered("d"),
        messages.DeviceInfo("d", "type", ["op"], True),
        messages.Closed("d"),
        messages.ClosedAll(["d"]),
        messages.Bye(),
        messages.StatusReport(1, "1.0", "b", "log", 1, None, 0, [{"name": "d"}]),
        messages.Error("driver", "boom"),
    ]


def test_encode_decode_round_trip_for_every_kind() -> None:
    samples = _samples()
    assert {type(m) for m in samples} == set(CLIENT_KINDS.values()) | set(HAL_KINDS.values())
    for message in samples:
        table = CLIENT_KINDS if type(message) in CLIENT_KINDS.values() else HAL_KINDS
        line = codec.encode(message)
        assert line.endswith(b"\n")
        assert line.count(b"\n") == 1
        assert codec.decode(line, table) == message


def test_decode_refuses_malformed_lines() -> None:
    nested = b'{"kind":"result","value":' + b"[" * 70 + b"]" * 70 + b"}\n"
    lines = [
        (b"not json\n", HAL_KINDS),
        (b'{"kind":"open"}\n', CLIENT_KINDS),
        (b'{"kind":"nope"}\n', CLIENT_KINDS),
        (b'{"kind":"result","value":NaN}\n', HAL_KINDS),
        (nested, HAL_KINDS),
        (b"\xff\n", HAL_KINDS),
        (b"[1]\n", HAL_KINDS),
        (b'{"kind":"result","value":1e999}\n', HAL_KINDS),
    ]
    for line, table in lines:
        with pytest.raises(MalformedLine):
            codec.decode(line, table)


def test_an_oversized_message_is_refused_before_sending() -> None:
    with pytest.raises(MessageTooLarge):
        codec.encode(messages.Result("x" * (17 * 1024 * 1024)))


def test_read_line_stops_at_the_limit() -> None:
    stream = io.BytesIO(b"a" * (codec.MAX_MESSAGE_BYTES + 10))
    with pytest.raises(MalformedLine, match="line too long"):
        codec.read_line(stream)
    assert stream.tell() == codec.MAX_MESSAGE_BYTES + 1
    assert codec.read_line(io.BytesIO(b"")) is None
    assert codec.read_line(io.BytesIO(b"x\ny\n")) == b"x\n"


def test_decode_refuses_a_field_named_like_builds_parameters() -> None:
    for line in (b'{"kind":"open","table":1}\n', b'{"kind":"open","device":"d","x":1}\n'):
        with pytest.raises(MalformedLine):
            codec.decode(line, CLIENT_KINDS)


def test_decode_refuses_wrong_field_types() -> None:
    call = b'{"kind":"call","device":"d","operation":"o","args":%s,"kwargs":%s}\n'
    hello = (
        b'{"kind":"hello","pid":%s,"nonce":null,"version":"v","bench":"b",'
        b'"bench_sha256":"s","log":"l","open":[],"clients":1}\n'
    )
    cases: list[tuple[bytes, dict[str, type]]] = [
        (call % (b'"x"', b"{}"), CLIENT_KINDS),
        (call % (b"[]", b"5"), CLIENT_KINDS),
        (b'{"kind":"open","device":5}\n', CLIENT_KINDS),
        (b'{"kind":5,"device":"d"}\n', CLIENT_KINDS),
        (hello % b"true", HAL_KINDS),
        (b'{"kind":"opened","device":"d","device_type":"t","operations":[1]}\n', HAL_KINDS),
    ]
    for line, table in cases:
        with pytest.raises(MalformedLine):
            codec.decode(line, table)
    assert codec.decode(hello % b"7", HAL_KINDS).pid == 7


def test_tagged_forms_round_trip_in_every_field() -> None:
    message = messages.StatusReport(
        1, "v", "b", "l", 1, {"x": b"\x01"}, 0, [{"last_error": float("inf")}]
    )
    assert codec.decode(codec.encode(message), HAL_KINDS) == message
    status = (
        b'{"kind":"status","pid":1,"version":"v","bench":"b","log":"l","clients":1,'
        b'"busy":null,"queued":0,"devices":[%s]}\n'
    )
    for tag in (b'{"$float":"zz"}', b'{"$bytes":"!!"}'):
        with pytest.raises(MalformedLine):
            codec.decode(status % tag, HAL_KINDS)


def test_encode_refuses_too_deep_or_circular_values() -> None:
    deep: list[Any] = []
    for _ in range(100):
        deep = [deep]
    with pytest.raises(ValueError, match="nested deeper"):
        codec.encode(messages.Result(deep))
    loop: list[Any] = []
    loop.append(loop)
    with pytest.raises(ValueError, match="nested deeper"):
        codec.encode(messages.Result(loop))


def test_kind_of_refuses_a_non_message() -> None:
    with pytest.raises(ValueError, match="not a protocol message"):
        messages.kind_of("x")  # type: ignore[arg-type]
