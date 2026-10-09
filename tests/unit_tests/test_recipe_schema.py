"""
Unit tests for the recipe schema: the Pydantic models in recipe_schema.py.

The models see a recipe after the parser has normalized it (keys and the
steptype value lowercased), so these tests feed them lowercase mappings. What
a model must accept is what a recipe loads with today: the parser hands the
validated mapping to the step constructors, so a key the constructor takes is
accepted here and a key it would refuse is refused here - earlier, and
alongside every other problem in the file.
"""

import datetime
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from pypts.recipe.recipe_schema import (
    STEP_REQUIRED,
    STEP_SCHEMAS,
    STEP_TYPE_REQUIRED,
    UNNAMED_STEP_TYPES,
    HeaderSchema,
    IndexedStepSchema,
    PythonModuleStepSchema,
    SequenceSchema,
    SequenceStepSchema,
    UserInteractionStepSchema,
    UserLoadingStepSchema,
    UserWriteStepSchema,
    WaitStepSchema,
)
from pypts.step.sequence_step import REFUSED_KEYS

# -- helpers -------------------------------------------------------------------


def _header(**changes: Any) -> dict[str, Any]:
    header: dict[str, Any] = {"name": "Demo", "version": "0.2"}
    header.update(changes)
    return header


def _wait(**changes: Any) -> dict[str, Any]:
    step: dict[str, Any] = {"steptype": "wait", "step_name": "w", "wait_time": "1"}
    step.update(changes)
    return step


def _module(**changes: Any) -> dict[str, Any]:
    step: dict[str, Any] = {
        "steptype": "pythonmodule",
        "step_name": "x",
        "module": "m.py",
        "method_name": "f",
    }
    step.update(changes)
    return step


def _indexed(**changes: Any) -> dict[str, Any]:
    step: dict[str, Any] = {
        "steptype": "indexed",
        "step_name": "Loop",
        "template": _module(),
        "parameter_sets": [{"inputs": {"a": 1}}],
    }
    step.update(changes)
    return step


def _one_step(raw: Any) -> Any:
    return SequenceSchema.model_validate({"sequence_name": "M", "steps": [raw]}).steps[0]


def _problems(cls: type[BaseModel], raw: dict[str, Any]) -> list[tuple[tuple[Any, ...], str]]:
    """Every (location, message) the model reports for `raw`; [] if it is valid."""
    try:
        cls.model_validate(raw)
    except ValidationError as error:
        return [(tuple(e["loc"]), e["msg"]) for e in error.errors()]
    return []


def _step_problems(raw: Any) -> list[tuple[tuple[Any, ...], str]]:
    return _problems(SequenceSchema, {"sequence_name": "M", "steps": [raw]})


# -- HeaderSchema ----------------------------------------------------------------


def test_header_minimal_gets_every_default():
    header = HeaderSchema.model_validate(_header())
    assert header.name == "Demo"
    assert header.version == "0.2"
    assert header.description == ""
    assert header.main_sequence == ""
    assert header.globals == {}
    assert header.report_metadata == ["serial_number"]


def test_header_numeric_version_is_read_as_text():
    """`version: 0.2` is a float to YAML; every demo recipe writes it that way."""
    assert HeaderSchema.model_validate(_header(version=0.2)).version == "0.2"


@pytest.mark.parametrize("field", ["name", "version"])
def test_header_required_field_missing(field):
    raw = _header()
    del raw[field]
    assert _problems(HeaderSchema, raw) == [((field,), "Field required")]


@pytest.mark.parametrize("field", ["name", "version"])
def test_header_required_field_written_bare_is_missing(field):
    """A bare `name:` line reads as None - the same as not writing it."""
    assert _problems(HeaderSchema, _header(**{field: None})) == [((field,), "Field required")]


@pytest.mark.parametrize(
    "field, default",
    [
        ("description", ""),
        ("main_sequence", ""),
        ("globals", {}),
        ("report_metadata", ["serial_number"]),
    ],
)
def test_header_optional_field_written_bare_gets_its_default(field, default):
    header = HeaderSchema.model_validate(_header(**{field: None}))
    assert getattr(header, field) == default


