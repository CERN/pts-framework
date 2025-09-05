from PyQt6.QtWidgets import QToolBar, QAction, QStyle
from PyQt6.QtCore import QSize, Qt

self.toolbar = QToolBar()
self.toolbar.setIconSize(QSize(32, 32))
self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)  
# Text under icon looks better with colored buttons

# --- Open ---
self.action_open_recipe = QAction(
    self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
    "Open recipe",
    self
)
self.action_open_recipe.setProperty("cssClass", "open")

# --- Start ---
self.action_start_recipe_execution = QAction(
    self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay),
    "Start test",
    self
)
self.action_start_recipe_execution.setProperty("cssClass", "start")

# --- Abort ---
self.action_abort_recipe_execution = QAction(
    self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop),
    "Abort",
    self
)
self.action_abort_recipe_execution.setProperty("cssClass", "abort")

self.toolbar.addAction(self.action_open_recipe)
self.toolbar.addAction(self.action_start_recipe_execution)
self.toolbar.addAction(self.action_abort_recipe_execution)

# --- Style actions by cssClass ---
self.toolbar.setStyleSheet("""
QToolButton[cssClass="open"] {
    background-color: royalblue;
    color: white;
    font-weight: bold;
    border-radius: 6px;
    padding: 4px;
}
QToolButton[cssClass="start"] {
    background-color: green;
    color: white;
    font-weight: bold;
    border-radius: 6px;
    padding: 4px;
}
QToolButton[cssClass="abort"] {
    background-color: red;
    color: white;
    font-weight: bold;
    border-radius: 6px;
    padding: 4px;
}
""")
