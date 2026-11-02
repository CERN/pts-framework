"""StreamReader and read_whole_stream: the GUI's side of a stream CSV, no Qt."""

import csv
import logging

import numpy as np

from pypts.hmi.gui.stream_reader import StreamReader, read_whole_stream


def write_rows(path, *rows):
    """Append rows the way the stream writer does: csv.writer, newline=''."""
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow(row)


def test_reader_waits_for_file(tmp_path):
    path = tmp_path / "s.csv"
    reader = StreamReader(path)
    x, y = reader.poll()
    assert len(x) == 0
    assert len(y) == 0
    assert reader.exists is False
    write_rows(path, ["x", "y"], [0, 1])
    x, y = reader.poll()
    assert reader.exists is True
    assert list(x) == [0.0]
    assert list(y) == [1.0]
    reader.close()


def test_reader_reads_unit_and_rows(tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, ["x", "y [V]"], [0.0, 1.0], [0.1, 2.0])
    reader = StreamReader(path)
    assert reader.unit is None
    x, y = reader.poll()
    assert reader.unit == "V"
    assert list(x) == [0.0, 0.1]
    assert list(y) == [1.0, 2.0]
    reader.close()


def test_reader_returns_only_new_rows(tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, ["x", "y"], [0, 1], [1, 2])
    reader = StreamReader(path)
    reader.poll()
    write_rows(path, [2, 3])
    x, y = reader.poll()
    assert list(x) == [2.0]
    assert list(y) == [3.0]
    x, y = reader.poll()
    assert len(x) == 0
    reader.close()


def test_reader_holds_back_torn_row(tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, ["x", "y"], [0.0, 1.0])
    with path.open("a", newline="", encoding="utf-8") as handle:
        handle.write("0.2,3.")
    reader = StreamReader(path)
    x, _ = reader.poll()
    assert list(x) == [0.0]
    with path.open("a", newline="", encoding="utf-8") as handle:
        handle.write("5\r\n")
    x, y = reader.poll()
    assert list(x) == [0.2]
    assert list(y) == [3.5]
    reader.close()


def test_reader_handles_crlf(tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, ["x", "y"], [1, 2], [3, 4])
    assert b"\r\n" in path.read_bytes()
    reader = StreamReader(path)
    x, y = reader.poll()
    assert not np.isnan(x).any()
    assert not np.isnan(y).any()
    assert list(y) == [2.0, 4.0]
    reader.close()


def test_reader_skips_unparsable_row(tmp_path, caplog):
    path = tmp_path / "s.csv"
    write_rows(path, ["x", "y"], [0, 1], ["x", "oops"], [2, 3])
    reader = StreamReader(path)
    with caplog.at_level(logging.DEBUG):
        x, y = reader.poll()
    assert list(x) == [0.0, 2.0]
    assert list(y) == [1.0, 3.0]
    assert any(record.levelno == logging.DEBUG for record in caplog.records)
    reader.close()


def test_read_whole_stream_static(tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, ["x", "y [mV]"], [0, 1], [1, 2])
    result = read_whole_stream(path)
    assert result is not None
    unit, x, y = result
    assert unit == "mV"
    assert list(x) == [0.0, 1.0]
    assert list(y) == [1.0, 2.0]


def test_read_whole_stream_missing_returns_none(tmp_path):
    assert read_whole_stream(tmp_path / "nope.csv") is None


def test_non_finite_rows_are_skipped(tmp_path):
    path = tmp_path / "s.csv"
    write_rows(path, ["x", "y"], [0, 1], ["nan", 2], [2, "inf"], ["-inf", 3], [3, "nan"], [4, 5])
    reader = StreamReader(path)
    x, y = reader.poll()
    assert list(x) == [0.0, 4.0]
    assert list(y) == [1.0, 5.0]
    reader.close()
    _unit, x, y = read_whole_stream(path)
    assert list(x) == [0.0, 4.0]
    assert list(y) == [1.0, 5.0]
