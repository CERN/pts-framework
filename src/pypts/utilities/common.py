# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Small helpers with no home of their own.
"""


def convert_string_to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        # `from None` rather than bare `raise`: the message below says everything
        # the original did, so chaining would only add "During handling of the
        # above exception..." to what the caller sees.
        raise ValueError(f"Cannot convert '{value}' to integer.") from None
    except TypeError:
        raise TypeError("Input must be a string or number.") from None
