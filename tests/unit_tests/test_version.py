import pypts._version as version_module  # replace with your actual package name
from packaging.version import Version, InvalidVersion
import pytest

def test_version_format():
    v = version_module.version
    assert isinstance(v, str)
    try:
        Version(v)
    except InvalidVersion:
        pytest.fail(f"{v!r} is not a valid PEP 440 version")

@pytest.mark.parametrize("version_attr", ["__version__", "version"])
def test_version_string_format(version_attr):
    version = getattr(version_module, version_attr)
    assert isinstance(version, str)
    try:
        Version(version)
    except InvalidVersion:
        pytest.fail(f"{version!r} is not a valid PEP 440 version")

@pytest.mark.parametrize("tuple_attr", ["__version_tuple__", "version_tuple"])
def test_version_tuple_format(tuple_attr):
    vt = getattr(version_module, tuple_attr)
    assert isinstance(vt, tuple)
    assert len(vt) >= 2
    assert isinstance(vt[0], int)
    assert isinstance(vt[1], int)
    for v in vt[2:]:
        assert isinstance(v, (int, str))

def test_version_aliases_equal():
    assert version_module.__version__ == version_module.version
    assert version_module.__version_tuple__ == version_module.version_tuple