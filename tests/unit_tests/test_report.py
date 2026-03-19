# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for pypts.report — covers report __main__ generation, _result_to_dict,
_flatten_single_result, _serialize_step, Report class, and report_listener."""

import csv
import json
import uuid
import subprocess
import sys
import threading
import pytest
from pathlib import Path
from queue import SimpleQueue
from datetime import datetime
from unittest.mock import MagicMock

from pypts.report import (
    Report,
    _result_to_dict,
    _flatten_single_result,
    _serialize_step,
    report_listener,
    STOP_LISTENER,
)
from pypts.recipe import Step, StepResult, ResultType

# Define the project root relative to this test file
PROJECT_ROOT = Path(__file__).parent.parent.parent

timestamp = datetime.now().strftime('%Y-%m-%d_%Hh%M')


# ============================================================
# Helpers
# ============================================================

def _make_step_result(step_name="TestStep", result_type=ResultType.PASS,
                      inputs=None, outputs=None, error_info=""):
    """Create a StepResult with common metadata pre-filled."""
    step = Step(step_name=step_name, id=uuid.uuid4())
    sr = StepResult(step=step)
    sr.recipe_name = "TestRecipe"
    sr.recipe_file_name = "recipe.yaml"
    sr.serial_number = "SN001"
    sr.sequence_name = "Main"
    sr.pypts_version = "1.0.0"
    sr.set_result(result_type, inputs=inputs or {}, outputs=outputs or {})
    if error_info:
        sr.error_info = error_info
    return sr


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def dummy_result():
    """Create a dummy StepResult with all metadata fields populated."""
    dummy_step = MagicMock(name="DummyStep")
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


# ============================================================
# report.py __main__ block tests
# ============================================================

class TestMainReportGeneration:
    def test_creates_report_file(self, tmp_path):
        """Verify that running report.py as __main__ creates a non-empty CSV report file."""
        report_py_path = PROJECT_ROOT / "src" / "pypts" / "report.py"
        output_dir = tmp_path / "temp_report_output"
        expected_report_path = output_dir / f"report_{timestamp}.csv"

        assert report_py_path.exists(), f"Script not found at {report_py_path}"

        command = [
            sys.executable, str(report_py_path),
            "-o", str(output_dir),
            "-t", str(timestamp)
        ]

        result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)

        assert result.returncode == 0, f"Script execution failed with return code {result.returncode}"
        assert expected_report_path.exists(), f"Expected report file not found at {expected_report_path}"
        assert expected_report_path.is_file()
        assert expected_report_path.stat().st_size > 0, "Report file is empty"

    def test_report_content(self, tmp_path):
        """Verify the CSV content matches the simulated data in report.py's __main__ block."""
        from datetime import timedelta

        report_py_path = PROJECT_ROOT / "src" / "pypts" / "report.py"
        output_dir = tmp_path / "temp_report_output"

        assert report_py_path.exists()
        command = [sys.executable, str(report_py_path), "-o", str(output_dir)]
        result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        assert result.returncode == 0, "Script execution failed"

        # Find the report file (may be current or next minute due to subprocess timing)
        ts_current = timestamp
        ts_next = (datetime.now() + timedelta(minutes=1)).strftime('%Y-%m-%d_%Hh%M')
        report_path = output_dir / f"report_{ts_current}.csv"
        if not report_path.exists():
            report_path = output_dir / f"report_{ts_next}.csv"

        assert report_path.exists(), "Report file was not created"
        assert report_path.stat().st_size > 0, "Report file is empty"

        # Read and verify CSV content
        results_by_step_name = {}
        with open(report_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                step_name = row.get('step_name')
                assert step_name, f"Row found without a step_name: {row}"
                try:
                    row['inputs'] = json.loads(row['inputs']) if row.get('inputs') else None
                except json.JSONDecodeError:
                    pytest.fail(f"Failed to parse inputs JSON for step '{step_name}': {row.get('inputs')}")
                try:
                    row['outputs'] = json.loads(row['outputs']) if row.get('outputs') else None
                except json.JSONDecodeError:
                    pytest.fail(f"Failed to parse outputs JSON for step '{step_name}': {row.get('outputs')}")
                results_by_step_name[step_name] = row

        assert len(results_by_step_name) == 4, f"Expected 4 rows in CSV, found {len(results_by_step_name)}"

        # Step 1: Run Other Test
        step1 = results_by_step_name["Run Other Test"]
        assert step1['result'] == str(ResultType.PASS)
        assert step1['inputs'] == {"arg1": 10}
        assert step1['outputs'] == {"some_return": True, "value": "abc"}
        assert not step1['error_info']

        # Step 2: Run Simple Output Test
        step2 = results_by_step_name["Run Simple Output Test"]
        assert step2['result'] == str(ResultType.PASS)
        assert step2['inputs'] == {"value": "abc"}
        assert step2['outputs'] == {"my_output": "calculated_abc"}
        assert not step2['error_info']

        # Step 3: Run Range Test (Fail)
        step3 = results_by_step_name["Run Range Test (Fail)"]
        assert step3['result'] == str(ResultType.FAIL)
        assert step3['inputs'] == {"value": 25, "min": 10, "max": 20}
        assert step3['outputs'] == {"compare": False}
        assert not step3['error_info']

        # Step 4: Generate Error
        step4 = results_by_step_name["Generate Error"]
        assert step4['result'] == str(ResultType.ERROR)
        assert step4['inputs'] == {}
        assert step4['outputs'] is None or step4['outputs'] == {}
        assert step4['error_info'] and "ValueError: Something went wrong deliberately" in step4['error_info']


# ============================================================
# _serialize_step
# ============================================================

class TestSerializeStep:
    def test_valid_step(self):
        """Verify that a Step is serialized to a dict with name, id, description, and type."""
        step = Step(step_name="S", id="abc", description="desc")
        result = _serialize_step(step)
        assert result["name"] == "S"
        assert result["id"] == "abc"
        assert result["description"] == "desc"
        assert result["type"] == "Step"

    def test_none_step(self):
        """Verify that None input returns None."""
        assert _serialize_step(None) is None


# ============================================================
# _result_to_dict
# ============================================================

class TestResultToDict:
    def test_valid_result(self, dummy_result):
        """Verify that a valid StepResult is converted to a dict with expected keys."""
        result_dict = _result_to_dict(dummy_result)
        assert result_dict["result"] == "PASS"
        assert result_dict["inputs"] == {"foo": "bar"}
        assert result_dict["outputs"] == {"baz": "qux"}

    def test_valid_result_with_helper(self):
        """Verify _result_to_dict with a helper-constructed StepResult."""
        sr = _make_step_result(inputs={"a": 1}, outputs={"b": 2})
        d = _result_to_dict(sr)
        assert d["result"] == "PASS"
        assert d["inputs"] == {"a": 1}
        assert d["outputs"] == {"b": 2}
        assert d["recipe_name"] == "TestRecipe"
        assert d["serial_number"] == "SN001"
        assert d["pypts_version"] == "1.0.0"

    def test_non_step_result_returns_none(self):
        """Verify that passing a non-StepResult object returns None."""
        assert _result_to_dict("not a StepResult") is None

    def test_error_result(self):
        """Verify that an ERROR result includes error_info."""
        sr = _make_step_result(result_type=ResultType.ERROR, error_info="boom")
        d = _result_to_dict(sr)
        assert d["result"] == "ERROR"
        assert d["error_info"] == "boom"

    def test_unserializable_inputs(self):
        """Verify that non-JSON-serializable inputs are handled gracefully."""
        sr = _make_step_result()
        sr.inputs = {"obj": object()}
        d = _result_to_dict(sr)
        assert "inputs" in d


# ============================================================
# _flatten_single_result
# ============================================================

class TestFlattenSingleResult:
    def test_flattens_correctly(self):
        """Verify that a result dict is flattened with step_name, step_id, and JSON-encoded fields."""
        result_dict = {
            "step": {"name": "Step1", "id": "123", "type": "PythonModuleStep"},
            "result": "PASS",
            "inputs": {"x": 1},
            "outputs": {"y": 2},
            "error_info": "",
            "recipe_name": "R",
            "recipe_file_name": "r.yaml",
            "serial_number": "SN",
            "sequence_name": "Main",
            "pypts_version": "1.0",
        }
        flat = _flatten_single_result(result_dict)
        assert flat["step_name"] == "Step1"
        assert flat["step_id"] == "123"
        assert flat["result"] == "PASS"
        assert json.loads(flat["inputs"]) == {"x": 1}
        assert json.loads(flat["outputs"]) == {"y": 2}

    def test_none_returns_none(self):
        """Verify that None input returns None."""
        assert _flatten_single_result(None) is None

    def test_missing_step(self):
        """Verify that a missing step serialization produces 'N/A' for step_name."""
        result_dict = {"step": None, "result": "DONE", "inputs": {}, "outputs": {}, "error_info": ""}
        flat = _flatten_single_result(result_dict)
        assert flat["step_name"] == "N/A"


# ============================================================
# Report class
# ============================================================

class TestReport:
    def test_creates_csv_file(self, tmp_path):
        """Verify that Report.finish_reports() creates the CSV file."""
        ts = "2025-01-01_12h00"
        report = Report(output_dir=tmp_path, timestamp=ts)
        report.finish_reports()
        assert (tmp_path / f"report_{ts}.csv").exists(), "Report CSV file was not created"

    def test_writes_header(self, tmp_path):
        """Verify that the CSV header contains expected column names."""
        ts = "2025-01-01_12h00"
        report = Report(output_dir=tmp_path, timestamp=ts)
        report.finish_reports()
        with open(tmp_path / f"report_{ts}.csv", 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
        assert "step_name" in header
        assert "result" in header
        assert "serial_number" in header

    def test_add_step_result(self, tmp_path):
        """Verify that a single step result is written to the CSV."""
        ts = "2025-01-01_12h00"
        report = Report(output_dir=tmp_path, timestamp=ts)
        sr = _make_step_result("MyStep", ResultType.PASS, {"a": 1}, {"b": 2})
        report.add_step_result(sr)
        report.finish_reports()

        with open(tmp_path / f"report_{ts}.csv", 'r') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["step_name"] == "MyStep"
        assert rows[0]["result"] == "PASS"
        assert json.loads(rows[0]["inputs"]) == {"a": 1}

    def test_multiple_results(self, tmp_path):
        """Verify that multiple step results are all written to the CSV."""
        ts = "2025-01-01_12h00"
        report = Report(output_dir=tmp_path, timestamp=ts)
        for i in range(5):
            sr = _make_step_result(f"Step{i}", ResultType.DONE)
            report.add_step_result(sr)
        report.finish_reports()

        with open(tmp_path / f"report_{ts}.csv", 'r') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 5

    def test_non_step_result_ignored(self, tmp_path):
        """Verify that non-StepResult objects are silently ignored."""
        ts = "2025-01-01_12h00"
        report = Report(output_dir=tmp_path, timestamp=ts)
        report.add_step_result("not a StepResult")
        report.finish_reports()

        with open(tmp_path / f"report_{ts}.csv", 'r') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 0

    def test_append_mode(self, tmp_path):
        """Verify that append mode adds rows to an existing CSV instead of overwriting."""
        ts = "2025-01-01_12h00"
        r1 = Report(output_dir=tmp_path, timestamp=ts, overwrite=True)
        r1.add_step_result(_make_step_result("S1"))
        r1.finish_reports()

        r2 = Report(output_dir=tmp_path, timestamp=ts, overwrite=False)
        r2.add_step_result(_make_step_result("S2"))
        r2.finish_reports()

        with open(tmp_path / f"report_{ts}.csv", 'r') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2

    def test_creates_output_dir_if_missing(self, tmp_path):
        """Verify that nested output directories are created automatically."""
        nested = tmp_path / "a" / "b" / "c"
        ts = "2025-01-01_12h00"
        report = Report(output_dir=nested, timestamp=ts)
        report.finish_reports()
        assert nested.exists()


# ============================================================
# report_listener
# ============================================================

class TestReportListener:
    def test_processes_results_until_stop(self, tmp_path):
        """Verify that report_listener processes queued results and stops on STOP_LISTENER."""
        rq = SimpleQueue()
        for i in range(3):
            rq.put(_make_step_result(f"Step{i}"))
        rq.put(STOP_LISTENER)

        t = threading.Thread(
            target=report_listener,
            args=(rq, str(tmp_path), True),
            daemon=True,
        )
        t.start()
        t.join(timeout=10)
        assert not t.is_alive(), "report_listener did not exit"

        csv_files = list(tmp_path.glob("report_*.csv"))
        assert len(csv_files) == 1
        with open(csv_files[0], 'r') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 3

    def test_ignores_unexpected_items(self, tmp_path):
        """Verify that non-StepResult items in the queue are ignored."""
        rq = SimpleQueue()
        rq.put("not a StepResult")
        rq.put(42)
        rq.put(_make_step_result("Valid"))
        rq.put(STOP_LISTENER)

        t = threading.Thread(
            target=report_listener,
            args=(rq, str(tmp_path), True),
            daemon=True,
        )
        t.start()
        t.join(timeout=10)
        assert not t.is_alive()

        csv_files = list(tmp_path.glob("report_*.csv"))
        assert len(csv_files) == 1
        with open(csv_files[0], 'r') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1  # Only the valid result
