# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The interactive shell frontend.

Everything about the protocol - which messages exist, how they are handled, how
shutdown is negotiated - is in HmiClient. This module is the presentation half:
reading a command line and printing what happens.
"""

import threading
import time

from pypts.hmi.hmi_client import HmiClient
from pypts.logger.log import log
from pypts.messages import QueueWrapper
from pypts.messages.common_messages import ModuleError, ResultType, StepOutcome
from pypts.messages.core_hmi_communication import CoreToHmi, HmiToCore, ReportReady
from pypts.messages.run_events import RecipeLoaded

#: Seconds between polls of the CORE inbox, in the background thread.
POLL_INTERVAL_S = 0.05

HELP_TEXT = (
    "Available commands: load_recipe <path>, start_sequence <name>, stop_sequence, "
    "status, exit, help"
)


def cli_main(to_core: QueueWrapper[HmiToCore], from_core: QueueWrapper[CoreToHmi]) -> None:
    """
    Entry point. Unlike the GUI this runs in the launcher's own process, so
    logging is already initialised by the time it is called.
    """
    CLI(to_core, from_core).run()


class CLI(HmiClient):
    """
    An interactive shell on the main thread, with the CORE inbox polled from a
    background thread. The split is what lets a status update print while the
    operator is still deciding what to type.
    """

    def __init__(
        self, to_core: QueueWrapper[HmiToCore], from_core: QueueWrapper[CoreToHmi]
    ) -> None:
        super().__init__(to_core, from_core)
        self.status = "Idle"
        self._lock = threading.Lock()  # guards `status` across the two threads

    # --- Shell ----------------------------------------------------------------

    def run(self) -> None:
        log.debug("CLI module starting.")
        log.info("CLI module started.")
        polling_thread = threading.Thread(target=self._poll_loop, name="cli-poll", daemon=True)
        polling_thread.start()

        try:
            self._command_loop()
        except KeyboardInterrupt:
            print("\nExiting pypts...")
            self.request_shutdown()
        except EOFError:
            # stdin closed - a pipe, a redirect, or Ctrl+D. Treat it as a
            # request to leave rather than letting it escape the shell.
            print("\nInput stream closed, exiting pypts...")
            self.request_shutdown()

        # request_shutdown() only *asks*. CORE stops every module and answers
        # StopHmi, which the polling thread turns into stop(); this waits for
        # that handshake so CORE learns the frontend is gone before the process
        # ends. Bounded, so a wedged CORE cannot hang the exit.
        self.wait_until_stopped()
        polling_thread.join(timeout=1.0)
        log.info("CLI module stopped.")

    def _command_loop(self) -> None:
        """
        Read and dispatch commands until the operator leaves.

        Note that input() blocks: if CORE sends StopHmi while the operator is at
        the prompt, `running` goes False in the polling thread but this loop
        only notices after the next Enter.
        """
        while self.running:
            # One split, so `parts` is either empty, [command] or
            # [command, argument] - the commands below take at most one argument.
            parts = input("pypts> ").strip().split(maxsplit=1)
            if parts:
                command = parts[0].lower()
            else:
                command = ""

            match command:
                case "exit" | "quit" | "stop":
                    print("Shutting down...")
                    self.request_shutdown()
                    return
                case "start_sequence":
                    if len(parts) == 2:
                        self.start_sequence(parts[1])
                    else:
                        print("Usage: start_sequence <sequence_name>")
                case "stop_sequence":
                    # Aborts the run only; plain `stop` above exits the shell.
                    self.stop_sequence()
                case "load_recipe":
                    if len(parts) == 2:
                        self.load_recipe(parts[1])
                    else:
                        print("Usage: load_recipe <recipe_path>")
                case "status":
                    with self._lock:
                        print(f"Current status: {self.status}")
                case "help":
                    print(HELP_TEXT)
                case "":
                    pass
                case other:
                    print(f"Unknown command: {other}. Type 'help' for available commands.")

    def _poll_loop(self) -> None:
        """Drain the CORE inbox and send heartbeats, while the shell blocks on input."""
        while self.running:
            self.poll_core()
            self.do_periodic_tasks()
            time.sleep(POLL_INTERVAL_S)

    # --- Presentation ---------------------------------------------------------

    def show_status(self, text: str) -> None:
        with self._lock:
            self.status = text
        log.debug("Status line: %s", text)
        print(f"Status updated: {text}")

    def show_error(self, error: ModuleError) -> None:
        # CORE has already written this failure to the run log in the
        # operator's words; the CLI's job here is the console, not a second
        # copy of the record - logging_rules.md section 5.
        log.debug("Error received from %s: %s", error.source, error.message)
        print(f"ERROR [{error.source}] {error.message}")

    def show_recipe_loaded(self, event: RecipeLoaded) -> None:
        print(f"Recipe loaded: {event.recipe_name} (version {event.recipe_version})")
        # Name the sequences so the operator knows what start_sequence accepts.
        names = []
        for sequence in event.sequences:
            if sequence.sequence_name == event.main_sequence:
                names.append(f"{sequence.sequence_name} (main)")
            else:
                names.append(sequence.sequence_name)
        print(f"Sequences: {', '.join(names)}")

    def show_run_started(self, recipe_name: str, recipe_description: str) -> None:
        print(f"Running {recipe_name}: {recipe_description}")

    def show_run_finished(self, result: ResultType, outcomes: tuple[StepOutcome, ...]) -> None:
        print(f"Run finished: {result} ({len(outcomes)} steps)")

    def show_sequence_finished(self, sequence_name: str, result: ResultType) -> None:
        print(f"  {sequence_name}: {result}")

    def show_step_finished(self, outcome: StepOutcome) -> None:
        line = f"    {outcome.step_name}: {outcome.result}"
        if outcome.error_info:
            line = f"{line} - {outcome.error_info}"
        print(line)

    def show_report_ready(self, event: ReportReady) -> None:
        log.debug("ReportReady received: %s", event.report_path)
        print(f"Report: {event.report_path}")

    def on_stop(self) -> None:
        print("Goodbye!")
