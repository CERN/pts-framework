<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Release configuration

Before creating the first release tag, a GitHub organization owner must create
two repository Environments:

* `testpypi`, with no required reviewers;
* `pypi`, with required reviewers and deployment access restricted to protected
  tags.

Register trusted publishers in the TestPyPI and PyPI project settings using the
following values:

| Setting | Value |
| --- | --- |
| Owner | `CERN` |
| Repository | `pts-framework` |
| Workflow | `release.yml` |
| Environment | `testpypi` or `pypi`, respectively |

The project is published as `pts-framework`. Protect the `master` branch and
limit creation of `vX.Y.Z` tags to maintainers. A release tag first publishes its
artifact to TestPyPI. Install and smoke-test that version using the command in
the README, then approve the pending `pypi` Environment deployment to publish
the identical artifact to PyPI.
