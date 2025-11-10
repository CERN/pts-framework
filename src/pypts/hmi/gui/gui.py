# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Empty
from time import sleep
from pypts.core.core_interface import HMIToCoreInterface
from pypts.core.CORE_MESSAGES import CoreToHMIEvent, CoreToHMICommand
from pypts.logger.log import log


def gui_main(core: HMIToCoreInterface, core_to_hmi_queue):
    """Entry point called by launcher"""
    gui = GUI(core, core_to_hmi_queue)
    gui.start()


class GUI:
    def __init__(self, core_interface: HMIToCoreInterface, core_to_hmi_queue):
        self.core = core_interface                # interface for sending to Core
        self.core_to_hmi_queue = core_to_hmi_queue            # queue for receiving from Core
        self.running = True

    def start(self):
        log.info("[gui] Starting module...")
        self.main_loop()
        log.info("[gui] Stopping module...")

    def main_loop(self):
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            sleep(0.01)

    def poll_core(self):
        try:
            event: CoreToHMIEvent = self.core_to_hmi_queue.get(timeout=0)
            self.handle_command(event)
        except Empty:
            pass

    def handle_command(self, event: CoreToHMIEvent):
        print(f"[gui] Received event from core: {event}")

        match event.cmd:
            case CoreToHMICommand.UPDATE_STATUS:
                self.update_status(event.payload.get("text", ""))
            case CoreToHMICommand.STOP:
                self.running = False
            case _:
                print(f"[gui] Unknown event: {event}")

    def update_status(self, text: str):
        print(f"[gui] status update: {text}")

    def do_periodic_tasks(self):
        """Example GUI behavior: periodically request something"""
        # Example: Keep telling Core to start same sequence
