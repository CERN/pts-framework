# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Hardware Abstraction Layer.

Empty - roadmap Phase 5, and the last of the three empty engine modules to be
filled. Unlike `pypts.recipe` and `pypts.step` there is nothing to port: no
version of this ever existed. What follows is the shape the specification and
the architecture review agreed on, recorded here so the module is not designed
from scratch twice.

What it is meant to be
----------------------
A **plain library**, imported by the Sequencer and called with ordinary function
calls. No process, no event loop, no queue, no messages of its own. That is a
decision rather than an omission: it keeps the specification's "HAL usable
standalone, outside the framework" true by construction, and it is what lets a
driver be exercised without booting PyPTS at all.

The shape
---------
    Device                      base: connect(config) / teardown() / recover()
    PowerSupply, DAQ, Load, ...  family bases, one per instrument class,
                                declaring the standard verbs of that family
    <vendor driver>             concrete, one per instrument

A recipe refers to a device by **logical name**. The Config Handler supplies the
communication parameters for that name and the Sequencer hands the driver to the
step, so nothing in a recipe ever names a COM port or a VISA resource string.

Where the hardware actually lives today
---------------------------------------
Nowhere in this module, which is why the framework hard-depends on `nidmm`,
`hightime`, `nptdms`, `pyserial` and `paramiko`. A recipe reaches an instrument
in one of two ways: a `PythonModuleStep` calls into the user's own test package,
which imports the driver itself, or `SSHConnectStep` speaks paramiko directly
and publishes the session as a global. Phase 5 is where those dependencies leave
the core - drivers become pip-installable plugin packages depending only on
`pypts.api`, and the core ships with none of them.

Open before any of this is written
----------------------------------
- **How a bench is described in the configuration.** The placeholder
  `[hardware.example_device]` section and the prefix rule that validated
  `[hardware.<name>]` against it were deliberately *removed* rather than left to
  be designed around, so there is no shape to inherit and no migration to undo.
  A hand-written `[hardware.dmm1]` is preserved and returned as untyped text
  today; nothing reads it. See `config_handler/config_handler.md`.
- What `recover()` should do beyond disconnect-and-reconnect, and who decides to
  call it.
- The promotion rule: a driver gets a process of its own only in response to a
  concrete incident - wrap the one crash-prone C driver in a sidecar process,
  never the whole HAL.
"""
