import subprocess
import logging
import os
from threading import Thread
from queue import Queue
from ast import literal_eval


logger = logging.getLogger(__name__)

class Interpreter():

    _python_path = ""
    _file = ""
    _id = ""
    _running = False

    def __init__(self, interpreter_path, name):
        self._python_path = interpreter_path
        self._name = name
        
    def start(self):
        logger.info(f"Starting interpreter {self._name} at {self._python_path}")
        try:
            self._proc = subprocess.Popen([self._python_path, "interpreter_bridge.py"], 
                                          stdout=subprocess.PIPE, 
                                          stdin=subprocess.PIPE, 
                                          stderr=subprocess.STDOUT,
                                          text=True,
                                          #bufsize=1,
                                          )
            self.queue = Queue()
            self.thread = Thread(target=self.__process_stdout)
            self.thread.start()
            self._proc.stdin.write(self._name + '\n') # sends the name to the interpreter
            self._running = True
        except (OSError, Exception):
            print("Error")
            self._proc.kill()
        
    def restart(self):
        pass

    def stop(self):
        if self._running:
            logger.info(f"Stopping interpreter {self._name}.")
            output = self._send_command("stop")
            self.thread.join()
            self._running = False
            self._proc.kill()
        else:
            output = "{}"
        return literal_eval(output)

    def run_method(self, module_name=None, method_name=None, method_parameters=None):
        logger.info(f"Calling method {method_name} from module {module_name} with parameters {method_parameters}.")
        output = self._send_command("run_method", module_name, method_name, method_parameters)
        return literal_eval(output)

    def read_attribute(self, module_name=None, attribute_name=None):
        logger.info(f"Reading attribute {attribute_name} from module {module_name}.")
        output = self._send_command("read_attribute", module_name, attribute_name)
        return literal_eval(output)

    def write_attribute(self, module_name=None, attribute_name=None, attribute_value=None):
        logger.info(f"Writing attribute {attribute_name} from module {module_name}.")
        output = self._send_command("write_attribute", module_name, attribute_name, attribute_value)
        return literal_eval(output)

    def _send_command(self, command, *args):
        try:
            self._proc.stdin.write(command + '\n')
            for arg in args:
                self._proc.stdin.write(str(arg) + '\n')
            self._proc.stdin.flush()
            output = self.queue.get()
            return output
        except (OSError, Exception):
            print("Problem with child")
            return {}
        
    def __process_stdout(self):
        logger.info(f"Starting stdout listening thread for interpreter {self._name}")
        count = 0
        while True:
            line = self._proc.stdout.readline().strip()
            logger.debug(line)
            if not line:
                break
            # if count == 100:
            #     break
            match line[0:5]:
                case "[LOG]":
                    print(line[5:])
                case "[RES]":
                    self.queue.put(line[5:])
                    #print(line[5:])
                case _:
                    count += 1
                    print(count, line)
        logger.info(f"Stopping stdout listening thread for interpreter {self._name}")