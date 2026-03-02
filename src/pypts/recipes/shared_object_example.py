# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

class test_class():
    def __init__(self, value: str):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value: str):
        self.value = value

def create_object():
    test_object = test_class("just created")
    return {"test_object": test_object}

def update_object_value(object: test_class, value: str):
    object.set_value(value)

def get_object_value(object: test_class):
    return {"object_value": object.get_value()}
