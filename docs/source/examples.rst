.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _examples:

########
Examples
########

This page walks through the built-in examples shipped with pypts. They are
located under ``src/pypts/examples/`` and ``src/pypts/example_tests.py``.

.. _sinewave_example:

Sinewave Validation Example
============================

This example demonstrates the complete pypts workflow — from a test method that
produces a matplotlib plot, through the recipe YAML that wires the step up, to
the HTML report that embeds the chart automatically.

What it does
------------

1. A Python test method generates a 60 Hz sinewave, analyses its frequency
   content with an FFT, and saves a two-panel plot (time domain + spectrum) to
   a temporary PNG file.
2. The recipe step maps the returned image path with ``type: image`` so the
   framework copies the file into the report directory.
3. The HTML report embeds the chart at the bottom of the page, captioned with
   the step name and PASS/FAIL result.

Test method (``example_tests.py``)
------------------------------------

.. code-block:: python

   import tempfile
   import numpy as np
   import matplotlib
   matplotlib.use('Agg')          # non-interactive backend — safe in a test thread
   import matplotlib.pyplot as plt

   def generate_sinewave(frequency=60, duration=1.0, tolerance=1.0):
       sampling_rate = frequency * 10
       t    = np.linspace(0, duration, int(sampling_rate * duration), endpoint=False)
       data = np.sin(2 * np.pi * frequency * t)

       # FFT analysis
       fft_result = np.fft.fft(data)
       fft_freq   = np.fft.fftfreq(len(data), 1 / sampling_rate)
       magnitude  = np.abs(fft_result[: len(fft_result) // 2])
       freq_bins  = fft_freq[: len(fft_freq) // 2]
       detected   = abs(freq_bins[np.argmax(magnitude)])
       test_passed = abs(detected - frequency) <= tolerance

       # Build plot
       fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6))
       ax1.plot(t, data, linewidth=0.8)
       ax1.set(xlabel="Time (s)", ylabel="Amplitude",
               title=f"Sinewave — {frequency} Hz")
       ax1.grid(True, alpha=0.3)

       ax2.plot(freq_bins, magnitude, linewidth=0.8)
       ax2.axvline(detected, color="red", linestyle="--",
                   label=f"Peak: {detected:.1f} Hz")
       ax2.set(xlabel="Frequency (Hz)", ylabel="Magnitude", title="FFT Spectrum")
       ax2.legend()
       ax2.grid(True, alpha=0.3)

       plt.tight_layout()
       tmp = tempfile.NamedTemporaryFile(suffix="_sinewave.png", delete=False)
       fig.savefig(tmp.name, dpi=100, bbox_inches="tight")
       plt.close(fig)

       return {"passed": test_passed, "chart": tmp.name}

Key points:

* ``matplotlib.use('Agg')`` must be called before importing ``pyplot`` — the
  ``Agg`` backend renders to a file without opening a display window, which is
  required inside a test thread.
* ``tempfile.NamedTemporaryFile(delete=False)`` creates the file in the OS
  temporary directory and keeps it on disk after the function returns.  The
  framework copies it into the report directory, so the caller does not need
  to manage the temporary file's lifetime.
* The method returns a plain ``dict``.  The ``chart`` key holds the absolute
  path to the PNG; ``passed`` is the boolean verdict.

Recipe step (``Minimal_setup_recipe.yml``)
------------------------------------------

.. code-block:: yaml

   - steptype: PythonModuleStep
     step_name: Sinewave test (60 Hz)
     description: >
       Generate a 60 Hz sinewave, validate it via FFT,
       and attach the plot to the report.
     action_type: method
     module: example_tests.py
     method_name: generate_sinewave
     input_mapping:
       frequency: {type: direct, value: 60}
       tolerance: {type: direct, value: 1.0}
     output_mapping:
       passed: {type: passfail}   # PASS when frequency error ≤ tolerance
       chart:  {type: image}      # PNG copied into report and embedded in HTML

The ``type: image`` mapping tells pypts to:

1. Copy the file at ``chart``'s path into ``<report_dir>/img/``.
2. Record the relative path in the CSV report (``image_paths`` column).
3. Embed the image in the **Images** section at the bottom of the HTML report,
   with the step name and result as a caption.

.. note::
   ``type: image`` does **not** affect the step's pass/fail verdict.
   The verdict comes from the ``passed: {type: passfail}`` mapping.
   Both output keys are independent.

HTML report output
------------------

After the recipe runs, the HTML report (``pts_reports/report_<timestamp>.html``)
contains an **Images** section at the bottom:

.. code-block:: html

   <figure>
     <img src="img/<step_id>_<filename>_sinewave.png">
     <figcaption>
       <strong>Step:</strong> Sinewave test (60 Hz) —
       <strong>Result:</strong> PASS
     </figcaption>
   </figure>

The ``img/`` subdirectory sits next to the HTML file so the report is
self-contained and portable — copy the whole ``pts_reports/`` folder to share
it.

Where to find the example files
---------------------------------

+------------------------------------------------------------------+------------------------------------------------------+
| File                                                             | Role                                                 |
+==================================================================+======================================================+
| ``src/pypts/example_tests.py``                                   | Test methods (main example set)                      |
+------------------------------------------------------------------+------------------------------------------------------+
| ``src/pypts/recipes/simple_recipe.yml``                          | Reference recipe with all output mapping types       |
+------------------------------------------------------------------+------------------------------------------------------+
| ``src/pypts/examples/environment_setup_tools/Minimal_setup/``    | Minimal (file-based) setup example                   |
+------------------------------------------------------------------+------------------------------------------------------+
| ``src/pypts/examples/environment_setup_tools/Package_based_setup/`` | Package-based setup example                      |
+------------------------------------------------------------------+------------------------------------------------------+
