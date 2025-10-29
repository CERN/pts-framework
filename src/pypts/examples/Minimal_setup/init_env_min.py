# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
# Example test for initializing the minimal setup environment for a testing show of recipe and directory requirement.
#It should initialize once called in a new directory, kept with a working directory. 

from pypts.utils import get_project_root
import shutil
from pathlib import Path

def main():
    project_root = get_project_root()
    tests_dir = project_root / "tests"
    tests_dir.mkdir(exist_ok=True)


    #locating path of this script. will be used to copy the examples out.
    package_root = Path(__file__).resolve().parent

    # Copy example recipe for minimal setup
    recipe_src = package_root / "Minimal_setup_recipe.yml"
    recipe_dest = project_root / "Minimal_setup_recipe.yml"
    if not recipe_dest.exists():
        shutil.copy(recipe_src, recipe_dest)
        print(f"Copied example recipe → {recipe_dest}")
    else:
        print(f"Example recipe already exists at {recipe_dest}")

    # Copy Minimal setup tests
    tests_src = package_root / "example_tests"
    for file in tests_src.glob("*.py"):
        dest_file = tests_dir / file.name
        if not dest_file.exists():
            shutil.copy(file, dest_file)
            print(f"Copied test file → {dest_file}")
        else:
            print(f"Test file already exists: {dest_file}")

    print("\n Environment initialized successfully.")


if __name__ == "__main__":
    main()