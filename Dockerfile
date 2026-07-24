# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

ARG PYTHON_VERSION=3.13.14
FROM python:${PYTHON_VERSION}-slim-trixie

# PySide6 wheels include Qt itself. These runtime libraries are required for Qt's
# headless platform plugin while the test suite is running in the container.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libdbus-1-3 \
        libegl1 \
        libglib2.0-0 \
        libgl1 \
        libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

ARG SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK=0+unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QT_QPA_PLATFORM=offscreen \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK=${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK}

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir ".[test]" build

CMD ["python", "-m", "pytest", "tests"]
