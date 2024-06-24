import imported
from threading import Thread
from importlib import import_module, reload
from pathlib import Path
import sys

def threaded_function():
    imported.some_function()
    import imported_b
    imported_b.this_is_b()
    print(dir())
    print(sys.modules)
    del sys.modules["imported_b"]
    print(sys.modules)

def read_attribute(module_name: Path, attribute_name: str):
    output = {}
    # try:
    module = load_module(module_name)
    output[attribute_name] = getattr(module, attribute_name)
    # except:
    #     print(f"Error reading attribute")
    print(output)
    return output

def write_attribute(module_name: Path, attribute_name: str, attribute_value):
    try:
        module = load_module(module_name)
        setattr(module, attribute_name, attribute_value)
    except:
        print(f"Error writing attribute")

def load_module(module_full_path: Path):
    module_path = str(module_full_path.parent)
    module_filename = module_full_path.stem
    if module_path not in sys.path:
        sys.path.append(module_path)
    module = import_module(module_filename)
    return module

imported.some_function()
t = Thread(target=read_attribute, args=[Path("imported.py"), "att"])
t.start()
t.join()
t = Thread(target=write_attribute, args=[Path("imported.py"), "att", 3])
t.start()
t.join()
t = Thread(target=read_attribute, args=[Path("imported.py"), "att"])
t.start()
t.join()


