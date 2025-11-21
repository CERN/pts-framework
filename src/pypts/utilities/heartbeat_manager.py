import time
import logging
from queue import Empty

log = logging.getLogger(__name__)


def poll_queue_nonblocking(queue, handler):
    """
    Attempts to get an event from the queue without blocking.
    If an event is retrieved, the provided handler function is called with the event.
    If the queue is empty, the function silently returns without blocking.

    Args:
        queue (queue.Queue): The queue to poll for events.
        handler (callable): A function to process an event if retrieved.
    """
    try:
        # Try to get an event without blocking; raises Empty if queue is empty
        event = queue.get_nowait()
        if event:
            handler(event)
    except Empty:
        # No events in the queue, simply pass
        pass


class HeartbeatManager:
    """
    Manages sending periodic heartbeat signals at a specified interval.

    Attributes:
        send_heartbeat (callable): Function to call to send the heartbeat. Receives the current Unix time.
        interval (float): Minimum interval in seconds between heartbeats.
        last_sent (float): Timestamp when the last heartbeat was sent.
    """
    def __init__(self, send_heartbeat_func, interval=1.0):
        self.send_heartbeat = send_heartbeat_func
        self.interval = interval
        self.last_sent = 0

    def tick(self):
        now = time.time()
        if now - self.last_sent > self.interval:
            self.send_heartbeat(now)
            self.last_sent = now