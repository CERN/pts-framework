"""The copied pyrade_xy_graph package: only the plot path loads, and it stays quiet."""

import subprocess
import sys

_PROBE = """
import sys
import pyqtgraph
before = (pyqtgraph.getConfigOption("background"), pyqtgraph.getConfigOption("foreground"))
from pyrade_xy_graph.ui.plot_widget import ScopePlotWidget
from pyrade_xy_graph.core.data_store import DataStore
after = (pyqtgraph.getConfigOption("background"), pyqtgraph.getConfigOption("foreground"))
print("SAME" if before == after else "CHANGED")
for name in ("h5py", "nptdms", "pandas", "pyrade_xy_graph.ui.tdms_exporter"):
    print(name, "LOADED" if name in sys.modules else "ABSENT")
"""


def _run_probe() -> dict[str, str]:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True
    )
    lines = result.stdout.split()
    return {"config": lines[0], **dict(zip(lines[1::2], lines[2::2], strict=False))}


def test_plot_path_imports() -> None:
    from pyrade_xy_graph.core.data_store import DataStore
    from pyrade_xy_graph.ui.plot_widget import ScopePlotWidget

    assert ScopePlotWidget is not None
    assert DataStore is not None


def test_no_tdms_exporter_registered() -> None:
    import pyrade_xy_graph.ui.plot_widget  # noqa: F401

    assert "pyrade_xy_graph.ui.tdms_exporter" not in sys.modules


def test_import_leaves_pyqtgraph_config_alone() -> None:
    assert _run_probe()["config"] == "SAME"


def test_heavy_deps_not_pulled_in() -> None:
    probe = _run_probe()
    for name in ("h5py", "nptdms", "pandas"):
        assert probe[name] == "ABSENT", name
