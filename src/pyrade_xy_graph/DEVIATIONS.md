<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# pyrade_xy_graph: deviations from upstream

This package is a copy of CERN's `pyrade_xy_graph`, taken until it becomes a real dependency.

- Upstream: `https://gitlab.cern.ch/pyrade/hmi/gui/pyrade_xy_graph`
- Commit copied: `af9e4b0`
- Copied: `__init__.py`, `main.py`, `core/*.py`, `ui/*.py`. Not copied: `old_graph/`, `tests/`,
  `.DS_Store`, `*.pyc`, upstream `pyproject.toml`, the PNGs.

Everything is byte-identical to upstream except two edits in `ui/plot_widget.py`.

## 1. The TDMS exporter import is removed

Original line 11:

```python
from pyrade_xy_graph.ui import tdms_exporter  # noqa: F401  (registers TDMS in pyqtgraph's native right-click Export dialog)
```

Deleted, so importing the plot widget does not pull in `nptdms`.

## 2. The import-time pyqtgraph configuration is removed

Original lines 14-20:

```python
# White background, dark foreground/axes/text. useOpenGL is off: it made
# the system cursor invisible over the GL viewport on macOS, and the
# per-curve point budget already bounds render cost regardless of backend.
pg.setConfigOptions(antialias=False, useOpenGL=False)
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')
```

Deleted, so importing the module does not change pyqtgraph's global configuration for the whole
application. Nothing replaces it globally.

## Reported upstream

`requires-python >=3.9` is wrong (the code uses 3.10+ syntax), `pymeasure` is stale, and there is
no licence file.
