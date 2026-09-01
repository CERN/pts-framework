# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the recent-recipes store (src/pypts/utilities/recent_recipes.py).

Every test runs against a file in `tmp_path`: the `store` fixture monkeypatches
`file_locations.recent_recipes_path`, which is the only place the store asks
where its file is. Nothing here touches the real per-user state directory.

The two that matter beyond ordinary coverage are the corruption tests. This
file is app-owned and rewritten constantly, so it is the one most likely to be
found truncated or hand-mangled - and a recents list must never be able to stop
the GUI from starting. Both assert the same rule: discard, log, carry on empty.
"""

import json

import pytest

from pypts.config_handler import file_locations
from pypts.utilities.recent_recipes import MAX_ENTRIES, RecentEntry, RecentRecipes


@pytest.fixture
def store_path(tmp_path, monkeypatch):
    """Point the store at tmp_path; the real state directory is never touched."""
    path = tmp_path / "recent_recipes.json"
    monkeypatch.setattr(file_locations, "recent_recipes_path", lambda: path)
    return path


@pytest.fixture
def store(store_path):
    return RecentRecipes()


@pytest.fixture
def recipe_file(tmp_path):
    """An existing .yml, since the store only ever remembers files that load."""
    path = tmp_path / "smoke_test.yml"
    path.write_text("name: smoke test\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Reading and writing
# --------------------------------------------------------------------------


def test_a_fresh_store_is_empty_and_writes_no_file(store, store_path):
    """Starting pypts must not create state before there is any to keep."""
    assert store.entries() == []
    assert not store_path.exists()


def test_remember_then_read_back_in_a_new_instance(store, store_path, recipe_file):
    """The point of the store: a second run of pypts sees the first run's list."""
    store.remember(str(recipe_file), "Smoke test")

    reloaded = RecentRecipes()
    entries = reloaded.entries()
    assert len(entries) == 1
    assert entries[0].recipe_name == "Smoke test"
    assert entries[0].path == str(recipe_file.resolve())
    assert entries[0].opened_at != ""


def test_the_file_is_json_a_human_can_read(store, store_path, recipe_file):
    """It is state, not a cache: someone should be able to open and fix it."""
    store.remember(str(recipe_file), "Smoke test")

    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["entries"][0]["recipe_name"] == "Smoke test"


# --------------------------------------------------------------------------
# Ordering, deduplication, cap
# --------------------------------------------------------------------------


def test_most_recent_first(store, tmp_path):
    first = tmp_path / "first.yml"
    second = tmp_path / "second.yml"
    for path in (first, second):
        path.write_text("x", encoding="utf-8")

    store.remember(str(first), "First")
    store.remember(str(second), "Second")

    assert [entry.recipe_name for entry in store.entries()] == ["Second", "First"]


def test_reopening_moves_an_entry_to_the_front_without_duplicating_it(store, tmp_path):
    """The whole reason entries are keyed by path rather than appended."""
    first = tmp_path / "first.yml"
    second = tmp_path / "second.yml"
    for path in (first, second):
        path.write_text("x", encoding="utf-8")

    store.remember(str(first), "First")
    store.remember(str(second), "Second")
    store.remember(str(first), "First")

    assert [entry.recipe_name for entry in store.entries()] == ["First", "Second"]


def test_the_same_file_reached_by_a_different_spelling_is_one_entry(store, tmp_path):
    """Paths are resolved before comparison, so ./a.yml and a.yml agree."""
    recipe = tmp_path / "recipe.yml"
    recipe.write_text("x", encoding="utf-8")

    store.remember(str(recipe), "Recipe")
    store.remember(str(tmp_path / "." / "recipe.yml"), "Recipe")

    assert len(store.entries()) == 1


