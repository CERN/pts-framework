# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import threading
import time
from pypts.core.HMI_to_core_interface import HMIToCoreInterface
from pypts.core.CORE_MESSAGES import CoreToHMIEvent, CoreToHMICommand
from pypts.logger.log import log
from pypts.utilities.error_handling import catch_and_report_errors
from pypts.utilities.heartbeat_manager import HeartbeatManager
from pypts.utilities.common import poll_queue


def cli_main(hmiToCoreInterface: HMIToCoreInterface, core_to_hmi_queue):
    # Start the CLI interface (interactive shell)
    cli = CLI(hmiToCoreInterface, core_to_hmi_queue)
    cli.run()


class CLI:
    """
    Command Line Interface module connecting to Core via the same interface as GUI.
    Provides an interactive shell to send commands and view statuses.
    """

    def __init__(self, hmiToCoreInterface: HMIToCoreInterface, core_to_hmi_queue):
        # Initialize CLI with communication interfaces
        self.core = hmiToCoreInterface
        self.core_to_hmi_queue = core_to_hmi_queue
        # Heartbeat manager for keep-alive signals
        self.heartbeat_manager = HeartbeatManager(self.core.send_heartbeat)
        self.running = True  # control framework for the main loop
        self.status = "Idle"  # current status text
        self._lock = threading.Lock()  # lock to synchronize status access

        log.info("Starting module...")  # log startup

    @catch_and_report_errors()
    def poll_core(self):
        # Poll the core queue for new events
        poll_queue(self.core_to_hmi_queue, self.handle_core_event)

    @catch_and_report_errors()
    def handle_core_event(self, event: CoreToHMIEvent):
        # Handle incoming events from core
        log.info(f"Received core event: {event}")
        match event.cmd:
            case CoreToHMICommand.UPDATE_STATUS:
                self.update_status(event.payload.get("text", ""))
            case CoreToHMICommand.STOP:
                # Core sent stop command, so update running state
                log.info("Received STOP command from Core")
                self.running = False
            case _:
                # Log unknown events
                log.error(f"Unknown event: {event}")

    def update_status(self, text: str):
        # Thread-safe update of status text
        with self._lock:
            self.status = text
        log.info(f"status update: {text}")
        print(f"Status updated: {text}")  # print to console

    def do_periodic_tasks(self):
        # Perform periodic background tasks
        self.heartbeat_manager.tick()

    def run(self):
        """
        Runs an interactive CLI loop in main thread and polls Core asynchronously.
        """
        log.info("Starting CLI module...")

        # Start polling thread for core queue
        polling_thread = threading.Thread(target=self._poll_loop, daemon=True)
        polling_thread.start()

        try:
            while self.running:
                # Command input from user
                cmd = input("pypts> ").strip().lower()
                # Split command and args
                parts = cmd.split(maxsplit=1)
                # Use match-case on the command keyword
                match parts[0] if parts else "":
                    case "exit" | "quit" | "stop":
                        self.stop()
                    case "start_sequence":
                        # Command: start_sequence <name>
                        if len(parts) == 2:
                            self.core.start_sequence(parts[1])
                        else:
                            print("Usage: start_sequence <sequence_name>")
                    case "load_recipe":
                        # Command: load_recipe <name>
                        if len(parts) == 2:
                            self.core.load_recipe(parts[1])
                        else:
                            print("Usage: load_recipe <recipe_name>")
                    case "status":
                        # Print current status
                        print(f"Current status: {self.status}")
                    case "help":
                        # Help menu
                        print("Available commands: start_sequence <name>, load_recipe <name>, exit, help")
                    case "":
                        # Empty input, do nothing
                        pass
                    case other:
                        # Unknown command
                        print(f"Unknown command: {other}. Type 'help' for available commands.")
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            print("\nExiting pypts...")
            self.stop()

        # Wait for polling thread to finish before exit
        polling_thread.join()
        log.info("CLI module stopped.")

    def _poll_loop(self):
        """
        Periodically poll the core queue and perform periodic tasks.
        Runs in a separate thread, while the main thread handles user input.
        """
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(0.05)

    @catch_and_report_errors()
    def stop(self):
        # Graceful shutdown of CLI
        log.info("Stopping module")
        self.running = False
        self.core.stop()  # send stop command to core
        print("STOP request sent, aborting...\nGoodbye!")
