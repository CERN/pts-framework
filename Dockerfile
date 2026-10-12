# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

ARG PYTHON_VERSION=3.13.14

FROM python:${PYTHON_VERSION}-slim-trixie AS base

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /usr/local/bin/

# PySide6 wheels include Qt itself. These runtime libraries are required for Qt's
# headless platform plugin.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libdbus-1-3 \
        libegl1 \
        libfontconfig1 \
        libglib2.0-0 \
        libgl1 \
        libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project


FROM base AS ci

ENV QT_QPA_PLATFORM=offscreen

RUN uv sync --locked --no-install-project --extra test --extra doc

ARG SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK=0+unknown
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK=${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK}

COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-editable --extra test --extra doc

COPY tests ./tests
COPY docs ./docs

CMD ["python", "-m", "pytest", "tests"]


FROM base AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-dejavu-core \
        libx11-xcb1 \
        libxcb-cursor0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-shape0 \
        libxcb-sync1 \
        libxcb-xfixes0 \
        libxcb-xinerama0 \
        libxcb-xinput0 \
        libxcb-xkb1 \
        libxkbcommon-x11-0 \
        novnc \
        openbox \
        tini \
        websockify \
        x11-utils \
        x11vnc \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

ARG SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK=0+unknown
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK=${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PTS_FRAMEWORK}

COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-editable

RUN useradd --create-home --uid 1000 --shell /bin/bash pts \
    && mkdir --mode=1777 /tmp/.X11-unix \
    && install --directory --owner=pts --group=pts /home/pts/pts_reports \
    && ln -s "$(python -c 'from importlib.resources import files; print(files("pypts") / "recipes")')" /home/pts/examples

COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/pts-entrypoint

ENV DISPLAY=:0 \
    RESOLUTION=1920x1080 \
    NOVNC_PORT=6080 \
    PYPTS_REPORT_DIR=/home/pts/pts_reports

USER pts
WORKDIR /home/pts

EXPOSE 6080

ENTRYPOINT ["tini", "--", "pts-entrypoint"]
CMD ["python", "-m", "pypts"]
