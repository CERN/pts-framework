# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import interpreter
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == '__main__':
    my_int = interpreter.Interpreter("C:\dev\pypts\.venv\Scripts\python.exe")
    my_int.start()
    print(my_int._send_command('echo', 'bla'))
    print(my_int.run_method(module_name="test_thing", method_name="test_to_run", method_parameters={"target": 42}))
    print(my_int.run_method(module_name="test_thing", method_name="test_to_run", method_parameters={"target": 43}))
    print(my_int.run_method(module_name="test_thing", method_name="test_to_run", method_parameters={"target": 43}))
    print(my_int.stop())
