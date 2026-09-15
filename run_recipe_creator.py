# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Starts the Recipe Creator, exactly as
`python -m pypts.helper_applications.recipe_creator` does.

`src` is put on the path first, so this works from a checkout even where pypts
has not been installed into the interpreter running it.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pypts.helper_applications.recipe_creator.recipe_creator_new import (  # noqa: E402
    main,  # needs the path set above
)

if __name__ == "__main__":
    sys.exit(main())