@pytest.mark.parametrize("field", ["name", "version", "description", "main_sequence"])
def test_header_single_value_field_refuses_a_list(field):
    problems = _problems(HeaderSchema, _header(**{field: ["a", "b"]}))
    assert [loc for loc, _ in problems] == [(field,)]


@pytest.mark.parametrize("written", [5, [1, 2], "text"])
def test_header_globals_must_be_a_mapping(written):
    problems = _problems(HeaderSchema, _header(globals=written))
    assert [loc for loc, _ in problems] == [("globals",)]


def test_header_report_metadata_names_are_stripped():
    header = HeaderSchema.model_validate(_header(report_metadata=[" batch_id ", "operator"]))
    assert header.report_metadata == ["batch_id", "operator"]


def test_header_report_metadata_may_be_empty():
    assert HeaderSchema.model_validate(_header(report_metadata=[])).report_metadata == []


@pytest.mark.parametrize("written", [3, "serial_number", [3], [""], ["  "], [None]])
def test_header_report_metadata_must_be_a_list_of_names(written):
    """They become CSV columns, so a column called `3` or `` is refused."""
    problems = _problems(HeaderSchema, _header(report_metadata=written))
    assert problems
    assert all(loc[0] == "report_metadata" for loc, _ in problems)


def test_header_unknown_key_is_ignored():
    assert _problems(HeaderSchema, _header(bogus_key="hello")) == []


def test_header_reports_every_problem_at_once():
    problems = _problems(HeaderSchema, {"name": ["a"], "globals": 5})
    assert sorted(loc for loc, _ in problems) == [("globals",), ("name",), ("version",)]


# -- SequenceSchema --------------------------------------------------------------


def test_sequence_minimal_gets_every_default():
    sequence = SequenceSchema.model_validate({"sequence_name": "Main", "steps": [_wait()]})
    assert sequence.sequence_name == "Main"
    assert sequence.description == ""
    assert sequence.teardown_steps == []
    assert len(sequence.steps) == 1


def test_sequence_numeric_name_is_read_as_text():
    sequence = SequenceSchema.model_validate({"sequence_name": 7, "steps": [_wait()]})
    assert sequence.sequence_name == "7"


@pytest.mark.parametrize("field", ["sequence_name", "steps"])
def test_sequence_required_field_missing(field):
    raw: dict[str, Any] = {"sequence_name": "Main", "steps": [_wait()]}
    del raw[field]
    assert _problems(SequenceSchema, raw) == [((field,), "Field required")]


def test_sequence_steps_must_hold_a_step():
    problems = _problems(SequenceSchema, {"sequence_name": "Main", "steps": []})
    assert [loc for loc, _ in problems] == [("steps",)]


def test_sequence_teardown_steps_may_be_empty():
    raw = {"sequence_name": "Main", "steps": [_wait()], "teardown_steps": []}
    assert _problems(SequenceSchema, raw) == []


def test_sequence_bare_teardown_steps_means_none():
    raw = {"sequence_name": "Main", "steps": [_wait()], "teardown_steps": None}
    assert SequenceSchema.model_validate(raw).teardown_steps == []


def test_sequence_unknown_key_is_ignored():
    raw = {"sequence_name": "Main", "steps": [_wait()], "bogus_key": 1}
    assert _problems(SequenceSchema, raw) == []


def test_teardown_steps_are_validated_too():
    raw = {"sequence_name": "Main", "steps": [_wait()], "teardown_steps": [_wait(wait_time=None)]}
    locs = [loc for loc, _ in _problems(SequenceSchema, raw)]
    assert locs == [("teardown_steps", 0, "wait", "wait_time")]


# -- every steptype --------------------------------------------------------------

