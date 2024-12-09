"""
Tests for the pypts package.

"""

import pypts


def test_version():
    # Check tha the package has a __version__ attribute.
    assert pypts.__version__ is not None
