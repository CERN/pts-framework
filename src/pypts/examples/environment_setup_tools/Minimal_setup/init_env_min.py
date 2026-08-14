# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
# Example test for initializing the minimal setup environment for a testing show of recipe and directory requirement.
#It should initialize once called in a new directory, kept with a working directory. 

import shutil
from importlib.resources import as_file, files
from pathlib import Path


def main():
    project_root = Path.cwd()
    tests_dir = project_root / "tests"
    tests_dir.mkdir(exist_ok=True)

    (tests_dir / "__init__.py").touch(exist_ok=True)
    package_resources = files(__package__)

    # Copy example recipe for minimal setup
    recipe_dest = project_root / "Minimal_setup_recipe.yml"
    if not recipe_dest.exists():
        with as_file(package_resources.joinpath("Minimal_setup_recipe.yml")) as recipe_src:
            shutil.copy(recipe_src, recipe_dest)
        print(f"Copied example recipe -> {recipe_dest}")
    else:
        print(f"Example recipe already exists at {recipe_dest}")

    # Copy Minimal setup tests
    tests_resources = package_resources.joinpath("tests")
    for resource in tests_resources.iterdir():
        if not resource.name.endswith(".py"):
            continue
        dest_file = tests_dir / resource.name
        if not dest_file.exists():
            with as_file(resource) as source:
                shutil.copy(source, dest_file)
            print(f"Copied test file -> {dest_file}")
        else:
            print(f"Test file already exists: {dest_file}")

    print("\n Environment initialized successfully.")


if __name__ == "__main__":
    main()
