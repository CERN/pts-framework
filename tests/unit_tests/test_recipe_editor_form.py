"""The Recipe Editor v2's form: generated from the schema, written through the model."""

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox, QLineEdit

from pypts.helper_applications.recipe_creator.rc_model import RecipeModel
from pypts.helper_applications.recipe_editor import schema_form
from pypts.helper_applications.recipe_editor.row_map import StepRef
from pypts.helper_applications.recipe_editor.schema_form import (
    INPUTS,
    OUTPUTS,
    SKIP,
    YAML_BOX,
    SchemaForm,
    field_kind,
    read_value,
    value_text,
)
from pypts.recipe.recipe_schema import (
    OUTPUT_SCHEMAS,
    STEP_SCHEMAS,
    HeaderSchema,
    ParameterSet,
    SequenceSchema,
)

_RECIPE = """\
# A comment the form must not lose.
name: Form test
version: "1.0"
globals:
  port: ''
---
sequence_name: Main
steps:
  - steptype: Wait
    step_name: Settle
    wait_time: 2
  - steptype: PythonModule
    step_name: Measure
    module: my_tests.py
    method_name: measure
    inputs:
      voltage: 5
      channel: {type: global, global_name: port}
    outputs:
      result: {type: range, min: 4.9, max: 5.1}
  - steptype: Indexed
    step_name: Add
    template:
      steptype: PythonModule
      module: my_tests.py
      method_name: add
      outputs:
        sum: {type: passfail}
    parameter_sets:
      - inputs: {a: 1, b: 2}
        expect: {sum: 3}
"""

_ALL_MODELS = [
    *STEP_SCHEMAS.values(),
    *OUTPUT_SCHEMAS.values(),
    HeaderSchema,
    SequenceSchema,
    ParameterSet,
]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def model(qapp):
    recipe = RecipeModel()
    recipe.load_yaml(_RECIPE)
    return recipe


@pytest.fixture
def form(model):
    widget = SchemaForm(model)
    model.changed.connect(widget.refresh)
    yield widget
    widget.deleteLater()


def _ref(index: int) -> StepRef:
    return StepRef(
        sequence_index=0, list_name="steps", step_index=index, first_line=0, last_line=0
    )


def _field(form: SchemaForm, *path):
    for field in form._fields:
        if field.path[-len(path) :] == path:
            return field
    raise AssertionError(f"no field for {path}: {[f.path for f in form._fields]}")


# -- generated from the schema -------------------------------------------------------


@pytest.mark.parametrize("model_cls", _ALL_MODELS, ids=lambda m: m.__name__)
def test_every_field_gets_a_widget_of_its_own(model_cls):
    # The YAML box is the fallback; a field landing there needs a widget on purpose.
    for name, info in model_cls.model_fields.items():
        kind = field_kind(model_cls, name, info)
        assert kind != YAML_BOX, f"{model_cls.__name__}.{name} has no widget"


def test_refused_keys_and_tags_are_not_fields():
    sequence_step = STEP_SCHEMAS["sequence"]
    assert field_kind(sequence_step, "inputs", sequence_step.model_fields["inputs"]) == SKIP
    wait = STEP_SCHEMAS["wait"]
    assert field_kind(wait, "steptype", wait.model_fields["steptype"]) == SKIP
    assert field_kind(SequenceSchema, "steps", SequenceSchema.model_fields["steps"]) == SKIP


def test_inputs_and_outputs_get_their_editors():
    module = STEP_SCHEMAS["pythonmodule"]
    assert field_kind(module, "inputs", module.model_fields["inputs"]) == INPUTS
    assert field_kind(module, "outputs", module.model_fields["outputs"]) == OUTPUTS


def test_a_field_carries_its_schema_description(form):
    form.show_step(_ref(0), 0)
    field = _field(form, "wait_time")
    assert field.editor.toolTip() == STEP_SCHEMAS["wait"].model_fields["wait_time"].description


def test_the_heading_is_the_step_type_and_its_sentence(form):
    from PySide6.QtWidgets import QLabel

    form.show_step(_ref(0), 0)
    texts = [label.text() for label in form.widget().findChildren(QLabel)]
    assert "Wait" in texts
    assert STEP_SCHEMAS["wait"].model_fields["steptype"].description in texts


# -- values -----------------------------------------------------------------------------


def test_a_value_field_reads_text_the_way_yaml_does():
    assert read_value("2") == 2
    assert read_value("[Continue, Abort]") == ["Continue", "Abort"]
    assert read_value("hello") == "hello"
    assert read_value("[unclosed") == "[unclosed"


def test_a_value_is_shown_as_it_would_be_written():
    assert value_text(2) == "2"
    assert value_text(["A", "B"]) == "[A, B]"
    assert value_text("text") == "text"


