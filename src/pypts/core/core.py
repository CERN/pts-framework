# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
CORE - the mediator.

Every message in the framework except log records passes through here. CORE owns
the links to the Sequencer and the Report, holds the link to the HMI that the
launcher built, and is the only module that talks to more than one other.

The three handlers below are the whole routing table. Each one ends in
unhandled(), so a message nobody thought about raises instead of being dropped.
"""

import time
from multiprocessing import Process, Queue

from pypts.logger.log import init_logging, log
from pypts.messages import Channel, UnhandledMessage, unhandled
from pypts.messages.common import ErrorSeverity, Heartbeat, ModuleError
from pypts.messages.debug_link import (
    CORE_TO_REPORT,
    CORE_TO_SEQUENCER,
    REPORT_TO_CORE,
    SEQUENCER_TO_CORE,
    InjectMessage,
    InjectTarget,
)
from pypts.messages.hmi_link import (
    CoreToHmi,
    HmiStopped,
    HmiToCore,
    LoadRecipe,
    ModuleErrorReported,
    ShutdownRequested,
    StartSequence,
    StatusChanged,
    StopHmi,
)
from pypts.messages.report_link import (
    CoreToReport,
    ReportExported,
    ReportGenerated,
    ReportStopped,
    ReportToCore,
    StopReport,
)
from pypts.messages.run_events import (
    RunFinished,
    RunStarted,
    SequenceFinished,
    SequenceStarted,
    SerialNumberRequest,
    SerialNumberResponse,
    StepFinished,
    StepStarted,
    UserPromptRequest,
    UserPromptResponse,
)
from pypts.messages.sequencer_link import (
    CoreToSequencer,
    RunSequence,
    SequencerStopped,
    SequencerToCore,
    StopSequencer,
)
from pypts.report.report import report_main
from pypts.sequencer.sequencer import sequencer_main

#: Names CORE knows modules by. They match the `source` field every module puts
#: on its Heartbeat, which is how one handler can serve all three links.
HMI = "hmi"
SEQUENCER = "sequencer"
REPORT = "report"

#: A module is presumed dead if it has not been heard from for this long.
HEARTBEAT_TIMEOUT_S = 5.0


def core_main(
    to_hmi: Channel[CoreToHmi],
    from_hmi: Channel[HmiToCore],
    log_queue,
    tap=None,
    debug_inbox=None,
) -> None:
    """
    Entry point for the launcher. Runs in the Core process.

    Routing log records to the Logger has to happen before anything is logged
    and before the submodules are spawned, so it is the first thing done here.

    Args:
        tap: a ChannelTap under `--mode debug`, None in every normal run. See
            Core.__init__.
        debug_inbox: a Channel[DebugToCore] under `--mode debug`, None otherwise.
    """
    init_logging(log_queue)
    Core(to_hmi, from_hmi, log_queue, tap=tap, debug_inbox=debug_inbox).start()


class Core:
    """
    Mediator and supervisor of the Sequencer and the Report.

    Naming convention for the six channels: `to_x` is what CORE sends to module
    x, `from_x` is what x sends to CORE. CORE builds both halves of its own
    links and hands them to the child, so a module cannot construct a channel to
    anyone it has no business talking to.
    """

    def __init__(
        self,
        to_hmi: Channel[CoreToHmi],
        from_hmi: Channel[HmiToCore],
        log_queue,
        queue_factory=Queue,
        tap=None,
        debug_inbox=None,
    ) -> None:
        """
        Args:
            queue_factory: what to build the submodule queues out of. This is
                the seam the roadmap's thread migration turns: pass queue.Queue
                and the Sequencer and the Report become threads without any
                other change. Tests use it to build a CORE that spawns nothing.
            tap: optional observer put on all four submodule channels, so the
                debug console can see traffic that never leaves this process.
                None in a normal run, and then these channels are exactly what
                they were before.
            debug_inbox: optional Channel[DebugToCore]. Present only under
                `--mode debug`; polled alongside the three real inboxes.
        """
        self.to_hmi = to_hmi
        self.from_hmi = from_hmi

        # Shared with the submodules so every process writes through one Logger.
        self.log_queue = log_queue

        self.tap = tap
        self.debug_inbox = debug_inbox

        # One queue per direction. The Channel type parameter is the union that
        # queue is allowed to carry, and `link` is the name it goes by in the
        # debug trace.
        self.to_sequencer: Channel[CoreToSequencer] = Channel(
            queue_factory(), link=CORE_TO_SEQUENCER, observer=tap
        )
        self.from_sequencer: Channel[SequencerToCore] = Channel(
            queue_factory(), link=SEQUENCER_TO_CORE, observer=tap
        )
        self.to_report: Channel[CoreToReport] = Channel(
            queue_factory(), link=CORE_TO_REPORT, observer=tap
        )
        self.from_report: Channel[ReportToCore] = Channel(
            queue_factory(), link=REPORT_TO_CORE, observer=tap
        )

        self.running = True
        self.shutting_down = False

        # Which modules CORE is still waiting for before it may exit.
        self.module_running = {HMI: True, SEQUENCER: True, REPORT: True}
        self.last_heartbeat = {name: time.time() for name in self.module_running}

        # Which modules have already been reported late. The main loop turns
        # every 10 ms, so without this the timeout below would log the same
        # warning about a hundred times a second for the rest of the run.
        self.heartbeat_lost = {name: False for name in self.module_running}

    # --- Startup --------------------------------------------------------------

    def start(self) -> None:
        log.info("Starting module...")
        self.start_submodules()
        self.main_loop()
        log.info("Stopping module...")

    def start_submodules(self) -> None:
        """
        Spawn the Sequencer and the Report, handing each the two channels it
        needs: its outbox to CORE and its inbox from CORE.
        """
        self.sequencer_process = Process(
            target=sequencer_main,
            name="Sequencer",
            args=(self.from_sequencer, self.to_sequencer, self.log_queue),
        )
        self.sequencer_process.start()

        self.report_process = Process(
            target=report_main,
            name="Report",
            args=(self.from_report, self.to_report, self.log_queue),
        )
        self.report_process.start()

    # --- Main event loop ------------------------------------------------------

    def main_loop(self) -> None:
        log.info("Starting main event loop.")
        while self.running:
            self.poll_all_sources()
            self.do_periodic_tasks()
            self.check_stop_status()
            time.sleep(0.01)

    def poll_all_sources(self) -> None:
        self.poll(self.from_hmi, self.handle_hmi_message)
        self.poll(self.from_sequencer, self.handle_sequencer_message)
        self.poll(self.from_report, self.handle_report_message)
        if self.debug_inbox is not None:
            self.poll(self.debug_inbox, self.handle_debug_message)

    def poll(self, channel, handler) -> None:
        """
        Handle what is waiting on one inbox, surviving anything it contains.

        CORE cannot use @catch_and_report_errors(): it is the module errors are
        reported *to*. A message it cannot handle is logged and dropped, because
        the alternative - letting it escape - takes the mediator down and with
        it every other module's only way of being heard.

        The cost of that guarantee is that one bad message abandons the rest of
        the batch: the exception leaves the receive() generator, and the
        remainder stays queued for the next tick. That is the right trade - they
        are not lost, only delayed - but it is why the try wraps the whole loop
        rather than each message, which would be the alternative.
        """
        try:
            for message in channel.receive():
                handler(message)
        except UnhandledMessage as exc:
            log.error(str(exc))
        except Exception:  # noqa: BLE001 - the mediator must outlive a bad message
            log.exception("Failure while handling a message")

    # --- Routing --------------------------------------------------------------

    def handle_hmi_message(self, message: HmiToCore) -> None:
        log.info(f"Received HMI message: {message}")
        match message:
            case ShutdownRequested():
                self.stop_all_modules()
            case HmiStopped():
                self.module_running[HMI] = False
            case LoadRecipe(recipe_path=recipe_path):
                self.load_recipe(recipe_path)
            case StartSequence(sequence_name=sequence_name):
                self.start_sequence(sequence_name)
            case UserPromptResponse() | SerialNumberResponse():
                # The operator's answer belongs to whoever asked the question.
                self.to_sequencer.send(message)
            case Heartbeat():
                self.note_heartbeat(message)
            case ModuleError():
                # Previously the HMI link had no branch for this at all, so
                # every error a frontend reported was silently discarded.
                self.handle_module_error(message)
            case _:
                unhandled(message)

    def handle_sequencer_message(self, message: SequencerToCore) -> None:
        log.info(f"Received Sequencer message: {message}")
        match message:
            case SequencerStopped():
                self.module_running[SEQUENCER] = False
            case (
                RunStarted()
                | RunFinished()
                | SequenceStarted()
                | SequenceFinished()
                | StepStarted()
                | StepFinished()
            ):
                # Progress is the frontend's business. CORE relays the same
                # object rather than repacking it, so nothing is lost on the way.
                self.to_hmi.send(message)
            case UserPromptRequest() | SerialNumberRequest():
                self.to_hmi.send(message)
            case Heartbeat():
                self.note_heartbeat(message)
            case ModuleError():
                self.handle_module_error(message)
            case _:
                unhandled(message)

    def handle_report_message(self, message: ReportToCore) -> None:
        log.info(f"Received Report message: {message}")
        match message:
            case ReportStopped():
                self.module_running[REPORT] = False
            case ReportGenerated(report_path=path):
                self.to_hmi.send(StatusChanged(f"Report generated: {path}"))
            case ReportExported(report_path=path):
                self.to_hmi.send(StatusChanged(f"Report exported: {path}"))
            case Heartbeat():
                self.note_heartbeat(message)
            case ModuleError():
                self.handle_module_error(message)
            case _:
                unhandled(message)

    def handle_debug_message(self, message: InjectMessage) -> None:
        """
        Do what the debug console asked. Reachable only under `--mode debug`.

        Kept apart from the three real handlers on purpose: this one is not part
        of the product, and grouping it with them would invite product logic to
        start depending on it.
        """
        log.info(f"Received debug message: {message}")
        match message:
            case InjectMessage(target=target, message=payload):
                self.inject(target, payload)
            case _:
                unhandled(message)

    def inject(self, target: InjectTarget, message: object) -> None:
        """
        Put a console-supplied message on one of CORE's links.

        It goes on the real queue, so it is drained, matched and forwarded by
        the same code a genuine message meets - which is the whole reason for
        injecting rather than just drawing the result. An injection into
        SEQUENCER_TO_CORE therefore appears in the trace twice: inbound here,
        and again when this routing table forwards it to the HMI.
        """
        channels = {
            InjectTarget.TO_HMI: self.to_hmi,
            InjectTarget.TO_SEQUENCER: self.to_sequencer,
            InjectTarget.FROM_SEQUENCER: self.from_sequencer,
            InjectTarget.TO_REPORT: self.to_report,
            InjectTarget.FROM_REPORT: self.from_report,
        }
        log.info(f"Injecting {type(message).__name__} on {target.value}")

        if self.tap is None:
            channels[target].send(message)
            return
        # Mark the send, and only this send, as simulated. What CORE does in
        # response is real traffic and is left unmarked.
        with self.tap.marking_injected():
            channels[target].send(message)

    # --- Orchestration --------------------------------------------------------

    def load_recipe(self, recipe_path: str) -> None:
        """
        Load and validate a recipe.

        The recipe layer has not been ported yet, so all CORE can honestly do is
        say so. Once it lands, this answers with RecipeLoaded on success and a
        ModuleError on a validation failure.
        """
        log.warning(f"Cannot load '{recipe_path}': the recipe layer is not ported yet.")
        self.to_hmi.send(StatusChanged(f"Recipe loading is not implemented yet ({recipe_path})"))

    def start_sequence(self, sequence_name: str) -> None:
        """
        Ask the Sequencer to run a sequence.

        The name now reaches the Sequencer, which the old interface could not do:
        its run_sequence() took no arguments, so the operator's choice stopped at
        CORE. Execution itself is still a stub inside the Sequencer.
        """
        log.info(f"Starting sequence '{sequence_name}'.")
        self.to_sequencer.send(RunSequence(sequence_name))

    def handle_module_error(self, error: ModuleError) -> None:
        """
        Record a module failure and, unless it is only a warning, show it to the
        operator. CORE deciding what reaches the frontend is what keeps the
        runtime log readable during a long run.
        """
        log.error(f"{error.source}: {error.message}\n{error.traceback or ''}")
        if error.severity is not ErrorSeverity.WARNING:
            self.to_hmi.send(ModuleErrorReported(error))

    def note_heartbeat(self, beat: Heartbeat) -> None:
        if beat.source not in self.last_heartbeat:
            log.warning(f"Heartbeat from an unknown module: {beat.source}")
            return

        # A module that was reported late and is now answering again is worth
        # one line, so the log says the outage ended instead of just going quiet.
        if self.heartbeat_lost[beat.source]:
            log.info(f"Module is responding again: {beat.source}")
            self.heartbeat_lost[beat.source] = False

        self.last_heartbeat[beat.source] = beat.timestamp

    # --- Background tasks -----------------------------------------------------

    def do_periodic_tasks(self) -> None:
        """
        Watch the heartbeats.

        Only modules still expected to be running are checked, so a module that
        has already reported itself stopped does not produce a timeout warning
        for the rest of the run. What CORE should *do* about a timeout - restart
        the module, abort the run, tell the operator - is still an open decision
        recorded in the roadmap; for now it warns.

        One warning per outage, not one per tick. The loop calling this turns
        every 10 ms and a timed-out module stays timed out, so logging on every
        pass would bury the ModuleError explaining the crash under thousands of
        copies of the same sentence. note_heartbeat() clears the flag when the
        module answers again, so a second outage is reported afresh.
        """
        now = time.time()
        for name, last_seen in self.last_heartbeat.items():
            if not self.module_running[name]:
                continue
            if now - last_seen > HEARTBEAT_TIMEOUT_S and not self.heartbeat_lost[name]:
                log.warning(f"Heartbeat timeout for module: {name}")
                self.heartbeat_lost[name] = True

    # --- Shutdown -------------------------------------------------------------

    def stop_all_modules(self) -> None:
        """
        Ask every module to stop. Each answers with its own *Stopped event.

        Idempotent, because shutdown is legitimately requested twice: the
        frontend asks when the operator leaves, and the launcher asks again once
        it has joined the UI process - it cannot assume the frontend got the
        chance. Without the guard every module is told to stop twice.
        """
        if self.shutting_down:
            return
        self.shutting_down = True

        log.info("Shutdown requested, stopping all modules.")
        self.to_report.send(StopReport())
        self.to_sequencer.send(StopSequencer())
        self.to_hmi.send(StopHmi())

    def check_stop_status(self) -> None:
        """
        CORE exits once every module has reported itself stopped.

        A module that dies without reporting leaves CORE waiting; the launcher's
        join timeout is the backstop. Turning that into a heartbeat-driven
        decision is the open policy question noted in do_periodic_tasks().
        """
        if not any(self.module_running.values()):
            log.info("All modules stopped cleanly")
            self.running = False
