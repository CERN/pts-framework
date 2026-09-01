# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for Remove Cache (src/pypts/utilities/data_removal.py).

**Every test passes all five locations explicitly.** `survey()` resolves them
from `file_locations` and the configuration when it is not told, which is what
the GUI does - but a test that let it do that would delete the developer's own
config, reports and logs the first time it ran. Nothing here is allowed near a
real path, and `test_survey_resolves_the_real_locations_when_not_told` is the
one test that checks resolution, with everything monkeypatched.

The guards earn their place beyond ordinary coverage: this module deletes
things, so the tests that assert it *refuses* matter more than the ones that
assert it succeeds.
"""

from pathlib import Path

import pytest

from pypts.utilities.data_removal import (
    RemovableItem,
    remove,
    survey,
    total_bytes,
)


@pytest.fixture
def locations(tmp_path):
    """A complete, populated pypts installation under tmp_path."""
    config_file = tmp_path / "config.ini"
    config_file.write_text("[paths]\n", encoding="utf-8")

    state_file = tmp_path / "recent_recipes.json"
    state_file.write_text('{"version": 1, "entries": []}', encoding="utf-8")

    reports_dir = tmp_path / "reports"
    for name in ("run_1", "run_2"):
        run = reports_dir / name
        run.mkdir(parents=True)
        (run / "report.html").write_text("x" * 100, encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    live_log = logs_dir / "pypts_now.log"
    live_log.write_text("y" * 50, encoding="utf-8")
    (logs_dir / "pypts_old.log").write_text("z" * 50, encoding="utf-8")

    return {
        "config_file": config_file,
        "state_file": state_file,
        "reports_dir": reports_dir,
        "logs_dir": logs_dir,
        "live_log": live_log,
    }


def surveyed(locations):
    return {item.key: item for item in survey(**locations)}


# --------------------------------------------------------------------------
# What the survey finds
# --------------------------------------------------------------------------


def test_all_four_categories_are_reported_in_a_fixed_order(locations):
    """The dialog lists them in this order; least to most precious."""
    keys = [item.key for item in survey(**locations)]
    assert keys == ["state", "config", "reports", "logs"]


def test_a_category_reports_its_size_and_count(locations):
    items = surveyed(locations)
    assert items["reports"].item_count == 2
    assert items["reports"].size_bytes == 200


def test_the_live_log_is_excluded_from_the_survey(locations):
    """It cannot be deleted while the Logger holds it open, so it is not offered."""
    logs = surveyed(locations)["logs"]

    assert logs.item_count == 1
    assert logs.size_bytes == 50
    assert locations["live_log"] not in logs.targets
    assert "in use" in logs.kept_note


def test_a_missing_category_is_still_listed_but_empty(tmp_path):
    """The dialog shows every category, so 'nothing to remove' is visible."""
    items = {
        item.key: item
        for item in survey(
            config_file=tmp_path / "nope.ini",
            state_file=tmp_path / "nope.json",
            reports_dir=tmp_path / "nope_reports",
            logs_dir=tmp_path / "nope_logs",
            live_log=None,
        )
    }
    assert all(item.item_count == 0 for item in items.values())
    assert all(item.size_bytes == 0 for item in items.values())
    assert total_bytes(items.values()) == 0


def test_total_bytes_adds_the_categories_up(locations):
    """config.ini + the recents file + two 100-byte reports + one 50-byte old log."""
    items = survey(**locations)

    expected = (
        locations["config_file"].stat().st_size
        + locations["state_file"].stat().st_size
        + 200
        + 50
    )
    assert total_bytes(items) == expected


# --------------------------------------------------------------------------
# What removal actually does
# --------------------------------------------------------------------------


def test_remove_deletes_every_surveyed_target(locations):
    outcome = remove(survey(**locations))

    assert not locations["config_file"].exists()
    assert not locations["state_file"].exists()
    assert list(locations["reports_dir"].iterdir()) == []
    assert outcome.failures == ()
    assert outcome.removed_count == 5


def test_the_live_log_survives_removal(locations):
    remove(survey(**locations))

    assert locations["live_log"].exists()
    assert locations["live_log"].read_text(encoding="utf-8") == "y" * 50


def test_the_directories_themselves_survive(locations):
    """Contents go; the folders stay, so the next run has somewhere to write."""
    remove(survey(**locations))

    assert locations["reports_dir"].is_dir()
    assert locations["logs_dir"].is_dir()


def test_removal_reports_the_bytes_it_freed(locations):
    items = survey(**locations)
    expected = total_bytes(items)

    outcome = remove(items)

    assert outcome.removed_bytes == expected


def test_a_target_that_cannot_be_deleted_is_reported_not_raised(locations, monkeypatch):
    """One locked file must not abort the other categories."""

    def refuse(path):
        raise PermissionError(f"in use: {path}")

    monkeypatch.setattr("pypts.utilities.data_removal.os.remove", refuse)

    outcome = remove(survey(**locations))

    assert outcome.failures != ()
    # The directory trees do not go through os.remove, so they still went.
    assert list(locations["reports_dir"].iterdir()) == []


def test_removing_nothing_is_not_an_error(tmp_path):
    outcome = remove(
        survey(
            config_file=tmp_path / "nope.ini",
            state_file=tmp_path / "nope.json",
            reports_dir=tmp_path / "nope_reports",
            logs_dir=tmp_path / "nope_logs",
            live_log=None,
        )
    )
    assert outcome.removed_count == 0
    assert outcome.removed_bytes == 0
    assert outcome.failures == ()


# --------------------------------------------------------------------------
# The guards - the tests that matter most here
# --------------------------------------------------------------------------


def test_a_directory_that_is_a_filesystem_root_is_refused(tmp_path):
    """A misconfigured reports_dir must not be able to empty a drive."""
    root = Path(tmp_path.anchor)

    items = survey(
        config_file=tmp_path / "config.ini",
        state_file=tmp_path / "state.json",
        reports_dir=root,
        logs_dir=tmp_path / "logs",
        live_log=None,
    )

    reports = {item.key: item for item in items}["reports"]
    assert reports.targets == ()
    assert "refused" in reports.kept_note.lower()


def test_the_home_directory_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    items = survey(
        config_file=tmp_path / "config.ini",
        state_file=tmp_path / "state.json",
        reports_dir=tmp_path,
        logs_dir=tmp_path / "logs",
        live_log=None,
    )

    reports = {item.key: item for item in items}["reports"]
    assert reports.targets == ()
    assert "refused" in reports.kept_note.lower()


def test_a_refused_directory_is_left_completely_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    keeper = tmp_path / "precious.txt"
    keeper.write_text("do not delete me", encoding="utf-8")

    remove(
        survey(
            config_file=tmp_path / "config.ini",
            state_file=tmp_path / "state.json",
            reports_dir=tmp_path,
            logs_dir=tmp_path / "logs",
            live_log=None,
        )
    )

    assert keeper.read_text(encoding="utf-8") == "do not delete me"


# --------------------------------------------------------------------------
# Resolution - the one test that exercises what the GUI calls
# --------------------------------------------------------------------------


def test_survey_resolves_the_real_locations_when_not_told(tmp_path, monkeypatch):
    """Everything monkeypatched: this must never see a real installation."""
    from pypts.config_handler import file_locations
    from pypts.utilities import data_removal

    monkeypatch.setattr(file_locations, "config_file_path", lambda: tmp_path / "c.ini")
    monkeypatch.setattr(file_locations, "recent_recipes_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(
        data_removal,
        "_configured_dir",
        lambda key: tmp_path / key,
    )
    monkeypatch.setattr(data_removal, "get_log_path", lambda: None)

    items = {item.key: item for item in survey()}

    assert items["config"].location == str(tmp_path / "c.ini")
    assert items["reports"].location == str(tmp_path / "paths.reports_dir")


def test_a_configuration_that_cannot_be_read_leaves_those_categories_empty(
    tmp_path, monkeypatch
):
    """Remove Cache must still open if the config is the thing that is broken."""
    from pypts.config_handler import file_locations
    from pypts.utilities import data_removal

    def broken(_key):
        raise OSError("no config")

    monkeypatch.setattr(file_locations, "config_file_path", lambda: tmp_path / "c.ini")
    monkeypatch.setattr(file_locations, "recent_recipes_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(data_removal, "_configured_dir", broken)
    monkeypatch.setattr(data_removal, "get_log_path", lambda: None)

    items = {item.key: item for item in survey()}

    assert items["reports"].targets == ()
    assert items["logs"].targets == ()


# --------------------------------------------------------------------------
# The value object
# --------------------------------------------------------------------------


def test_removable_item_is_frozen():
    item = RemovableItem(
        key="state",
        label="Recent recipes",
        detail="",
        location="",
        targets=(),
        size_bytes=0,
        item_count=0,
    )
    with pytest.raises(AttributeError):
        item.key = "config"  # type: ignore[misc]
