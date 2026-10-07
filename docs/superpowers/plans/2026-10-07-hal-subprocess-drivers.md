# HAL Subprocess Driver Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the HAL subprocess infrastructure and a concrete SSH driver as the first example, so every future driver follows the same pattern.

**Architecture:** Every driver is a plain Python class subclassing `Driver`. The framework spawns it as a subprocess (sidecar), communicates via newline-delimited JSON-RPC over a TCP socket on 127.0.0.1, and exposes it to step code via a `DriverProxy` that looks like a local object. The `Runtime` gets a new `get_driver` seam the Sequencer fills from a `HalManager`.

**Tech Stack:** Python 3.11, stdlib `socket`/`subprocess`/`json`/`threading`, `paramiko` (SSH driver only, optional extra)

## Global Constraints

- Python ≥ 3.11
- Line length 100 (`ruff`)
- `%-style` logging — never f-strings in log calls (`G004`)
- `match`/`case` closed with `unhandled()` wherever used
- No inline SPDX headers needed for `src/pypts/**/*.py` (covered by `reuse.toml`)
- `paramiko` must become `pts-framework[ssh]` optional extra — not a core dep
- Never call `init_logging()` from a thread entry point
- Never import `helper_applications/debug_monitor/` from anywhere
- Do NOT change `CONFIG_VERSION` (hardware sections are already returned as untyped text — no mandatory new keys added)
- Quality gate before done: `pytest tests`, `ruff check src tests`, `mypy`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/pypts/hardware_layer/driver.py` | `Driver` ABC + `DriverError` |
| Create | `src/pypts/hardware_layer/runner.py` | Generic sidecar runner (`__main__`) |
| Create | `src/pypts/hardware_layer/proxy.py` | `DriverProxy` — transparent IPC wrapper |
| Create | `src/pypts/hardware_layer/hal_manager.py` | `HalManager` — owns all proxies for one run |
| Create | `src/pypts/hardware_layer/drivers/__init__.py` | Empty package marker |
| Create | `src/pypts/hardware_layer/drivers/ssh.py` | `SshDriver` — first concrete driver |
| Create | `tests/unit_tests/test_hal.py` | All HAL tests |
| Modify | `src/pypts/hardware_layer/__init__.py` | Re-export public names |
| Modify | `src/pypts/step/runtime.py` | Add `get_driver` seam |
| Modify | `src/pypts/sequencer/sequencer.py` | Create `HalManager`, inject seam |
| Modify | `src/pypts/hardware_layer/hal.md` | Update — agreed shape is now implemented |
| Modify | `pyproject.toml` | Move `paramiko` to `[ssh]` optional extra |

---

## Protocol Reference (read before any task)

The runner picks a free TCP port and prints `PORT:<n>\n` to stdout. The proxy reads that line and connects. Every call is one JSON line request + one JSON line response.

**Request:**
```json
{"id": 1, "method": "execute", "args": ["ls -la"], "kwargs": {}}
```

**Success response:**
```json
{"id": 1, "result": {"stdout": "total 4\n...", "stderr": "", "exit_code": 0}}
```

**Error response:**
```json
{"id": 1, "error": {"type": "DriverError", "message": "host unreachable"}}
```

All driver exceptions are re-raised in the main process as `DriverError` — the original type is not reconstructed (it may not be importable in the main process).

---

## Task 1: `Driver` base class and `DriverError`

**Files:**
- Create: `src/pypts/hardware_layer/driver.py`
- Test: `tests/unit_tests/test_hal.py`

**Interfaces:**
- Produces: `Driver` (ABC with `connect`, `teardown`, `recover`), `DriverError`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit_tests/test_hal.py
import pytest
from pypts.hardware_layer.driver import Driver, DriverError


class _ConcreteDriver(Driver):
    def connect(self, config: dict) -> None:
        pass

    def teardown(self) -> None:
        pass


def test_driver_is_abstract():
    with pytest.raises(TypeError):
        Driver()  # type: ignore[abstract]


def test_concrete_driver_instantiates():
    d = _ConcreteDriver()
    assert isinstance(d, Driver)


def test_recover_default_calls_teardown_then_connect(monkeypatch):
    calls = []
    d = _ConcreteDriver()
    monkeypatch.setattr(d, "teardown", lambda: calls.append("teardown"))
    monkeypatch.setattr(d, "connect", lambda config: calls.append(("connect", config)))
    d.recover({"host": "h"})
    assert calls == ["teardown", ("connect", {"host": "h"})]


def test_driver_error_is_exception():
    err = DriverError("boom")
    assert str(err) == "boom"
    assert isinstance(err, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/unit_tests/test_hal.py -v
```
Expected: `ImportError` or `ModuleNotFoundError` — `driver.py` does not exist yet.

