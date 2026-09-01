# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The recipes this operator opened last, kept between runs.

**This is state, not a cache**, and the distinction decided where the file goes
and how it behaves. A cache is a disposable copy of something that can be
recomputed - delete it and the application only does the work again. Nothing
can recompute which recipes somebody opened last week: delete this file and the
information is gone. So it lives in `file_locations.state_dir()` rather than a
cache directory that OS cleanup tools treat as free to wipe.

It stores **references, not copies**. An entry is a path, the recipe's name and
when it was opened; opening a recent recipe re-reads the file from disk, so the
operator always runs the current version of it. Keeping a snapshot of the YAML
here would go stale silently the moment somebody edited the original, which is
the one failure a test bench must not have.

Three rules:

**Only recipes that loaded get in.** The GUI calls `remember()` when CORE has
answered `RecipeLoaded`, never when the file was merely chosen - a path that
does not parse is not something to offer again.

**A file that cannot be used is discarded, never repaired.** Truncated by a
kill mid-write, hand-edited into nonsense, or written by a future pypts: the
whole file is dropped for this run, the reason is a WARNING in the log, and the
list starts empty. This is `config_handler`'s rule, for the same reason - the
list is a convenience, and a convenience must never be able to stop the GUI
from starting. Individual entries are weaker still: one unusable row is dropped
on its own and the other nine survive.

**Nothing here raises.** A read-only state directory costs the operator the
list, not the run.

Two pypts instances writing at once is last-writer-wins, and one of them may
lose an entry. That is acceptable for this data; it does not justify a lock.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pypts.config_handler import file_locations
from pypts.logger.log import log

#: How many recipes the list holds. The oldest falls off the end.
MAX_ENTRIES = 10

#: Structure version of the file. A file declaring anything else is discarded
#: rather than guessed at - the same bargain config_handler strikes.
STORE_VERSION = 1


@dataclass(frozen=True, slots=True)
class RecentEntry:
    """One remembered recipe. Frozen, like every other value in pypts."""

    path: str
    recipe_name: str
    opened_at: str

    @property
    def file_name(self) -> str:
        """What the menu shows; the full path goes in the tooltip."""
        return Path(self.path).name


class RecentRecipes:
    """
    The recent-recipes list, read on construction and rewritten on every change.

    Deliberately not a singleton and deliberately not shared: the GUI builds one
    and keeps it. It holds no Qt and knows nothing about messages, so it is
    ordinary Python to test.
    """

    def __init__(self) -> None:
        self._entries: list[RecentEntry] = self._load()

    # --- Reading ---------------------------------------------------------------

    def entries(self) -> list[RecentEntry]:
        """Most recently opened first. A copy, so a caller cannot corrupt us."""
        return list(self._entries)

    # --- Changing --------------------------------------------------------------

    def remember(self, recipe_path: str, recipe_name: str) -> None:
        """Put this recipe at the front, having loaded successfully."""
        resolved = self._resolve(recipe_path)
        entry = RecentEntry(
            path=resolved,
            recipe_name=recipe_name,
            # Naive local time, deliberately: everything else pypts writes for a
            # human to read is local time with no offset.
            opened_at=datetime.now().isoformat(timespec="seconds"),  # noqa: DTZ005
        )
        self._entries = [entry] + [e for e in self._entries if e.path != resolved]
        del self._entries[MAX_ENTRIES:]
        self._save()

    def forget(self, recipe_path: str) -> None:
        """Drop one entry - the GUI calls this when a remembered file is gone."""
        resolved = self._resolve(recipe_path)
        remaining = [entry for entry in self._entries if entry.path != resolved]
        if len(remaining) == len(self._entries):
            return
        self._entries = remaining
        self._save()

    def clear(self) -> None:
        """The menu's "Clear list"."""
        self._entries = []
        self._save()

    # --- The file --------------------------------------------------------------

    @staticmethod
    def _resolve(recipe_path: str) -> str:
        """
        The key entries are compared by.

        `resolve()` so that `a.yml` and `./a.yml` are one entry rather than two.
        It is allowed to fail - a path on an unmounted share still deserves to
        be remembered - in which case the path is kept as it was given.
        """
        try:
            return str(Path(recipe_path).resolve())
        except OSError:
            return recipe_path

    def _load(self) -> list[RecentEntry]:
        """Whatever the file holds, or an empty list. Never raises."""
        path = file_locations.recent_recipes_path()
        if not path.is_file():
            return []

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Discarding the recent-recipes list, it cannot be read: %s", exc)
            return []

        if not isinstance(payload, dict) or payload.get("version") != STORE_VERSION:
            log.warning(
                "Discarding the recent-recipes list, it is not a version %d store: %s",
                STORE_VERSION,
                path,
            )
            return []

        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            log.warning("Discarding the recent-recipes list, its entries are not a list.")
            return []

        entries = []
        for raw in raw_entries[:MAX_ENTRIES]:
            entry = self._entry_from(raw)
            if entry is not None:
                entries.append(entry)
        return entries

    @staticmethod
    def _entry_from(raw: object) -> RecentEntry | None:
        """One row, or None if it is not usable. One bad row costs only itself."""
        if not isinstance(raw, dict):
            return None
        path = raw.get("path")
        if not isinstance(path, str) or path == "":
            return None
        name = raw.get("recipe_name")
        opened_at = raw.get("opened_at")
        return RecentEntry(
            path=path,
            recipe_name=name if isinstance(name, str) else Path(path).name,
            opened_at=opened_at if isinstance(opened_at, str) else "",
        )

    def _save(self) -> None:
        """
        Rewrite the file, atomically, and never raise.

        Written to a temporary file beside the real one and moved into place, so
        that a kill mid-write leaves the previous list intact rather than a
        truncated one. `os.replace` is atomic on both platforms.
        """
        path = file_locations.recent_recipes_path()
        payload = {
            "version": STORE_VERSION,
            "entries": [
                {
                    "path": entry.path,
                    "recipe_name": entry.recipe_name,
                    "opened_at": entry.opened_at,
                }
                for entry in self._entries
            ],
        }

        temporary = path.with_suffix(".json.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(temporary, path)
        except OSError as exc:
            log.warning("Could not save the recent-recipes list: %s", exc)
