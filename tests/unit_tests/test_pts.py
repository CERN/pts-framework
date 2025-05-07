import pytest
from unittest import mock
from queue import Queue, SimpleQueue
from pypts import recipe
from pathlib import Path
import threading
from pypts.pts import run_pts, PtsApi, DataChannelManager, DataChannel, create_channel, destroy_channel, get_channel


# Mocking the logger to avoid actual logging during tests
@pytest.fixture(autouse=True)
def mock_logger():
    with mock.patch("pypts.pts.logger") as mock_logger:
        yield mock_logger


# Test DataChannelManager functionality
def test_data_channel_manager():
    manager = DataChannelManager()

    # Create a new channel
    channel = manager.create_channel("test_channel")
    assert isinstance(channel, DataChannel)
    assert channel.name == "test_channel"
    assert channel.queue.empty()  # Queue should be empty initially

    # Destroy the channel
    manager.destroy_channel("test_channel")
    assert "test_channel" not in manager.channels

    # Try to get the destroyed channel
    with pytest.raises(KeyError):
        manager.get_channel("test_channel")

    # List available channels
    # Convert dict_keys to list for comparison
    assert list(manager.list_available_channels()) == []


# Test DataChannel functionality
def test_data_channel():
    channel = DataChannel("test_channel")

    # Send data
    channel.send("test_data")
    assert not channel.queue.empty()

    # Receive data
    received_data = channel.receive()
    assert received_data == "test_data"


# Test global functions (create_channel, destroy_channel, get_channel)
def test_global_channel_functions():
    # Mock the DataChannelManager methods
    with mock.patch.object(DataChannelManager, "create_channel") as mock_create_channel, \
            mock.patch.object(DataChannelManager, "destroy_channel") as mock_destroy_channel, \
            mock.patch.object(DataChannelManager, "get_channel") as mock_get_channel:
        # Test create_channel function
        create_channel("new_channel")
        mock_create_channel.assert_called_once_with("new_channel")

        # Test destroy_channel function
        destroy_channel("new_channel")
        mock_destroy_channel.assert_called_once_with("new_channel")

        # Test get_channel function
        get_channel("new_channel")
        mock_get_channel.assert_called_once_with("new_channel")

