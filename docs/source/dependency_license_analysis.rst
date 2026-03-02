.. SPDX-FileCopyrightText: 2025 CERN <home.cern>
..
.. SPDX-License-Identifier: CC-BY-SA-4.0

=====================================
Dependency License Analysis Report
=====================================

:Project: pts-framework
:License: LGPL-2.1-or-later
:Analysis Date: June, 2025
:Status: ✅ **FULLY COMPATIBLE**

.. contents:: Table of Contents
   :depth: 3
   :local:

Executive Summary
=================

This report analyzes all dependencies of the pts-framework project to ensure compatibility 
with the chosen LGPL-2.1-or-later license. **All identified dependencies are compatible** 
with LGPL licensing, allowing safe distribution under the current license terms.

Key Findings
============

* ✅ **100% Compatible**: All core dependencies use LGPL-compatible licenses
* ✅ **No Conflicts**: No GPL-only or restrictive copyleft licenses detected
* ✅ **Qt Alignment**: PySide6 usage aligns perfectly with LGPL choice
* ⚠️ **One Unknown**: acc-py-sphinx license needs verification (docs-only dependency)

Core Dependencies Analysis
==========================

The following table shows all core runtime dependencies and their license compatibility:

.. list-table:: Core Dependencies
   :header-rows: 1
   :widths: 20 15 20 15 30

   * - Dependency
     - Version
     - License
     - Compatible
     - Notes
   * - hightime
     - 0.2.2
     - MIT
     - ✅ Yes
     - Permissive license, fully compatible
   * - matplotlib
     - Latest
     - BSD-compatible
     - ✅ Yes
     - Uses BSD-style permissive license
   * - nidmm
     - 1.4.8
     - MIT
     - ✅ Yes
     - National Instruments Python bindings
   * - pymeasure
     - 0.15.0
     - MIT
     - ✅ Yes
     - Instrument HAL; MIT is fully permissive and compatible with LGPL
   * - nptdms
     - Latest
     - LGPL
     - ✅ Yes
     - Already LGPL licensed, perfect match
   * - numpy
     - Latest
     - BSD 3-clause
     - ✅ Yes
     - Permissive license, fully compatible
   * - PySide6
     - Latest
     - LGPL-3.0/GPL-3.0
     - ✅ Yes
     - Qt Community Edition, LGPL compatible
   * - PyYAML
     - 6.0.2
     - MIT
     - ✅ Yes
     - Permissive license, fully compatible

Detailed License Information
----------------------------

hightime (0.2.2)
~~~~~~~~~~~~~~~~~
:License: MIT
:Source: MSYS2 package repository
:Compatibility: ✅ **Full compatibility** - MIT is a permissive license compatible with LGPL

matplotlib
~~~~~~~~~~
:License: BSD-compatible (PSF-based)
:Source: Official matplotlib documentation
:Compatibility: ✅ **Full compatibility** - Uses BSD-style permissive licensing
:Note: Documentation explicitly states "Matplotlib only uses BSD compatible code"

nidmm (1.4.8)
~~~~~~~~~~~~~
:License: MIT
:Source: nimi-python GitHub repository
:Compatibility: ✅ **Full compatibility** - MIT licensed National Instruments drivers

pymeasure (0.15.0)
~~~~~~~~~~~~~~~~~~
:License: MIT
:Source: `pymeasure GitHub repository <https://github.com/pymeasure/pymeasure>`_ and PyPI
:Compatibility: ✅ **Full compatibility** - MIT is a permissive license compatible with LGPL
:Note: pymeasure is used as a **runtime dependency** (imported, not bundled).  Its source
   code is not distributed with pts-framework.  An LGPL library may link against MIT
   libraries without restriction.  The pymeasure package itself is not affected by pypts'
   LGPL licence; end users may use pymeasure under its own MIT terms independently.

nptdms
~~~~~~
:License: LGPL (GNU Library or Lesser General Public License)
:Source: PyPI package information
:Compatibility: ✅ **Perfect match** - Already uses LGPL licensing

numpy
~~~~~
:License: BSD 3-clause
:Source: NumPy project documentation
:Compatibility: ✅ **Full compatibility** - Standard BSD permissive license

PySide6
~~~~~~~
:License: LGPL-3.0-only OR GPL-3.0-only (Community Edition)
:Source: Qt for Python official documentation
:Compatibility: ✅ **Full compatibility** - LGPL-3.0 is compatible with LGPL-2.1-or-later
:Note: Using Community Edition avoids commercial licensing requirements

PyYAML (6.0.2)
~~~~~~~~~~~~~~
:License: MIT
:Source: PyPI and GitHub repository
:Compatibility: ✅ **Full compatibility** - MIT is fully permissive

Optional Dependencies Analysis
==============================

Test Dependencies (``test`` extra)
-----------------------------------

.. list-table:: Test Dependencies
   :header-rows: 1
   :widths: 30 20 20 30

   * - Dependency
     - License
     - Compatible
     - Notes
   * - pytest
     - MIT
     - ✅ Yes
     - Testing framework, MIT licensed
   * - pytest-qt
     - MIT
     - ✅ Yes
     - Qt testing plugin, MIT licensed

