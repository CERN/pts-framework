.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

.. _instruments:

##############################
Instrument Abstraction Layer
##############################

pypts communicates with physical instruments through the
`pymeasure <https://pymeasure.readthedocs.io>`_ library (MIT licence).
pymeasure provides a mature Hardware Abstraction Layer (HAL) built around
three concepts — **Adapters**, **Instruments**, and **property descriptors** —
that together decouple the instrument-protocol definition from the specific
communication bus in use (GPIB, USB, RS-232, Ethernet, …).

pypts adds only instrument-specific behaviour that is not (yet) present in
upstream pymeasure.  All core infrastructure is imported directly from the
``pymeasure`` package; nothing is duplicated inside this repository.

.. contents:: Page contents
   :depth: 2
   :local:


Architecture
============

The diagram below shows the layers involved when pypts talks to a physical
instrument.

.. code-block:: text

    ┌───────────────────────────────────────────┐
    │          pypts recipe / test step         │
    └──────────────────┬────────────────────────┘
                       │ calls
    ┌──────────────────▼────────────────────────┐
    │   pypts.instruments.<vendor>.<model>      │  ← pypts-owned: subclasses only
    │   (e.g. CNT91 with trigger_level,         │
    │    configure_pulse_output)                │
    └──────────────────┬────────────────────────┘
                       │ inherits
    ┌──────────────────▼────────────────────────┐
    │   pymeasure.instruments.<vendor>.<model>  │  ← upstream driver (MIT)
    │   (e.g. pymeasure CNT91: gate_time,       │
    │    buffer_frequency_time_series, …)       │
    └──────────────────┬────────────────────────┘
                       │ inherits / uses
    ┌──────────────────▼────────────────────────┐
    │   pymeasure Instrument + SCPIUnknownMixin │  ← SCPI base (MIT)
    └──────────────────┬────────────────────────┘
                       │ delegates to
    ┌──────────────────▼────────────────────────┐
    │   VISAAdapter  (pymeasure.adapters)       │  ← wraps PyVISA (MIT)
    └──────────────────┬────────────────────────┘
                       │ opens
    ┌──────────────────▼────────────────────────┐
    │   PyVISA resource  (GPIB / USB / serial)  │  ← physical hardware
    └───────────────────────────────────────────┘


pymeasure building blocks
--------------------------

The following classes from pymeasure are used directly; import them from
``pymeasure`` rather than re-implementing them in pypts.

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Class / function
     - Import path
     - Purpose
   * - ``Instrument``
     - ``pymeasure.instruments``
     - Base class for all instrument drivers.
   * - ``SCPIMixin``
     - ``pymeasure.instruments``
     - Adds standard SCPI commands (``*IDN?``, ``*CLS``, ``*RST``, …).
   * - ``SCPIUnknownMixin``
     - ``pymeasure.instruments``
     - Like ``SCPIMixin`` but tolerates instruments that do not fully
       implement the SCPI standard.
   * - ``Channel``
     - ``pymeasure.instruments``
     - Base class for sub-channels of a multi-channel instrument.
   * - ``VISAAdapter``
     - ``pymeasure.adapters``
     - Connects to any PyVISA resource (GPIB, USB, RS-232, TCP/IP).
   * - ``ProtocolAdapter``
     - ``pymeasure.adapters``
     - In-process adapter used by ``expected_protocol`` during testing.
   * - ``strict_range``, ``strict_discrete_set``, ``truncated_range``
     - ``pymeasure.instruments.validators``
     - Validator functions for property setters.
   * - ``Parameter``, ``FloatParameter``, ``IntegerParameter``, …
     - ``pymeasure.experiment``
     - Typed, range-checked experiment parameters.
   * - ``expected_protocol``
     - ``pymeasure.test``
     - Context manager for protocol-level unit tests without hardware.


Property descriptors
---------------------

pymeasure provides three class-level descriptors that map Python property
access directly to SCPI command strings:

* ``Instrument.control(get_cmd, set_cmd, docs, …)`` — readable *and* writable.
* ``Instrument.measurement(get_cmd, docs, …)`` — read-only.
* ``Instrument.setting(set_cmd, docs, …)`` — write-only.

