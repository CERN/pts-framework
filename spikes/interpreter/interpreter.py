# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import subprocess
import logging
import os
from threading import Thread
from queue import Queue
from ast import literal_eval
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

class Interpreter():

    def __init__(self, interpreter_path=None, name=""):
        if interpreter_path is None:
            interpreter_path = sys.executable
        self.python_path = Path(interpreter_path).joinpath("python.exe")
        self.name = name
        self.running = False
        
    def start(self):
        logger.info(f"Starting interpreter {self.name} at {self.python_path}")
        try:
            self._proc = subprocess.Popen([self.python_path, "interpreter_bridge.py"], 
                                          stdout=subprocess.PIPE, 
                                          stdin=subprocess.PIPE, 
                                          stderr=subprocess.STDOUT,
                                          text=True,
                                          )
            self.queue = Queue()
            self.thread = Thread(target=self.__stdout_listener)
            self.thread.start()
            self._proc.stdin.write(self.name + '\n') # sends the name to the interpreter
            self.running = True
        except (OSError, Exception):
            print("Error")
            self._proc.kill()
        
    def restart(self):
        pass

    def stop(self):
        if self.running:
            logger.info(f"Stopping interpreter {self.name}.")
            output = self._send_command("stop")
            self.thread.join()
            self.running = False
            self._proc.kill()
        else:
            output = {}
        return output

    def run_method(self, module_name=None, method_name=None, method_parameters=None):
        logger.info(f"Calling method {method_name} from module {module_name} with parameters {method_parameters}.")
        output = self._send_command("run_method", module_name, method_name, method_parameters)
        return output

    def read_attribute(self, module_name=None, attribute_name=None):
        logger.info(f"Reading attribute {attribute_name} from module {module_name}.")
        output = self._send_command("read_attribute", module_name, attribute_name)
        return output

    def write_attribute(self, module_name=None, attribute_name=None, attribute_value=None):
        logger.info(f"Writing attribute {attribute_name} from module {module_name}.")
        output = self._send_command("write_attribute", module_name, attribute_name, attribute_value)
        return output

    def _send_command(self, command: str, *args) -> str:
        """Formats and sends a command to the subprocess. The data comes back as a string and
        is evaluated back into Python data.
        Data is sent through a text pipe in the following format:
        command\n
        arg1\n
        arg2\n
        ...
        The subprocess knows how many arguments to expect based on the command

        Args:
            command (str): The name of the command to send

        Returns:
            _type_: _description_
        """
        try:
            self._proc.stdin.write(command + '\n')
            for arg in args:
                self._proc.stdin.write(str(arg) + '\n')
            self._proc.stdin.flush()
            output = self.queue.get()
            return literal_eval(output)
        except (OSError, Exception):
            print("Problem with child")
            return "{}"
        
    def __stdout_listener(self):
        logger.info(f"Starting stdout listening thread for interpreter {self.name}")
        count = 0
        stop_communication = False
        while not stop_communication:
            line = self._proc.stdout.readline().strip()
            #logger.debug(line)
            match line[0:5]:
                case "[LOG]":
                    print(line[5:])
                case "[RES]":
                    self.queue.put(line[5:])
                case "[FIN]":
                    stop_communication = True
                case _:
                    #count += 1
                    print(line)
        logger.info(f"Stopping stdout listening thread for interpreter {self.name}")