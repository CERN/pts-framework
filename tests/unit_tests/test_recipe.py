import pytest
from unittest.mock import MagicMock
from pypts.recipe import Recipe

def test_recipe_loading():
    '''
    Test that the recipe is loaded correctly by loading a fake recipe and checking the attributes.
    Also tests that the recipe is run with the correct serial number.
    '''
    # Prepare test data
    recipe_data = [
        {"name": "Test Recipe", "description": "For testing", "version": "1.0", "globals": {}},
        {"sequence_name": "Main", "locals": {}, "parameters": {}, "outputs": {},
         "setup_steps": [], "steps": [], "teardown_steps": []}
    ]
    
    # Create mock dependencies
    mock_file_loader = MagicMock()
    mock_file_loader.return_value = iter(recipe_data)
    
    # Track sent events
    sent_events = []
    def mock_event_sender(runtime, event_name, *event_data):
        sent_events.append((runtime, event_name, event_data))
    
    # Create a mock for getting serial numbers
    def mock_get_serial_number(runtime):
        return "TEST123"
    
    # Create the recipe with injected dependencies
    recipe = Recipe(
        recipe_file_path="fake_path.yaml", 
        file_loader=mock_file_loader, 
        event_sender=mock_event_sender
    )
    
    # Verify the recipe was loaded correctly
    assert recipe.name == "Test Recipe"
    assert recipe.description == "For testing"
    assert "Main" in recipe.sequences
    
    # Create a mock runtime for running the recipe
    mock_runtime = MagicMock()
    
    # Run the recipe with the injected serial number function
    recipe.run(
        runtime=mock_runtime,
        get_serial_number_func=mock_get_serial_number
    )
    
    # Verify the expected events were sent
    assert len(sent_events) > 0
    assert sent_events[0][1] == "pre_run_recipe"
    assert sent_events[0][2] == ("Test Recipe", "For testing")
    
    # Verify runtime was called correctly
    mock_runtime.set_global.assert_any_call("serial_number", "TEST123") 