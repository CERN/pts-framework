import csv
import logging
import threading
from pathlib import Path

import pytest

from pypts.stream_handler import (
    STREAMS_FOLDER,
    StreamError,
    StreamSession,
    abandon_active_session,
    register_stream,
    stream_csv_path,
    unit_from_header,
)


def read_rows(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def test_stream_csv_path_is_inside_streams(tmp_path: Path) -> None:
    assert STREAMS_FOLDER == "streams"
    assert stream_csv_path(tmp_path, "sine") == tmp_path / "streams" / "sine.csv"


def test_unsafe_names_stay_inside_streams(tmp_path: Path) -> None:
    for name in ["ch?1", "a/b", "V:out", "..\report"]:
        assert stream_csv_path(tmp_path, name).parent == tmp_path / "streams"
    assert stream_csv_path(tmp_path, "ch?1").name == "ch_1.csv"
    assert len(stream_csv_path(tmp_path, "a" * 100).stem) == 60


def test_header_with_and_without_unit(tmp_path: Path) -> None:
    with StreamSession(tmp_path) as session:
        with_unit = session.register("a", unit="V")
        without_unit = session.register("b")
    assert with_unit.unit == "V"
    assert without_unit.unit is None
    assert with_unit.path is not None and without_unit.path is not None
    assert read_rows(with_unit.path)[0] == ["x", "y [V]"]
    assert read_rows(without_unit.path)[0] == ["x", "y"]
    assert unit_from_header(["x", "y [V]"]) == "V"
    assert unit_from_header(["x", "y"]) is None


def test_push_scalar_and_arrays(tmp_path: Path) -> None:
    with StreamSession(tmp_path) as session:
        stream = session.register("sine")
        stream.push(0.0, 1.0)
        stream.push([0.1, 0.2], [2.0, 3.0])
    assert stream.path is not None
    rows = read_rows(stream.path)
    assert len(rows) == 4
    assert [(float(x), float(y)) for x, y in rows[1:]] == [(0.0, 1.0), (0.1, 2.0), (0.2, 3.0)]
    raw = stream.path.read_bytes()
    assert raw.endswith(b"\r\n")
    assert b"\r\r\n" not in raw


def test_push_unequal_lengths_raises(tmp_path: Path) -> None:
    with StreamSession(tmp_path) as session:
        stream = session.register("sine")
        with pytest.raises(ValueError):
            stream.push([1, 2], [1])


def test_reregister_appends_to_same_file(tmp_path: Path) -> None:
    with StreamSession(tmp_path) as session:
        first = session.register("sine")
        first.push(1, 2)
        first.close()
        second = session.register("sine")
        second.push(3, 4)
    assert second.path is not None
    rows = read_rows(second.path)
    assert rows == [["x", "y"], ["1", "2"], ["3", "4"]]


def test_push_after_close_is_dropped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with StreamSession(tmp_path) as session:
        stream = session.register("sine")
        stream.close()
        stream.close()
        assert stream.path is not None
        before = stream.path.read_bytes()
        with caplog.at_level(logging.DEBUG, logger="pypts.stream_handler"):
            stream.push(1, 1)
            stream.push(2, 2)
        assert stream.path.read_bytes() == before
        assert stream.closed is True
    dropped = [r for r in caplog.records if "sine" in r.getMessage()]
    assert len(dropped) == 1
    assert dropped[0].levelno == logging.DEBUG


def test_push_after_session_close_is_dropped(tmp_path: Path) -> None:
    session = StreamSession(tmp_path)
    stream = session.register("sine")
    session.close()
    stream.push(1, 1)
    assert stream.closed is True


def test_stale_handle_never_writes_into_next_session(tmp_path: Path) -> None:
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    with StreamSession(folder_a) as session_a:
        old = session_a.register("sine")
    with StreamSession(folder_b):
        old.push(1, 1)
    assert not folder_b.exists()


def test_push_from_thread(tmp_path: Path) -> None:
    with StreamSession(tmp_path) as session:
        stream = session.register("sine")

        def push_many() -> None:
            for i in range(1000):
                stream.push(i, i)

        worker = threading.Thread(target=push_many)
        worker.start()
        push_many()
        worker.join()
    assert stream.path is not None
    rows = read_rows(stream.path)[1:]
    assert len(rows) == 2000
    for row in rows:
        assert len(row) == 2
        float(row[0])
        float(row[1])


def test_register_without_active_session_raises() -> None:
    with pytest.raises(StreamError):
        register_stream("sine")


def test_session_without_folder_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG, logger="pypts.stream_handler")
    with StreamSession(None) as session:
        assert session.records_streams is False
        stream = register_stream("sine")
        stream.push(1, 1)
        session.register("other")
    assert stream.path is None
    assert list(tmp_path.iterdir()) == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "sine" in warnings[0].getMessage()
    assert "no run folder" in warnings[0].getMessage()


def test_has_stream(tmp_path: Path) -> None:
    for folder in [tmp_path, None]:
        with StreamSession(folder) as session:
            assert session.has_stream("x") is False
            session.register("x")
            assert session.has_stream("x") is True


def test_closing_another_session_does_not_clear_active(tmp_path: Path) -> None:
    outer = StreamSession(tmp_path / "a")
    with outer:
        other = StreamSession(tmp_path / "b")
        other.close()
        stream = register_stream("x")
    assert stream.path == tmp_path / "a" / "streams" / "x.csv"
    assert not (tmp_path / "b").exists()


def test_abandon_active_session(tmp_path: Path) -> None:
    abandon_active_session()
    session = StreamSession(tmp_path)
    session.__enter__()
    stream = register_stream("x")
    abandon_active_session()
    assert stream.closed is True
    with pytest.raises(StreamError):
        register_stream("x")
    with pytest.raises(StreamError):
        session.register("y")


def test_register_after_close_writes_no_file(tmp_path: Path) -> None:
    session = StreamSession(tmp_path)
    session.close()
    stream = session.register("late")
    assert stream.path is None
    stream.push(1.0, 2.0)
    assert not (tmp_path / "streams").exists()


def test_has_stream_compares_file_safe_names(tmp_path: Path) -> None:
    with StreamSession(tmp_path) as session:
        session.register("ch 1")
        assert session.has_stream("ch_1") is True
        assert session.has_stream("ch 2") is False