def test_editing_a_value_writes_a_number_as_one_undo_entry(model, form):
    form.show_step(_ref(0), 0)
    edit = _field(form, "wait_time").editor
    assert isinstance(edit, QLineEdit)
    edit.setText("7.5")
    edit.editingFinished.emit()
    assert model.steps(0)[0]["wait_time"] == 7.5
    assert model.undo_stack.count() == 1
    assert "# A comment the form must not lose." in model.to_yaml()


def test_a_refill_keeps_the_same_editor(model, form):
    form.show_step(_ref(0), 0)
    edit = _field(form, "wait_time").editor
    edit.setText("3")
    edit.editingFinished.emit()
    assert _field(form, "wait_time").editor is edit
    model.undo_stack.undo()
    assert edit.text() == "2"


def test_emptying_an_optional_text_field_removes_the_key(model, form):
    form.show_step(_ref(0), 0)
    edit = _field(form, "description").editor
    edit.setText("Let it settle")
    edit.editingFinished.emit()
    assert model.steps(0)[0]["description"] == "Let it settle"
    edit.setText("")
    edit.editingFinished.emit()
    assert "description" not in model.steps(0)[0]


def test_a_checkbox_writes_a_bool(model, form):
    form.show_step(_ref(0), 0)
    box = _field(form, "skip").editor
    assert isinstance(box, QCheckBox)
    box.setChecked(True)
    assert model.steps(0)[0]["skip"] is True


def test_an_output_row_writes_its_type_and_fields(model, form):
    form.show_step(_ref(1), 0)
    field = _field(form, "outputs")
    edits = field.editor.findChildren(QLineEdit)
    min_edit = next(e for e in edits if e.placeholderText() == "min")
    min_edit.setText("4.5")
    min_edit.editingFinished.emit()
    assert schema_form.plain(model.steps(0)[1]["outputs"]["result"]) == {
        "type": "range",
        "min": 4.5,
        "max": 5.1,
    }


def test_a_global_input_keeps_its_kind(model, form):
    form.show_step(_ref(1), 0)
    field = _field(form, "inputs")
    edits = field.editor.findChildren(QLineEdit)
    edits[0].editingFinished.emit()
    assert schema_form.plain(model.steps(0)[1]["inputs"]["channel"]) == {
        "type": "global",
        "global_name": "port",
    }


def test_adding_an_output_rebuilds_the_form_with_it(model, form):
    form.show_step(_ref(0), 0)
    form._add_entry(1, ("steps", 0, "outputs"), "result", {"type": "pass"})
    assert schema_form.plain(model.steps(0)[0]["outputs"]) == {"result_1": {"type": "pass"}}
    titles = [group.title() for group in form.widget().findChildren(QGroupBox)]
    assert "Outputs (1)" in titles


def test_the_template_is_a_nested_form(form):
    form.show_step(_ref(2), 0)
    field = _field(form, "template", "method_name")
    assert field.editor.text() == "add"


def test_parameter_sets_are_a_table_of_inputs_and_expectations(model, form):
    form.show_step(_ref(2), 0)
    table = _field(form, "parameter_sets").editor
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers == ["in: a", "in: b", "expect: sum"]
    table.item(0, 2).setText("4")
    assert schema_form.plain(model.steps(0)[2]["parameter_sets"]) == [
        {"inputs": {"a": 1, "b": 2}, "expect": {"sum": 4}}
    ]


# -- header and sequence ----------------------------------------------------------------


def test_with_nothing_selected_the_header_and_sequence_are_edited(model, form):
    form.show_step(None, 0)
    name = _field(form, "name").editor
    assert name.text() == "Form test"
    name.setText("Renamed")
    name.editingFinished.emit()
    assert model.header()["name"] == "Renamed"
    sequence_name = [f for f in form._fields if f.document == 1 and f.path == ("sequence_name",)]
    assert sequence_name[0].editor.text() == "Main"


def test_report_metadata_is_one_comma_separated_field(model, form):
    form.show_step(None, 0)
    edit = _field(form, "report_metadata").editor
    edit.setText("serial_number, operator")
    edit.editingFinished.emit()
    assert schema_form.plain(model.header()["report_metadata"]) == ["serial_number", "operator"]


# -- problems on fields -------------------------------------------------------------------


def test_a_problem_outlines_its_field(form):
    from pypts.helper_applications.recipe_creator.issue import ValidationIssue

    form.show_step(_ref(1), 0)
    issue = ValidationIssue(
        "error",
        "sequence 'Main', steps[2] 'Measure'",
        "outputs -> result -> max: Field required",
        "hint",
        12,
        document=1,
        path=("steps", 1, "outputs", "result", "max"),
    )
    form.set_issues([issue])
    field = _field(form, "outputs")
    assert field.editor.property("problem") is True
    assert "Field required" in field.problem_label.text()
