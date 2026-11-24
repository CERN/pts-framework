<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# stream_handler — the stream container

Live (x, y) data from test code, written to one CSV file per stream inside the run folder.
The Sequencer opens one `StreamSession` per run (`sequencer/sequencer.md`); the GUI draws a
step's `graph:` from these files, at `stream_csv_path(RunStarted.run_dir, graph)`
(`hmi/gui/gui.md` §18, §19).

## Files

| File | Holds |
|---|---|
| `stream_file.py` | `STREAMS_FOLDER`, `stream_csv_path()`, `unit_from_header()`, `Stream` |
| `stream_session.py` | `StreamSession`, `register_stream()`, `StreamError` |
| `__init__.py` | the public API (all of the above) |

## The interface

- `register_stream(name, unit=None) -> Stream` — what test code calls; works on the active
  session, raises `StreamError` when none is active.
- `Stream.push(x, y)` — two numbers are one row; two sequences of equal length are many rows
  (`ValueError` when the lengths differ). Thread-safe; each push is flushed, so a reader sees it at once.
- `Stream.close()`, `Stream.closed`, `Stream.name`, `Stream.path`, `Stream.unit`.
- `StreamSession(folder)` — one per run, a context manager that makes itself the active
  session. `register()`, `has_stream()`, `records_streams` (folder is not None), `close()`.
  `has_stream(name)` compares file-safe names (the rule `stream_csv_path` uses), so
  after `register("ch 1")` `has_stream("ch_1")` is True - the same name the GUI reads.
- A script outside PyPTS uses it the same way: `with StreamSession(folder): ...`.

## Lifetime rules

- One active session per process, in a module slot (not thread-local: test code may push from
  threads of its own). It is the stream counterpart of `pyhal.run_scope()`'s active scope, with an
  identity-checked deactivate: leaving a session that is no longer the active one leaves the slot alone.
- Leaving the `with` block closes every stream of the session. A handle that outlives its
  session drops pushes (one DEBUG line per stream) and never writes into the next run.
- `close()` marks the session closed; a `register()` after that returns a `Stream` that writes
  nothing (path None, one DEBUG line), so no handle is opened that nobody would close.
- Registering a name again opens a new `Stream` on the same file, which appends; the header is
  written only when the file is new or empty.
- `StreamSession(None)` means streams are off (no run folder): `register()` returns a `Stream`
  with `path` None that writes nothing, and logs one WARNING per session.

## The CSV format — the CORE / GUI contract

`<run folder>/streams/<safe name>.csv`. Safe name: alphanumerics kept, every other character
an underscore, at most 60 characters (the rule of `utilities.local_storage.safe_name_part()`,
written out again here). The file is written with `csv.writer` (`mode="a"`, `newline=""`,
`encoding="utf-8"`, so rows end in `\r\n`). First line `x,y [<unit>]`, or `x,y` without a unit;
then one `x,y` row per sample. The GUI reads the unit back with `unit_from_header()`.

## Why it imports nothing of pypts

The container is stdlib only, so test code and scripts can use it with no PyPTS around, and
nothing it imports can create an import cycle with the Sequencer or the GUI. Its log lines go
through `logging.getLogger(__name__)` (precedent: `pyhal/drivers/loopback.py`); wording in
`logger/logging_rules.md` §6.

## Known gaps

- CSV is the only storage; TDMS / HDF5 are not implemented.
