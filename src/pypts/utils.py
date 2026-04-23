# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path
import hashlib
import io
import sys
from importlib import util
from importlib.resources import files, as_file
from PySide6.QtGui import QImageReader
import serial
from serial.tools import list_ports
import threading

"""Module that provides the utilities to the project.
    """
EXCLUDE_DIRS = {
    '.git',
    '__pycache__',
    'archive',
    'backup',
    'old_tests',
    'results',
    'pts_reports',
    'dist',         
    'build',  
    '.eggs',         # eggs cache
    '.mypy_cache',   # mypy cache
    '.pytest_cache', # pytest cache
    '.tox',          # tox environment
    'node_modules',  # if you have JS deps
    '.idea',         # PyCharm config
    '.vscode',       # VSCode config
    '.cache',        # generic cache dirs
}

WAIT_FOR_TERMINATION = threading.Event()

def get_step_result_colors(result_value, result_type_enum) -> tuple[str, str]:
    """
    result_type_enum: the enum class (e.g., recipe.ResultType)
    result_value: an enum member from that class (e.g., recipe.ResultType.PASS)
    """
    color_map = {
        result_type_enum.PASS:  ("#C8E6C9", "#1B4F24"),
        result_type_enum.FAIL:  ("#F28B82", "#7B0000"),
        result_type_enum.DONE:  ("#B2EBF2", "#004D52"),
        result_type_enum.SKIP:  ("#FFF9C4", "#C49000"),
        result_type_enum.ERROR: ("#FFCC80", "#BF360C"),
        result_type_enum.STOP: ("#D3D3D3", "#4B4B4B"),
    }
    return color_map.get(result_value, ("#FFFFFF", "#000000"))



# def get_project_root() -> Path:
#     return Path(__file__).parent.parent.parent

def get_project_root() -> Path:
    # Walk up from CWD (the user's project), not from __file__ (pypts package).
    current = Path.cwd().resolve()

    # Look for pyproject.toml up the tree. It should often be there
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    #trying other base settings
    for parent in [current, *current.parents]:
        if (parent / "setup.py").exists() or (parent / "requirements.txt").exists():
            return parent

    #if in venv, return its parent
    if hasattr(sys, 'base_prefix') and sys.prefix != sys.base_prefix:
        return Path(sys.prefix).resolve().parent
    return current.parent

def get_package_root(package_name: str) -> Path:
    spec = util.find_spec(package_name)
    if spec is None or spec.origin is None:
        raise ImportError(f"Cannot find package '{package_name}'")
    return Path(spec.origin).parent

def find_resource_path(module_name_str: str, root: Path) -> Path:
    """
    Resolve a module path under `root` from either:
      - 'example_test'   (no suffix)
      - 'example_test.py'
      - 'subdir/example_test' or 'subdir/example_test.py'

    Returns a path *relative to* root.
    Raises FileNotFoundError if not found.
    """
    module_name = Path(module_name_str)
    search_root = root / module_name.parent if str(module_name.parent) not in ("", ".") else root

    # Try both with and without ".py" when no suffix was provided
    names_to_try = (
        [module_name.name] if module_name.suffix == ".py" else [module_name.name, f"{module_name.name}.py"]
    )

    for name in names_to_try:
        for path in search_root.rglob(name):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if path.name == name:
                return path.relative_to(root)
            
    if module_name.suffix.lower in (str(fmt.data().decode()) for fmt in QImageReader.supportedImageFormats()):
        return files('pypts') / 'images' / 'CERN_Logo.png'
    #raise FileNotFoundError(f"Module '{module_name_str}' not found under {root}")

def resolve_package_resource(filename: str, package_name: str) -> Path | None:
    """Resolve a resource file inside an installed Python package.
    Returns absolute Path if found, None otherwise.
    Works with both regular and editable installs.
    """
    try:
        # Try exact path first (e.g. "resources/power_Green.jpg")
        resource = files(package_name).joinpath(filename)
        with as_file(resource) as p:
            if p.exists():
                return Path(p)
    except (ModuleNotFoundError, TypeError, FileNotFoundError):
        pass

    # Bare filename — search one level of subdirs (resources/, bin/, images/)
    if "/" not in filename and "\\" not in filename:
        try:
            package_root = files(package_name)
            for item in package_root.iterdir():
                if item.is_dir():
                    candidate = item.joinpath(filename)
                    try:
                        with as_file(candidate) as p:
                            if p.exists():
                                return Path(p)
                    except (TypeError, FileNotFoundError):
                        continue
        except (ModuleNotFoundError, TypeError):
            pass

    return None

