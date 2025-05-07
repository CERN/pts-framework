import pypts._version as version_module  # replace with your actual package name
import re
import pytest

def test_version_format():
    # Check presence of version variables
    assert hasattr(version_module, "__version__")
    assert hasattr(version_module, "version")
    assert hasattr(version_module, "__version_tuple__")
    assert hasattr(version_module, "version_tuple")

    # Check aliases are consistent
    assert version_module.__version__ == version_module.version
    assert version_module.__version_tuple__ == version_module.version_tuple

    # Check version is a non-empty string and follows expected format (e.g., "0.1.dev123+g52d4bd6")
    assert isinstance(version_module.version, str)
    assert re.match(r"^\d+\.\d+(\.\w+)?(\+\w+)?$", version_module.version)

    # Check version_tuple structure: (int, int, str, str)
    vt = version_module.version_tuple
    assert isinstance(vt, tuple)
    assert len(vt) >= 2
    assert isinstance(vt[0], int)
    assert isinstance(vt[1], int)
    for v in vt[2:]:
        assert isinstance(v, (int, str))

@pytest.mark.parametrize("version_attr", ["__version__", "version"])
def test_version_string_format(version_attr):
    version = getattr(version_module, version_attr)
    assert isinstance(version, str)
    assert re.match(r"^\d+\.\d+(?:\.\w+)?(?:\+\w+)?$", version)

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