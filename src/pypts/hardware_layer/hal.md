<!--
SPDX-FileCopyrightText: 2026 CERN <home.cern>

SPDX-License-Identifier: CC-BY-SA-4.0
-->

# hardware_layer — HAL (not implemented)

**No code.** `hal.py` holds only a module docstring recording the design that was agreed, so
the module is not designed from scratch twice. Nothing imports it. Building it is **roadmap
Phase 5** (`pypts_implementation_status.html` → *Phase 5 — Hardware Abstraction Layer*).

Nothing is ported here: no version of a HAL existed in `old_code/`.

## Agreed shape

- **A plain library**, imported by the Sequencer and called with ordinary function calls. No
  process, no event loop, no queue, no messages of its own. That keeps the spec's "HAL usable
  standalone, outside the framework" true by construction.
- A class hierarchy:
  ```
  Device                        base: connect(config) / teardown() / recover()
  PowerSupply, DAQ, Load, ...   family bases, one per instrument class, with its standard verbs
  <vendor driver>               concrete, one per instrument
  ```
  The public bases are planned as `pypts.api.hal`.
- A recipe names a device by **logical name**. The Config Handler supplies that device's
  communication parameters; nothing in a recipe names a COM port or a VISA resource.
- Drivers become **pip-installable plugin packages** depending only on `pypts.api`; the core
  ships with none. That is when `nidmm`, `hightime`, `nptdms`, `pyserial` and `paramiko` leave
  `pyproject.toml`'s dependencies.
- **Promotion rule**: a driver gets its own process only in response to a concrete incident —
  wrap that one crash-prone driver in a sidecar process, never the whole HAL.

## Where hardware is reached today

Only from user code: a `PythonModule` step calls into the recipe's own test package, which
imports its drivers itself. The old engine's `SSHConnectStep` / `SSHCloseStep` were **not
ported as step types**; SSH becomes part of the framework (HAL or a service — not decided),
with credentials in the Config Handler.

## Open before any code is written

- **How a bench is described in the configuration.** The placeholder
  `[hardware.example_device]` section and its prefix rule were removed, so the design is
  unconstrained. A hand-written `[hardware.<name>]` section is kept and returned as untyped
  text today; nothing reads it. Adding anything mandatory needs a `CONFIG_VERSION` major change.
  See `config_handler/config_handler.md`.
- What `recover()` does beyond disconnect-and-reconnect, and who decides to call it.
- How a step reaches a device. Not designed; the roadmap's plugin section sketches a device
  lookup on the step's context object.
