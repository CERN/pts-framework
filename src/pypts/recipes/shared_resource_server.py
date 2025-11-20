# This is an example of how to implement a class that will be shared across the execution.
# Generally, framework will at some point provide an instance of the shared resource handler (hardware layer)
# But at this point, anyone is allowed to use bare-bone python code

# Example shows how to implement a resource handler in a thread
# resource_server.py
# resource_server.py
import socket
import threading
import json

class Device:
    def __init__(self):
        self.value = 0

    def increment(self, n):
        self.value += n
        return self.value

    def get_value(self):
        return self.value


class ResourceServer:
    def __init__(self, host="127.0.0.1", port=5005):
        self.host = host
        self.port = port
        self.device = Device()
        self._stop_event = threading.Event()

    def handle_client(self, conn):
        with conn:
            data = conn.recv(4096).decode()
            req = json.loads(data)
            method = getattr(self.device, req["method"])
            result = method(*req.get("args", []), **req.get("kwargs", {}))
            conn.sendall(json.dumps(result).encode())

    def serve(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen()
            while not self._stop_event.is_set():
                s.settimeout(0.5)
                try:
                    conn, _ = s.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self.handle_client, args=(conn,), daemon=True).start()

    def start(self):
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop_event.set()
        self.thread.join()
