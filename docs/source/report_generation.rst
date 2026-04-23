.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

=====================
Report Generation
=====================

The pypts framework includes an automated reporting system that generates a detailed CSV report of the execution flow and results of a recipe run. This process runs incrementally in the background.

Initialization
--------------

When a pypts recipe execution is initiated via the ``pts.run_pts`` function:

1.  A ``SimpleQueue`` named ``report_queue`` is created. This queue serves as the communication channel between the main recipe execution thread and the reporting thread.
2.  A report output directory is determined. Currently, this is hardcoded within ``pts.run_pts`` to be ``./pts_reports`` relative to the directory where the pypts application was launched. The directory is created if it doesn't exist.
3.  A dedicated daemon thread is started, running the ``report.report_listener`` function. This function is passed the ``report_queue`` and the path to the output directory.
4.  The ``report_queue`` is passed to the ``recipe.Runtime`` object, making it accessible during recipe execution.

Sending Results to the Queue
----------------------------

As the recipe executes, each time a ``recipe.Step`` finishes its execution within the ``Step.run`` method:

1.  A ``recipe.StepResult`` object, containing details about the step's execution (inputs, outputs, result status, errors, UUIDs, etc.), is created.
2.  Immediately after the ``post_run_step`` event is emitted, this ``StepResult`` object is placed onto the ``report_queue`` using ``runtime.report_queue.put(step_result)``.

Report Listener (`report_listener`)
-----------------------------------

The ``report_listener`` function runs continuously in its own thread, monitoring the ``report_queue``. Its primary responsibilities are:

1.  **Initialization:** Upon starting, it instantiates a ``report.Report`` object, passing it the designated output directory. The ``Report`` object handles the creation and management of the actual report file (``report.csv``).
2.  **Waiting for Results:** It blocks, waiting for items to appear on the ``report_queue`` using ``result_queue.get()``.
3.  **Processing Results:**
    *   If the received item is a ``StepResult`` object, it calls ``report_manager.add_step_result(item)`` to process and write the result to the report file.
    *   If the received item is the special sentinel object ``report.STOP_LISTENER``, it signifies the end of the recipe execution.
    *   Any other unexpected item type is logged as a warning.
4.  **Termination:** Upon receiving the ``STOP_LISTENER`` sentinel, the listener loop terminates.

Report Manager (`Report` Class)
-------------------------------

The ``report.Report`` class manages the actual file I/O for the CSV report:

1.  **Initialization (`__init__`)**:
    *   Takes the output directory path.
    *   Creates the directory if needed.
    *   Opens the ``report.csv`` file in write mode (`'w'`), effectively overwriting any previous report in that location for the current run.
    *   Creates a ``csv.DictWriter`` instance, configured with the predefined CSV headers.
    *   Writes the header row to the CSV file.
2.  **Adding Results (`add_step_result`)**:
    *   Takes a ``StepResult`` object as input.
    *   Uses internal helper functions (``_result_to_dict``, ``_flatten_single_result``) to convert the potentially nested ``StepResult`` object into a flat dictionary suitable for a single CSV row. Complex data structures like inputs and outputs are JSON-serialized.
    *   Copies any image files referenced in ``result.image_paths`` into ``<output_dir>/img/`` (see :ref:`image_outputs` below).
    *   Writes the flattened dictionary as a row to the CSV file using the ``DictWriter``.
    *   Flushes the file buffer to ensure the data is written to disk promptly.
3.  **Finalization (`finish_reports`)**:
    *   Called by the ``report_listener`` just before it exits.
    *   Closes the CSV file handle, ensuring all data is saved.

After the CSV is finalised, ``report_listener`` generates an HTML report (``report_{timestamp}.html``) from the CSV data. The HTML report includes:

*   A **Run Context** block (recipe name, file, serial number, pypts version).
*   A **Summary** with the total number of steps.
*   A colour-coded **Details** table (PASS = green, FAIL/ERROR = red, SKIP = yellow).
*   An **Images** section at the bottom, embedding any images returned by test steps (see below).

Stopping the Listener
---------------------

When the main recipe execution completes in ``recipe.Recipe.run``:

1.  Before returning the final results, it imports the ``report.STOP_LISTENER`` sentinel object.
2.  It places this sentinel onto the ``report_queue`` using ``runtime.report_queue.put(STOP_LISTENER)``.
3.  This signals the ``report_listener`` thread to stop waiting for more results, finalize the report, and exit.

.. _image_outputs:

Image Outputs
-------------

Test methods executed by ``PythonModuleStep`` can return image file paths (PNG, JPG, SVG, etc.) as part of their output dictionary. The framework automatically copies these files into the report directory and embeds them at the bottom of the HTML report with the corresponding step name and result as a caption.

**How it works**

1.  The test method returns a dictionary that includes a key mapped to an image file path.
2.  In the recipe's ``output_mapping``, that key is declared with ``type: image``.
3.  When the step finishes, the framework stores the path in ``StepResult.image_paths``.
4.  The ``Report.add_step_result()`` method copies the file to ``<output_dir>/img/<step_id>_<filename>``.
5.  The relative path is recorded in the CSV (``image_paths`` column).
6.  ``generate_html_report()`` embeds each image in an **Images** section at the bottom of the HTML report.

**Example Python test method**

.. code-block:: python

   import matplotlib.pyplot as plt
   import tempfile, os

   def run_signal_analysis(data=None, **kwargs):
       fig, ax = plt.subplots()
       ax.plot(data)
       ax.set_title("Signal")

       path = os.path.join(tempfile.gettempdir(), "signal_plot.png")
       fig.savefig(path)
       plt.close(fig)

       passed = max(data) < 1.0
       return {"chart": path, "passed": passed}

**Corresponding recipe step**

.. code-block:: yaml

   - steptype: PythonModuleStep
     step_name: Analyse Signal
     module: my_tests.py
     action_type: method
     method_name: run_signal_analysis
     input_mapping:
       data: {type: global, global_name: raw_signal}
     output_mapping:
       chart:
         type: image    # file is copied into the report and embedded in the HTML
       passed:
         type: passfail

.. note::
   The ``type: image`` mapping does **not** affect the step's pass/fail result — it only
   triggers file copying and HTML embedding.  Combine it with ``passfail``, ``equals``,
   or ``range`` mappings on other output keys to get a verdict as usual.

**Supported image formats**: ``.png``, ``.jpg``, ``.jpeg``, ``.gif``, ``.bmp``,
``.svg``, ``.tiff``, ``.webp``.

**Output directory structure after a run with images**::

   pts_reports/
   ├── report_2025-01-15_14h30.csv
   ├── report_2025-01-15_14h30.html
   └── img/
       └── <step_id>_signal_plot.png
