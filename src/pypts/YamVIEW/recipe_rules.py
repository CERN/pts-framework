# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

# Define required fields and expected types for top-level recipe sections
RECIPE_HEADER_REQUIRED_FIELDS = {
    "version": str,
    "description": str,
    "main_sequence": str,
    "globals": dict,
    "continue_on_error": bool,
}

RECIPE_SEQUENCE_REQUIRED_FIELDS = {
    "description": str,
    "setup_steps": list,
    "steps": list,  # we expect steps subsection, validated separately
    "teardown_steps": list,
    "parameters": dict,
    "outputs": dict,
    "locals": dict,
}

# Define required fields for step types
STEP_REQUIRED_FIELDS = {
    "userinteractionstep": ["steptype", "step_name", "description"],
    "waitstep": ["steptype", "step_name", "description"],
    "pythonmodulestep": ["steptype", "step_name", "action_type", "module", "method_name", "description"],
    "userloadingstep" : ["steptype", "step_name", "description"],
    "userrunmethodstep": ["steptype", "step_name", "action_type", "module", "description"],
    "userwritestep": ["steptype", "step_name", "description"],
    "sshconnectstep": ["steptype", "step_name", "description"],
    "sshclosestep": ["steptype", "step_name", "description"],
    "default": ["steptype", "step_name", "action_type", "module", "method_name", "description"],
}