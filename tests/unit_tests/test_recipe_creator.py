import pytest
from unittest.mock import patch, mock_open, MagicMock
from PySide6.QtWidgets import QTreeWidgetItem
from pypts.recipe_creator import YamlTreeEditor, HashableTreeItem


@pytest.fixture
def editor(qtbot):
    # Create app instance, qtbot is pytest-qt fixture for Qt testing
    w = YamlTreeEditor()
    qtbot.addWidget(w)
    return w


def test_mark_required_field_colors_text(editor):
    # Create a dummy QTreeWidgetItem
    item = QTreeWidgetItem(["field", "value"])
    # Initially no foreground set
    editor.mark_required_field(item, True)
    # The foreground color of column 0 should be the orange star color (210, 40, 0)
    color = item.foreground(0).color()
    assert color.red() == 210
    assert color.green() == 40
    assert color.blue() == 0


def test_extract_item_data_simple_and_complex(editor):
    # Build tree manually
    root = QTreeWidgetItem(["root", ""])
    # Child scalar leaf
    leaf1 = QTreeWidgetItem(root, ["leaf1", "value1"])
    # Child with children, map structure
    parent = QTreeWidgetItem(root, ["parent", ""])
    child1 = QTreeWidgetItem(parent, ["key1", "val1"])
    child2 = QTreeWidgetItem(parent, ["key2", "val2"])

    # Extract data from root
    result = editor.extract_item_data(root)
    assert isinstance(result, dict)
    assert "leaf1" in result and result["leaf1"] == "value1"
    assert "parent" in result
    assert result["parent"] == {"key1": "val1", "key2": "val2"}


def test_extract_item_data_lists(editor):
    root = QTreeWidgetItem(["root", ""])
    child0 = QTreeWidgetItem(root, ["[0]", "val0"])
    child1 = QTreeWidgetItem(root, ["[1]", "val1"])
    child2 = QTreeWidgetItem(root, ["[2]", "val2"])

    result = editor.extract_item_data(root)
    assert isinstance(result, list)
    assert result == ["val0", "val1", "val2"]


def test_on_tree_item_clicked_highlights_line(editor):
    # Setup item and line mapping
    item = QTreeWidgetItem(["key", "value"])
    hash_item = HashableTreeItem(item)
    editor.item_to_line[hash_item] = 42

    # Patch highlight_line method to track calls
    with patch.object(editor, "highlight_line") as mock_highlight:
        editor.on_tree_item_clicked(item, 0)
        mock_highlight.assert_called_once_with(42)


def test_on_tree_item_clicked_no_line_no_highlight(editor):
    item = QTreeWidgetItem(["key", "value"])
    with patch.object(editor, "highlight_line") as mock_highlight:
        editor.on_tree_item_clicked(item, 0)
        mock_highlight.assert_not_called()


def test_log_appends_message(editor):
    prev_count = editor.log_console.document().blockCount()
    editor.log("Test log message")
    new_count = editor.log_console.document().blockCount()
    assert new_count == prev_count + 1
    last_text = editor.log_console.toPlainText().splitlines()[-1]
    assert "Test log message" in last_text


@patch("builtins.open", new_callable=mock_open, read_data="key: value\n")
def test_load_yaml_success(mock_file, editor):
    # Patch QFileDialog to return a known file path
    with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=("dummy.yaml", "YAML Files (*.yaml)")):
        editor.load_yaml_path()

    # After loading, current_file_path should be set
    assert editor.current_file_path == "dummy.yaml"
    # Tree should have top level items (document root)
    assert editor.tree.topLevelItemCount() > 0


@patch("builtins.open", new_callable=mock_open, read_data="invalid: [yaml")
def test_load_yaml_parse_error(mock_file, editor):
    # Patch QFileDialog to return a known file path
    with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=("bad.yaml", "YAML Files (*.yaml)")):
        editor.load_yaml_path()

    # Log console should contain a parse error message
    logs = editor.log_console.toPlainText()
    assert "YAML parse error" in logs


def test_on_save_recipe_clicked_no_file(editor):
    editor.current_file_path = ""
    editor.log_console.clear()
    editor.on_save_recipe_clicked()
    logs = editor.log_console.toPlainText()
    assert "No YAML file loaded" in logs



def test_toggle_dark_mode_changes_style_and_logs(editor):
    editor.log_console.clear()
    editor.toggle_dark_mode(True)
    assert "Dark Mode enabled" in editor.log_console.toPlainText()
    editor.toggle_dark_mode(False)
    assert "Light Mode restored" in editor.log_console.toPlainText()
