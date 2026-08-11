# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The debug console - a development frontend, not a product one.

Reached with `python -m pypts --mode debug`. It is a third HmiClient beside the
GUI and the CLI, so it speaks the same protocol CORE already knows; what it adds
is a view of the links no frontend can normally see, and the ability to put
messages on them.

    tap.py            ChannelTap - the observer that copies traffic to the console
    console.py        the window, and DebugConsole(HmiClient)
    trace_model.py    the Qt model behind the trace table
    inject_panel.py   curated buttons and the generic message form
    message_forms.py  builds a form from a message dataclass by introspection
"""
