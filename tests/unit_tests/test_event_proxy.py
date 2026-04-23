# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Tests for RecipeEventProxy — covers all signal types, user interaction,
unsupported events, and stop/sentinel behaviour."""

import pytest
import uuid
from unittest.mock import MagicMock, patch
from queue import SimpleQueue
from PySide6.QtCore import QCoreApplication
from pypts.event_proxy import RecipeEventProxy
from pypts import recipe


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def event_q():
    """Create a fresh SimpleQueue for proxy events."""
    return SimpleQueue()


@pytest.fixture
def proxy(event_q):
    """Create a RecipeEventProxy with all signals mocked."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])

    proxy = RecipeEventProxy(event_q)

    # Mock all signals to capture emit calls
    for attr in dir(proxy):
        if attr.endswith('_signal'):
            setattr(proxy, attr, MagicMock())
    return proxy


# ============================================================
# pre_run_recipe_signal
# ============================================================

def test_pre_run_recipe_signal(proxy, event_q):
    """Verify that a 'pre_run_recipe' event emits the signal with recipe name and description."""
    event_q.put(("pre_run_recipe", ("My Recipe", "Does something")))
    proxy.run_once()

    proxy.pre_run_recipe_signal.emit.assert_called_once_with({
        "recipe_name": "My Recipe",
        "recipe_description": "Does something"
    })


# ============================================================
# post_run_recipe_signal
# ============================================================

class TestPostRunRecipeSignal:
    def test_emits_results(self, proxy, event_q):
        """Verify that 'post_run_recipe' emits the signal with the results list."""
        mock_results = [MagicMock(), MagicMock()]
        event_q.put(("post_run_recipe", (mock_results,)))
        proxy.run_once()

        proxy.post_run_recipe_signal.emit.assert_called_once_with(
            {"results": mock_results}
        )


# ============================================================
# pre_run_sequence_signal
# ============================================================

class TestPreRunSequenceSignal:
    def test_emits_sequence(self, proxy, event_q):
        """Verify that 'pre_run_sequence' emits the signal with the sequence object."""
        mock_seq = MagicMock()
        event_q.put(("pre_run_sequence", (mock_seq,)))
        proxy.run_once()

        proxy.pre_run_sequence_signal.emit.assert_called_once_with(
            {"sequence": mock_seq}
        )


# ============================================================
# get_serial_number_signal
# ============================================================

class TestGetSerialNumberSignal:
    def test_emits_response_queue(self, proxy, event_q):
        """Verify that 'get_serial_number' emits the signal with a response queue."""
        response_q = SimpleQueue()
        event_q.put(("get_serial_number", (response_q,)))
        proxy.run_once()

        proxy.get_serial_number_signal.emit.assert_called_once_with(
            {"response_q": response_q}
        )


# ============================================================
# post_run_step_signal
# ============================================================

class TestPostRunStepSignal:
    def test_emits_for_non_sequence_step(self, proxy, event_q):
        """Verify that 'post_run_step' emits step UUID, status text and colour for regular steps."""
        mock_step_result = MagicMock()
        mock_step_result.step = MagicMock()  # Not a SequenceStep
        mock_step_result.step.id = uuid.uuid4()
        mock_step_result.get_result.return_value = recipe.ResultType.PASS

        event_q.put(("post_run_step", (mock_step_result,)))
        proxy.run_once()

        proxy.post_run_step_signal.emit.assert_called_once()
        emitted = proxy.post_run_step_signal.emit.call_args[0][0]
        assert emitted["step_uuid"] == mock_step_result.step.id
        assert emitted["status_text"] == "PASS"
        assert "status_color" in emitted

    def test_ignores_sequence_step(self, proxy, event_q):
        """Verify that 'post_run_step' does NOT emit for SequenceStep instances."""
        mock_step_result = MagicMock()
        mock_step_result.step = MagicMock(spec=recipe.SequenceStep)

        event_q.put(("post_run_step", (mock_step_result,)))
        proxy.run_once()

        proxy.post_run_step_signal.emit.assert_not_called()


# ============================================================
# pre_run_step_signal
# ============================================================

class TestPreRunStepSignal:
    def test_emits_for_non_sequence_step(self, proxy, event_q):
        """Verify that 'pre_run_step' emits step UUID and name for regular steps."""
        mock_step = MagicMock()
        mock_step.id = uuid.uuid4()
        mock_step.name = "TestStep"

        event_q.put(("pre_run_step", (mock_step,)))
        proxy.run_once()

        proxy.pre_run_step_signal.emit.assert_called_once()
        emitted = proxy.pre_run_step_signal.emit.call_args[0][0]
        assert emitted["step_uuid"] == mock_step.id
        assert emitted["step_name"] == "TestStep"

    def test_ignores_sequence_step(self, proxy, event_q):
        """Verify that 'pre_run_step' does NOT emit for SequenceStep instances."""
        mock_step = MagicMock(spec=recipe.SequenceStep)
        event_q.put(("pre_run_step", (mock_step,)))
        proxy.run_once()

        proxy.pre_run_step_signal.emit.assert_not_called()


# ============================================================
# post_load_recipe_signal
# ============================================================

class TestPostLoadRecipeSignal:
    def test_emits_name_and_version(self, proxy, event_q):
        """Verify that 'post_load_recipe' emits recipe name and version."""
        mock_recipe = MagicMock()
        mock_recipe.name = "MyRecipe"
        mock_recipe.version = "2.0"

        event_q.put(("post_load_recipe", (mock_recipe,)))
        proxy.run_once()

        proxy.post_load_recipe_signal.emit.assert_called_once_with({
            "recipe_name": "MyRecipe",
            "recipe_version": "2.0",
        })

    def test_none_recipe_does_not_emit(self, proxy, event_q):
        """Verify that 'post_load_recipe' with None recipe data does not emit."""
        event_q.put(("post_load_recipe", (None,)))
        proxy.run_once()
        proxy.post_load_recipe_signal.emit.assert_not_called()

    def test_empty_data_does_not_emit(self, proxy, event_q):
        """Verify that 'post_load_recipe' with empty tuple data does not emit."""
        event_q.put(("post_load_recipe", ()))
        proxy.run_once()
        proxy.post_load_recipe_signal.emit.assert_not_called()