_ONE_OF_EACH: dict[str, tuple[dict[str, Any], type[BaseModel]]] = {
    "pythonmodule": (_module(), PythonModuleStepSchema),
    "userinteraction": (
        {"steptype": "userinteraction", "step_name": "q", "message": "m", "options": ["Y", "N"]},
        UserInteractionStepSchema,
    ),
    "userwrite": ({"steptype": "userwrite", "step_name": "q", "message": "m"}, UserWriteStepSchema),
    "userloading": (
        {"steptype": "userloading", "step_name": "q", "message": "m"},
        UserLoadingStepSchema,
    ),
    "wait": (_wait(), WaitStepSchema),
    "sequence": ({"steptype": "sequence", "sequence_name": "Other"}, SequenceStepSchema),
    "indexed": (_indexed(), IndexedStepSchema),
}


def test_every_steptype_in_the_rules_has_a_model():
    assert sorted(_ONE_OF_EACH) == sorted(STEP_TYPE_REQUIRED)


@pytest.mark.parametrize("steptype", sorted(_ONE_OF_EACH))
def test_step_schemas_names_each_steptype_s_model(steptype):
    """The table a tool reads to ask a steptype which keys it takes."""
    assert STEP_SCHEMAS[steptype] is _ONE_OF_EACH[steptype][1]
    assert sorted(STEP_SCHEMAS) == sorted(STEP_TYPE_REQUIRED)


@pytest.mark.parametrize("steptype", sorted(_ONE_OF_EACH))
def test_a_valid_step_parses_into_its_model(steptype):
    raw, model = _ONE_OF_EACH[steptype]
    assert isinstance(_one_step(raw), model)


@pytest.mark.parametrize("steptype", sorted(_ONE_OF_EACH))
def test_the_required_fields_are_the_ones_the_rules_name(steptype):
    """The constants (read by the Recipe Creator) and the models must not drift."""
    _, model = _ONE_OF_EACH[steptype]
    expected = set(STEP_REQUIRED) | set(STEP_TYPE_REQUIRED[steptype])
    if steptype in UNNAMED_STEP_TYPES:
        expected.discard("step_name")
    required = {name for name, field in model.model_fields.items() if field.is_required()}
    assert required == expected


@pytest.mark.parametrize("steptype", sorted(_ONE_OF_EACH))
def test_each_required_field_written_bare_is_missing(steptype):
    raw, _ = _ONE_OF_EACH[steptype]
    for field in STEP_TYPE_REQUIRED[steptype]:
        problems = _step_problems({**raw, field: None})
        assert [(loc[-1], msg) for loc, msg in problems] == [(field, "Field required")]


def test_unknown_steptype_names_the_ones_that_exist():
    problems = _step_problems(_wait(steptype="bogus"))
    assert len(problems) == 1
    loc, message = problems[0]
    assert loc == ("steps", 0)
    assert "'bogus'" in message
    assert "'pythonmodule'" in message


def test_missing_steptype_is_refused():
    problems = _step_problems({"step_name": "x"})
    assert [loc for loc, _ in problems] == [("steps", 0)]


def test_steptype_is_matched_in_lowercase_only():
    """The parser lowercases the value before validating; the models do not."""
    assert _step_problems(_wait(steptype="Wait"))


def test_a_step_that_is_not_a_mapping_is_refused():
    assert _step_problems("just text")


def test_a_typo_in_a_step_key_is_refused():
    """The step constructor would refuse it at build time; now it is named with the rest."""
    problems = _step_problems(_wait(contine_on_error=False))
    assert problems == [
        (("steps", 0, "wait", "contine_on_error"), "Extra inputs are not permitted")
    ]


def test_a_step_id_is_accepted():
    assert _one_step(_wait(id="6f1c2d9e")).id == "6f1c2d9e"


def test_a_numeric_step_name_is_read_as_text():
    assert _one_step(_wait(step_name=7)).step_name == "7"


def test_an_optional_step_field_written_bare_stays_unset():
    """Unset, so model_dump(exclude_unset=True) leaves the default to the constructor
    - and an Indexed wrapper's skip / continue_on_error still reaches its steps."""
    step = _one_step(_wait(skip=None, continue_on_error=None, description=None, id=None))
    assert step.skip is False
    assert step.continue_on_error is True
    assert step.description == ""
    assert step.id == ""
    assert step.model_fields_set == {"steptype", "step_name", "wait_time"}


