# SPDX-FileCopyrightText: 2025 'CERN'
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import datetime
import importlib.util

from pypts._version import __version__


project = "pypts"
author = "Alvaro Martinez Landete"
version = __version__

copyright = "{0}, CERN".format(datetime.datetime.now().year)


# -- General configuration ----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.doctest',
    'sphinx.ext.napoleon',
]
if importlib.util.find_spec("acc_py_sphinx") is not None:
    extensions.insert(0, "acc_py_sphinx.theme")


# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "acc_py" if "acc_py_sphinx.theme" in extensions else "alabaster"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]
html_show_sphinx = False
html_show_sourcelink = True


# -- Options for sphinx.ext.autosummary

autosummary_generate = True
autosummary_imported_members = True
