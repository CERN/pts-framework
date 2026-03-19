# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for pypts.pts — covers DataChannel, DataChannelManager,
global channel functions, PtsApi, command_handler_loop, and run_pts."""

import pytest
import threading
from queue import Queue, SimpleQueue
from unittest import mock
from unittest.mock import MagicMock, patch
from pypts import recipe
from pypts.pts import (
    run_pts,
    PtsApi,
    DataChannelManager,
    DataChannel,
    create_channel,
    destroy_channel,
    get_channel,
    command_handler_loop,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def mock_logger():
    """Suppress actual logging output during tests."""
    with mock.patch("pypts.pts.logger") as mock_logger:
        yield mock_logger


# ============================================================
# DataChannel
# ============================================================

class TestDataChannel:
    def test_send_and_receive(self):
        """Verify basic send/receive on a DataChannel."""
        channel = DataChannel("test_channel")
        channel.send("test_data")
        assert not channel.queue.empty()
        assert channel.receive() == "test_data"

    def test_fifo_ordering(self):
        """Verify that messages are received in FIFO order."""
        ch = DataChannel("ch1")
        ch.send("a")
        ch.send("b")
        assert ch.receive() == "a"
        assert ch.receive() == "b"

    def test_name_attribute(self):
        """Verify the channel exposes its name."""
        ch = DataChannel("my_channel")
        assert ch.name == "my_channel"

    def test_send_various_types(self):
        """Verify that different Python types (int, dict, list) can be sent and received."""
        ch = DataChannel("ch")
        ch.send(42)
        ch.send({"key": "val"})
        ch.send([1, 2, 3])
        assert ch.receive() == 42
        assert ch.receive() == {"key": "val"}
        assert ch.receive() == [1, 2, 3]


# ============================================================
# DataChannelManager
# ============================================================

class TestDataChannelManager:
    def test_create_and_get(self):
        """Verify that a created channel can be retrieved by name."""
        mgr = DataChannelManager()
        ch = mgr.create_channel("test")
        assert isinstance(ch, DataChannel)
        assert ch.name == "test"
        assert mgr.get_channel("test") is ch

    def test_destroy_channel(self):
        """Verify that destroying a channel removes it and subsequent get raises KeyError."""
        mgr = DataChannelManager()
        mgr.create_channel("test_channel")
        mgr.destroy_channel("test_channel")
        assert "test_channel" not in mgr.channels
        with pytest.raises(KeyError):
            mgr.get_channel("test_channel")

    def test_list_channels(self):
        """Verify listing returns all created channel names."""
        mgr = DataChannelManager()
        mgr.create_channel("a")
        mgr.create_channel("b")
        names = list(mgr.list_available_channels())
        assert "a" in names
        assert "b" in names

    def test_list_empty(self):
        """Verify listing on a fresh manager returns an empty list."""
        mgr = DataChannelManager()
        assert list(mgr.list_available_channels()) == []

    def test_multiple_channels_independent(self):
        """Verify that data sent to one channel is not received on another."""
        mgr = DataChannelManager()
        ch1 = mgr.create_channel("ch1")
        ch2 = mgr.create_channel("ch2")
        ch1.send("data1")
        ch2.send("data2")
        assert ch1.receive() == "data1"
        assert ch2.receive() == "data2"


# ============================================================
# Global channel functions
# ============================================================

class TestGlobalChannelFunctions:
    def test_delegates_to_manager(self):
        """Verify that create/destroy/get_channel delegate to the DataChannelManager singleton."""
        with mock.patch.object(DataChannelManager, "create_channel") as mock_create, \
                mock.patch.object(DataChannelManager, "destroy_channel") as mock_destroy, \
                mock.patch.object(DataChannelManager, "get_channel") as mock_get:
            create_channel("new_channel")
            mock_create.assert_called_once_with("new_channel")

            destroy_channel("new_channel")
            mock_destroy.assert_called_once_with("new_channel")

            get_channel("new_channel")
            mock_get.assert_called_once_with("new_channel")


# ============================================================
# PtsApi
# ============================================================

class TestPtsApi:
    def test_has_required_queues(self):
        """Verify that PtsApi stores all three queues (input, event, recipe)."""
        api = PtsApi(
            input_queue=Queue(),
            event_queue=SimpleQueue(),
            recipe_queue=SimpleQueue(),
        )
        assert api.input_queue is not None
        assert api.event_queue is not None
        assert api.recipe_queue is not None


# ============================================================
# command_handler_loop
# ============================================================

class TestCommandHandlerLoop:
    def test_exits_on_none(self):
        """Verify that sending None cleanly exits the loop."""
        cmd_q = Queue()
        report_q = SimpleQueue()
        event_q = SimpleQueue()
        cmd_q.put(None)

        t = threading.Thread(
            target=command_handler_loop,
            args=(cmd_q, report_q, event_q),
            daemon=True,
        )
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "command_handler_loop did not exit on None"

    def test_ignores_non_tuple_commands(self):
        """Verify that non-tuple commands are skipped without crashing."""
        cmd_q = Queue()
        report_q = SimpleQueue()
        event_q = SimpleQueue()
        cmd_q.put("not a tuple")
        cmd_q.put(None)  # Exit signal

        t = threading.Thread(
            target=command_handler_loop,
            args=(cmd_q, report_q, event_q),
            daemon=True,
        )
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()

    @patch("pypts.pts.recipe.Recipe")
    @patch("pypts.pts.recipe.Runtime")
    def test_load_command_creates_recipe(self, MockRuntime, MockRecipe):
        """Verify that the LOAD command instantiates Recipe and Runtime."""
        mock_recipe_instance = MagicMock()
        mock_recipe_instance.name = "Test"
        mock_recipe_instance.version = "1.0"
        MockRecipe.return_value = mock_recipe_instance

        mock_runtime_instance = MagicMock()
        MockRuntime.return_value = mock_runtime_instance

        cmd_q = Queue()
        report_q = SimpleQueue()
        event_q = SimpleQueue()
        cmd_q.put(("LOAD", "fake_recipe.yaml"))
        cmd_q.put(None)

        t = threading.Thread(
            target=command_handler_loop,
            args=(cmd_q, report_q, event_q),
            daemon=True,
        )
        t.start()
        t.join(timeout=5)

        MockRecipe.assert_called_once_with("fake_recipe.yaml")
        mock_runtime_instance.send_event.assert_called_once()

    def test_exit_command_breaks_loop(self):
        """Verify that the EXIT command terminates the handler loop."""
        cmd_q = Queue()
        report_q = SimpleQueue()
        event_q = SimpleQueue()
        cmd_q.put(("EXIT",))

        t = threading.Thread(
            target=command_handler_loop,
            args=(cmd_q, report_q, event_q),
            daemon=True,
        )
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()


# ============================================================
# run_pts
# ============================================================

class TestRunPts:
    @patch("pypts.pts.command_handler_loop")
    def test_returns_api_with_queues(self, mock_handler):
        """Verify that run_pts returns a PtsApi with properly typed queues."""
        api = run_pts()
        assert isinstance(api, PtsApi)
        assert isinstance(api.input_queue, Queue)
        assert isinstance(api.event_queue, SimpleQueue)
        assert isinstance(api.recipe_queue, SimpleQueue)
