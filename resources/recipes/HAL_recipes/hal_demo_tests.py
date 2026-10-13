# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The test functions hal_demo.yml calls: test code reaching bench devices by
logical name. The names are declared in config.ini, one [hardware.<name>]
section each - see the comment at the top of hal_demo.yml.
"""

from pypts.hal import get_device


def loopback_echo(text):
    """Send text to the loopback device and get it back."""
    device = get_device("loop1")
    return {"echoed": device.echo(text)}


def ssh_uname():
    """Ask the remote host what it runs."""
    result = get_device("ssh1").execute("uname -a")
    return {"exit_code": result["exit_code"], "system": result["stdout"].strip()}