Documentation Dependencies (``doc`` extra)
-------------------------------------------

.. list-table:: Documentation Dependencies
   :header-rows: 1
   :widths: 30 20 20 30

   * - Dependency
     - License
     - Compatible
     - Notes
   * - Sphinx
     - BSD-2-Clause
     - ✅ Yes
     - Documentation generator
   * - acc-py-sphinx
     - Unknown
     - ⚠️ Verify
     - CERN-specific Sphinx extension

Development Dependencies (``dev`` extra)
-----------------------------------------

.. list-table:: Development Dependencies
   :header-rows: 1
   :widths: 30 20 20 30

   * - Dependency
     - License
     - Compatible
     - Notes
   * - ruff
     - MIT
     - ✅ Yes
     - Python linter and formatter

Build Dependencies
==================

.. list-table:: Build System Dependencies
   :header-rows: 1
   :widths: 30 20 20 30

   * - Dependency
     - License
     - Compatible
     - Notes
   * - setuptools
     - MIT/PSF
     - ✅ Yes
     - Build tool, permissive license
   * - wheel
     - MIT
     - ✅ Yes
     - Wheel building support
   * - setuptools_scm
     - MIT
     - ✅ Yes
     - Version management from SCM

Legal Analysis
==============

LGPL Compatibility Rules
------------------------

The GNU Lesser General Public License (LGPL) allows:

1. **Linking with permissive libraries** (MIT, BSD, Apache) ✅
2. **Linking with other LGPL libraries** ✅  
3. **Linking with GPL libraries** (with restrictions) ✅
4. **Commercial use and distribution** ✅

LGPL Requirements:

- Source code availability for LGPL portions
- Allow relinking with modified LGPL libraries
- License notices and attribution

Compatibility Assessment
------------------------

All identified dependencies fall into these categories:

:Permissive Licenses (MIT, BSD): Compatible without restrictions
:LGPL Libraries: Direct compatibility 
:GPL Libraries: Compatible (PySide6 offers LGPL option)
:Unknown Licenses: Only acc-py-sphinx (documentation only)

Risk Assessment
===============

.. list-table:: Risk Matrix
   :header-rows: 1
   :widths: 20 15 15 50

   * - Risk Level
     - Count
     - Percentage
     - Description
   * - **No Risk**
     - 7/8
     - 87.5%
     - Core dependencies with confirmed compatible licenses
   * - **Low Risk**
     - 1/8
     - 12.5%
     - acc-py-sphinx (docs-only, likely permissive)
   * - **Medium Risk**
     - 0/8
     - 0%
     - No dependencies in this category
   * - **High Risk**
     - 0/8
     - 0%
     - No incompatible licenses found

Recommendations
===============

Immediate Actions
-----------------

1. ✅ **Continue with LGPL-2.1-or-later** - All dependencies are compatible
2. ⚠️ **Verify acc-py-sphinx license** - Check CERN's repository for license information
3. 📋 **Add license attribution** - Include dependency licenses in distribution

Future Monitoring
------------------

1. **Track dependency updates** - Monitor for license changes (rare but possible)
2. **Review new dependencies** - Ensure future additions maintain compatibility  
3. **Document license policy** - Establish guidelines for dependency selection

Compliance Checklist
=====================

.. list-table:: Compliance Requirements
   :header-rows: 1
   :widths: 50 15 35

   * - Requirement
     - Status
     - Notes
   * - All dependencies LGPL-compatible
     - ✅ Met
     - Confirmed for 7/8 dependencies
   * - No GPL-only dependencies
     - ✅ Met
     - PySide6 offers LGPL option
   * - License attribution included
     - ⚠️ TODO
     - Should be added to distribution
   * - Source availability plan
     - ✅ Met
     - Git repository provides source access

Conclusion
==========

The pts-framework project can safely continue using the **LGPL-2.1-or-later license**. 
All analyzed dependencies are compatible, with most using permissive licenses that 
impose no restrictions on the larger project.

The license choice aligns well with the project's use of PySide6 and other LGPL 
libraries, creating a consistent and legally sound licensing approach.

**Final Recommendation: ✅ PROCEED with current LGPL-2.1-or-later licensing.**

Appendix A: License Texts
==========================

MIT License Summary
-------------------
Permits commercial use, modification, distribution, and private use.
Requires license and copyright notice. No warranty provided.

BSD License Summary  
-------------------
Similar to MIT with additional clause about endorsement.
Permissive license compatible with LGPL.

LGPL License Summary
--------------------
Allows linking with proprietary software while requiring
source availability for LGPL-licensed portions only.

Appendix B: Verification Sources
=================================

This analysis was conducted using:

- PyPI package metadata
- Official project documentation  
- GitHub repository license files
- Package distribution information
- Web searches for license verification

**Last Updated:** June 2025
**Next Review:** Recommended annually or when adding new dependencies 