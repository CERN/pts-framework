# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Test code for stepgraph_demo.yml - two sine waves pushed into live streams.

A test function registers a stream by name and pushes samples; the GUI draws
the stream live in the right column while a step that names it with `graph:`
runs. The samples are also written to <run folder>/streams/<name>.csv.

    run_sine()    pushes "sine" for `duration_s` seconds, then returns - the
                  step lasts as long as the push.
    start_sine()  starts a thread that pushes "bg_sine" and returns at once -
                  a later step watches it with `graph: bg_sine`.
"""

import math
import threading
import time

from pypts.stream_handler import register_stream

#: Samples per second, and samples per push call.
SAMPLE_RATE_HZ = 100
BATCH_SIZE = 10


def _push_sine(name: str, duration_s: float) -> None:
    """Register `name`, push a 1 Hz sine in batches for `duration_s`, close."""
    stream = register_stream(name, unit="V")
    total_samples = int(duration_s * SAMPLE_RATE_HZ)
    batch_period_s = BATCH_SIZE / SAMPLE_RATE_HZ
    try:
        for first in range(0, total_samples, BATCH_SIZE):
            x_values = [(first + i) / SAMPLE_RATE_HZ for i in range(BATCH_SIZE)]
            y_values = [math.sin(2 * math.pi * x) for x in x_values]
            stream.push(x_values, y_values)
            time.sleep(batch_period_s)
    finally:
        stream.close()


def run_sine(duration_s: float = 10) -> None:
    """Push the "sine" stream; returns when the push is done."""
    _push_sine("sine", float(duration_s))


def start_sine(duration_s: float = 10) -> None:
    """Start pushing the "bg_sine" stream on a daemon thread and return at once."""
    thread = threading.Thread(
        target=_push_sine, args=("bg_sine", float(duration_s)), name="bg_sine", daemon=True
    )
    thread.start()