.. code-block:: python

   from pymeasure.instruments import Instrument
   from pymeasure.instruments.validators import strict_range

   class MyInstrument(Instrument):
       voltage = Instrument.control(
           "VOLT?", "VOLT %g",
           "Control output voltage in V.",
           validator=strict_range,
           values=[0, 30],
       )

When you write ``inst.voltage = 5.0``, pymeasure sends ``VOLT 5.0`` to the
instrument.  When you read ``inst.voltage``, pymeasure sends ``VOLT?`` and
casts the response to ``float``.


pypts instrument drivers
-------------------------

pypts-owned code lives exclusively in ``src/pypts/instruments/``.  Each
sub-package corresponds to a manufacturer; each module corresponds to one
model.

.. code-block:: text

   src/pypts/instruments/
   ├── __init__.py
   └── pendulum/
       ├── __init__.py
       └── cnt91.py          ← CNT91 subclass with pypts extensions

A driver module contains a single class that **subclasses** the upstream
pymeasure driver and adds only the methods or properties not yet present
upstream.  The goal is to keep this code as small as possible; ideally the
subclass can be removed entirely once the extensions are merged into pymeasure.


Usage
=====

Connecting to an instrument
----------------------------

Pass a VISA resource string to the instrument constructor.  pymeasure
creates a :class:`~pymeasure.adapters.VISAAdapter` automatically.

.. code-block:: python

   from pypts.instruments.pendulum import CNT91

   counter = CNT91("USB0::0x14EB::0x0091::205575::INSTR")

For serial (RS-232) connections, supply the baud rate as a keyword argument:

.. code-block:: python

   counter = CNT91("ASRL1::INSTR", asrl={"baud_rate": 256000})

The CNT-91 already sets the correct baud rate in its ``__init__``, so this
is only needed if you want to override the default.

Use the instrument as a context manager to ensure the connection is closed
when the block exits:

.. code-block:: python

   with CNT91("USB0::0x14EB::0x0091::205575::INSTR") as counter:
       print(counter.id)


Standard SCPI commands
-----------------------

All SCPI base commands are available through the inherited ``SCPIUnknownMixin``:

.. code-block:: python

   counter.clear()         # *CLS — clear status registers
   counter.reset()         # *RST — restore factory defaults
   print(counter.id)       # *IDN? — manufacturer / model / serial / firmware
   counter.check_errors()  # SYST:ERR? — log any error queue entries


Configuring and reading gate time
----------------------------------

.. code-block:: python

   counter.gate_time = 0.1     # 100 ms gate time
   print(counter.gate_time)    # reads back ':ACQ:APER?'


Buffered frequency time-series
--------------------------------

The most common acquisition mode for frequency stability measurements:

.. code-block:: python

   from pypts.instruments.pendulum import CNT91

   RESOURCE = "USB0::0x14EB::0x0091::205575::INSTR"
   N = 1000          # samples
   GATE = 0.01       # 10 ms gate time

   with CNT91(RESOURCE) as counter:
       # Configure and start the buffered acquisition.
       # trigger_level is a pypts extension: sets ':INP1:LEV 2.4' before
       # starting the measurement.
       counter.buffer_frequency_time_series(
           channel="A",
           n_samples=N,
           gate_time=GATE,
           trigger_level=2.4,   # optional, V
       )

       # Block until the buffer is full, then retrieve all samples.
       frequencies = counter.read_buffer(N)

   print(f"Mean frequency: {sum(frequencies)/len(frequencies):.3f} Hz")

Without the pypts ``trigger_level`` extension, the call is identical to the
upstream pymeasure API:

.. code-block:: python

   counter.buffer_frequency_time_series(channel="A", n_samples=N, gate_time=GATE)


Rear-panel pulse output (pypts extension)
------------------------------------------

The ``configure_pulse_output`` method is a pypts addition that configures the
TTL pulse output on the rear panel of the CNT-91.

.. code-block:: python

   with CNT91(RESOURCE) as counter:
       counter.configure_pulse_output(
           enabled=True,
           period=1.0,    # 1 s period
           width=0.01,    # 10 ms pulse width
           source="TIME", # time-based pulsing
       )

       # Disable the pulse output when done.
       counter.configure_pulse_output(enabled=False, period=1.0, width=0.01)

