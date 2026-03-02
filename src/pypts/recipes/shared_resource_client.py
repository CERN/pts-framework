# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# resource_client.py
import socket
import json

class RemoteDevice:
    def __init__(self, host="127.0.0.1", port=5005):
        self.host = host
        self.port = port

    def call(self, method, *args, **kwargs):
        req = {"method": method, "args": args, "kwargs": kwargs}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.host, self.port))
            s.sendall(json.dumps(req).encode())
            resp = json.loads(s.recv(4096).decode())
            return resp

    # Convenience wrappers
    def increment(self, n): return self.call("increment", n)
    def get_value(self): return self.call("get_value")
