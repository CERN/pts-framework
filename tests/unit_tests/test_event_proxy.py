# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import pytest
from unittest.mock import MagicMock
from queue import SimpleQueue
from PySide6.QtCore import QCoreApplication
from pypts.event_proxy import RecipeEventProxy
from pypts import recipe
import uuid

# todo - make unit test for post_run_recipe_signal
# todo - make unit test for pre_run_sequence_signal
# todo - make unit test for get_serial_number_signal
# todo - make unit test for post_run_step_signal
# todo - make unit test for pre_run_step_signal
# todo - make unit test for post_load_recipe_signal
# todo - make unit test for post_run_sequence_signal

@pytest.fixture
def event_q():
    return SimpleQueue()

@pytest.fixture
def proxy(event_q):
    # Use existing Qt application instance or create one if none exists
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    
    proxy = RecipeEventProxy(event_q)

    # Mock all signals
    for attr in dir(proxy):
        if attr.endswith('_signal'):
            setattr(proxy, attr, MagicMock())
    return proxy

def test_pre_run_recipe_signal(proxy, event_q):
    event_q.put(("pre_run_recipe", ("My Recipe", "Does something")))
    proxy.run_once()

    proxy.pre_run_recipe_signal.emit.assert_called_once_with({
        "recipe_name": "My Recipe",
        "recipe_description": "Does something"
    })

def test_user_interact_signal(proxy, event_q):
    q = SimpleQueue()
    event_q.put(("user_interact", (q, "Choose wisely", "/some/image.png", ["Yes", "No"])))
    proxy.run_once()

    proxy.user_interact_signal.emit.assert_called_once()
    emitted = proxy.user_interact_signal.emit.call_args[0][0]
    assert emitted["message"] == "Choose wisely"
    assert emitted["options"] == ["Yes", "No"]

def test_unsupported_event_logs_warning(proxy, event_q, caplog):
    '''
    Testing if unsupported signal type is properly handled
    '''

    event_q.put(("non_existing_event", ("some", "data")))
    with caplog.at_level("WARNING"):
        proxy.run_once()
        assert "No dictionary created for event: non_existing_event" in caplog.text
