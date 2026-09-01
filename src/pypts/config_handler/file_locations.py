# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Where pypts keeps its files on this machine.

Two functions, deliberately trivial, deliberately in their own module. They are
the only place in the framework that decides a location, and they are the seam
the unit tests monkeypatch: a test points `config_file_path` at `tmp_path` and
the whole handler follows it there, with no environment variable and no
constructor argument to thread through.

That is also why `config_handler.py` calls them as
`file_locations.config_file_path()`
rather than importing the names directly - a `from ... import` would bind the
original function and make the monkeypatch invisible.

The previous implementation put everything under `tempfile.gettempdir()`, which
is lost on cleanup and awkward for a bench with a fixed configuration. These are
the conventional per-user locations instead:

    Windows   config  %LOCALAPPDATA%\\pypts\\config.ini
              data    %LOCALAPPDATA%\\pypts\\{logs,reports}
    Linux     config  ~/.config/pypts/config.ini
              data    ~/.local/share/pypts/{logs,reports}
              state   ~/.local/state/pypts/recent_recipes.json

Config, data and state are three different things, and that split is why there
are three functions rather than one. *Config* is the user's - pypts reads it and
never rewrites it. *Data* is output the user would miss if it vanished: logs and
reports. *State* is what pypts keeps for its own convenience - the recent-recipes
list today, a window size or a last-used folder tomorrow: app-owned, rewritten
constantly, and losing it costs a convenience rather than information. None of it
is a *cache*, which would mean a copy of something pypts could recompute; there is
nothing of that kind here yet, and `platformdirs.user_cache_dir` is where it would
go if there ever is.

On Windows all three collapse onto %LOCALAPPDATA%\\pypts, so the distinction costs
nothing there and is correct on Linux.

There is no override - no `--config` flag, no environment variable. Every
process resolves the same path by computing it, which is what lets a child
process read the configuration without anything being passed to it.
"""

from pathlib import Path

import platformdirs

#: The application name every location is built from. `appauthor=False` keeps
#: the Windows path at %LOCALAPPDATA%\pypts instead of inserting a vendor
#: directory nobody would recognise.
APP_NAME = "pypts"

#: The file name inside the config directory.
CONFIG_FILE_NAME = "config.ini"

#: The file name inside the state directory.
RECENT_RECIPES_FILE_NAME = "recent_recipes.json"


def config_dir() -> Path:
    """The per-user directory holding config.ini."""
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def config_file_path() -> Path:
    """
    Full path of the configuration file, whether or not it exists yet.

    Monkeypatch this in tests; everything else derives from it.
    """
    return config_dir() / CONFIG_FILE_NAME


def state_dir() -> Path:
    """The per-user directory holding what pypts remembers between runs."""
    return Path(platformdirs.user_state_dir(APP_NAME, appauthor=False))


def recent_recipes_path() -> Path:
    """
    Full path of the recent-recipes list, whether or not it exists yet.

    Monkeypatch this in tests, the way `config_file_path` is monkeypatched; the
    store asks nothing else where its file lives.
    """
    return state_dir() / RECENT_RECIPES_FILE_NAME


def default_data_dir() -> Path:
    """
    Where logs and reports go unless the user says otherwise.

    Only ever read once, when the config file is created: it becomes the stored
    value of `paths.base_dir`, and from then on the file is the authority. A
    user who edits that value keeps it - this function is not consulted again.
    """
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
