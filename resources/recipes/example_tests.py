# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The test functions python_demo.yml calls - the shape user test code takes.

Framework-free on purpose: a PythonModuleStep calls a plain function with the
recipe's resolved inputs as keyword arguments, and judges whatever comes back.
A dict is judged key by key against the step's output_mapping; anything else
is wrapped as {"output": value}.
"""


def add(a, b):
    """Return the sum - the recipe checks it with an `equals` mapping."""
    return {"sum": a + b}


def measure_voltage():
    """Pretend to measure something - the recipe checks it with a `range`."""
    return {"voltage": 12.1}


def is_even(number):
    """A boolean check - the recipe judges it with `passfail`."""
    return {"even": number % 2 == 0}


def greet(name):
    """A scalar return - wrapped as {"output": ...} by the framework."""
    return f"Hello, {name}!"
