# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The Recipe Creator, and the verificator it is the only user of.

`verificator.py` and `issue.py` lived in a sibling `recipe_verificator/`
package until 2026-09-16. Nothing in the framework ever imported them - only
this application did - so they moved in here, where everything the Creator
owns sits in one folder. See recipe_creator.md.

Only the verificator is exported. The GUI is deliberately not imported here:
it pulls in PySide6, and `verify_string` has to be usable without a display.
"""

from pypts.helper_applications.recipe_creator.issue import ValidationIssue
from pypts.helper_applications.recipe_creator.verificator import verify_file, verify_string

__all__ = ["ValidationIssue", "verify_file", "verify_string"]
