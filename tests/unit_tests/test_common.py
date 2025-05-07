import pytest
from pypts.common import convert_string_to_int  # Replace with actual import path

def test_valid_integer_string():
    assert convert_string_to_int("42") == 42
    assert convert_string_to_int("-100") == -100
    assert convert_string_to_int("0") == 0

def test_invalid_string_raises_value_error():
    with pytest.raises(ValueError, match="Cannot convert 'abc' to integer."):
        convert_string_to_int("abc")

    with pytest.raises(ValueError):
        convert_string_to_int("4.2")  # not a valid int string

def test_none_raises_type_error():
    with pytest.raises(TypeError, match="Input must be a string or number."):
        convert_string_to_int(None)

def test_actual_int_pass_through():
    assert convert_string_to_int(123) == 123
    assert convert_string_to_int(-10) == -10
