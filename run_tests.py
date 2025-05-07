import pytest

if __name__ == "__main__":
    exit_code = pytest.main([
        "-s",
        "-v",
        "--color=yes",
        "tests/unit_tests"])
    exit(exit_code)
