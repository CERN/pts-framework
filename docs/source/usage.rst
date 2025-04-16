.. _usage:

Usage
=====

This guide provides a basic overview of how to run a test recipe using the ``pypts`` framework.

1. Define your Recipe (`my_recipe.yaml`)
-----------------------------------------

Create a YAML file defining your test sequence. The recipe consists of a main document defining metadata and global variables, followed by documents defining named sequences.

.. code-block:: yaml
   :caption: my_recipe.yaml

   # Main recipe definition
   name: MyTestRecipe
   description: Example recipe demonstrating basic steps.
   version: "1.0"
   globals:
     device_address: "COM3"
     test_voltage: 5.0
   ---
   # Main sequence definition
   sequence_name: Main
   parameters:
     # Input parameters for this sequence (if any)
   locals:
     # Local variables initialized for this sequence
     measurement: null
   outputs:
     # Values from locals to expose as sequence output
     - measurement
   setup_steps: []
   steps:
     - steptype: WaitStep
       step_name: Initial Delay
       input_mapping:
         wait_time: { type: direct, value: 2 }
     - steptype: PythonModuleStep
       step_name: Configure Device
       module: path/to/your/device_driver.py
       action_type: method
       method_name: setup_device
       input_mapping:
         port: { type: global, global_name: device_address }
         voltage: { type: global, global_name: test_voltage }
       output_mapping:
         success: { type: passfail }
     - steptype: PythonModuleStep
       step_name: Take Measurement
       module: path/to/your/device_driver.py
       action_type: method
       method_name: read_measurement
       input_mapping: {}
       output_mapping:
         measured_value: { type: local, local_name: measurement }
         # Example pass/fail check
         status: { type: range, min: 4.8, max: 5.2 }
   teardown_steps:
     - steptype: PythonModuleStep
       step_name: Disconnect Device
       module: path/to/your/device_driver.py
       action_type: method
       method_name: disconnect
       input_mapping: {}
       output_mapping: {}

.. note::
   Replace ``path/to/your/device_driver.py`` with the actual path to your Python module containing the methods called by ``PythonModuleStep``.

2. Run the Recipe (`run_my_recipe.py`)
---------------------------------------

Use the ``run_pts`` function from the ``pypts.pts`` module to execute your recipe file. This will start the recipe execution in a background thread.

.. code-block:: python
   :caption: run_my_recipe.py

   import logging
   from pypts.pts import run_pts
   import time

   # Configure logging (optional but recommended)
   logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

   print("Starting the pypts recipe...")
   # Specify the path to your recipe file
   recipe_file = "my_recipe.yaml"

   # Run the default 'Main' sequence
   api = run_pts(recipe_file=recipe_file)

   print(f"Recipe '{recipe_file}' started in background thread.")
   print("Monitoring event queue (press Ctrl+C to stop early):")

   # Example: Monitor the event queue for completion or errors
   # In a real application, you might have more sophisticated handling
   try:
       while True:
           event_name, event_data = api.event_queue.get() # Blocking call
           print(f"EVENT: {event_name} - Data: {event_data}")
           if event_name == "post_run_recipe":
               print("Recipe finished.")
               break
           # Add handling for specific errors or other events if needed
           time.sleep(0.1)
   except KeyboardInterrupt:
       print("\nStopping monitoring.")
   except Exception as e:
       print(f"An error occurred: {e}")

   print("Main script finished.")

3. Check the Reports
--------------------

After execution (or during, for the CSV), check the ``./pts_reports/`` directory (relative to where you ran the Python script) for:

*   ``report.csv``: Incrementally updated CSV file with detailed step results.
*   ``report.html``: HTML version of the report generated after the recipe finishes.
