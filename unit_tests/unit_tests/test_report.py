# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pypts import _result_to_dict
from unittest.mock import MagicMock
import subprocess
import sys
from pathlib import Path
import pytest
import csv
import json
from pypts import ResultType

# Define the project root relative to this test file
PROJECT_ROOT = Path(__file__).parent.parent.parent

def test_main_report_generation(tmp_path):
    """
    Tests the __main__ block of report.py to ensure it runs and creates a report file.
    """
    report_py_path = PROJECT_ROOT / "src" / "pypts" / "report.py"
    output_dir = tmp_path / "temp_report_output"
    expected_report_path = output_dir / "report.csv"

    # Ensure the script path exists
    assert report_py_path.exists(), f"Script not found at {report_py_path}"

    # Construct the command
    # Use sys.executable to ensure the same Python interpreter is used
    command = [
        sys.executable,
        str(report_py_path),
        "-o", str(output_dir)
    ]

    # Execute the script as a subprocess
    # Run from the project root to handle relative imports/paths within the script if any
    result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    # Print stdout/stderr for debugging if the test fails
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)

    # Assertions
    assert result.returncode == 0, f"Script execution failed with return code {result.returncode}"
    assert expected_report_path.exists(), f"Expected report file not found at {expected_report_path}"
    assert expected_report_path.is_file(), f"Expected report path is not a file: {expected_report_path}"

    # Optional: Basic check on file content (e.g., not empty)
    assert expected_report_path.stat().st_size > 0, "Report file is empty"

    # Cleanup is handled automatically by pytest's tmp_path fixture

def test_main_report_content(tmp_path):
    """
    Tests the content of the generated report.csv from the __main__ block of report.py.
    """
    report_py_path = PROJECT_ROOT / "src" / "pypts" / "report.py"
    output_dir = tmp_path / "temp_report_output"
    report_path = output_dir / "report.csv"

    # --- Run the script (similar to test_main_report_generation) ---
    assert report_py_path.exists(), f"Script not found at {report_py_path}"
    command = [sys.executable, str(report_py_path), "-o", str(output_dir)]
    result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    assert result.returncode == 0, "Script execution failed"
    assert report_path.exists(), "Report file was not created"
    assert report_path.stat().st_size > 0, "Report file is empty"
    # --- End script run ---

    # --- Read and verify CSV content ---
    results_by_step_name = {}
    try:
        with open(report_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Use step_name as a key, assuming step names are unique in the example
                step_name = row.get('step_name')
                if step_name:
                    # Parse JSON strings back into dicts for easier comparison
                    try:
                        row['inputs'] = json.loads(row['inputs']) if row.get('inputs') else None
                    except json.JSONDecodeError:
                        pytest.fail(f"Failed to parse inputs JSON for step '{step_name}': {row.get('inputs')}")
                    try:
                        row['outputs'] = json.loads(row['outputs']) if row.get('outputs') else None
                    except json.JSONDecodeError:
                         pytest.fail(f"Failed to parse outputs JSON for step '{step_name}': {row.get('outputs')}")
                    results_by_step_name[step_name] = row
                else:
                    pytest.fail(f"Row found without a step_name: {row}")

    except FileNotFoundError:
        pytest.fail(f"Report file not found at {report_path} after script execution.")
    except Exception as e:
        pytest.fail(f"Error reading or parsing CSV file: {e}")

    # --- Assertions based on the simulated data in report.py __main__ ---
    assert len(results_by_step_name) == 4, f"Expected 4 rows in CSV, found {len(results_by_step_name)}"

    # Step 1: Run Other Test
    step1_name = "Run Other Test"
    assert step1_name in results_by_step_name
    step1_res = results_by_step_name[step1_name]
    assert step1_res['result'] == str(ResultType.PASS), f"{step1_name} result mismatch"
    assert step1_res['inputs'] == {"arg1": 10}, f"{step1_name} inputs mismatch"
    assert step1_res['outputs'] == {"some_return": True, "value": "abc"}, f"{step1_name} outputs mismatch"
    assert not step1_res['error_info'], f"{step1_name} should have no error info"

    # Step 2: Run Simple Output Test
    step2_name = "Run Simple Output Test"
    assert step2_name in results_by_step_name
    step2_res = results_by_step_name[step2_name]
    assert step2_res['result'] == str(ResultType.PASS), f"{step2_name} result mismatch"
    assert step2_res['inputs'] == {"value": "abc"}, f"{step2_name} inputs mismatch"
    assert step2_res['outputs'] == {"my_output": "calculated_abc"}, f"{step2_name} outputs mismatch"
    assert not step2_res['error_info'], f"{step2_name} should have no error info"

    # Step 3: Run Range Test (Fail)
    step3_name = "Run Range Test (Fail)"
    assert step3_name in results_by_step_name
    step3_res = results_by_step_name[step3_name]
    assert step3_res['result'] == str(ResultType.FAIL), f"{step3_name} result mismatch"
    assert step3_res['inputs'] == {"value": 25, "min": 10, "max": 20}, f"{step3_name} inputs mismatch"
    assert step3_res['outputs'] == {"compare": False}, f"{step3_name} outputs mismatch"
    assert not step3_res['error_info'], f"{step3_name} should have no error info"

    # Step 4: Generate Error
    step4_name = "Generate Error"
    assert step4_name in results_by_step_name
    step4_res = results_by_step_name[step4_name]
    # The result for an error might be None or explicitly 'ERROR' depending on implementation
    # Checking for the presence of error_info is more robust.
    assert step4_res['result'] == str(ResultType.ERROR), f"{step4_name} result should be ERROR"
    assert step4_res['inputs'] == {}, f"{step4_name} inputs mismatch"
    # Outputs might be None or empty dict when error occurs before output generation
    assert step4_res['outputs'] == None or step4_res['outputs'] == {}, f"{step4_name} outputs mismatch"
    assert step4_res['error_info'] is not None and step4_res['error_info'] != "", f"{step4_name} should have error info"
    assert "ValueError: Something went wrong deliberately" in step4_res['error_info'], f"{step4_name} error message mismatch"

    # Cleanup is handled automatically by pytest's tmp_path fixture



@pytest.fixture
def dummy_step():
    step = MagicMock(spec=Step)
    step.name = "MockStep"
    step.id = uuid.uuid4()
    step.description = "Mock step description"
    return step


@pytest.fixture
def dummy_step():
    return MagicMock(name="DummyStep")

@pytest.fixture
def dummy_result(dummy_step):
    result = StepResult(step=dummy_step)
    result.result = ResultType.PASS
    result.inputs = {"foo": "bar"}
    result.outputs = {"baz": "qux"}
    result.error_info = None
    result.uuid = uuid.uuid4()
    result.recipe_name = "Test Recipe"
    result.recipe_file_name = "recipe.json"
    result.serial_number = "SN123456"
    result.sequence_name = "MainSequence"
    result.pypts_version = "1.2.3"
    return result

def test_result_to_dict_valid(dummy_result):
    result_dict = _result_to_dict(dummy_result)
    assert result_dict["result"] == "PASS"
    assert result_dict["inputs"] == {"foo": "bar"}
    assert result_dict["outputs"] == {"baz": "qux"}

