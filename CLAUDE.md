# Project rules for Claude

## Operating rules

- **Ask when clarity is below 95%.** If certainty on any topic (scope, intent, which files/folders are in-scope, terminology, expected outcome, etc.) is below 95%, stop and ask the user before acting. Do not silently assume. Batch related clarifying questions into one message.

## Repository layout notes

- Everything under `src/pypts/` is new/in-development code **except** `src/pypts/old_code/`, which is legacy — do not modify `old_code/` unless explicitly asked.
- In-progress stubs and helper apps (e.g. `helper_applications/`, `spikes/`, `hardware_layer/`, `stream_handler/`, `step/`, `recipe/`) still count as new code and are in-scope for reviews.
- Entry point: `src/pypts/__main__.py`.
- Test runner: `run_tests.py` in the repo root.