- [ ] **Step 3: Write the implementation**

```python
# src/pypts/hardware_layer/driver.py
from abc import ABC, abstractmethod


class DriverError(Exception):
    """Raised when a driver operation fails."""


class Driver(ABC):
    """
    Base class for all HAL drivers.

    A driver is a plain Python class — no framework imports, no IPC code.
    The sidecar runner wraps it; step code receives a DriverProxy that
    forwards calls here transparently.
    """

    @abstractmethod
    def connect(self, config: dict[str, str]) -> None:
        """Establish the connection described by config."""

    @abstractmethod
    def teardown(self) -> None:
        """Release the connection cleanly."""

    def recover(self, config: dict[str, str]) -> None:
        """Attempt recovery after a failure: teardown then reconnect."""
        self.teardown()
        self.connect(config)
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit_tests/test_hal.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pypts/hardware_layer/driver.py tests/unit_tests/test_hal.py
git commit -m "feat(hal): add Driver ABC and DriverError"
```

---

## Task 2: Sidecar runner

**Files:**
- Create: `src/pypts/hardware_layer/runner.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Consumes: `Driver` from Task 1
- Produces: executable module `python -m pypts.hardware_layer.runner --driver <dotted.ClassName>`
  - Prints `PORT:<n>\n` to stdout
  - Accepts newline-delimited JSON requests on TCP 127.0.0.1:<n>
  - Returns newline-delimited JSON responses

- [ ] **Step 1: Write the failing test**

Append to `tests/unit_tests/test_hal.py`:

```python
import json
import socket
import subprocess
import sys
import time


class _EchoDriver:
    """A driver that echoes its arguments — used only by the runner tests."""

    def connect(self, config: dict) -> None:
        self._config = config

    def teardown(self) -> None:
        pass

    def echo(self, message: str) -> str:
        return message

    def raises(self, message: str) -> None:
        raise RuntimeError(message)


def _start_runner(driver_class: str) -> tuple[subprocess.Popen, int]:
    """Spawn the runner and return (process, port)."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "pypts.hardware_layer.runner", "--driver", driver_class],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline()
    assert line.startswith("PORT:"), f"unexpected runner output: {line!r}"
    port = int(line.strip().split(":")[1])
    return proc, port


def _rpc(sock: socket.socket, method: str, args=None, kwargs=None) -> dict:
    request = json.dumps({"id": 1, "method": method, "args": args or [], "kwargs": kwargs or {}})
    sock.sendall((request + "\n").encode())
    response = b""
    while b"\n" not in response:
        chunk = sock.recv(4096)
        assert chunk, "connection closed"
        response += chunk
    return json.loads(response.split(b"\n")[0])


def test_runner_starts_and_accepts_connection(tmp_path):
    proc, port = _start_runner("tests.unit_tests.test_hal._EchoDriver")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            pass
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_runner_forwards_method_call(tmp_path):
    proc, port = _start_runner("tests.unit_tests.test_hal._EchoDriver")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            resp = _rpc(s, "echo", args=["hello"])
            assert resp == {"id": 1, "result": "hello"}
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_runner_serializes_exception(tmp_path):
    proc, port = _start_runner("tests.unit_tests.test_hal._EchoDriver")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            resp = _rpc(s, "raises", args=["boom"])
            assert resp["id"] == 1
            assert "error" in resp
            assert resp["error"]["message"] == "boom"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_runner_handles_unknown_method(tmp_path):
    proc, port = _start_runner("tests.unit_tests.test_hal._EchoDriver")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            resp = _rpc(s, "no_such_method")
            assert "error" in resp
    finally:
        proc.terminate()
        proc.wait(timeout=5)
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit_tests/test_hal.py::test_runner_starts_and_accepts_connection -v
```
Expected: FAIL — `runner.py` does not exist.

- [ ] **Step 3: Write the implementation**

```python
# src/pypts/hardware_layer/runner.py
"""
Generic sidecar runner.

