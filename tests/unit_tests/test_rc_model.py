import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


_RECIPE = (
    "name: Test Recipe\n"
    'version: "0.1"\n'
    "---\n"
    "sequence_name: Main\n"
    "steps:\n"
    "  - steptype: wait\n"
    "    step_name: First wait\n"
    "    wait_time: 1.0\n"
)


@pytest.fixture
def model(qapp):
    from pypts.helper_applications.recipe_creator.rc_model import RecipeModel

    m = RecipeModel()
    m.load_yaml(_RECIPE)
    return m


def test_header_read(model):
    assert model.header()["name"] == "Test Recipe"


def test_sequences_read(model):
    seqs = model.sequences()
    assert len(seqs) == 1
    assert seqs[0]["sequence_name"] == "Main"


def test_steps_read(model):
    assert len(model.steps(0)) == 1
    assert model.steps(0)[0]["steptype"] == "wait"


def test_set_header_field_emits_changed(model):
    received = []
    model.changed.connect(lambda: received.append(1))
    model.set_header_field("name", "New Name")
    assert received
    assert model.header()["name"] == "New Name"


def test_set_header_field_is_undoable(model):
    original = model.header()["name"]
    model.set_header_field("name", "Changed")
    assert model.header()["name"] == "Changed"
    model.undo_stack.undo()
    assert model.header()["name"] == original


def test_add_step_inserts_at_position(model):
    count_before = len(model.steps(0))
    model.add_step(0, "wait", 0)
    assert len(model.steps(0)) == count_before + 1
    assert model.steps(0)[0]["steptype"] == "wait"


def test_add_step_is_undoable(model):
    count_before = len(model.steps(0))
    model.add_step(0, "wait", 0)
    model.undo_stack.undo()
    assert len(model.steps(0)) == count_before


def test_remove_step_is_undoable(model):
    step_name = model.steps(0)[0]["step_name"]
    model.remove_step(0, 0)
    assert len(model.steps(0)) == 0
    model.undo_stack.undo()
    assert model.steps(0)[0]["step_name"] == step_name


def test_move_step_changes_order(model):
    model.add_step(0, "userinteraction", 1)
    model.steps(0)[1]["step_name"] = "Second"
    first_name = model.steps(0)[0]["step_name"]
    model.move_step(0, 0, 1)
    assert model.steps(0)[1]["step_name"] == first_name


def test_set_step_field(model):
    model.set_step_field(0, 0, "wait_time", 5.0)
    assert model.steps(0)[0]["wait_time"] == 5.0


def test_add_remove_sequence(model):
    count = len(model.sequences())
    model.add_sequence("New Seq")
    assert len(model.sequences()) == count + 1
    model.remove_sequence(len(model.sequences()) - 1)
    assert len(model.sequences()) == count


def test_load_yaml_clears_undo_stack(model):
    model.set_header_field("name", "Something")
    assert model.undo_stack.canUndo()
    model.load_yaml(_RECIPE)
    assert not model.undo_stack.canUndo()


def test_set_from_text_is_undoable(model):
    original_yaml = model.to_yaml()
    new_yaml = original_yaml.replace("Test Recipe", "Modified")
    model.set_from_text(new_yaml)
    assert model.header()["name"] == "Modified"
    model.undo_stack.undo()
    assert model.header()["name"] == "Test Recipe"


def test_to_yaml_produces_valid_recipe(model):
    from pypts.helper_applications.recipe_verificator import verify_string

    issues = verify_string(model.to_yaml())
    errors = [i for i in issues if i.is_error]
    assert not errors, [str(i) for i in errors]


def test_default_step_has_required_fields(qapp):
    from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
    from pypts.recipe.rules import STEP_TYPE_REQUIRED

    m = RecipeModel()
    for steptype in STEP_TYPE_REQUIRED:
        step = m._default_step(steptype)
        assert step["steptype"] == steptype
        for field in STEP_TYPE_REQUIRED[steptype]:
            assert field in step, f"{steptype} missing {field}"


def test_rc_widgets_importable(qapp):
    from pypts.helper_applications.recipe_creator.rc_widgets import (
        PaletteYamlHighlighter,
        YamlEditor,
        VerificationPanel,
    )

    assert PaletteYamlHighlighter is not None
    assert YamlEditor is not None
    assert VerificationPanel is not None