@pytest.mark.parametrize("written", [True, datetime.date(2024, 1, 1), ["a", "b"]])
def test_a_text_field_refuses_what_is_not_text_or_a_number(written):
    """`message: yes` is a YAML boolean, and a date is a date: the author quotes
    the value. Only numbers are read as text."""
    raw = {"steptype": "userwrite", "step_name": "q", "message": written}
    problems = _step_problems(raw)
    assert [(loc[-1], msg) for loc, msg in problems] == [
        ("message", "Input should be a valid string")
    ]


def test_userloading_select_defaults_to_file():
    raw, _ = _ONE_OF_EACH["userloading"]
    assert _one_step(raw).select == "file"


def test_a_falsy_value_is_still_a_value():
    step = _one_step(_wait(wait_time=0))
    assert step.wait_time == 0


# -- inputs and outputs ----------------------------------------------------------


def test_an_input_written_as_itself_is_a_literal():
    step = _one_step(_module(inputs={"limit": 42, "names": ["a", "b"]}))
    assert step.inputs == {"limit": 42, "names": ["a", "b"]}


def test_a_global_input_needs_its_global_name():
    problems = _step_problems(_module(inputs={"v": {"type": "global"}}))
    assert len(problems) == 1
    loc, message = problems[0]
    assert loc == ("steps", 0, "pythonmodule", "inputs", "v")
    assert "global_name" in message


def test_an_input_mapping_must_name_its_type():
    problems = _step_problems(_module(inputs={"v": {"global_name": "g"}}))
    assert len(problems) == 1
    assert "type" in problems[0][1]


def test_an_unknown_input_type_is_refused():
    problems = _step_problems(_module(inputs={"v": {"type": "local", "global_name": "g"}}))
    assert len(problems) == 1
    assert "'local'" in problems[0][1]


def test_a_well_formed_global_input_is_kept_as_written():
    entry = {"type": "global", "global_name": "g"}
    assert _one_step(_module(inputs={"v": entry})).inputs == {"v": entry}


@pytest.mark.parametrize(
    "entry",
    [
        {"type": "pass"},
        {"type": "passfail"},
        {"type": "equals", "value": 0},
        {"type": "range", "min": 1, "max": 2},
        {"type": "global", "global_name": "g"},
    ],
)
def test_every_output_type_is_accepted(entry):
    step = _one_step(_module(outputs={"r": entry}))
    assert step.model_dump(exclude_unset=True)["outputs"] == {"r": entry}


def test_an_unknown_output_type_is_refused():
    problems = _step_problems(_module(outputs={"r": {"type": "local"}}))
    assert len(problems) == 1
    assert "'local'" in problems[0][1]


def test_a_range_output_needs_both_bounds():
    problems = _step_problems(_module(outputs={"r": {"type": "range", "min": 1}}))
    assert problems == [
        (("steps", 0, "pythonmodule", "outputs", "r", "range", "max"), "Field required")
    ]


def test_an_equals_output_written_bare_has_no_value():
    problems = _step_problems(_module(outputs={"r": {"type": "equals", "value": None}}))
    assert [(loc[-1], msg) for loc, msg in problems] == [("value", "Field required")]


def test_an_output_must_be_a_mapping():
    assert _step_problems(_module(outputs={"r": "pass"}))


def test_a_wait_step_may_carry_inputs_and_outputs():
    """WaitStep takes them through Step's constructor, as every ordinary step does."""
    assert _step_problems(_wait(inputs={"a": 1}, outputs={"r": {"type": "pass"}})) == []


# -- Sequence steps --------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(REFUSED_KEYS))
def test_a_sequence_step_refuses_its_refused_keys_with_the_reason(key):
    raw = {"steptype": "sequence", "sequence_name": "Other", key: "x"}
    problems = _step_problems(raw)
    assert problems == [(("steps", 0, "sequence", key), REFUSED_KEYS[key])]


def test_a_sequence_step_refuses_a_sequence_object():
    """`sequence` is the called Sequence, which the parser adds after validation."""
    raw = {"steptype": "sequence", "sequence_name": "Other", "sequence": "x"}
    assert _step_problems(raw)


