# SPDX-FileCopyrightText: 2025 2025 CERN <home.cern>
# SPDX-FileCopyrightText: 2025 CERN
#
# SPDX-License-Identifier: LGPL-2.1-or-later

def convert_string_to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Cannot convert '{value}' to integer.")
    except TypeError:
        raise TypeError("Input must be a string or number.")
