# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

import re

def sanitize_booleans(yaml_str: str) -> str:
    sanitized_lines = []

    for line in yaml_str.splitlines():
        # Convert the line to lowercase
        line = line.lower()

        # Remove quotes around 'true' or 'false'
        line = re.sub(r"(['\"])\s*(true|false)\s*\1", r"\2", line)

        sanitized_lines.append(line)

    return "\n".join(sanitized_lines)

# Example usage:
yaml_content = """
step1:
  skip: 'True'
step2:
  skip: "FALSE"
step3:
  skip: True
step4:
  skip: 'FaLsE'
"""

normalized_yaml = sanitize_booleans(yaml_content)
print(normalized_yaml)
