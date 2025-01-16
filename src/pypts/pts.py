from queue import Queue, SimpleQueue
import logging
import recipe
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# This value starts False. It is used to know whether a PTS has been configured to run or not. This way, when we import
# pts into step routines, it will be able to know whether it's running as part of PTS or standalone and provide
# appropriate behaviors. It gets set to True when a PTS recipe starts.
_pts_context = False



@dataclass
class PtsApi:
    input_queue: Queue
    event_queue: SimpleQueue
    recipe_queue: SimpleQueue
    

def run_pts(recipe_file, sequence_name="Main"):
    input_queue = Queue()
    event_queue = SimpleQueue()
    report_queue = SimpleQueue()
    global _pts_context
    _pts_context = True
    api = PtsApi(input_queue, event_queue, report_queue)
    runtime = recipe.Runtime(event_queue, report_queue)
    recipe_to_run = recipe.Recipe(recipe_file)
    runtime.send_event("post_load_recipe", recipe_to_run)
    threading.Thread(target=recipe_to_run.run, kwargs={"runtime": runtime, "sequence_name": sequence_name}, daemon=True).start()
    # threading.Thread(target=recipe.parse_q_input, args=[q_in], daemon=True).start()

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

