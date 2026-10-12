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

Once the PyPI deployment succeeds, the same release run deploys the
documentation to GitHub Pages and pushes the container image to Docker Hub.

## Documentation

GitHub Pages must use "GitHub Actions" as its source, and the `github-pages`
Environment must allow deployments from `vX.Y.Z` tags.

## Container image

In the repository's Actions settings, add:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `DOCKERHUB_TOKEN` | Docker Hub access token with write access to the repository |
| Variable | `DOCKERHUB_USERNAME` | Docker Hub user or organization the token logs in as |
| Variable | `DOCKERHUB_IMAGE` | Full image name, for example `cern/pts-framework` |

Pushes to `master` publish the `edge` and `sha-<commit>` tags. A release tag
publishes `X.Y.Z`, `X.Y`, `X` (not for `0.y.z`), `latest` and `sha-<commit>`.

## Dependencies

`uv.lock` pins every dependency used by CI and the container image. The image
build runs `uv sync --locked`, so it fails when `pyproject.toml` and `uv.lock`
disagree. Commit the regenerated `uv.lock` together with any dependency change.

Regenerate it with [uv](https://docs.astral.sh/uv/), using the version pinned in
the `Dockerfile`:

```sh
uv lock
```

To move every package to the newest version `pyproject.toml` allows, or just one
package, use:

```sh
uv lock --upgrade
uv lock --upgrade-package numpy
```

To check that the lock is up to date without changing it, run `uv lock --check`.

Without installing uv, run it in a container from the repository root:

```sh
docker run --rm -v "$PWD":/work -w /work \
  -e SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK=0+unknown \
  python:3.13-slim-trixie sh -c "pip install uv==0.13.0 && uv lock"
```