# ============================================================
# post_run_sequence_signal
# ============================================================

class TestPostRunSequenceSignal:
    def test_emits_name_and_result(self, proxy, event_q):
        """Verify that 'post_run_sequence' emits sequence name and result string."""
        mock_seq = MagicMock()
        mock_seq.name = "Main"
        mock_result = recipe.ResultType.PASS

        event_q.put(("post_run_sequence", (mock_seq, mock_result)))
        proxy.run_once()

        proxy.post_run_sequence_signal.emit.assert_called_once_with({
            "sequence_name": "Main",
            "sequence_result": "PASS",
        })


# ============================================================
# user_interact_signal
# ============================================================

def test_user_interact_signal(proxy, event_q):
    """Verify that 'user_interact' emits message, options, response queue and image path."""
    proxy.user_interact_signal = MagicMock()

    q = SimpleQueue()
    event_q.put(("user_interact", (q, "Choose wisely", "image.png", ["Yes", "No"])))

    # Patch find_resource_path so it doesn't raise FileNotFoundError
    with patch("pypts.event_proxy.find_resource_path", return_value="image.png"):
        proxy.run_once()

    proxy.user_interact_signal.emit.assert_called_once()
    emitted = proxy.user_interact_signal.emit.call_args[0][0]
    assert emitted["message"] == "Choose wisely"
    assert emitted["options"] == ["Yes", "No"]
    assert emitted["response_q"] == q
    assert emitted["image_path"].endswith("image.png")


def test_user_interact_resolves_via_test_package(proxy, event_q):
    """When test_package is set via post_load_recipe, resolve_package_resource is used."""
    proxy.user_interact_signal = MagicMock()

    # First, send post_load_recipe to set _test_package
    mock_recipe = MagicMock()
    mock_recipe.name = "TestRecipe"
    mock_recipe.version = "1.0"
    mock_recipe.test_package = "my_test_pkg"
    event_q.put(("post_load_recipe", (mock_recipe,)))
    proxy.run_once()

    assert proxy._test_package == "my_test_pkg"

    # Now send user_interact and mock resolve_package_resource to return a path
    from pathlib import Path
    q = SimpleQueue()
    event_q.put(("user_interact", (q, "Check image", "power_Green.jpg", ["OK"])))

    with patch("pypts.event_proxy.resolve_package_resource", return_value=Path("/fake/pkg/resources/power_Green.jpg")) as mock_resolve:
        proxy.run_once()

    mock_resolve.assert_called_once_with("power_Green.jpg", "my_test_pkg")
    emitted = proxy.user_interact_signal.emit.call_args[0][0]
    assert emitted["image_path"] == "/fake/pkg/resources/power_Green.jpg"


def test_user_interact_falls_back_when_package_resolution_fails(proxy, event_q):
    """When resolve_package_resource returns None, fall back to CWD-based resolution."""
    proxy.user_interact_signal = MagicMock()

    # Set _test_package
    mock_recipe = MagicMock()
    mock_recipe.name = "TestRecipe"
    mock_recipe.version = "1.0"
    mock_recipe.test_package = "my_test_pkg"
    event_q.put(("post_load_recipe", (mock_recipe,)))
    proxy.run_once()

    q = SimpleQueue()
    event_q.put(("user_interact", (q, "Check image", "missing.jpg", ["OK"])))

    with patch("pypts.event_proxy.resolve_package_resource", return_value=None), \
         patch("pypts.event_proxy.find_resource_path", return_value="images/missing.jpg") as mock_find, \
         patch("pypts.event_proxy.get_project_root", return_value=MagicMock(__truediv__=lambda self, other: MagicMock(__str__=lambda s: f"/project/{other}"))):
        proxy.run_once()

    mock_find.assert_called_once()
    emitted = proxy.user_interact_signal.emit.call_args[0][0]
    assert "missing.jpg" in emitted["image_path"]


def test_user_interact_without_test_package(proxy, event_q):
    """When no post_load_recipe was sent, resolve_package_resource is never called."""
    proxy.user_interact_signal = MagicMock()

    q = SimpleQueue()
    event_q.put(("user_interact", (q, "Check image", "image.png", ["OK"])))

    with patch("pypts.event_proxy.resolve_package_resource") as mock_resolve, \
         patch("pypts.event_proxy.find_resource_path", return_value="image.png"):
        proxy.run_once()

    mock_resolve.assert_not_called()
    emitted = proxy.user_interact_signal.emit.call_args[0][0]
    assert emitted["image_path"].endswith("image.png")


# ============================================================
# Unsupported events
# ============================================================

def test_unsupported_event_logs_warning(proxy, event_q, caplog):
    """Verify that an unknown event type logs a warning instead of crashing."""
    event_q.put(("non_existing_event", ("some", "data")))
    with caplog.at_level("WARNING"):
        proxy.run_once()
        assert "No dictionary created for event: non_existing_event" in caplog.text


# ============================================================
# Stop / sentinel
# ============================================================

class TestStopBehavior:
    def test_none_sentinel_stops_proxy(self, proxy, event_q):
        """Verify that putting None in the queue stops the proxy (sets _running to False)."""
        event_q.put(None)
        proxy.run_once()
        assert proxy._running is False
