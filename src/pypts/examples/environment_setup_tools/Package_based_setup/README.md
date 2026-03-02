# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# Guide for Package-based use of PTS Framework
This document aims to explain how to use the PTS framework in a package based setup.
A package-based setup consists of utilizing the PTS framework and repackagining it into another frame that can be used.
An example would be if an entire testsetup is made for a device and packagining the tests into a package for easier distribution.


## Setting up the framework
To setup the test from scratch, run the executeable ``init_env_pack.exe``. 
```
init_env_pack
```

This will setup the entire required framework, but additional information to understanding it will be described here.

The entire setup is handled by the initializing script that sets up the framework. Knowing how it is done however is useful for when making your own test package by using this framework.
When making package-based test using the PTS framework, it is required to include a *pyproject.toml* file. This file will describe what the package is to contain in the package. This includes which libraries it requires.

The framework requires the pts framework to operate, even as a package and is such required to be installed.

To be able to run the test by itself, through ```python -m example_package ``` the following command is run.

```
python -m pip install -e .
```

This installs the example_package as a callable package that can be used.

## Using the framework
To use the framework, the file ```__main__.py``` is required. The file shown in the example shows what is required to run the framework.

Once the entire framework is set up, in order to run the framework, two methods are possible.
To run the package-based framework, call the following command.
```
python -m example_package 
```
For unpackaged framework, call the following.
```
python -m pypts
```
This initializes the standard gui. Both methods are viable approaches for initializing the gui.
From The gui, you can can see the different actions to perform.

Click `open` to load the recipe into the framework. This will show the recipe in the gui.
Click `start` to start the tests. This will start running the tests in the recipe. The example shows an example of user interaction as first step. The buttons to click are visible on right side, below the image. 
Clicking `stop` will stop the currently running test and cleanly shut down the tests and finalize the results before showing a summary of them in the gui. 




For full documentation, please visit [PTS Framework Documentation](https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/stable/).

