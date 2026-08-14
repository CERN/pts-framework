# SPDX-FileCopyrightText: 2026 CERN <home.cern>
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Typed recipe-to-runtime construction and execution tests."""

import queue
from pathlib import Path

import pytest
from pydantic import TypeAdapter

import pypts.recipe
from pypts.recipe import (
    STEP_TYPE_REGISTRY,
    IndexedStep,
    Recipe,
    ResultType,
    Runtime,
    Step,
)
from pypts.recipe_language import STEP_DEFINITION_MODELS, StepDefinition
from pypts.recipe_language import Recipe as RecipeDefinition
from pypts.recipe_parser import RecipeParseError, recipe_to_yaml

ROOT = Path(__file__).parents[2]
BUNDLED_RECIPES = sorted((ROOT / "src" / "pypts" / "recipes").glob("*.yml"))


def step_example(kind, **updates):
    value = {
        "steptype": kind,
        "step_name": kind,
        "description": f"Exercise {kind}.",
        "input_mapping": {},
        "output_mapping": {},
    }
    value.update(updates)
    return value


STEP_EXAMPLES = {
    "PythonModuleStep": step_example(
        "PythonModuleStep", action_type="method", module="tests.py", method_name="run"
    ),
    "SequenceStep": step_example(
        "SequenceStep", sequence={"type": "internal", "name": "Target"}
    ),
    "UserInteractionStep": step_example("UserInteractionStep"),
    "WaitStep": step_example(
        "WaitStep", input_mapping={"wait_time": {"type": "direct", "value": 0}}
    ),
    "UserLoadingStep": step_example(
        "UserLoadingStep",
        file_save_location={"type": "local", "variable": "selected"},
    ),
    "UserRunMethodStep": step_example(
        "UserRunMethodStep",
        trigger_response="run",
        action_type="method",
        module="tests.py",
        method_name="run",
    ),
    "UserWriteStep": step_example("UserWriteStep"),
    "SerialNumberStep": step_example("SerialNumberStep"),
    "SSHConnectStep": step_example("SSHConnectStep"),
    "SSHCloseStep": step_example("SSHCloseStep"),
    "SSHUploadStep": step_example(
        "SSHUploadStep",
        files=[{"local": "bin/tool", "remote": "/tmp/tool"}],
        permissions="0755",
        skip_if_sha256_match=True,
        local_package="fixtures",
    ),
}


def wait_step(name, *, indexed=False):
    value = [0, 0] if indexed else 0
    mapping = {"type": "direct", "value": value}
    if indexed:
        mapping["indexed"] = True
    return {
        "steptype": "WaitStep",
        "step_name": name,
        "description": name,
        "input_mapping": {"wait_time": mapping},
    }


def definition():
    return RecipeDefinition.model_validate({
        "header": {
            "name": "Runtime recipe",
            "version": "1.0",
            "recipe_version": "2.0.0",
            "description": "Typed runtime fixture.",
            "main_sequence": "Main",
            "globals": {"shared": 1},
        },
        "sequences": [
            {
                "sequence_name": "Main",
                "description": "Main.",
                "parameters": {},
                "outputs": {},
                "locals": {"local": 1},
                "setup_steps": [wait_step("setup")],
                "steps": [
                    wait_step("indexed", indexed=True),
                    {
                        "steptype": "SequenceStep",
                        "step_name": "nested",
                        "description": "Nested.",
                        "sequence": {"type": "internal", "name": "Sub"},
                    },
                ],
                "teardown_steps": [wait_step("teardown")],
            },
            {
                "sequence_name": "Sub",
                "description": "Sub.",
                "parameters": {},
                "outputs": {},
                "locals": {},
                "setup_steps": [],
                "steps": [wait_step("sub")],
                "teardown_steps": [],
            },
        ],
    })


def runtime():
    Runtime.stop_event.clear()
    return Runtime(queue.SimpleQueue(), queue.SimpleQueue())


def test_recipe_from_definition_constructs_typed_runtime_state_without_reparse():
    model = definition()
    recipe = Recipe.from_definition(model, "fixture.yml")
    assert recipe.definition is model
    assert recipe.recipe_file_name == "fixture.yml"
    assert list(recipe.sequences) == ["Main", "Sub"]
    assert isinstance(recipe.sequences["Main"].steps[1], IndexedStep)
    assert recipe.total_steps == 8


def test_recipe_path_requires_v2_and_raises_structured_error(tmp_path):
    v2 = tmp_path / "v2.yml"
    v2.write_text(recipe_to_yaml(definition()), encoding="utf-8")
    assert Recipe(v2).main_sequence == "Main"

    legacy = tmp_path / "v1.yml"
    legacy.write_text(v2.read_text(encoding="utf-8").replace("2.0.0", "1.0.0"))
    with pytest.raises(RecipeParseError) as caught:
        Recipe(legacy)
    assert "unsupported-recipe-version" in {d.code for d in caught.value.diagnostics}


@pytest.mark.parametrize("path", BUNDLED_RECIPES)
def test_every_bundled_recipe_constructs_runtime_state(path):
    recipe = Recipe(path)
    assert recipe.definition.header.recipe_version == "2.0.0"
    assert recipe.main_sequence in recipe.sequences


@pytest.mark.parametrize("path", BUNDLED_RECIPES)
def test_every_bundled_recipe_enters_execution_without_hardware(path, monkeypatch):
    monkeypatch.setattr(pypts.recipe.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        pypts.recipe.ExecutableSequenceStep,
        "run",
        lambda self, active_runtime, inputs, stop_event: ResultType.DONE,
    )
    active_runtime = runtime()
    recipe = Recipe(path)

    assert recipe.run(active_runtime) == []
    assert active_runtime.recipe_name == recipe.name
    assert active_runtime.recipe_file_name == path.name
    Runtime.stop_event.clear()


def test_registry_exactly_matches_step_definition_discriminators():
    discriminators = {
        model.model_fields["steptype"].examples[0]
        for model in STEP_DEFINITION_MODELS
    }
    assert set(STEP_TYPE_REGISTRY) == discriminators


@pytest.mark.parametrize("name", STEP_EXAMPLES)
def test_every_typed_definition_builds_its_concrete_executable(name):
    typed = TypeAdapter(StepDefinition).validate_python(STEP_EXAMPLES[name])
    executable = Step.build_step(typed)
    assert type(executable).__name__ == name
    assert executable.input_mapping == typed.model_dump(
        mode="python", by_alias=True
    )["input_mapping"]


def test_indexed_direct_input_is_the_only_source_of_runtime_wrapping():
    typed = definition().sequences[0].steps[0]
    executable = Step.build_step(typed)
    assert isinstance(executable, IndexedStep)
    assert executable.template_step.input_mapping["wait_time"]["indexed"] is True


def test_setup_main_nested_and_teardown_execute_with_existing_runtime_behavior():
    recipe = Recipe.from_definition(definition())
    active_runtime = runtime()
    active_runtime.set_globals(recipe.globals)
    active_runtime.set_sequences(recipe.sequences)
    result = recipe.sequences["Main"].run(active_runtime, {})
    assert result == ResultType.DONE
    assert [item.step.name for item in active_runtime.results] == [
        "setup", "indexed", "nested", "teardown"
    ]


def test_recipe_run_constructs_top_level_sequence_step_directly(monkeypatch):
    recipe = Recipe.from_definition(definition())
    active_runtime = runtime()
    monkeypatch.setattr(pypts.recipe.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        Step,
        "build_step",
        staticmethod(lambda _: (_ for _ in ()).throw(AssertionError("synthetic dict factory used"))),
    )
    results = recipe.run(active_runtime)
    assert results
    assert active_runtime.recipe_name == recipe.name

    pending = list(results)
    result_count = 0
    while pending:
        result = pending.pop()
        result_count += 1
        pending.extend(result.subresults)
    assert result_count == recipe.total_steps
