.. SPDX-FileCopyrightText: 2026 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

GUI Architecture
================

This page describes the current high-level structure of the two graphical
applications shipped with ``pypts``:

* the runtime application launched with ``python -m pypts``
* the recipe editor application known as ``YamVIEW``

The two applications are still separate Qt windows and, when launched from the
runtime GUI, separate processes. They now share a common theme layer and a
common visual language, but they do not yet share all widgets.

Runtime GUI
-----------

The runtime GUI is built around :class:`pypts.gui.MainWindow`. It is a
panelized ``QMainWindow`` composed from smaller widgets and helper modules.

Startup path
~~~~~~~~~~~~

The standard startup path is:

1. ``pypts.__main__`` creates the backend API with ``run_pts()``
2. ``pypts.startup.create_and_start_gui()`` creates the ``QApplication`` and ``MainWindow``
3. the runtime/event-proxy layer is connected to the window slots
4. ``app.exec()`` starts the Qt event loop

Main window structure
~~~~~~~~~~~~~~~~~~~~~

``MainWindow`` contains the following major areas:

* a menu bar
* a top toolbar
* a top tab bar representing the current screen state: Idle, Running, Prompt, Results
* a recipe label area
* a central horizontal splitter with left and right panels
* a status bar

The left and right panels are intentionally distinct:

* left side: sequence progress and final results
* right side: operator interaction and log output

The left side uses a stacked widget so the window can switch between:

* an idle placeholder
* a live step-status table
* a final hierarchical results panel

The right side contains:

* an interaction panel for images, prompts, and runtime buttons
* a log panel for textual runtime output

Runtime window diagram
~~~~~~~~~~~~~~~~~~~~~~

The runtime window is structured approximately as follows:

.. code-block:: text

   +---------------------------------------------------------------+
   | Menu Bar                                                      |
   +---------------------------------------------------------------+
   | Toolbar                                                       |
   +---------------------------------------------------------------+
   | Screen Tabs: Idle | Running | Prompt | Results                |
   +---------------------------------------------------------------+
   | Recipe Label / Description                                    |
   +-------------------------------+-------------------------------+
   | Left Panel                    | Right Panel                   |
   |                               |                               |
   |  +-------------------------+  |  +-------------------------+  |
   |  | Idle Placeholder       |  |  | Interaction Panel       |  |
   |  | or Live Step Table     |  |  | - image                 |  |
   |  | or Results Panel       |  |  | - prompt text           |  |
   |  |                         |  |  | - action buttons        |  |
   |  +-------------------------+  |  +-------------------------+  |
   |                               |                               |
   |                               |  +-------------------------+  |
   |                               |  | Log Panel               |  |
   |                               |  +-------------------------+  |
   +-------------------------------+-------------------------------+
   | Status Bar                                                    |
   +---------------------------------------------------------------+

Reusable runtime widgets
~~~~~~~~~~~~~~~~~~~~~~~~

The panelized runtime GUI is assembled from reusable components in
``pypts.gui_components``:

* ``PtsToolBar``: top action bar
* ``StepTable``: live execution table
* ``ResultsPanel``: hierarchical results tree and summary badges
* ``InteractionPanel``: prompt/image/button area for operator interaction
* ``LogPanel``: formatted runtime log display
* ``resources`` and ``styles``: assets and base style tokens

This split keeps ``MainWindow`` focused on orchestration and screen changes
instead of widget-specific rendering logic.

Theme system
~~~~~~~~~~~~

The shared theme layer lives in ``pypts.gui_theme``.

It is responsible for:

* detecting whether the operating system is currently using a dark color scheme
* listening for Qt color-scheme changes where supported
* providing shared palette values
* exposing the top-level stylesheet used by ``YamVIEW``

The runtime GUI still uses its existing reusable widgets from
``pypts.gui_components``, but initial dark-mode state and OS theme synchronization
now come from the shared theme helper instead of a local hardcoded toggle.

YamVIEW / Recipe Editor
-----------------------

The recipe editor is still implemented in the ``pypts.YamVIEW`` package and is
centered around :class:`pypts.YamVIEW.recipe_creator.RecipeEditorMainMenu`.

High-level layout
~~~~~~~~~~~~~~~~~

The editor window contains:

* a menu bar
* a toolbar for file/editing actions
* a status field for recipe validation state
* a main split view with:
  
  * a sequencer panel on the left
  * a YAML editor on the right

* a log console at the bottom
* a watermark/empty-state screen shown when no recipe is open

The main editing widgets are still specific to ``YamVIEW``:

* ``SequencerWidget`` for sequence/step manipulation
* ``ScintillaYamlEditor`` for YAML text editing and highlighting
* several recipe-editing dialogs in ``recipe_step_setup.py`` and related modules

Relationship Between The Two GUIs
---------------------------------

Before the refactor, the runtime GUI and ``YamVIEW`` were visually and
structurally mostly separate.

Current state:

* they are still separate windows
* the runtime GUI launches ``YamVIEW`` as a separate process when editing a recipe
* they now share dark-mode detection and theme tokens
* they now use a shared visual palette so they look like the same product family
* they still do not share most concrete widgets

In practice, this means:

* shared: palette, top-level style rules, OS dark-mode behavior
* separate: layout implementation, editor widgets, runtime widgets

Runtime/editor relationship diagram
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The two GUIs are related like this at a high level:

.. code-block:: text

   +-------------------------------+
   | pypts runtime process         |
   |                               |
   |  run_pts()                    |
   |    -> backend API             |
   |  create_and_start_gui()       |
   |    -> QApplication            |
   |    -> MainWindow              |
   |                               |
   |  MainWindow                   |
   |    -> uses pypts.gui_components
   |    -> uses pypts.gui_theme    |
   |    -> can launch YamVIEW      |
   +---------------+---------------+
                   |
                   | subprocess.Popen(...)
                   v
   +-------------------------------+
   | YamVIEW editor process        |
   |                               |
   |  QApplication                 |
   |  RecipeEditorMainMenu         |
   |    -> SequencerWidget         |
   |    -> ScintillaYamlEditor     |
   |    -> editor dialogs          |
   |    -> uses pypts.gui_theme    |
   +-------------------------------+

Both applications therefore share theme behavior, but not the same main widget
tree.

This is an intentional intermediate architecture. The UI is already unified at
the theme level, while widget-level convergence can happen incrementally later.

Why The Runtime GUI Is Called Panelized
---------------------------------------

The runtime GUI is described as panelized because the window is composed from
independent functional panels rather than one monolithic central widget.

Examples:

* the interaction area is its own panel widget
* the logging area is its own panel widget
* the results display is its own panel widget
* the live step display is its own panel widget

This provides several practical benefits:

* clearer ownership of GUI behavior
* easier targeted tests for individual panels
* easier theming and visual refreshes
* less coupling between execution flow and rendering details

See also
--------

* :doc:`usage`
* :doc:`gui_event_handling`
* :doc:`architecture`
