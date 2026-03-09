# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for SSHUploadStep, exec_command (pypts.utils), and the SSH
SHA-256 helper functions (_sha256_file, _remote_file_exists, _remote_sha256).

No real SSH connection is required — paramiko internals are mocked.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Import recipe first to resolve the circular steps↔recipe import dependency.
import pypts.recipe  # noqa: F401
from pypts.steps import SSHUploadStep, _sha256_file, _remote_file_exists, _remote_sha256
from pypts.utils import exec_command


# ---------------------------------------------------------------------------
# Helpers — fake paramiko channel
# ---------------------------------------------------------------------------

class _FakeChannel:
    """Minimal paramiko.Channel substitute for exec_command tests."""

    def __init__(self, stdout_bytes=b"", stderr_bytes=b"", exit_code=0, hang=False):
        self._stdout = stdout_bytes
        self._stderr = stderr_bytes
        self._exit_code = exit_code
        self._hang = hang

    def settimeout(self, t):
        pass

    def exec_command(self, cmd):
        pass

    def makefile(self, mode):
        if self._hang:
            r, w = os.pipe()
            return os.fdopen(r, "rb")
        return io.BytesIO(self._stdout)

    def makefile_stderr(self, mode):
        if self._hang:
            r, w = os.pipe()
            return os.fdopen(r, "rb")
        return io.BytesIO(self._stderr)

    def recv_exit_status(self):
        return self._exit_code

    def close(self):
        pass


def _make_client(channel: _FakeChannel) -> MagicMock:
    client = MagicMock()
    client.get_transport.return_value.open_session.return_value = channel
    return client


# ---------------------------------------------------------------------------
# Minimal MockRuntime for SSHUploadStep._step
# ---------------------------------------------------------------------------

class MockRuntime:
    def __init__(self, ssh_client=None):
        self._globals = {"ssh_client": ssh_client}
        self.continue_on_error = False

    def get_global(self, name):
        return self._globals.get(name)

    def set_global(self, name, value):
        self._globals[name] = value

    def get_local(self, name):
        return None

    def set_local(self, name, value):
        pass

    def send_event(self, *a, **kw):
        pass


# ---------------------------------------------------------------------------
# exec_command tests
# ---------------------------------------------------------------------------

class TestExecCommand:
    def test_happy_path_returns_stdout_stderr_rc(self):
        channel = _FakeChannel(stdout_bytes=b"hello\n", stderr_bytes=b"warn\n", exit_code=0)
        client = _make_client(channel)
        stdout, stderr, rc = exec_command(client, "echo hello", timeout=5)
        assert stdout == "hello\n"
        assert stderr == "warn\n"
        assert rc == 0

    def test_nonzero_exit_code_returned(self):
        channel = _FakeChannel(stdout_bytes=b"", stderr_bytes=b"bad\n", exit_code=1)
        client = _make_client(channel)
        _, stderr, rc = exec_command(client, "false", timeout=5)
        assert rc == 1
        assert "bad" in stderr

    def test_large_output_no_deadlock(self):
        big = b"x" * 100_000
        channel = _FakeChannel(stdout_bytes=big, stderr_bytes=big, exit_code=0)
        client = _make_client(channel)
        stdout, stderr, rc = exec_command(client, "gen", timeout=10)
        assert len(stdout) == 100_000
        assert len(stderr) == 100_000

    def test_timeout_raises(self):
        channel = _FakeChannel(hang=True)
        client = _make_client(channel)
        with pytest.raises(TimeoutError):
            exec_command(client, "sleep 9999", timeout=1)


# ---------------------------------------------------------------------------
# _sha256_file tests
# ---------------------------------------------------------------------------

