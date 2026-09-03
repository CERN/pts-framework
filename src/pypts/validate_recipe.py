# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Command-line validation of recipe-language 2.0.0 YAML files.

Usage:
    python -m pypts.validate_recipe <recipe.yml>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence as ArgSequence

from pypts.recipe_parser import parse_recipe_file
from pypts.YamVIEW.verify_recipe import format_diagnostic


def main(argv: ArgSequence[str] | None = None) -> int:
    """Validate the given recipe file and print diagnostics; return a process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m pypts.validate_recipe",
        description="Validate a recipe-language 2.0.0 YAML file and report diagnostics.",
    )
    parser.add_argument("recipe", help="Path to the recipe YAML file to validate.")
    args = parser.parse_args(argv)

    result = parse_recipe_file(args.recipe)

    for diagnostic in result.diagnostics:
        stream = sys.stderr if diagnostic.severity == "error" else sys.stdout
        print(format_diagnostic(diagnostic), file=stream)

    if result.is_valid:
        print(f"OK: {args.recipe} is a valid recipe-language 2.0.0 recipe.")
        return 0

    print(f"FAILED: {len(result.errors)} error(s), {len(result.warnings)} warning(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
