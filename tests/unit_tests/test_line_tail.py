"""LineTail alone: whole lines out of a growing file, no Qt."""

from pypts.hmi.gui.line_tail import LineTail


def test_whole_lines_holds_back_partial(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"a\nb")
    tail = LineTail(path)
    tail.open()
    assert tail.is_open
    assert tail.whole_lines() == ["a"]
    with path.open("ab") as handle:
        handle.write(b"c\n")
    assert tail.whole_lines() == ["bc"]
    assert tail.whole_lines() == []
    tail.close()


def test_strips_crlf(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"a\r\nb\r\n")
    tail = LineTail(path)
    tail.open()
    assert tail.whole_lines() == ["a", "b"]
    tail.close()


def test_close_twice_and_before_open(tmp_path):
    tail = LineTail(tmp_path / "f.txt")
    tail.close()
    assert not tail.is_open
    assert tail.whole_lines() == []
    (tmp_path / "f.txt").write_bytes(b"a\n")
    tail.open()
    tail.close()
    tail.close()
    assert not tail.is_open
