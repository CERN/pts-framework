import sys
from importlib import import_module
from ast import literal_eval
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format='[LOG]%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("interpreter_core")
interpreter_name = ""


def main_loop():
    __stop = False
    while not __stop:
        line = sys.stdin.readline().strip()
        logger.info(f"Received command '{line}'")
        output = {} # default for now
        match line:
            case 'stop':
                __stop = True
            
            case 'run_method':
                output = {"pass": False}
                module_name = Path(sys.stdin.readline().strip())
                method_name = sys.stdin.readline().strip()
                method_parameters = literal_eval(sys.stdin.readline().strip())
                try:
                    module = load_module(module_name)
                    method = getattr(module, method_name)
                    output = method(**method_parameters)
                except Exception as e:
                    logger.error(f"Error loading module {e.with_traceback()}")
            
            case 'read_attribute':
                output = {"pass": False}
                module_name = Path(sys.stdin.readline().strip())
                attribute_name = sys.stdin.readline().strip()
                try:
                    module = load_module(module_name)
                    output = getattr(module, attribute_name)
                except Exception as e:
                    logger.error(f"Error loading module {e.with_traceback()}")  

            case 'write_attribute':
                output = {"pass": True}
                module_name = Path(sys.stdin.readline().strip())
                attribute_name = sys.stdin.readline().strip()
                attribute_value = sys.stdin.readline().strip()
                try:
                    module = load_module(module_name)
                    setattr(module, attribute_name, attribute_value)
                except Exception as e:
                    logger.error(f"Error loading module {e.with_traceback()}")

            case 'echo':
                output = {"echo": sys.stdin.readline().strip()}
            
            case _:
                logger.info(f"Unknown command: '{line}'")
        logger.info("Command executed")
        return_result(output)


def return_result(results):
    sys.stdout.write('[RES]' + str(results) + '\n')
    sys.stdout.flush()

def load_module(module_full_path: Path):
    module_path = str(module_full_path.parent)
    module_filename = module_full_path.stem
    if module_path not in sys.path:
        sys.path.append(module_path)
    module = import_module(module_filename)
    return module

if __name__ == "__main__":
    interpreter_name = sys.stdin.readline().strip()
    logger = logging.getLogger(f"interpreter_core[{interpreter_name}]")
    logger.info(f"Started subprocess {interpreter_name}")
    main_loop()
    logger.info(f"Ended subprocess {interpreter_name}")
    sys.stdout.close()