Usage: python -m pypts.hardware_layer.runner --driver dotted.module.ClassName

Prints PORT:<n> to stdout, then listens for newline-delimited JSON-RPC on
127.0.0.1:<n>. Each connection is handled sequentially; clients send one
request and receive one response per call.
"""

from __future__ import annotations

import importlib
import json
import logging
import socket
import sys
import threading
from typing import Any


log = logging.getLogger(__name__)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _load_driver_class(dotted: str) -> type:
    module_path, _, class_name = dotted.rpartition(".")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls


def _handle_connection(conn: socket.socket, driver: Any) -> None:
    with conn:
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                response = _dispatch(driver, line)
                conn.sendall((json.dumps(response) + "\n").encode())


def _dispatch(driver: Any, raw: bytes) -> dict:
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"id": None, "error": {"type": "ProtocolError", "message": str(exc)}}

    req_id = request.get("id")
    method_name = request.get("method", "")
    args = request.get("args", [])
    kwargs = request.get("kwargs", {})

    method = getattr(driver, method_name, None)
    if method is None:
        return {"id": req_id, "error": {"type": "DriverError", "message": f"no method {method_name!r}"}}
    try:
        result = method(*args, **kwargs)
        return {"id": req_id, "result": result}
    except Exception as exc:
        return {"id": req_id, "error": {"type": type(exc).__name__, "message": str(exc)}}


def run(driver_class_path: str) -> None:
    cls = _load_driver_class(driver_class_path)
    driver = cls()

    port = _find_free_port()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(1)

    sys.stdout.write(f"PORT:{port}\n")
    sys.stdout.flush()

    while True:
        conn, _ = server.accept()
        _handle_connection(conn, driver)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True)
    args = parser.parse_args()
    run(args.driver)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit_tests/test_hal.py -k "runner" -v
```
Expected: all 4 runner tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pypts/hardware_layer/runner.py tests/unit_tests/test_hal.py
git commit -m "feat(hal): add generic sidecar runner"
```

---

## Task 3: `DriverProxy`

**Files:**
- Create: `src/pypts/hardware_layer/proxy.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Consumes: runner from Task 2
- Produces: `DriverProxy(driver_class_path, config, python_executable=sys.executable)`
  - `connect() -> None` — spawns sidecar, reads port, sends `connect` RPC
  - `teardown() -> None` — sends `teardown` RPC, terminates subprocess
  - `__getattr__(name) -> Callable` — forwards any other call as RPC
  - On RPC error: raises `DriverError`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit_tests/test_hal.py`:

```python
from pypts.hardware_layer.proxy import DriverProxy
from pypts.hardware_layer.driver import DriverError


_ECHO_DRIVER_PATH = "tests.unit_tests.test_hal._EchoDriver"


def test_proxy_connect_and_call():
    proxy = DriverProxy(_ECHO_DRIVER_PATH, config={})
    proxy.connect()
    result = proxy.echo("world")
    assert result == "world"
    proxy.teardown()


def test_proxy_raises_driver_error_on_exception():
    proxy = DriverProxy(_ECHO_DRIVER_PATH, config={})
    proxy.connect()
    with pytest.raises(DriverError):
        proxy.raises("boom")
    proxy.teardown()


def test_proxy_raises_driver_error_on_unknown_method():
    proxy = DriverProxy(_ECHO_DRIVER_PATH, config={})
    proxy.connect()
    with pytest.raises(DriverError):
        proxy.no_such_method()
    proxy.teardown()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit_tests/test_hal.py -k "proxy" -v
```
Expected: FAIL — `proxy.py` does not exist.

- [ ] **Step 3: Write the implementation**

```python
# src/pypts/hardware_layer/proxy.py
from __future__ import annotations

import json
import socket
import subprocess
import sys
from typing import Any

from pypts.hardware_layer.driver import DriverError


class DriverProxy:
    """
    Transparent proxy for a Driver running in a sidecar subprocess.

    Call connect() once to spawn the sidecar and establish the connection.
    After that, any attribute access returns a callable that forwards the
    call as a JSON-RPC request and returns the result or raises DriverError.
    """

    def __init__(
        self,
        driver_class_path: str,
        config: dict[str, str],
        python_executable: str = sys.executable,
    ) -> None:
        self._driver_class_path = driver_class_path
        self._config = config
        self._python = python_executable
        self._proc: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._counter = 0

    def connect(self) -> None:
        self._proc = subprocess.Popen(
            [self._python, "-m", "pypts.hardware_layer.runner", "--driver", self._driver_class_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        line = self._proc.stdout.readline()
        if not line.startswith("PORT:"):
            stderr = self._proc.stderr.read()
            raise DriverError(f"sidecar failed to start: {stderr or line!r}")
        port = int(line.strip().split(":")[1])

        self._sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self._call("connect", [], {"config": self._config})

    def teardown(self) -> None:
        if self._sock is not None:
            try:
                self._call("teardown", [], {})
            except Exception:
                pass
            self._sock.close()
            self._sock = None
        if self._proc is not None:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args: Any, **kwargs: Any) -> Any:
            return self._call(name, list(args), kwargs)

        return _call

    def _call(self, method: str, args: list, kwargs: dict) -> Any:
        if self._sock is None:
            raise DriverError("proxy not connected — call connect() first")
        self._counter += 1
        req_id = self._counter
        request = json.dumps({"id": req_id, "method": method, "args": args, "kwargs": kwargs})
        self._sock.sendall((request + "\n").encode())

        buf = b""
        while b"\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise DriverError("sidecar closed the connection unexpectedly")
            buf += chunk
        raw = buf.split(b"\n")[0]
        response = json.loads(raw)

        if "error" in response:
            raise DriverError(response["error"]["message"])
        return response.get("result")
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit_tests/test_hal.py -k "proxy" -v
```
Expected: all 3 proxy tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pypts/hardware_layer/proxy.py tests/unit_tests/test_hal.py
git commit -m "feat(hal): add DriverProxy — transparent sidecar wrapper"
```

---

## Task 4: `SshDriver`

**Files:**
- Create: `src/pypts/hardware_layer/drivers/__init__.py`
- Create: `src/pypts/hardware_layer/drivers/ssh.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Consumes: `Driver`, `DriverError` from Task 1
- Produces: `SshDriver(Driver)`
  - `connect(config: dict[str, str]) -> None` — keys: `host`, `username`, `password` (optional), `key_filename` (optional), `port` (optional, default `"22"`)
  - `execute(command: str) -> dict[str, str]` — keys: `stdout`, `stderr`, `exit_code`
  - `teardown() -> None`
  - All return values are standard serializable types

- [ ] **Step 1: Write the failing test**

Append to `tests/unit_tests/test_hal.py`:

```python
from unittest.mock import MagicMock, patch


def test_ssh_driver_connect_calls_paramiko(monkeypatch):
    import pypts.hardware_layer.drivers.ssh as ssh_mod

    mock_client = MagicMock()
    monkeypatch.setattr(ssh_mod.paramiko, "SSHClient", lambda: mock_client)

    from pypts.hardware_layer.drivers.ssh import SshDriver

    driver = SshDriver()
    driver.connect({"host": "myhost", "username": "user", "port": "22"})
    mock_client.connect.assert_called_once_with(
        hostname="myhost", username="user", port=22, password=None, key_filename=None
    )


def test_ssh_driver_execute_returns_dict():
    import pypts.hardware_layer.drivers.ssh as ssh_mod

    mock_client = MagicMock()
    stdout_mock = MagicMock()
    stdout_mock.read.return_value = b"hello\n"
    stdout_mock.channel.recv_exit_status.return_value = 0
    stderr_mock = MagicMock()
    stderr_mock.read.return_value = b""
    mock_client.exec_command.return_value = (MagicMock(), stdout_mock, stderr_mock)

    from pypts.hardware_layer.drivers.ssh import SshDriver

    driver = SshDriver()
    driver._client = mock_client
    result = driver.execute("echo hello")
    assert result == {"stdout": "hello\n", "stderr": "", "exit_code": 0}


def test_ssh_driver_teardown_closes_client():
    from pypts.hardware_layer.drivers.ssh import SshDriver

    mock_client = MagicMock()
    driver = SshDriver()
    driver._client = mock_client
    driver.teardown()
    mock_client.close.assert_called_once()
    assert driver._client is None


def test_ssh_driver_connect_raises_driver_error_on_failure(monkeypatch):
    import pypts.hardware_layer.drivers.ssh as ssh_mod
    import paramiko

    mock_client = MagicMock()
    mock_client.connect.side_effect = paramiko.ssh_exception.NoValidConnectionsError({("host", 22): Exception("refused")})
    monkeypatch.setattr(ssh_mod.paramiko, "SSHClient", lambda: mock_client)

    from pypts.hardware_layer.drivers.ssh import SshDriver
    from pypts.hardware_layer.driver import DriverError

    driver = SshDriver()
    with pytest.raises(DriverError):
        driver.connect({"host": "myhost", "username": "user"})
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit_tests/test_hal.py -k "ssh" -v
```
Expected: FAIL — `drivers/ssh.py` does not exist.

- [ ] **Step 3: Write the implementation**

```python
# src/pypts/hardware_layer/drivers/__init__.py
```

```python
# src/pypts/hardware_layer/drivers/ssh.py
from __future__ import annotations

import paramiko

from pypts.hardware_layer.driver import Driver, DriverError


class SshDriver(Driver):
    """
    SSH connection driver backed by paramiko.

    Config keys:
        host          — hostname or IP
        username      — SSH username
        password      — SSH password (optional if key_filename given)
        key_filename  — path to private key file (optional)
        port          — SSH port as string (optional, default "22")
    """

    def __init__(self) -> None:
        self._client: paramiko.SSHClient | None = None
        self._config: dict[str, str] = {}

    def connect(self, config: dict[str, str]) -> None:
        self._config = config
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=config["host"],
                username=config["username"],
                port=int(config.get("port", "22")),
                password=config.get("password"),
                key_filename=config.get("key_filename"),
            )
        except Exception as exc:
            raise DriverError(str(exc)) from exc
        self._client = client

    def execute(self, command: str) -> dict[str, str]:
        if self._client is None:
            raise DriverError("not connected")
        _, stdout, stderr = self._client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        return {
            "stdout": stdout.read().decode(errors="replace"),
            "stderr": stderr.read().decode(errors="replace"),
            "exit_code": exit_code,
        }

    def teardown(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit_tests/test_hal.py -k "ssh" -v
```
Expected: all 4 SSH tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pypts/hardware_layer/drivers/ tests/unit_tests/test_hal.py
git commit -m "feat(hal): add SshDriver — first concrete driver"
```

---

## Task 5: `HalManager`

**Files:**
- Create: `src/pypts/hardware_layer/hal_manager.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Consumes: `DriverProxy` from Task 3, `ConfigHandler` (already exists)
- Produces: `HalManager(config: ConfigHandler)`
  - `get_driver(logical_name: str) -> DriverProxy` — connects on first access, then cached
  - `teardown_all() -> None` — tears down every connected proxy

Config format expected in `config.ini`:
```ini
[hardware.ssh1]
driver = pypts.hardware_layer.drivers.ssh.SshDriver
host = myhost
username = testuser
port = 22
```
The `driver` key names the class. All other keys are passed as `config` to `connect()`.
The optional `python` key overrides the Python interpreter for the sidecar.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit_tests/test_hal.py`:

```python
from unittest.mock import patch, MagicMock
from pypts.hardware_layer.hal_manager import HalManager


def _make_config(sections: dict[str, dict[str, str]]):
    """Return a minimal ConfigHandler stub that serves hardware sections."""
    config = MagicMock()

    def get_whole_config():
        return sections

    config.get_whole_config.side_effect = get_whole_config
    return config


def test_hal_manager_get_driver_returns_proxy(monkeypatch):
    cfg = _make_config({
        "hardware.ssh1": {
            "driver": "pypts.hardware_layer.drivers.ssh.SshDriver",
            "host": "h",
            "username": "u",
        }
    })
    mock_proxy = MagicMock()

    with patch("pypts.hardware_layer.hal_manager.DriverProxy", return_value=mock_proxy):
        manager = HalManager(cfg)
        proxy = manager.get_driver("ssh1")
        mock_proxy.connect.assert_called_once()
        assert proxy is mock_proxy


def test_hal_manager_get_driver_cached(monkeypatch):
    cfg = _make_config({
        "hardware.ssh1": {
            "driver": "pypts.hardware_layer.drivers.ssh.SshDriver",
            "host": "h",
            "username": "u",
        }
    })
    mock_proxy = MagicMock()

    with patch("pypts.hardware_layer.hal_manager.DriverProxy", return_value=mock_proxy) as cls:
        manager = HalManager(cfg)
        manager.get_driver("ssh1")
        manager.get_driver("ssh1")
        assert cls.call_count == 1


def test_hal_manager_get_driver_unknown_name():
    cfg = _make_config({})
    manager = HalManager(cfg)
    with pytest.raises(KeyError):
        manager.get_driver("no_such_device")


def test_hal_manager_teardown_all(monkeypatch):
    cfg = _make_config({
        "hardware.ssh1": {
            "driver": "pypts.hardware_layer.drivers.ssh.SshDriver",
            "host": "h",
            "username": "u",
        }
    })
    mock_proxy = MagicMock()

    with patch("pypts.hardware_layer.hal_manager.DriverProxy", return_value=mock_proxy):
        manager = HalManager(cfg)
        manager.get_driver("ssh1")
        manager.teardown_all()
        mock_proxy.teardown.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit_tests/test_hal.py -k "hal_manager" -v
```
Expected: FAIL — `hal_manager.py` does not exist.

- [ ] **Step 3: Write the implementation**

```python
# src/pypts/hardware_layer/hal_manager.py
from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from pypts.hardware_layer.proxy import DriverProxy

if TYPE_CHECKING:
    from pypts.config_handler import ConfigHandler

log = logging.getLogger(__name__)

_DRIVER_KEY = "driver"
_PYTHON_KEY = "python"
_HARDWARE_PREFIX = "hardware."


class HalManager:
    """
    Owns all DriverProxy instances for one session.

    Reads [hardware.<name>] sections from the config to discover declared
    drivers. Proxies are created and connected lazily on first get_driver()
    call, then cached for the session lifetime.
    """

    def __init__(self, config: ConfigHandler) -> None:
        self._raw = self._read_hardware_sections(config)
        self._proxies: dict[str, DriverProxy] = {}

    @staticmethod
    def _read_hardware_sections(config: ConfigHandler) -> dict[str, dict[str, str]]:
        all_sections = config.get_whole_config()
        return {
            name[len(_HARDWARE_PREFIX):]: dict(values)
            for name, values in all_sections.items()
            if name.startswith(_HARDWARE_PREFIX)
        }

    def get_driver(self, logical_name: str) -> DriverProxy:
        if logical_name in self._proxies:
            return self._proxies[logical_name]

        if logical_name not in self._raw:
            raise KeyError("no hardware section [hardware.%s] in config" % logical_name)

        section = dict(self._raw[logical_name])
        driver_class_path = section.pop(_DRIVER_KEY)
        python_exe = section.pop(_PYTHON_KEY, sys.executable)

        proxy = DriverProxy(
            driver_class_path=driver_class_path,
            config=section,
            python_executable=python_exe,
        )
        proxy.connect()
        log.info("driver connected: %s (%s)", logical_name, driver_class_path)
        self._proxies[logical_name] = proxy
        return proxy

    def teardown_all(self) -> None:
        for name, proxy in list(self._proxies.items()):
            try:
                proxy.teardown()
                log.info("driver torn down: %s", name)
            except Exception as exc:
                log.warning("driver teardown failed for %s: %s", name, exc)
        self._proxies.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit_tests/test_hal.py -k "hal_manager" -v
```
Expected: all 4 HalManager tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pypts/hardware_layer/hal_manager.py tests/unit_tests/test_hal.py
git commit -m "feat(hal): add HalManager — owns driver proxies for one session"
```

---

## Task 6: Wire into Runtime and Sequencer

**Files:**
- Modify: `src/pypts/step/runtime.py`
- Modify: `src/pypts/sequencer/sequencer.py`
- Test: `tests/unit_tests/test_hal.py` (append)

**Interfaces:**
- Consumes: `HalManager` from Task 5, `Runtime` (existing)
- Produces:
  - `Runtime` gains `get_driver: Callable[[str], Any]` seam
  - `Sequencer` creates a `HalManager` in `start()` and tears it down in `stop()`
  - `Sequencer.execute_sequence()` fills the `get_driver` seam on the Runtime it builds

- [ ] **Step 1: Write the failing test**

Append to `tests/unit_tests/test_hal.py`:

```python
from pypts.step.runtime import Runtime


def test_runtime_get_driver_default_raises():
    runtime = Runtime()
    with pytest.raises(RuntimeError):
        runtime.get_driver("ssh1")


def test_runtime_get_driver_calls_injected_callable():
    sentinel = object()
    runtime = Runtime(get_driver=lambda name: sentinel)
    assert runtime.get_driver("ssh1") is sentinel
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit_tests/test_hal.py -k "runtime" -v
```
Expected: FAIL — `Runtime` has no `get_driver`.

- [ ] **Step 3: Add `get_driver` seam to `Runtime`**

In `src/pypts/step/runtime.py`, add the seam following the exact pattern of the `ask` seam.

Add this default function near the other defaults (after `_nothing_to_drop`):

```python
def _no_hal(name: str) -> Any:
    """No HAL behind this Runtime."""
    raise RuntimeError(
        "no HAL available in this Runtime — the Sequencer must inject get_driver"
    )
```

Add `get_driver` parameter to `Runtime.__init__` after `drop_pending_pause`:

```python
get_driver: Callable[[str], Any] | None = None,
```

Add the assignment in the body of `__init__` after `self.drop_pending_pause`:

```python
self.get_driver: Callable[[str], Any] = get_driver if get_driver is not None else _no_hal
```

- [ ] **Step 4: Run Runtime tests to verify they pass**

```
pytest tests/unit_tests/test_hal.py -k "runtime" -v
```
Expected: both PASS.

- [ ] **Step 5: Wire HalManager into the Sequencer**

In `src/pypts/sequencer/sequencer.py`:

Find the `Sequencer.__init__` method. Add import at top of file:
```python
from pypts.hardware_layer.hal_manager import HalManager
from pypts.config_handler import ConfigHandler
```

In `Sequencer.__init__`, add:
```python
self._hal: HalManager = HalManager(ConfigHandler())
```

Find the `execute_sequence()` method where `Runtime(...)` is constructed. Add `get_driver=self._hal.get_driver` to the `Runtime(...)` call.

Find the `stop()` method (the one that sends `SequencerStopped`). Before the existing stop logic, add:
```python
self._hal.teardown_all()
```

- [ ] **Step 6: Run all HAL and sequencer tests**

```
pytest tests/unit_tests/test_hal.py tests/unit_tests/test_sequencer.py -v
```
Expected: all PASS. If sequencer tests that construct `Runtime` break, they need `get_driver` added only if they call it — the default raises, the no-op default is `_no_hal`. Existing tests that do not call `get_driver` are unaffected.

- [ ] **Step 7: Commit**

```bash
git add src/pypts/step/runtime.py src/pypts/sequencer/sequencer.py tests/unit_tests/test_hal.py
git commit -m "feat(hal): wire get_driver seam into Runtime and Sequencer"
```

---

## Task 7: `__init__.py`, `pyproject.toml`, and documentation

**Files:**
- Modify: `src/pypts/hardware_layer/__init__.py`
- Modify: `pyproject.toml`
- Modify: `src/pypts/hardware_layer/hal.md`

**Interfaces:**
- Produces: `from pypts.hardware_layer import Driver, DriverError, DriverProxy, HalManager`

- [ ] **Step 1: Update `__init__.py`**

```python
# src/pypts/hardware_layer/__init__.py
from pypts.hardware_layer.driver import Driver, DriverError
from pypts.hardware_layer.hal_manager import HalManager
from pypts.hardware_layer.proxy import DriverProxy

__all__ = ["Driver", "DriverError", "DriverProxy", "HalManager"]
```

- [ ] **Step 2: Move `paramiko` to optional extra in `pyproject.toml`**

Remove `"paramiko"` from `dependencies`.

Add to `[project.optional-dependencies]`:
```toml
ssh = ["paramiko"]
```

- [ ] **Step 3: Run the full test suite to verify nothing broke**

```
pytest tests
ruff check src tests
mypy
```
Expected: all pass. If `paramiko` import in `ssh.py` fails (not installed in dev env), add it: `pip install paramiko` or `pip install -e ".[ssh]"`.

- [ ] **Step 4: Update `hal.md`**

Replace the entire contents of `src/pypts/hardware_layer/hal.md` with a description of what now exists:
- The agreed shape is implemented
- List all files and their responsibilities
- Document the protocol (PORT:<n>, JSON-RPC request/response)
- Document the config format (`[hardware.<name>]`, `driver =`, `python =`)
- Document `SshDriver` config keys
- Mark SSH as the reference driver; note packaging: `pip install pts-framework[ssh]`
- Remove "open before any code is written" section (answered by this implementation)
- Add "known gaps": bulk data (binary side-channel not yet implemented); recover() not yet called by HalManager on crash detection

- [ ] **Step 5: Commit**

```bash
git add src/pypts/hardware_layer/__init__.py pyproject.toml src/pypts/hardware_layer/hal.md
git commit -m "feat(hal): wire up exports, move paramiko to [ssh] extra, update hal.md"
```

---

## Self-Review

**Spec coverage check:**
- Driver base class with `connect`/`teardown`/`recover` → Task 1 ✓
- Sidecar runner, generic, no driver-side IPC code → Task 2 ✓
- DriverProxy with transparent `__getattr__` forwarding → Task 3 ✓
- SshDriver as first concrete driver → Task 4 ✓
- HalManager reads config, lazy connect, teardown_all → Task 5 ✓
- Runtime `get_driver` seam → Task 6 ✓
- paramiko moved to optional extra → Task 7 ✓
- One subprocess per driver (not one HAL process) → Task 3/5 ✓
- Driver class usable standalone without framework → Task 1/4 ✓ (plain class, no framework import)

**Placeholder scan:** None found — all steps contain actual code.

**Type consistency:**
- `Driver.connect(config: dict[str, str])` — used in Task 1, 4, 5 ✓
- `DriverProxy(driver_class_path, config, python_executable)` — defined Task 3, consumed Task 5 ✓
- `HalManager.get_driver(logical_name: str) -> DriverProxy` — defined Task 5, injected Task 6 ✓
- `Runtime.get_driver: Callable[[str], Any]` — defined Task 6, matches injection Task 6 ✓
