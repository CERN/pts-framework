# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for pypts.utils — covers get_project_root, get_step_result_colors,
path_to_importable_module, AbortTestException, and exec_command."""

import io
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from pypts.utils import (
    get_project_root,
    get_step_result_colors,
    path_to_importable_module,
    AbortTestException,
    exec_command,
)
from pypts.recipe import ResultType


# ============================================================
# get_project_root
# ============================================================

class TestGetProjectRoot:
    def test_returns_expected_root(self):
        """Verify that get_project_root returns the directory two levels above this test file."""
        expected_root = Path(__file__).resolve().parents[2]
        assert get_project_root().resolve() == expected_root

    def test_returns_path_object(self):
        """Verify that the return type is a Path."""
        assert isinstance(get_project_root(), Path)

    def test_pyproject_toml_exists_at_root(self):
        """Verify that pyproject.toml exists in the detected project root."""
        root = get_project_root()
        assert (root / "pyproject.toml").exists()


# ============================================================
# get_step_result_colors
# ============================================================

class TestGetStepResultColors:
    def test_pass_color(self):
        """Verify PASS returns green background and dark green text."""
        bg, text = get_step_result_colors(ResultType.PASS, ResultType)
        assert bg == "#C8E6C9"
        assert text == "#1B4F24"

    def test_fail_color(self):
        """Verify FAIL returns red background and dark red text."""
        bg, text = get_step_result_colors(ResultType.FAIL, ResultType)
        assert bg == "#F28B82"
        assert text == "#7B0000"

    def test_done_color(self):
        """Verify DONE returns a cyan-ish background."""
        bg, text = get_step_result_colors(ResultType.DONE, ResultType)
        assert bg == "#B2EBF2"

    def test_skip_color(self):
        """Verify SKIP returns a yellow background."""
        bg, text = get_step_result_colors(ResultType.SKIP, ResultType)
        assert bg == "#FFF9C4"

    def test_error_color(self):
        """Verify ERROR returns an orange background."""
        bg, text = get_step_result_colors(ResultType.ERROR, ResultType)
        assert bg == "#FFCC80"

    def test_stop_color(self):
        """Verify STOP returns a grey background."""
        bg, text = get_step_result_colors(ResultType.STOP, ResultType)
        assert bg == "#D3D3D3"

    def test_unknown_value_returns_default(self):
        """Verify that an unknown value returns white background and black text."""
        bg, text = get_step_result_colors("nonexistent", ResultType)
        assert bg == "#FFFFFF"
        assert text == "#000000"

    def test_all_result_types_have_colors(self):
        """Verify every ResultType member has a non-default colour mapping."""
        for member in ResultType:
            bg, text = get_step_result_colors(member, ResultType)
            assert bg != "#FFFFFF", f"{member} has no color mapping"


# ============================================================
# path_to_importable_module
# ============================================================

class TestPathToImportableModule:
    def test_basic_conversion(self):
        """Verify that a site-packages path converts to a dotted module name."""
        path = Path("/some/venv/lib/site-packages/pypts/example_tests.py")
        result = path_to_importable_module(path)
        assert result == "pypts.example_tests"

    def test_nested_module(self):
        """Verify that deeply nested paths convert correctly."""
        path = Path("/some/venv/lib/site-packages/pypts/instruments/pendulum/cnt91.py")
        result = path_to_importable_module(path)
        assert result == "pypts.instruments.pendulum.cnt91"

    def test_not_in_site_packages_raises(self):
        """Verify that paths outside site-packages raise ValueError."""
        path = Path("/home/user/projects/mymod.py")
        with pytest.raises(ValueError, match="not inside site-packages"):
            path_to_importable_module(path)


# ============================================================
# AbortTestException
# ============================================================

class TestAbortTestException:
    def test_is_exception(self):
        """Verify that AbortTestException is a subclass of Exception."""
        assert issubclass(AbortTestException, Exception)

    def test_can_raise_and_catch(self):
        """Verify that AbortTestException can be raised and caught."""
        with pytest.raises(AbortTestException):
            raise AbortTestException("test aborted")


# ============================================================
# exec_command
# ============================================================

class TestExecCommand:
    def _make_mock_client(self, stdout_data=b"", stderr_data=b"", exit_code=0, hang=False):
        """Create a mock SSH client with configurable stdout, stderr, exit code, and hang behaviour."""
        client = MagicMock()
        transport = MagicMock()
        channel = MagicMock()

        client.get_transport.return_value = transport
        transport.open_session.return_value = channel

        stdout_stream = io.BytesIO(stdout_data)
        stderr_stream = io.BytesIO(stderr_data)

        if hang:
            import time
            def blocking_read(*a, **kw):
                time.sleep(10)
                return b""
            hanging_stream = MagicMock()
            hanging_stream.read = blocking_read
            channel.makefile.return_value = hanging_stream
            channel.makefile_stderr.return_value = hanging_stream
        else:
            channel.makefile.side_effect = lambda *a, **kw: stdout_stream
            channel.makefile_stderr.side_effect = lambda *a, **kw: stderr_stream

        channel.recv_exit_status.return_value = exit_code
        return client

    def test_successful_command(self):
        """Verify that a successful command returns stdout and exit code 0."""
        client = self._make_mock_client(stdout_data=b"hello\n", exit_code=0)
        stdout, stderr, rc = exec_command(client, "echo hello")
        assert stdout.strip() == "hello"
        assert rc == 0

    def test_command_with_stderr(self):
        """Verify that stderr output and non-zero exit code are captured."""
        client = self._make_mock_client(stderr_data=b"warning\n", exit_code=1)
        stdout, stderr, rc = exec_command(client, "bad_cmd")
        assert "warning" in stderr
        assert rc == 1

    def test_timeout_raises(self):
        """Verify that a hanging command raises TimeoutError when timeout is exceeded."""
        client = self._make_mock_client(hang=True)
        with pytest.raises(TimeoutError, match="timed out"):
            exec_command(client, "sleep 100", timeout=1)
