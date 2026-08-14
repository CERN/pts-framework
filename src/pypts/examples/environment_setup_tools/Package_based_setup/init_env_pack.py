# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later
# Example test for initializing the package-based environment for a testing show of recipe and directory requirement.
#It should initialize once called in a new directory, kept with a working directory. 


import shutil
import subprocess
import sys
from importlib.resources import as_file, files
from pathlib import Path


def main():
    package_example = "example_package"
    project_root = Path.cwd()
    src_dir = project_root / "src"
    package_dir = src_dir / package_example
    bin_dir = package_dir / "bin"
    resource_dir = package_dir / "resources"
    tests_dir = package_dir/ "tests"
    src_dir.mkdir(exist_ok=True)
    package_dir.mkdir(exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    resource_dir.mkdir(exist_ok=True)
    tests_dir.mkdir(exist_ok=True)

    (package_dir / "__init__.py").touch(exist_ok=True)
    (bin_dir / "__init__.py").touch(exist_ok=True)
    (resource_dir / "__init__.py").touch(exist_ok=True)
    package_resources = files(__package__)

    # Copy example recipe for minimal setup
    recipe_dest = resource_dir /"Package_based_recipe.yml"
    if not recipe_dest.exists():
        with as_file(package_resources.joinpath("Package_based_recipe.yml")) as recipe_src:
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

    pyproject_dest = project_root/ "pyproject.toml"
    if not pyproject_dest.exists():
        with as_file(package_resources.joinpath("pyproject.toml")) as pyproject_toml:
            shutil.copy(pyproject_toml, pyproject_dest)
        print(f"Copied example recipe -> {pyproject_dest}")
    else:
        print(f"Example recipe already exists at {pyproject_dest}")

    #write the main file

    main_code = """\
from pypts.pts import run_pts
from pypts.startup import create_and_start_gui
import sys

if __name__ == '__main__':
    api = run_pts()
    
    window, app = create_and_start_gui(api)
    # Start the Qt event loop
    exit_code = app.exec()
    
    # Exit with the application's exit code
    sys.exit(exit_code)
    """
    with open(package_dir / "__main__.py", "w", encoding="utf-8") as f:
        f.write(main_code)

    subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", "."])

    print("\n Environment initialized successfully.")



if __name__ == "__main__":
    main()
