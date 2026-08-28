# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Indexed steps can now store values. `local` and `global` output mappings on a
  step with an `indexed: true` input are no longer discarded: the wrapper saves
  the aggregated list of per-iteration values (one entry per iteration) under the
  configured `local_name` / `global_name`. `passfail`, `equals`, `range` and
  `image` outputs continue to be evaluated and attached per iteration.
- An indexed step whose indexed lists are empty now stores empty lists instead of
  erroring, and an iteration that errors no longer masks its own failure with a
  `KeyError` while the aggregate is stored.

### Removed

- Handling of `indexed: true` on an *output* mapping in `IndexedStep`. Every
  output model is `extra="forbid"`, so the field was rejected by validation and
  the branch was unreachable from any valid recipe.

## [0.6.1] - 2026-08-27

- Add CHANGELOG.md
- No changes in software code

## [0.6.0] - 2026-08-14

### Added

- Progress bar shown during test execution, with accompanying unit tests.
- Pydantic-validated recipe language step model, replacing the previous
  recipe parser.

### Fixed

- Packaging: include required `.yml` and example files so the CI-built
  package works correctly.
- Documentation build: removed a stale `_static` reference.

### Note

Versions prior to 0.6.0 (`v0.1`-`v0.5.1`) predate this changelog; see the
git history and GitHub tags for that history.