def path_to_importable_module(file_path: Path) -> str:
    """
    Convert an absolute file path (in site-packages) to an importable module path.
    E.g., /.../.venv/lib/site-packages/pypts/example_tests.py -> pypts.example_tests

    It is used for if the user desires to load the pypts package downloaded as an example to how it runs. 
    """
    parts = file_path.resolve().parts
    try:
        idx = parts.index("site-packages")
        relevant_parts = parts[idx + 1:]  # Skip 'site-packages' itself
    except ValueError:
        raise ValueError("Path is not inside site-packages")

    mod_path = Path(*relevant_parts).with_suffix("")  # remove .py
    return ".".join(mod_path.parts)

class AbortTestException(Exception):
    """Raised to stop test execution cleanly if setup is not confirmed."""
    pass

def query_device_id(port, baudrate=9600, timeout=1):
    try:
        with serial.Serial(port, baudrate, timeout=timeout) as ser:
            ser.write(b'ID?\n')  # Command to query the device ID
            response = ser.readline().decode().strip()
            return response
    except (serial.SerialException, UnicodeDecodeError):
        return None

def find_serial_device(target: str = None,  baudrate: int=None, timeout=1):
    # Situation: If port_name is given, find the device ID
    common_baudrates = [
    300,1200,2400,4800,
    9600,14400,19200, 28800,
    38400, 57600, 74880, 115200,
    128000,230400,250000, 256000,
    460800, 500000, 576000, 921600,
    1000000, 1500000,2000000,3000000,4000000,]
    
    available_ports = [port.device for port in list_ports.comports()]

    try:
        baud_int = int(baudrate) if baudrate is not None else None
    except ValueError:
        baud_int = None

    # Build the baudrate list with optional prioritization
    baudrate_list = (
        [baud_int] + [b for b in common_baudrates if b != baud_int]
        if baud_int is not None
        else common_baudrates
    )

    def is_valid_port_name(name: str):
        return any(name == port for port in available_ports)
    
    if is_valid_port_name(target):
        for baud_r in baudrate_list:
            id_response = query_device_id(target, baud_r, timeout)
            if id_response:
                return target, id_response, baud_r
        return target, "Error", baud_r
    else:
        # Assume it's a device ID; scan all ports
        for port in available_ports:
            for baud_r in baudrate_list:
                id_response = query_device_id(port, baud_r, timeout)
                if id_response == target:
                    return port, target, baud_r
        raise RuntimeError(f"Device with ID '{target}' not found on any available COM port.")


def exec_command(
    client: "paramiko.SSHClient",
    cmd: str,
    timeout: int = 30,
) -> "tuple[str, str, int]":
    """
    Execute a shell command on a remote host via an open paramiko SSH client.

    Both stdout and stderr are drained concurrently in daemon threads to prevent
    SSH channel buffer deadlock — the classic paramiko pitfall when a remote
    command writes to both streams simultaneously.

    Args:
        client:  Connected ``paramiko.SSHClient`` (typically the ``ssh_client``
                 global set by :class:`~pypts.steps.SSHConnectStep`).
        cmd:     Shell command to run on the remote host.
        timeout: Hard timeout in seconds. Raises ``TimeoutError`` if the command
                 does not complete within this limit.

    Returns:
        A ``(stdout_text, stderr_text, exit_code)`` tuple with the full output
        of the command.

    Raises:
        TimeoutError: if the command does not finish within ``timeout`` seconds.
    """
    import paramiko  # local import — pypts core does not hard-require paramiko

    channel = client.get_transport().open_session()
    channel.settimeout(timeout)
    channel.exec_command(cmd)

    stdout_buf: io.StringIO = io.StringIO()
    stderr_buf: io.StringIO = io.StringIO()

    def _drain(source, dest: io.StringIO) -> None:
        while True:
            chunk = source.read(4096)
            if not chunk:
                break
            dest.write(chunk.decode("utf-8", errors="replace"))

    t_out = threading.Thread(target=_drain, args=(channel.makefile("rb"), stdout_buf), daemon=True)
    t_err = threading.Thread(target=_drain, args=(channel.makefile_stderr("rb"), stderr_buf), daemon=True)
    t_out.start()
    t_err.start()
    t_out.join(timeout=timeout)
    t_err.join(timeout=timeout)

    if t_out.is_alive() or t_err.is_alive():
        channel.close()
        raise TimeoutError(f"exec_command timed out after {timeout}s: {cmd!r}")

    exit_code = channel.recv_exit_status()
    channel.close()
    return stdout_buf.getvalue(), stderr_buf.getvalue(), exit_code


if __name__ == "__main__":
    print(get_project_root())

