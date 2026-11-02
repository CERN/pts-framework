import logging

from PySide6.QtWidgets import QMainWindow

from pyrade_xy_graph.ui.graph_widget import PyradeXYGraphWidget

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """
    Standalone runnable window (what main.py shows) - a thin QMainWindow
    wrapper around PyradeXYGraphWidget, which owns all the actual
    functionality and is itself the thing to embed into another
    application. Adds a native menu bar and nothing else.
    """

    def __init__(self, parent=None, live_max_len: int = 5_000_000):
        super().__init__(parent)
        self.setWindowTitle("PyRade XY Graph")
        self.resize(1280, 800)

        self.graph = PyradeXYGraphWidget(live_max_len=live_max_len, show_legend=False)
        self.setCentralWidget(self.graph)

        self._init_menu_bar()

        # Passthrough attributes - state lives on self.graph.
        # Safe as one-time copies since each is a stable object mutated
        # in place, never reassigned after construction. file_loader is
        # different - see its property.
        self.data_store = self.graph.data_store
        self.plot_widget = self.graph.plot_widget
        self.signal_tree = self.graph.signal_tree
        self.math_dock = self.graph.math_dock
        self.log_panel = self.graph.log_panel
        self.sessions = self.graph.sessions

    @property
    def file_loader(self):
        """Live property, not a one-time copy: PyradeXYGraphWidget.file_loader
        is reassigned to a new FileLoadWorker on every open_file()
        call."""
        return self.graph.file_loader

    def _init_menu_bar(self):
        # file_menu/view_menu are kept as attributes, not local
        # variables: PySide6/shiboken can garbage-collect a QMenu's
        # Python wrapper once nothing references it, taking the
        # underlying C++ object down with it even though Qt's own
        # QMenuBar ownership would otherwise keep it alive.
        g = self.graph
        self.file_menu = self.menuBar().addMenu("File")
        self.file_menu.addAction(g.action_open_file)
        self.file_menu.addSeparator()
        self.file_menu.addAction(g.action_start_acquisition)
        self.file_menu.addAction(g.action_stop_acquisition)
        self.file_menu.addSeparator()
        self.file_menu.addAction(g.action_screenshot)
        self.file_menu.addAction(g.action_export_data)
        self.file_menu.addSeparator()
        self.file_menu.addAction("Exit", self.close)

        # Zoom mode / downsample method / file-load decimation method
        # are toolbar combo boxes (PyradeXYGraphWidget._build_actions),
        # not QActions, so they have no menu entry here.
        self.view_menu = self.menuBar().addMenu("View")
        view_menu = self.view_menu
        view_menu.addAction(g.action_autoscale)
        view_menu.addAction(g.action_set_x_range)
        view_menu.addSeparator()
        view_menu.addAction(g.action_scope_window)
        view_menu.addAction(g.action_file_load_decimation)
        view_menu.addAction(g.action_load_visible_detail)

    # ---- passthroughs ------------------------------------------------

    def open_file(self, *args, **kwargs):
        return self.graph.open_file(*args, **kwargs)

    def start_live_acquisition(self, *args, **kwargs):
        return self.graph.start_live_acquisition(*args, **kwargs)

    def stop_live_acquisition(self, *args, **kwargs):
        return self.graph.stop_live_acquisition(*args, **kwargs)

    def closeEvent(self, event):
        self.graph.shutdown()
        super().closeEvent(event)
