# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

from queue import Queue, SimpleQueue
import logging, time
from pypts import recipe
import threading
from dataclasses import dataclass
from pypts.report import report_listener, STOP_LISTENER, LISTENER_RUNNING
from pypts.recipe import Runtime, runtime_bridge
from pathlib import Path
import importlib.metadata

logger = logging.getLogger(__name__)

# This value starts False. It is used to know whether a PTS has been configured to run or not. This way, when we import
# pts into step routines, it will be able to know whether it's running as part of PTS or standalone and provide
# appropriate behaviors. It gets set to True when a PTS recipe starts.
_pts_context = False

current_run_thread = None
current_runtime = None


@dataclass
class PtsApi:
    input_queue: Queue
    event_queue: SimpleQueue
    recipe_queue: SimpleQueue
    
    """
    Starts a PTS recipe running in a separate thread and returns an API object to interact with it.
    Also starts a background thread (`report_listener`) to generate a CSV report (`report.csv`)
    incrementally in the `./pts_reports/` directory relative to the execution path.

    Args:
        recipe_file (str): Path to the YAML recipe file to run
        sequence_name (str, optional): Name of the sequence in the recipe to run. Defaults to "Main".

    Returns:
        PtsApi: An object containing queues for interacting with the running recipe:
            - input_queue: Queue for sending commands to the recipe
            - event_queue: Queue for receiving events from the recipe
            - recipe_queue: Queue for receiving recipe execution reports
    """

def run_pts(sequence_name: str = "Main") -> PtsApi:
    input_queue = Queue()
    event_queue = SimpleQueue()
    report_queue = SimpleQueue()
    global _pts_context
    _pts_context = True
    api = PtsApi(input_queue, event_queue, report_queue)

    command_thread = threading.Thread(target=command_handler_loop, args=(api.input_queue, report_queue,event_queue), daemon=True)
    command_thread.start()

    return api


class DataChannelManager:
    def __init__(self):
        self.channels = dict()
    
    def create_channel(self, name):
        channel = DataChannel(name)
        self.channels[name] = channel
        return channel
    
    def destroy_channel(self, name):
        del self.channels[name]

    def get_channel(self, name):
        return self.channels[name]
    
    def list_available_channels(self):
        return self.channels.keys()


class DataChannel:
    def __init__(self, name):
        self.name = name
        self.queue = SimpleQueue()

    def send(self, data):
        self.queue.put(data)

    def receive(self):
        return self.queue.get()
    

_channel_manager = DataChannelManager()

def create_channel(name):
    return _channel_manager.create_channel(name)

def destroy_channel(name):
    _channel_manager.destroy_channel(name)

def get_channel(name):
    return _channel_manager.get_channel(name)


def command_handler_loop(queue, report_queue, event_queue):
    # Define output directory for reports
    report_output_dir = Path("./pts_reports")
    report_output_dir.mkdir(parents=True, exist_ok=True)

    recipe_to_run = None
    recipe_file = None
    runtime = None
    while not report_queue.empty():
        try:
            report_queue.get_nowait()
        except Exception:
            break
    while True:
        try:
            command = queue.get()
            if command is None:
                break

            if not isinstance(command, tuple):
                continue

            cmd = command[0]
            if cmd == "LOAD":
                global current_run_thread, current_runtime
                recipe_file = command[1]
                
                try:
                    logger.info(f"Loading recipe from: {recipe_file}")

                    # Set up queues and runtime
                    runtime = recipe.Runtime(event_queue, report_queue)
                    try:
                        runtime.pypts_version = importlib.metadata.version('pts-framework')
                        logger.info(f"pypts version: {runtime.pypts_version}")
                    except importlib.metadata.PackageNotFoundError:
                        runtime.pypts_version = "unknown"
                        logger.warning("Could not determine pypts version. Package not found by importlib.metadata.")

                    # Create the recipe with default file_loader and event_sender
                    try:
                        recipe_to_run = recipe.Recipe(recipe_file)
                        logger.debug(f"Recipe created successfully. Name: {getattr(recipe_to_run, 'name', 'MISSING')}, Version: {getattr(recipe_to_run, 'version', 'MISSING')}")
                        logger.debug(f"Recipe object type: {type(recipe_to_run)}")
                        
                        # Validate recipe object before sending event
                        if not hasattr(recipe_to_run, 'name'):
                            logger.error("Recipe object missing 'name' attribute")
                            raise AttributeError("Recipe object missing 'name' attribute")
                        if not hasattr(recipe_to_run, 'version'):
                            logger.error("Recipe object missing 'version' attribute")
                            raise AttributeError("Recipe object missing 'version' attribute")
                            
                    except Exception as e:
                        logger.error(f"Failed to create recipe from {recipe_file}: {e}", exc_info=True)
                        raise
                    
                    # Send event using runtime's send_event method
                    logger.debug(f"Sending post_load_recipe event with recipe: {recipe_to_run}")
                    runtime.send_event("post_load_recipe", recipe_to_run)

                except Exception as e:
                    logger.error(f"Failed to load recipe: {e}", exc_info=True)

            if cmd == "START":
                global LISTENER_RUNNING
                while not report_queue.empty():
                    try:
                        report_queue.get_nowait()
                    except Exception:
                        break

                if current_run_thread and current_run_thread.is_alive():
                    logger.warning("Recipe thread already running. Start command ignored.")
                else:
                    #added here so every time a new runtime thread is made, so is a new report thread.
                    LISTENER_RUNNING = False
                    # Start the recipe in a new thread
                    current_run_thread = threading.Thread(
                        target=recipe_to_run.run,
                        kwargs={
                            "runtime": runtime,
                            "sequence_name": "Main"
                        },
                        daemon=True
                    )
                    current_run_thread.start()
                    current_runtime = runtime  # save reference to stop later
                    logger.info("Recipe execution thread started.")

                    if not LISTENER_RUNNING:
                        # Start the report listener thread
                        #Moved to here so it is not initialized only once during setup
                        threading.Thread(
                                target=report_listener,
                                args=(report_queue, str(report_output_dir)),
                                daemon=True
                            ).start()
                        logger.info(f"Report listener started. Output directory: {report_output_dir.resolve()}")
                        LISTENER_RUNNING = True
                    else:
                        logger.debug("Report listener already running.")

                runtime_bridge.start_signal.emit()
            elif cmd == "STOP":
                report_queue.put(STOP_LISTENER)
                logger.info("STOP command received. Sent STOP_LISTENER to report queue.")
                runtime_bridge.stop_signal.emit()
                LISTENER_RUNNING = False
            elif cmd == "EXIT":
                runtime_bridge.stop_signal.emit()
                break
        except Exception as e:
            logger.error(f"Command handler failed: {e}", exc_info=True)