.. note::

   ``width`` must be strictly less than ``period``; otherwise
   :class:`ValueError` is raised before any command is sent to the instrument.


Integration with pypts recipes
--------------------------------

Instrument functions are called from recipe YAML steps via the
``PythonModuleStep`` mechanism (see :ref:`yaml_format`).  The function
receives its arguments from the recipe's variable scope.

.. code-block:: yaml
   :caption: Example recipe step calling the CNT-91

   ---
   name: Frequency Stability Test
   version: "1.0"
   recipe_version: "1.1.0"
   test_package: pypts.Instrument_test_examples
   globals:
     device_name: "USB0::0x14EB::0x0091::205575::INSTR"
     gate_time: 0.01
     n_samples: 500

   ---
   name: Main
   steps:
     - type: python_module
       function: run_cnt91
       args:
         device_name: ${device_name}
         gate_times: ${gate_time}
         samples: ${n_samples}
         channels: 1

The function must follow the pypts step contract: it must return a dict with
at least the key ``"output"`` set to ``True`` on success.


Testing
========

All instrument drivers, including pypts extensions, are tested without physical
hardware using :func:`pymeasure.test.expected_protocol`.  This context manager
replaces the real VISA connection with a :class:`~pymeasure.adapters.ProtocolAdapter`
that checks every byte written to and read from the instrument against a
pre-defined list of command/response pairs.

.. code-block:: python

   from pymeasure.test import expected_protocol
   from pypts.instruments.pendulum import CNT91

   def test_configure_pulse_output():
       with expected_protocol(
           CNT91,
           [
               (b"OUTP:PULS:STAT ON", None),
               (b"OUTP:PULS:SOUR TIME", None),
               (b"OUTP:PULS:PER 1.0", None),
               (b"OUTP:PULS:WIDT 0.01", None),
           ],
       ) as inst:
           inst.configure_pulse_output()

Key rules for writing protocol tests:

* Commands and responses are expressed as **byte strings** (``b"…"``).
  Termination characters (``\n``, ``\r\n``) are **not** included.
* ``None`` in the response position means the command has no response.
* ``None`` in the command position means the instrument sends data
  spontaneously (without a prior query).
* The context manager asserts that all listed pairs were consumed in order
  and that no pairs are left over.

.. note::

   Tests in ``tests/unit_tests/instruments/`` cover only the pypts
   extensions.  The full upstream CNT-91 protocol (gate-time control,
   continuous mode, arming, buffer readout, etc.) is tested by pymeasure's
   own test suite.  You do not need to re-test behaviour that the subclass
   inherits unchanged.


Adding a new instrument driver
================================

Follow these steps to add support for a new instrument.

**1. Check pymeasure first.**
   Browse ``pymeasure.instruments`` — the instrument may already be
   supported upstream.  If it is, import it directly:

   .. code-block:: python

      from pymeasure.instruments.keithley import Keithley2450

   Only create a pypts subclass if you need to add behaviour that is not in
   upstream.

**2. Create the subclass.**
   Add a module under ``src/pypts/instruments/<vendor>/``:

   .. code-block:: python

      # src/pypts/instruments/acme/xyz123.py
      # SPDX-FileCopyrightText: 2025 CERN <home.cern>
      # SPDX-License-Identifier: LGPL-2.1-or-later

      from pymeasure.instruments.acme import XYZ123 as _UpstreamXYZ123

      class XYZ123(_UpstreamXYZ123):
          """ACME XYZ-123 with pypts extensions."""

          def my_extension(self, value):
              """Description of what this adds."""
              self.write(f"MYEXT {value}")

   Export it from ``src/pypts/instruments/<vendor>/__init__.py``:

   .. code-block:: python

      from .xyz123 import XYZ123
      __all__ = ["XYZ123"]

**3. Write protocol tests.**
   Create ``tests/unit_tests/instruments/<vendor>/test_xyz123.py`` and test
   every method added by the subclass using ``expected_protocol`` (see
   :ref:`Testing <instruments>` above).

**4. Consider contributing upstream.**
   If the extension is generally useful, open a pull request in the
   `pymeasure repository <https://github.com/pymeasure/pymeasure>`_.
   Once merged, the pypts subclass can be removed.
