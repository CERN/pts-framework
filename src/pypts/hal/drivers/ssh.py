"""
SSH - a remote shell, over paramiko. The reference driver: a new driver
follows its shape.

Keys of its [hardware.<name>] section (all text):

    host                 required
    username             required
    port                 default 22
    password             optional - config.ini is plain text, prefer key_filename
    key_filename         optional, path to a private key
    known_hosts          optional, a known_hosts file read beside the system one
    accept_unknown_host  default false: a host whose key is not known is refused
    connect_timeout_s    default 10

Needs paramiko: pip install pts-framework[ssh].
"""

from typing import Any

try:
    import paramiko
except ImportError as exc:
    raise ImportError("The SSH driver needs paramiko: pip install pts-framework[ssh]") from exc

from pypts.hal.base_driver import DriverError
from pypts.hal.families import SSH

#: How a yes is written in config.ini - the configuration's own vocabulary.
TRUE_TEXT = ("1", "yes", "true", "on")

DEFAULT_PORT = 22
DEFAULT_CONNECT_TIMEOUT_S = 10.0


class SshDriver(SSH):
    """One SSH session to one host."""

    def __init__(self) -> None:
        self._client: Any = None

    def connect(self, config: dict[str, str]) -> None:
        host = config.get("host", "").strip()
        username = config.get("username", "").strip()
        if not host or not username:
            raise DriverError("SSH needs 'host' and 'username' in its [hardware.<name>] section.")
        port_text = config.get("port", "").strip()
        if port_text:
            if not port_text.isdigit():
                raise DriverError(f"SSH port must be a whole number, not '{port_text}'.")
            port = int(port_text)
        else:
            port = DEFAULT_PORT
        timeout_text = config.get("connect_timeout_s", "").strip()
        if timeout_text:
            try:
                timeout_s = float(timeout_text)
            except ValueError:
                raise DriverError(
                    f"SSH connect_timeout_s must be a number of seconds, not '{timeout_text}'."
                ) from None
        else:
            timeout_s = DEFAULT_CONNECT_TIMEOUT_S
        password = config.get("password") or None
        key_filename = config.get("key_filename") or None
        known_hosts = config.get("known_hosts", "").strip()
        accept_unknown = config.get("accept_unknown_host", "").strip().lower() in TRUE_TEXT

        client = paramiko.SSHClient()
        try:
            client.load_system_host_keys()
            if known_hosts:
                client.load_host_keys(known_hosts)
            if accept_unknown:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                key_filename=key_filename,
                timeout=timeout_s,
            )
        except Exception as exc:  # paramiko raises many types; one DriverError for the caller
            client.close()
            raise DriverError(
                f"SSH connection to {username}@{host}:{port} failed: {exc}"
            ) from exc
        self._client = client

    def execute(self, command: str, timeout_s: float | None = None) -> dict[str, Any]:
        """Run one command and wait for it. Output is read before the exit status, so a
        command that prints a lot cannot fill the channel and hang."""
        client = self._connected()
        _, stdout, stderr = client.exec_command(command, timeout=timeout_s)
        out_text = stdout.read().decode("utf-8", errors="replace")
        err_text = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        return {"stdout": out_text, "stderr": err_text, "exit_code": exit_code}

    def put_file(self, local_path: str, remote_path: str) -> None:
        sftp = self._connected().open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()

    def get_file(self, remote_path: str, local_path: str) -> None:
        sftp = self._connected().open_sftp()
        try:
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()

    def teardown(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _connected(self) -> Any:
        if self._client is None:
            raise DriverError("SSH is not connected.")
        return self._client
