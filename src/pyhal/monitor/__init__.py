"""
The HAL monitor: a small standalone window that shows a running HAL server's status and can
close its devices, stop it, start one and show its latest log lines.

The window imports PySide6; `link.py`, its connection to the HAL, does not. `pyhal` never
imports this package, so `import pyhal` (which every driver process runs) stays import-light.
"""
