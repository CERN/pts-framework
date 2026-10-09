"""
Unit tests for the SSH driver (src/pypts/hal/drivers/ssh.py), in-process, with
paramiko's SSHClient replaced by a mock - no host is needed. Skipped where
paramiko is not installed (pip install pts-framework[ssh]).
"""

from unittest.mock import MagicMock

import pytest

paramiko = pytest.importorskip("paramiko")

from pypts.hal import DriverError  # noqa: E402 - after the importorskip on purpose
from pypts.hal.base_driver import operations_of  # noqa: E402 - after the importorskip on purpose
from pypts.hal.drivers import ssh as ssh_module  # noqa: E402 - after the importorskip on purpose
from pypts.hal.drivers.ssh import SshDriver  # noqa: E402 - after the importorskip on purpose


@pytest.fixture
def client(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(ssh_module.paramiko, "SSHClient", lambda: mock)
    return mock


def connected(client):
    driver = SshDriver()
    driver.connect({"host": "bench-pc", "username": "tester"})
    return driver


def test_the_ssh_driver_is_an_ssh():
    assert SshDriver.FAMILY == "SSH"
    assert operations_of(SshDriver) == ["execute", "get_file", "put_file"]


def test_connect_passes_the_settings_and_refuses_unknown_hosts(client):
    SshDriver().connect(
        {"host": "bench-pc", "username": "tester", "port": "2222", "password": "pw"}
    )
    client.load_system_host_keys.assert_called_once_with()
    policy = client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.RejectPolicy)
    client.connect.assert_called_once_with(
        hostname="bench-pc",
        port=2222,
        username="tester",
        password="pw",
        key_filename=None,
        timeout=10.0,
    )


def test_accept_unknown_host_opts_out_per_device(client):
    SshDriver().connect({"host": "h", "username": "u", "accept_unknown_host": "yes"})
    policy = client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.AutoAddPolicy)


def test_a_known_hosts_file_is_read_too(client):
    SshDriver().connect({"host": "h", "username": "u", "known_hosts": "C:/keys/known_hosts"})
    client.load_host_keys.assert_called_once_with("C:/keys/known_hosts")


@pytest.mark.parametrize(
    ("config", "words"),
    [
        ({"username": "u"}, "needs 'host' and 'username'"),
        ({"host": "h"}, "needs 'host' and 'username'"),
        ({"host": "h", "username": "u", "port": "ssh"}, "port must be a whole number"),
        ({"host": "h", "username": "u", "connect_timeout_s": "soon"}, "connect_timeout_s"),
    ],
)
def test_a_bad_config_is_a_driver_error(client, config, words):
    with pytest.raises(DriverError, match=words):
        SshDriver().connect(config)
    client.connect.assert_not_called()


def test_a_failed_connection_is_a_driver_error_and_closes_the_client(client):
    client.connect.side_effect = OSError("No route to host")
    with pytest.raises(DriverError, match=r"tester@bench-pc:22 failed: No route to host"):
        connected(client)
    client.close.assert_called_once_with()


def test_execute_returns_output_and_exit_code(client):
    stdout = MagicMock()
    stdout.read.return_value = "Linux bench 6.1 µs\n".encode()
    stdout.channel.recv_exit_status.return_value = 0
    stderr = MagicMock()
    stderr.read.return_value = b""
    client.exec_command.return_value = (MagicMock(), stdout, stderr)

    result = connected(client).execute("uname -a", timeout_s=5.0)

    client.exec_command.assert_called_once_with("uname -a", timeout=5.0)
    assert result == {"stdout": "Linux bench 6.1 µs\n", "stderr": "", "exit_code": 0}


def test_execute_before_connect_is_a_driver_error():
    with pytest.raises(DriverError, match="not connected"):
        SshDriver().execute("ls")


def test_put_and_get_file_use_sftp_and_close_it(client):
    sftp = client.open_sftp.return_value
    driver = connected(client)
    driver.put_file("local.bin", "/tmp/remote.bin")
    driver.get_file("/tmp/log.txt", "log.txt")
    sftp.put.assert_called_once_with("local.bin", "/tmp/remote.bin")
    sftp.get.assert_called_once_with("/tmp/log.txt", "log.txt")
    assert sftp.close.call_count == 2


def test_teardown_closes_once_and_is_safe_twice(client):
    driver = connected(client)
    driver.teardown()
    driver.teardown()
    client.close.assert_called_once_with()
