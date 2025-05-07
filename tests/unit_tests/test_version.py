
import pypts._version as version_module  # replace with your actual package name
def test_version_values():

    assert hasattr(version_module, "__version__")
    assert hasattr(version_module, "version")
    assert hasattr(version_module, "__version_tuple__")
    assert hasattr(version_module, "version_tuple")

    # Check equality between aliases
    assert version_module.__version__ == version_module.version
    assert version_module.__version_tuple__ == version_module.version_tuple

    # Check actual version content
    assert isinstance(version_module.version, str)
    assert version_module.version.startswith("0.1.dev")
    assert version_module.version_tuple[0] == 0
    assert version_module.version_tuple[1] == 1
