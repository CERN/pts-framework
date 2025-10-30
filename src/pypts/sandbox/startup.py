# startup.py
from multiprocessing import Process, Queue
from core import core
from gui import gui

if __name__ == '__main__':
    hmi_to_core = Queue()
    core_to_hmi = Queue()

    p_core = Process(target=core, args=(hmi_to_core, core_to_hmi))
    p_gui = Process(target=gui, args=(hmi_to_core, core_to_hmi))

    p_core.start()
    p_gui.start()

    p_core.join()
    p_gui.join()
