.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

Troubleshooting
===============

- **"GUI mode needs PySide6"** — install PySide6, or start with ``--mode cli``.
- **"pypts configuration discarded"** — ``config.ini`` is broken or outdated. The run
  continues on defaults; fix the file, or delete it to have it recreated.
- **A recipe won't load** — the error names the problem. Open the recipe in the Recipe
  Creator (``run_recipe_creator.bat``) to see every issue at once.
- **Anything else** — rerun with ``--log-level TRACE`` and attach the run log.

The full table is in ``usage_manual.html``, section *Troubleshooting*.