class TestSha256File:
    def test_returns_64_char_hex(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\xde\xad\xbe\xef" * 64)
        digest = _sha256_file(f)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_matches_hashlib(self, tmp_path):
        content = b"CERN DIOT test" * 500
        f = tmp_path / "content.bin"
        f.write_bytes(content)
        assert _sha256_file(f) == hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# _remote_file_exists tests
# ---------------------------------------------------------------------------

class TestRemoteFileExists:
    def test_false_when_missing(self):
        sftp = MagicMock()
        sftp.stat.side_effect = FileNotFoundError
        assert _remote_file_exists(sftp, "/tmp/missing") is False

    def test_true_when_present(self):
        sftp = MagicMock()
        sftp.stat.return_value = MagicMock()
        assert _remote_file_exists(sftp, "/tmp/present") is True


# ---------------------------------------------------------------------------
# _remote_sha256 tests
# ---------------------------------------------------------------------------

class TestRemoteSha256:
    def test_returns_digest_on_success(self):
        digest = "a" * 64
        channel = _FakeChannel(stdout_bytes=f"{digest}  /tmp/file\n".encode(), exit_code=0)
        client = _make_client(channel)
        assert _remote_sha256(client, "/tmp/file") == digest

    def test_returns_empty_string_on_failure(self):
        channel = _FakeChannel(stdout_bytes=b"", exit_code=1)
        client = _make_client(channel)
        assert _remote_sha256(client, "/tmp/missing") == ""


# ---------------------------------------------------------------------------
# SSHUploadStep unit tests
# ---------------------------------------------------------------------------

class TestSSHUploadStepInit:
    def test_permissions_from_octal_string(self):
        step = SSHUploadStep(step_name="s", files=[], permissions="0o755")
        assert step.permissions == 0o755

    def test_permissions_from_integer(self):
        step = SSHUploadStep(step_name="s", files=[], permissions=0o644)
        assert step.permissions == 0o644

    def test_defaults(self):
        step = SSHUploadStep(step_name="s", files=[])
        assert step.permissions == 0o755
        assert step.skip_if_sha256_match is True
        assert step.local_package is None
        assert step.continue_on_error is False


class TestSSHUploadStepNoClient:
    def test_raises_when_ssh_client_is_none(self, tmp_path):
        step = SSHUploadStep(
            step_name="upload",
            files=[{"local": str(tmp_path / "x"), "remote": "/tmp/x"}],
        )
        runtime = MockRuntime(ssh_client=None)
        with pytest.raises(ValueError, match="ssh_client global is None"):
            step._step(runtime, {}, uuid.uuid4())


class TestSSHUploadStepDeploy:
    """Upload behaviour with mocked SFTP and SSH client."""

    def _make_step_and_runtime(self, tmp_path, skip_if_sha256_match=True):
        local_file = tmp_path / "tool"
        local_file.write_bytes(b"\x00" * 1024)
        digest = hashlib.sha256(b"\x00" * 1024).hexdigest()

        step = SSHUploadStep(
            step_name="upload",
            files=[{"local": str(local_file), "remote": "/tmp/tool"}],
            skip_if_sha256_match=skip_if_sha256_match,
        )

        sftp = MagicMock()
        client = MagicMock()
        client.open_sftp.return_value = sftp

        return step, sftp, client, digest

    def test_uploads_when_remote_missing(self, tmp_path):
        step, sftp, client, _ = self._make_step_and_runtime(tmp_path)
        sftp.stat.side_effect = FileNotFoundError  # remote file absent

        runtime = MockRuntime(ssh_client=client)
        result = step._step(runtime, {}, uuid.uuid4())

        assert result["passed"] is True
        assert "tool" in result["deployed"]
        assert result["skipped"] == []
        sftp.put.assert_called_once()
        sftp.chmod.assert_called_once_with("/tmp/tool", 0o755)

    def test_skips_when_sha256_matches(self, tmp_path):
        step, sftp, client, digest = self._make_step_and_runtime(tmp_path)
        sftp.stat.return_value = MagicMock()  # remote exists

        # Patch _remote_sha256 to return matching digest
        with patch("pypts.steps._remote_sha256", return_value=digest):
            runtime = MockRuntime(ssh_client=client)
            result = step._step(runtime, {}, uuid.uuid4())

        assert result["passed"] is True
        assert result["deployed"] == []
        assert "tool" in result["skipped"]
        sftp.put.assert_not_called()

    def test_reuploads_when_sha256_differs(self, tmp_path):
        step, sftp, client, _ = self._make_step_and_runtime(tmp_path)
        sftp.stat.return_value = MagicMock()  # remote exists

        with patch("pypts.steps._remote_sha256", return_value="0" * 64):
            runtime = MockRuntime(ssh_client=client)
            result = step._step(runtime, {}, uuid.uuid4())

        assert "tool" in result["deployed"]
        assert result["skipped"] == []
        sftp.put.assert_called_once()

    def test_skip_disabled_always_uploads(self, tmp_path):
        step, sftp, client, digest = self._make_step_and_runtime(
            tmp_path, skip_if_sha256_match=False
        )
        sftp.stat.return_value = MagicMock()

        runtime = MockRuntime(ssh_client=client)
        result = step._step(runtime, {}, uuid.uuid4())

        assert "tool" in result["deployed"]
        sftp.put.assert_called_once()

    def test_raises_on_missing_local_file(self, tmp_path):
        step = SSHUploadStep(
            step_name="upload",
            files=[{"local": str(tmp_path / "nonexistent"), "remote": "/tmp/x"}],
        )
        client = MagicMock()
        client.open_sftp.return_value = MagicMock()
        runtime = MockRuntime(ssh_client=client)

        with pytest.raises(FileNotFoundError):
            step._step(runtime, {}, uuid.uuid4())

    def test_continue_on_error_returns_failed_dict(self, tmp_path):
        step = SSHUploadStep(
            step_name="upload",
            files=[{"local": str(tmp_path / "nonexistent"), "remote": "/tmp/x"}],
            continue_on_error=True,
        )
        client = MagicMock()
        client.open_sftp.return_value = MagicMock()
        runtime = MockRuntime(ssh_client=client)

        result = step._step(runtime, {}, uuid.uuid4())
        assert result["passed"] is False
        assert "error" in result
