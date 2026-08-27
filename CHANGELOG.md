# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
