import time
import logging
from queue import Empty

log = logging.getLogger(__name__)

def poll_queue_nonblocking(queue, handler):
    try:
        event = queue.get_nowait()
        if event:
            handler(event)
    except Empty:
        pass

class HeartbeatManager:
    def __init__(self, send_heartbeat_func, interval=1.0):
        self.send_heartbeat = send_heartbeat_func
        self.interval = interval
        self.last_sent = 0

    def tick(self):
        now = time.time()
        if now - self.last_sent > self.interval:
            self.send_heartbeat(now)
            self.last_sent = now