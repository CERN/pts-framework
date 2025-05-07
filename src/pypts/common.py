def convert_string_to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Cannot convert '{value}' to integer.")
    except TypeError:
        raise TypeError("Input must be a string or number.")
