# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
What "Remove Cache" removes, and the guards that stop it removing more.

This module deletes the operator's files, so it is written the way a delete
routine has to be: it finds out first (`survey()`), hands the caller a list to
show somebody, and only deletes what is in that list (`remove()`). Nothing here
decides on its own that something should go.

Four categories, listed least to most precious:

    state     the recent-recipes list      a convenience
    config    config.ini                   the user's settings, recreated on
                                           the next start from the template
    reports   every run folder             **test records** - real evidence
    logs      every run log                **test records**

Only the first is a *cache* in any real sense. Reports and logs are data: a
report is the evidence that a unit passed. This module exists because the
operator asked for one action that clears all four, and the GUI dialog names
what each one is before anything happens.

**Three guards, because the configuration is user-editable.**

*Named files, never their directory.* On Windows `state_dir()`, `config_dir()`
and the default `base_dir` all collapse onto `%LOCALAPPDATA%\\pypts`. Deleting a
*directory* would therefore take all four categories, and on a bench whose
`paths.base_dir` points somewhere shared it would take a great deal more. The
config and state files are deleted by name; reports and logs have their
*contents* removed and the folder itself left, so the next run has somewhere to
write.

*Roots and home are refused.* `paths.reports_dir` is a value in an INI file that
somebody may edit. If it resolves to a filesystem root or the user's home
directory, that category is dropped from the survey with a reason, and the
dialog shows the reason instead of a size.

*The live log is never offered.* The Logger process holds an open handler on
this run's log for as long as pypts is up, so on Windows it cannot be deleted
at all. It is excluded from the survey rather than attempted and reported as a
failure.

Nothing here raises: a target that will not go is counted as a failure and the
rest of the removal continues.
"""

import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pypts.config_handler import file_locations
from pypts.logger.log import get_log_path, log


@dataclass(frozen=True, slots=True)
class RemovableItem:
    """One category, as the dialog shows it and as `remove()` acts on it."""

    key: str
    label: str
    detail: str
    location: str
    targets: tuple[Path, ...]
    size_bytes: int
    item_count: int
    #: Why something in this category is staying: the live log, or a refused
    #: directory. Empty when everything found is going.
    kept_note: str = ""


@dataclass(frozen=True, slots=True)
class RemovalOutcome:
    """What actually happened. Handed straight to the dialog's result view."""

    removed_bytes: int = 0
    removed_count: int = 0
    failures: tuple[str, ...] = field(default=())


def total_bytes(items: Iterable[RemovableItem]) -> int:
    return sum(item.size_bytes for item in items)


# --- Finding out --------------------------------------------------------------


def survey(
    *,
    config_file: Path | None = None,
    state_file: Path | None = None,
    reports_dir: Path | None = None,
    logs_dir: Path | None = None,
    live_log: Path | None = None,
) -> list[RemovableItem]:
    """
    The four categories, with what each would cost to remove.

    Every argument may be passed in, and the tests always do: a test that let
    this resolve the real locations would delete the developer's own reports
    the first time it ran. The GUI passes nothing and gets the real thing.
    """
    if config_file is None:
        config_file = file_locations.config_file_path()
    if state_file is None:
        state_file = file_locations.recent_recipes_path()
    if reports_dir is None:
        reports_dir = _configured_dir_or_none("paths.reports_dir")
    if logs_dir is None:
        logs_dir = _configured_dir_or_none("paths.logs_dir")
    if live_log is None:
        live_log = _live_log_path()

    return [
        _file_item(
            key="state",
            label="Recent recipes",
            detail="The File → Open Recent list.",
            path=state_file,
        ),
        _file_item(
            key="config",
            label="Configuration",
            detail="config.ini. Recreated from the template on the next start.",
            path=config_file,
        ),
        _directory_item(
            key="reports",
            label="Reports",
            detail="Every run folder: CSV and HTML results.",
            directory=reports_dir,
        ),
        _directory_item(
            key="logs",
            label="Run logs",
            detail="Every previous run log.",
            directory=logs_dir,
            keep=live_log,
        ),
    ]