@pytest.mark.parametrize("blank", ["   ", "\t", " \n "])
def test_a_sequence_step_refuses_a_name_of_only_whitespace(blank):
    """Caught here, with every other problem and its line - not at build time, alone."""
    raw = {"steptype": "sequence", "sequence_name": blank}
    problems = _step_problems(raw)
    assert problems == [
        (
            ("steps", 0, "sequence", "sequence_name"),
            "'sequence_name' must be the name of a sequence in this recipe",
        )
    ]


def test_a_sequence_step_must_name_a_sequence():
    raw = {"steptype": "sequence", "sequence_name": ""}
    problems = _step_problems(raw)
    assert [loc for loc, _ in problems] == [("steps", 0, "sequence", "sequence_name")]


# -- Indexed steps ---------------------------------------------------------------


def test_an_indexed_template_is_validated_as_its_own_steptype():
    step = _one_step(_indexed())
    assert isinstance(step.template, PythonModuleStepSchema)


def test_an_indexed_template_may_leave_out_its_step_name():
    """Every generated step is named after its parameters, never after the template."""
    template = {"steptype": "wait", "wait_time": 1}
    step = _one_step(_indexed(template=template))
    assert isinstance(step.template, WaitStepSchema)
    assert "step_name" not in template  # the recipe's own mapping is not touched


def test_an_indexed_template_is_checked_as_the_step_it_becomes():
    problems = _step_problems(_indexed(template={"steptype": "wait"}))
    assert [loc for loc, _ in problems] == [
        ("steps", 0, "indexed", "template", "wait", "wait_time")
    ]


@pytest.mark.parametrize("key", ["id", "inputs", "outputs"])
def test_an_indexed_step_refuses_what_belongs_on_the_template(key):
    problems = _step_problems(_indexed(**{key: {"a": 1}}))
    assert len(problems) == 1
    loc, message = problems[0]
    assert loc == ("steps", 0, "indexed", key)
    assert key in message


@pytest.mark.parametrize(
    "template, word",
    [
        ({"steptype": "sequence", "sequence_name": "Other"}, "Sequence"),
        (_indexed(), "indexed"),
        (_module(id="abc"), "id"),
    ],
)
def test_an_indexed_template_cannot_be_a_group_or_carry_an_id(template, word):
    problems = _step_problems(_indexed(template=template))
    assert len(problems) == 1
    loc, message = problems[0]
    assert loc == ("steps", 0, "indexed", "template")
    assert word in message


@pytest.mark.parametrize("sets", [[], 5, [5], [{}], [{"inputs": {}}], [{"bogus": {"a": 1}}]])
def test_bad_parameter_sets_are_refused(sets):
    problems = _step_problems(_indexed(parameter_sets=sets))
    assert problems
    assert all(loc[:4] == ("steps", 0, "indexed", "parameter_sets") for loc, _ in problems)


def test_a_parameter_set_may_carry_only_an_expectation():
    assert _step_problems(_indexed(parameter_sets=[{"expect": {"r": 1}}])) == []


def test_wrapper_and_template_problems_are_reported_together():
    problems = _step_problems(_indexed(template={"steptype": "wait"}, parameter_sets=5))
    fields = sorted(loc[-1] for loc, _ in problems)
    assert fields == ["parameter_sets", "wait_time"]


# -- the hand-off to the build pipeline ------------------------------------------


def test_exclude_unset_dump_holds_only_what_the_recipe_wrote():
    raw = {"sequence_name": "Main", "steps": [_wait(skip=None)]}
    dumped = SequenceSchema.model_validate(raw).model_dump(exclude_unset=True)
    assert dumped == {
        "sequence_name": "Main",
        "steps": [{"steptype": "wait", "step_name": "w", "wait_time": "1"}],
    }


def test_exclude_unset_dump_keeps_the_text_a_number_was_read_as():
    raw = {"sequence_name": "Main", "steps": [_wait(step_name=7)]}
    dumped = SequenceSchema.model_validate(raw).model_dump(exclude_unset=True)
    assert dumped["steps"][0]["step_name"] == "7"
