# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# Guide for Package-based use of PTS Framework
This document aims to explain how to use the PTS framework in a package based setup.
A package-based setup consists of utilizing the PTS framework and repackagining it into another frame that can be used.
An example would be if an entire testsetup is made for a device and packagining the tests into a package for easier distribution.


## Setting up the framework
To setup the test from scratch, run the executeable ``init_env_min.exe``. 
```
init_env_min
```

This will setup the entire required framework, but additional information to understanding it will be described here.

The entire setup is handled by the initializing script that sets up the framework. Knowing how it is done however is useful for when making your own test package by using this framework.
Check the ```__main__.py``` file for how to initialize the gui.

## Using the framework
To use the framework, the file ```__main__.py``` is required. The file shown in the example shows what is required to run the framework.

Once the entire framework is set up, in order to run the framework, two methods are possible.
To run the framework, call the following command.
```
python -m pypts
```
This initializes the standard gui.
From The gui, you can can see the different actions to perform.

Click `open` to load the recipe into the framework. This will show the recipe in the gui.
Click `start` to start the tests. This will start running the tests in the recipe. The example shows an example of user interaction as first step. The buttons to click are visible on right side, below the image. 
Clicking `stop` will stop the currently running test and cleanly shut down the tests and finalize the results before showing a summary of them in the gui. 




For full documentation, please visit [PTS Framework Documentation](https://acc-py.web.cern.ch/gitlab/pts/framework/pypts/docs/stable/).

