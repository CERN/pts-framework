# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
The verdict colors, exactly as the old GUI painted them.

Operators know these at a glance, which is why they survived the rebuild
unchanged (old_code/utils.py get_step_result_colors, recorded in gui.md
section 2). Presentation only - nothing outside hmi/gui/ may care what color
a FAIL is.
"""

from pypts.messages.common_messages import ResultType

#: ResultType -> (background, text) as CSS hex colors.
RESULT_COLORS: dict[ResultType, tuple[str, str]] = {
    ResultType.PASS: ("#C8E6C9", "#1B4F24"),
    ResultType.FAIL: ("#F28B82", "#7B0000"),
    ResultType.DONE: ("#B2EBF2", "#004D52"),
    ResultType.SKIP: ("#FFF9C4", "#C49000"),
    ResultType.ERROR: ("#FFCC80", "#BF360C"),
    ResultType.STOP: ("#D3D3D3", "#4B4B4B"),
}

#: For a result nobody mapped - white on black, visibly wrong on purpose.
FALLBACK_COLORS = ("#FFFFFF", "#000000")
