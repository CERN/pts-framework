"""
The LogFollower alone: two plain files, no Qt, no GUI.

The GUI tests in test_hmi_gui.py exercise the same rules through the window;
these pin the follower's ordering contract where it lives, without a
QApplication.
"""

from pypts.hmi.gui.log_follower import LogFollower


def a_record(level: str, message: str) -> str:
    """One line in the shape log.LOG_FORMAT writes: time;LEVEL;process;where;message."""
    return f"2026-09-01 12:04:31.123;{level};Core;core.py:handle_message;{message}"


def write_records(path, *messages):
    """Append records to a log file the way the Logger does - whole lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for message in messages:
            handle.write(a_record("INFO", message) + "\n")


def a_follower(session_path, failures=None):
    reported = failures if failures is not None else []
    return LogFollower(
        get_session_log_path=lambda: str(session_path),
        report_open_failure=lambda exc, operation: reported.append((exc, operation)),
    )


def shown(lines):
    """The messages in the lines, stripped of the level/time prefix."""
    return "\n".join(lines)


def test_lines_cross_the_run_log_switch_in_the_order_they_were_written(tmp_path):
    session = tmp_path / "pypts_session.log"
    run_log = tmp_path / "run" / "pypts_run.log"
    write_records(session, "Before the run.")
    follower = a_follower(session)
    assert follower.follow_session_log(str(session)) == []

    assert "Before the run." in shown(follower.poll())
    assert follower.follow_run_log(str(run_log)) == []
    write_records(run_log, "During the run.")
    assert "During the run." in shown(follower.poll())
    follower.run_finished()
    write_records(run_log, "Run summary: DONE.")
    write_records(session, "After the run.")
    lines = shown(follower.poll())

    assert lines.index("Run summary: DONE.") < lines.index("After the run.")
    assert follower.run_tail is None  # done with, and released
    follower.stop()


def test_a_run_shorter_than_one_tick_still_shows_its_lines_first(tmp_path):
    """run_finished() before the run log was ever opened: it is read, then released."""
    session = tmp_path / "pypts_session.log"
    run_log = tmp_path / "run" / "pypts_run.log"
    write_records(session, "Before the run.")
    follower = a_follower(session)
    follower.follow_session_log(str(session))
    follower.poll()

    follower.follow_run_log(str(run_log))
    follower.run_finished()
    write_records(run_log, "The whole run.")
    write_records(session, "After the run.")
    lines = shown(follower.poll())

    assert lines.index("The whole run.") < lines.index("After the run.")
    assert follower.run_tail is None
    follower.stop()


def test_a_run_log_that_never_appears_becomes_a_notice(tmp_path):
    session = tmp_path / "pypts_session.log"
    write_records(session, "Before the run.")
    follower = a_follower(session)
    follower.follow_session_log(str(session))
    follower.poll()

    missing = tmp_path / "missing" / "pypts_run.log"
    follower.follow_run_log(str(missing))
    follower._run_log_deadline = 0.0  # already past
    lines = follower.poll()

    assert f"Could not open the run log: {missing}" in lines
    assert follower.run_tail is None
    assert follower.is_active()  # the session log is still followed
    follower.stop()


def test_a_new_session_log_is_picked_up_after_an_unload(tmp_path):
    current = {"path": str(tmp_path / "pypts_1.log")}
    write_records(tmp_path / "pypts_1.log", "Before the unload.")
    follower = LogFollower(
        get_session_log_path=lambda: current["path"],
        report_open_failure=lambda exc, operation: None,
    )
    follower.follow_session_log(current["path"])
    follower.poll()

    follower.stop()
    current["path"] = str(tmp_path / "pypts_2.log")
    follower.expect_new_session_log()
    assert follower.is_active()
    assert follower.poll() == []  # the Logger has not created it yet

    write_records(tmp_path / "pypts_2.log", "After the unload.")
    follower.poll()
    assert "After the unload." in shown(follower.poll())
    follower.stop()


def test_a_new_session_log_that_never_appears_ends_the_wait(tmp_path):
    missing = tmp_path / "pypts_2.log"
    follower = a_follower(missing)
    follower.expect_new_session_log()
    follower._new_log_deadline = 0.0  # already past

    lines = follower.poll()

    assert f"Could not open the run log: {missing}" in lines
    assert follower.is_active() is False  # nothing left to tick for
