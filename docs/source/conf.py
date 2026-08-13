# SPDX-FileCopyrightText: 2025 'CERN'
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import datetime
import sys
from pathlib import Path

from pypts._version import __version__

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


project = "pypts"
author = "Alvaro Martinez Landete"
version = __version__

copyright = f"{datetime.datetime.now(datetime.UTC).year}, CERN"


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
html_theme = "alabaster"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]
html_show_sphinx = False
html_show_sourcelink = True


def _generate_recipe_language_docs(app):
    """Generate the schema and its human reference for this Sphinx build."""
    from spikes.recipe_pydantic.artifacts import write_artifacts

    generated = Path(app.srcdir) / "_generated"
    write_artifacts(
        generated / "recipe_language.schema.json",
        generated / "recipe_language_reference.rst",
    )


def setup(app):
    app.connect("builder-inited", _generate_recipe_language_docs)
    return {"parallel_read_safe": True, "parallel_write_safe": True}


# -- Options for sphinx.ext.autosummary

autosummary_generate = True
autosummary_imported_members = True
