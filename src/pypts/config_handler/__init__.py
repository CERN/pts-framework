# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Configuration for the whole framework.

    from pypts.config_handler import ConfigHandler

    ConfigHandler.bootstrap()                        # launcher, once, first
    ConfigHandler().get_parameter("paths.logs_dir")  # anywhere, any process

The file lives in the per-user configuration directory of the platform
(`%LOCALAPPDATA%\\pypts` on Windows, `~/.config/pypts` on Linux) and is created
from a template the first time pypts runs. See `config_handler.py` for the
rules, `configuration_schema.py` for what the file contains, and
`file_locations.py` for where it is.
"""

from pypts.config_handler.config_handler import (
    ConfigError,
    ConfigFileMissing,
    ConfigHandler,
    ConfigKeyError,
    ConfigSchemaError,
    ConfigWriteError,
    Role,
)

__all__ = [
    "ConfigError",
    "ConfigFileMissing",
    "ConfigHandler",
    "ConfigKeyError",
    "ConfigSchemaError",
    "ConfigWriteError",
    "Role",
]
