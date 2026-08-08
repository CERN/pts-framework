# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pytest
import yaml

from pypts.recipe_language import STEP_SPECS, canonical_step_type, validate_recipe_documents


RECIPES = Path(__file__).parents[2] / "src" / "pypts" / "recipes"


def _recipe_with_step(step, *, contextual=True):
    sequence = {
        "sequence_name": "Main",
        "description": "Main sequence.",
        "parameters": {}, "outputs": {}, "locals": {},
        "setup_steps": [], "steps": [step], "teardown_steps": [],
    }
    step_type = canonical_step_type(step["steptype"])
    documents = [
        {
            "name": "Language contract",
            "version": "1.0",
            "recipe_version": "1.0.0",
            "description": "Contract fixture.",
            "main_sequence": "Main",
            "globals": {"ssh_client": None, "host": "target", "user": "root", "port": 22, "password": "secret"},
        },
    ]
    if contextual and step_type == "SequenceStep":
        documents.append({
            "sequence_name": step["sequence"]["name"], "description": "Target sequence.",
            "parameters": {}, "outputs": {}, "locals": {},
            "setup_steps": [], "steps": [], "teardown_steps": [],
        })
    if contextual and step_type == "SSHUploadStep":
        sequence["setup_steps"] = [{
            "steptype": "SSHConnectStep", "step_name": "Connect", "description": "Connect.",
        }]
        sequence["teardown_steps"] = [{
            "steptype": "SSHCloseStep", "step_name": "Close", "description": "Close.",
        }]
    documents.append(sequence)
    return documents


@pytest.mark.parametrize("path", sorted(path for path in RECIPES.glob("*.yml") if path.name != "subsequence_executions_draft.yml"))
def test_working_recipe_corpus_conforms(path):
    result = validate_recipe_documents(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    assert result.is_valid, result.errors


def test_empty_draft_is_not_a_recipe():
    draft = RECIPES / "subsequence_executions_draft.yml"
    result = validate_recipe_documents(yaml.safe_load_all(draft.read_text(encoding="utf-8")))
    assert [item.code for item in result.errors] == ["empty-recipe"]


@pytest.mark.parametrize("spec", [spec for spec in STEP_SPECS if spec.source_allowed], ids=lambda spec: spec.name)
def test_every_step_spec_has_a_valid_canonical_example(spec):
    result = validate_recipe_documents(_recipe_with_step(dict(spec.example)))
    assert result.is_valid, result.errors


def test_step_types_are_case_insensitive_but_have_one_canonical_name():
    assert canonical_step_type("pythonmodulestep") == "PythonModuleStep"
    assert canonical_step_type("UnknownStep") is None


def test_internal_indexed_step_cannot_be_written_in_a_recipe():
    step = {
        "steptype": "IndexedStep", "step_name": "Internal", "description": "Internal wrapper.",
        "input_mapping": {}, "output_mapping": {},
    }
    codes = {item.code for item in validate_recipe_documents(_recipe_with_step(step)).errors}
    assert "internal-step-type" in codes


def test_implicit_direct_input_is_accepted_as_legacy_syntax():
    step = {
        "steptype": "WaitStep", "step_name": "Wait", "description": "Wait.",
        "input_mapping": {"wait_time": {"value": 1}}, "output_mapping": {},
    }
    assert validate_recipe_documents(_recipe_with_step(step)).is_valid


def test_mapping_and_sequence_contract_failures_are_reported():
    step = {
        "steptype": "SequenceStep", "step_name": "Missing", "description": "Missing target.",
        "sequence": {"type": "internal", "name": "NoSuchSequence"},
        "input_mapping": {
            "left": {"type": "direct", "value": [1], "indexed": True},
            "right": {"type": "direct", "value": [1, 2], "indexed": True},
        },
        "output_mapping": {"result": {"type": "passthrough"}, "passed": {"type": "passfail"}},
    }
    codes = {item.code for item in validate_recipe_documents(_recipe_with_step(step, contextual=False)).errors}
    assert {"unequal-indexed-inputs", "mixed-passthrough", "unknown-sequence-reference"} <= codes


def test_ssh_lifecycle_is_part_of_the_contract():
    step = {
        "steptype": "SSHUploadStep", "step_name": "Upload", "description": "Upload.",
        "files": [], "output_mapping": {},
    }
    result = validate_recipe_documents(_recipe_with_step(step, contextual=False))
    assert "missing-ssh-connect" in {item.code for item in result.errors}