def test_the_list_is_capped_and_drops_the_oldest(store, tmp_path):
    for index in range(MAX_ENTRIES + 3):
        recipe = tmp_path / f"recipe_{index}.yml"
        recipe.write_text("x", encoding="utf-8")
        store.remember(str(recipe), f"Recipe {index}")

    entries = store.entries()
    assert len(entries) == MAX_ENTRIES
    assert entries[0].recipe_name == f"Recipe {MAX_ENTRIES + 2}"
    assert entries[-1].recipe_name == "Recipe 3"


# --------------------------------------------------------------------------
# Forgetting
# --------------------------------------------------------------------------


def test_forget_removes_one_entry(store, tmp_path):
    first = tmp_path / "first.yml"
    second = tmp_path / "second.yml"
    for path in (first, second):
        path.write_text("x", encoding="utf-8")
    store.remember(str(first), "First")
    store.remember(str(second), "Second")

    store.forget(str(first))

    assert [entry.recipe_name for entry in store.entries()] == ["Second"]


def test_forgetting_something_absent_is_not_an_error(store, recipe_file):
    """The GUI forgets on a failed open; the entry may already be gone."""
    store.remember(str(recipe_file), "Smoke test")
    store.forget(str(recipe_file.parent / "never_seen.yml"))
    assert len(store.entries()) == 1


def test_clear_empties_the_list(store, recipe_file):
    store.remember(str(recipe_file), "Smoke test")
    store.clear()
    assert store.entries() == []
    assert RecentRecipes().entries() == []


# --------------------------------------------------------------------------
# A file that cannot be used - discard, log, carry on
# --------------------------------------------------------------------------


def test_a_corrupt_file_is_discarded_not_raised(store_path, caplog):
    """Truncated mid-write by a kill. The GUI must still start."""
    store_path.write_text('{"version": 1, "entries": [{"path":', encoding="utf-8")

    with caplog.at_level("WARNING"):
        entries = RecentRecipes().entries()

    assert entries == []
    assert "recent" in caplog.text.lower()


def test_a_file_of_the_wrong_shape_is_discarded(store_path):
    """Hand-edited into something that parses but is not a store."""
    store_path.write_text('["not", "a", "store"]', encoding="utf-8")
    assert RecentRecipes().entries() == []


def test_entries_that_are_not_usable_records_are_dropped_individually(store_path):
    """One bad row does not cost the operator the other nine."""
    payload = {
        "version": 1,
        "entries": [
            {"path": "C:/recipes/good.yml", "recipe_name": "Good", "opened_at": "x"},
            {"recipe_name": "No path at all"},
            "not even a mapping",
        ],
    }
    store_path.write_text(json.dumps(payload), encoding="utf-8")

    entries = RecentRecipes().entries()
    assert [entry.recipe_name for entry in entries] == ["Good"]


def test_a_future_version_is_discarded_rather_than_guessed_at(store_path):
    payload = {"version": 99, "entries": [{"path": "a", "recipe_name": "b", "opened_at": "c"}]}
    store_path.write_text(json.dumps(payload), encoding="utf-8")
    assert RecentRecipes().entries() == []


def test_a_write_that_fails_does_not_raise(store_path, monkeypatch, recipe_file):
    """A read-only state directory costs the list, never the run."""

    def refuse(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr("pypts.utilities.recent_recipes.os.replace", refuse)
    store = RecentRecipes()
    store.remember(str(recipe_file), "Smoke test")

    # The in-memory list is still correct; only the persistence was lost.
    assert len(store.entries()) == 1


# --------------------------------------------------------------------------
# The entry itself
# --------------------------------------------------------------------------


def test_entry_exposes_the_file_name_for_the_menu_label(store, recipe_file):
    store.remember(str(recipe_file), "Smoke test")
    assert store.entries()[0].file_name == "smoke_test.yml"


def test_entry_is_frozen():
    entry = RecentEntry(path="a.yml", recipe_name="A", opened_at="2026-09-01T10:00:00")
    with pytest.raises(AttributeError):
        entry.path = "b.yml"  # type: ignore[misc]
