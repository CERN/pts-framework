# Tests

```
tests/
├── unit_tests/          tests for one module, no processes, fast
└── functional_tests/    tests that drive `python -m pypts` end to end
```

Run everything:

```bash
python run_tests.py           # unit + functional
python run_tests.py -k logger # arguments are passed through to pytest
pytest tests/unit_tests       # one folder
```

GUI tests need a display. On a headless machine set `QT_QPA_PLATFORM=offscreen`.

## Current state

Most of the suite is real now: the message protocol, the queue-wrapper trace,
the config handler, the logger, the sequencer (threading shape *and* engine),
the recipe and step layers, CORE's routing and the Debug Monitor all have live
tests. What remains **placeholder** - a named, skipped stub declaring intended
coverage - tracks the modules that are still stubs themselves
(`report.generate_report()`, `hal.py`, the stream handler) and the step types
not yet ported from `old_code/`.

The point of the skeleton is to fix the *shape* of the suite before the port
starts, so a ported module has an obvious place to land and the remaining gaps
show up in the test report rather than in someone's head. `pytest` reports the
stubs as skipped, so the suite stays green and the skip count tells you how much
groundwork is still open.

## Adding a real test

1. Find the placeholder that matches - it is usually already named.
2. Replace the body and drop the `@pytest.mark.skip`.
3. If nothing matches, add it next to its neighbours rather than in a new file.

Keep unit tests free of `multiprocessing` where you can. Per the agreed
topology, the Sequencer, the Report and the StreamHandler become threads inside
the engine process, so tests written against the channel and message types
survive that change while tests written against processes do not.

`test_logger.py` is the exception and shows the pattern for when you genuinely
need processes: module-level worker functions (Windows `spawn` pickles the
target by reference and re-imports the module in the child), a fixture that
restores the root logger, and no sleeps - stop the Logger and let it drain
rather than waiting a fixed time.

## Tests for the old engine

Deleted. They tested `src/pypts/old_code/` through a top-level `pypts` API that
no longer exists, so they could not run. They remain in git history if a case is
worth recovering while porting:

```bash
git show 27956b5:unit_tests/unit_tests/test_recipe.py
git show 27956b5 --stat -- unit_tests   # what was there
```

The roadmap's Phase 0 asks for characterization tests around `old_code` (run an
example recipe, assert on the CSV rows) as the safety net for the port - those
old files are the closest existing reference for what behaviour to pin down.
