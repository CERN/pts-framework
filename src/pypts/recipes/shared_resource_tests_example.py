# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from pypts.recipes.shared_resource_server import ResourceServer
from pypts.recipes.shared_resource_client import RemoteDevice

_server = ResourceServer()

def setup_resource_server():
    # Start server
    _server.start()

def stop_resource_server():
    # Stop server
    _server.stop()

def increment_value(how_much = 1):
    dev = RemoteDevice()
    return {"output": dev.increment(how_much)}

def get_value():
    dev = RemoteDevice()
    return {"output":dev.get_value()}

def simple_output(value):
    return {"output":value + 1}

def other_test():
    # logger.info("I could also do this.")
    return {"some_return": True, "value": 3}