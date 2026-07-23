import textwrap

import pytest

from pypts.YamVIEW.verify_recipe import RecipeValidationError, validate_recipe_file


def write_recipe(tmp_path, body):
    path = tmp_path / "recipe.yml"
    path.write_text(textwrap.dedent(body))
    return path


def test_validates_setup_main_and_teardown_semantics(tmp_path):
    path = write_recipe(tmp_path, """
        name: Valid
        version: "1"
        description: valid
        globals: {}
        ---
        sequence_name: Main
        description: main
        parameters: {}
        outputs: {}
        locals: {}
        setup_steps: []
        steps:
          - steptype: WaitStep
            step_name: wait
            description: wait
            input_mapping: {}
            output_mapping: {}
        teardown_steps: []
    """)
    validate_recipe_file(path)


@pytest.mark.parametrize("section", ["setup_steps", "steps", "teardown_steps"])
def test_rejects_invalid_step_in_every_section(tmp_path, section):
    path = write_recipe(tmp_path, f"""
        name: Invalid
        version: "1"
        description: invalid
        globals: {{}}
        ---
        sequence_name: Main
        description: main
        parameters: {{}}
        outputs: {{}}
        locals: {{}}
        setup_steps: {"[{steptype: Unknown, step_name: bad}]" if section == "setup_steps" else "[]"}
        steps: {"[{steptype: Unknown, step_name: bad}]" if section == "steps" else "[]"}
        teardown_steps: {"[{steptype: Unknown, step_name: bad}]" if section == "teardown_steps" else "[]"}
    """)
    with pytest.raises(RecipeValidationError, match="Validation failed"):
        validate_recipe_file(path)


def test_rejects_unknown_sequence_index_lengths_and_mixed_passthrough(tmp_path):
    path = write_recipe(tmp_path, """
        name: Invalid
        version: "1"
        description: invalid
        globals: {}
        ---
        sequence_name: Main
        description: main
        parameters: {}
        outputs: {}
        locals: {}
        setup_steps: []
        steps:
          - steptype: SequenceStep
            step_name: sub
            description: sub
            sequence: {type: internal, name: Missing}
            input_mapping:
              a: {value: [1], indexed: true}
              b: {value: [1, 2], indexed: true}
            output_mapping:
              result: {type: passthrough}
              ok: {type: passfail}
        teardown_steps: []
    """)
    with pytest.raises(RecipeValidationError) as error:
        validate_recipe_file(path)
    faults = "\n".join(error.value.faults)
    assert "equal lengths" in faults
    assert "sole verdict" in faults
    assert "unknown sequence 'Missing'" in faults


def test_rejects_invalid_mapping_fields_and_top_level_policy(tmp_path):
    path = write_recipe(tmp_path, """
        name: Invalid
        version: "1"
        description: invalid
        continue_on_error: true
        globals: {}
        ---
        sequence_name: Main
        description: main
        parameters: []
        outputs: []
        locals: {}
        setup_steps: []
        steps:
          - steptype: WaitStep
            step_name: wait
            description: wait
            input_mapping: {}
            output_mapping:
              measured: {type: range, min: 0}
        teardown_steps: []
    """)
    with pytest.raises(RecipeValidationError) as error:
        validate_recipe_file(path)
    faults = "\n".join(error.value.faults)
    assert "move it under 'globals'" in faults
    assert "'parameters' should be a dictionary" in faults
    assert "requires 'max'" in faults


def test_rejects_invalid_ssh_lifecycle(tmp_path):
    path = write_recipe(tmp_path, """
        name: Invalid SSH
        version: "1"
        description: invalid
        globals: {ssh_client: null}
        ---
        sequence_name: Main
        description: main
        parameters: {}
        outputs: {}
        locals: {}
        setup_steps: []
        steps:
          - steptype: SSHUploadStep
            step_name: upload
            description: upload
            files: []
            input_mapping: {}
            output_mapping: {}
        teardown_steps: []
    """)
    with pytest.raises(RecipeValidationError) as error:
        validate_recipe_file(path)
    faults = "\n".join(error.value.faults)
    assert "SSHUploadStep requires SSHConnectStep" in faults
    assert "require global 'host'" in faults