def _file_item(*, key: str, label: str, detail: str, path: Path | None) -> RemovableItem:
    if path is None:
        return RemovableItem(key, label, detail, "", (), 0, 0, "Location unknown.")

    size = _size_of(path)
    exists = path.is_file()
    return RemovableItem(
        key=key,
        label=label,
        detail=detail,
        location=str(path),
        targets=(path,) if exists else (),
        size_bytes=size,
        item_count=1 if exists else 0,
    )


def _directory_item(
    *,
    key: str,
    label: str,
    detail: str,
    directory: Path | None,
    keep: Path | None = None,
) -> RemovableItem:
    """
    A directory's *contents*, never the directory. See the module docstring.
    """
    if directory is None:
        return RemovableItem(key, label, detail, "", (), 0, 0, "Location unknown.")

    location = str(directory)
    refusal = _refuse_reason(directory)
    if refusal:
        log.warning("Remove Cache refuses %s: %s", directory, refusal)
        return RemovableItem(key, label, detail, location, (), 0, 0, refusal)

    if not directory.is_dir():
        return RemovableItem(key, label, detail, location, (), 0, 0)

    kept_note = ""
    targets = []
    try:
        children = sorted(directory.iterdir())
    except OSError as exc:
        return RemovableItem(key, label, detail, location, (), 0, 0, f"Cannot be read: {exc}")

    for child in children:
        if keep is not None and _same_path(child, keep):
            kept_note = "This run's log stays - it is in use while pypts is running."
            continue
        targets.append(child)

    return RemovableItem(
        key=key,
        label=label,
        detail=detail,
        location=location,
        targets=tuple(targets),
        size_bytes=sum(_size_of(target) for target in targets),
        item_count=len(targets),
        kept_note=kept_note,
    )


# --- Removing -----------------------------------------------------------------


def remove(items: Iterable[RemovableItem]) -> RemovalOutcome:
    """
    Delete exactly the targets the survey listed, and nothing else.

    A target that will not go is counted and named; the rest of the removal
    carries on. Never raises - a failed cleanup must not take the window down.
    """
    removed_bytes = 0
    removed_count = 0
    failures: list[str] = []

    for item in items:
        for target in item.targets:
            size = _size_of(target)
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    os.remove(target)
            except OSError as exc:
                failures.append(f"{target.name}: {exc.strerror or exc}")
                continue
            removed_bytes += size
            removed_count += 1

    log.info(
        "Remove Cache: %d item(s) removed, %d byte(s) freed, %d failure(s).",
        removed_count,
        removed_bytes,
        len(failures),
    )
    return RemovalOutcome(
        removed_bytes=removed_bytes,
        removed_count=removed_count,
        failures=tuple(failures),
    )


# --- The guards ---------------------------------------------------------------


def _refuse_reason(directory: Path) -> str:
    """
    Empty if the directory may have its contents removed, a reason if not.

    `paths.reports_dir` is a value in a file the user may edit. Emptying a
    filesystem root or a home directory is never what anybody meant.
    """
    try:
        resolved = directory.resolve()
    except OSError:
        return ""

    if resolved.parent == resolved:
        return "Refused: that is a filesystem root."
    try:
        if resolved == Path.home().resolve():
            return "Refused: that is your home directory."
    except OSError:
        pass
    return ""


# --- Plumbing -----------------------------------------------------------------


def _configured_dir(key: str) -> Path:
    """Split out so a test can replace it without importing ConfigHandler."""
    from pypts.config_handler import ConfigHandler

    return Path(ConfigHandler().get_parameter(key))


def _configured_dir_or_none(key: str) -> Path | None:
    """
    Remove Cache has to open even when the configuration is the broken thing.
    """
    try:
        return _configured_dir(key)
    except Exception as exc:  # noqa: BLE001 - any config failure means "unknown"
        log.warning("Remove Cache cannot resolve %s: %s", key, exc)
        return None


def _live_log_path() -> Path | None:
    path = get_log_path()
    return None if path is None else Path(path)


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _size_of(path: Path) -> int:
    """Bytes on disk, best effort. A file that cannot be measured counts as 0."""
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(
                item.stat().st_size for item in path.rglob("*") if item.is_file()
            )
    except OSError:
        return 0
    return 0
