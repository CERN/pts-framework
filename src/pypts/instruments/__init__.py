# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
pypts instrument drivers.

Each sub-package corresponds to a manufacturer and contains one module per
model.  Every driver is a thin subclass of the corresponding pymeasure driver;
only behaviour that is *not* present in upstream pymeasure lives here.

Upstream building blocks (Instrument, VISAAdapter, ProtocolAdapter, validators,
expected_protocol, …) are imported directly from pymeasure — do not duplicate
them here.
"""
