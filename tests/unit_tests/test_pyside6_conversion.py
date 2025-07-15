# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
# """Test to verify successful PyQt6 to PySide6 conversion"""
# import pytest
# from unittest.mock import patch
#
#
# def test_pyside6_imports():
#     """Test that all PySide6 imports work correctly after conversion"""
#     # Test recipe_creator imports
#     from pypts.recipe_creator import RecipeEditorMainMenu, HashableTreeItem
#     from PySide6.QtWidgets import QTreeWidgetItem
#
#     # Test that the editor can be instantiated
#     app = None
#     try:
#         from PySide6.QtWidgets import QApplication
#         import sys
#         app = QApplication.instance()
#         if not app:
#             app = QApplication(sys.argv)
#
#         editor = RecipeEditorMainMenu()
#         assert editor is not None
#         assert hasattr(editor, 'tree')
#         assert hasattr(editor, 'yaml_viewer')
#
#     finally:
#         if app:
#             app.processEvents()
#
#
# def test_qt_widget_creation():
#     """Test that Qt widgets can be created with PySide6"""
#     from PySide6.QtWidgets import QTreeWidgetItem
#
#     # Test QTreeWidgetItem creation (was failing before fix)
#     item = QTreeWidgetItem(["test_field", "test_value"])
#     assert item.text(0) == "test_field"
#     assert item.text(1) == "test_value"
#
#
# def test_file_dialog_mocking():
#     """Test that PySide6 QFileDialog can be mocked correctly"""
#     from unittest.mock import patch
#
#     # This was one of the failing imports in the original tests
#     with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=("test.yaml", "YAML Files (*.yaml)")):
#         # Should not raise ImportError
#         pass
#
#
# def test_gui_compatibility():
#     """Test that GUI components work with mixed imports"""
#     # Test that our custom ScintillaYamlEditor works with PySide6
#     from pypts.recipe_creator import ScintillaYamlEditor
#     from PySide6.QtWidgets import QApplication
#     import sys
#
#     app = QApplication.instance()
#     if not app:
#         app = QApplication(sys.argv)
#
#     try:
#         editor = ScintillaYamlEditor()
#
#         # Test basic functionality
#         test_text = "test: yaml content"
#         editor.setText(test_text)
#         assert editor.toPlainText() == test_text
#
#         # Test length function
#         assert editor.length() == len(test_text)
#
#         # Test SendScintilla stub (should not raise)
#         editor.SendScintilla(1, 2, 3)
#
#     finally:
#         app.processEvents()
#
#
# def test_color_functionality():
#     """Test that color functionality works with PySide6"""
#     from PySide6.QtGui import QColor
#     from PySide6.QtWidgets import QTreeWidgetItem, QApplication
#     import sys
#
#     app = QApplication.instance()
#     if not app:
#         app = QApplication(sys.argv)
#
#     try:
#         item = QTreeWidgetItem(["field", "value"])
#
#         # Test color setting (from mark_required_field)
#         orange_color = QColor(210, 40, 0)
#         item.setForeground(0, orange_color)
#
#         # Verify color was set
#         color = item.foreground(0).color()
#         assert color.red() == 210
#         assert color.green() == 40
#         assert color.blue() == 0
#
#     finally:
#         app.processEvents()
#
#
# if __name__ == "__main__":
#     pytest.main([__file__])