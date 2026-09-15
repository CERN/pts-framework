"""
Recipe verificator: validate a recipe YAML file or string and return every
problem found in one pass, with verbose, line-numbered diagnostics.

The public surface is two functions:

    verify_file(path)    -> list[ValidationIssue]
    verify_string(text)  -> list[ValidationIssue]

Both collect *all* problems before returning (no bail-out on first error),
so the author sees the full picture in one round trip. The schema source of
truth is pypts.recipe.rules - if rules.py changes, update the hint strings
and the known-key sets in this file to match.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pypts.recipe import rules
from pypts.step import indexed_step
from pypts.helper_applications.recipe_verificator.issue import ValidationIssue


# ---------------------------------------------------------------------------
# Keys that existed in the old recipe format and were deliberately removed.
# A recipe that still carries them gets a targeted warning rather than a
# generic "unknown key" message.
# ---------------------------------------------------------------------------
_REMOVED_SEQUENCE_KEYS: dict[str, str] = {
    "setup_steps": (
        "'setup_steps' was removed. Steps that belonged in setup_steps go at "
        "the front of 'steps' instead."
    ),
    "parameters": (
        "'parameters' was removed. Sequences no longer declare a call interface "
        "(SequenceStep is dropped). Remove this key."
    ),
    "outputs": (
        "'outputs' as a sequence-level key was removed (step-level 'outputs' "
        "mappings are still valid). Remove this key from the sequence header."
    ),
    "locals": (
        "'locals' was removed. There is now one scope for the whole run: "
        "'globals'. Declare variables there and read them from a step with "
        "{type: global, global_name: <name>}."
    ),
}

# Keys a sequence document may carry under the current schema.
_KNOWN_SEQUENCE_KEYS: frozenset[str] = frozenset(
    list(rules.SEQUENCE_REQUIRED) + list(rules.SEQUENCE_DEFAULTS)
)

# Common keys valid on every step regardless of type.
_STEP_COMMON_VALID: frozenset[str] = (
    frozenset(rules.STEP_REQUIRED) | frozenset(rules.STEP_COMMON_DEFAULTS)
)

# Per-type extra valid keys: required + optional (from STEP_TYPE_DEFAULTS).
_STEP_TYPE_VALID: dict[str, frozenset[str]] = {
    steptype: (
        frozenset(required)
        | frozenset(rules.STEP_TYPE_DEFAULTS.get(steptype, {}).keys())
    )
    for steptype, required in rules.STEP_TYPE_REQUIRED.items()
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_file(path: Path | str) -> list[ValidationIssue]:
    """Verify a recipe YAML file. Returns all issues, errors before warnings."""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [
            ValidationIssue(
                severity="error",
                field="file",
                message=f"Cannot read file: {exc}",
                hint="Check that the path is correct and the file is readable.",
            )
        ]
    return verify_string(content)


def verify_string(content: str) -> list[ValidationIssue]:
    """Verify a recipe YAML string. Returns all issues, errors before warnings."""
    ctx = _Context()
    _run(content, ctx)
    return sorted(ctx.issues, key=lambda i: (i.severity != "error", i.line or 0))


# ---------------------------------------------------------------------------
# Internal pipeline
# ---------------------------------------------------------------------------

class _Context:
    """Accumulates issues during one verification run."""

    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def error(
        self, field: str, message: str, hint: str, line: int | None = None
    ) -> None:
        self.issues.append(
            ValidationIssue("error", field, message, hint, line)
        )

    def warning(
        self, field: str, message: str, hint: str, line: int | None = None
    ) -> None:
        self.issues.append(
            ValidationIssue("warning", field, message, hint, line)
        )


class _LineMap:
    """Maps YAML key paths (tuples) to 1-based line numbers."""

    def __init__(self, node: yaml.Node) -> None:
        self._map: dict[tuple, int] = {}
        self.document_line: int = node.start_mark.line + 1
        self._walk(node, ())

    def _walk(self, node: yaml.Node, path: tuple) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = key_node.value
                child = path + (key,)
                self._map[child] = key_node.start_mark.line + 1
                self._walk(value_node, child)
        elif isinstance(node, yaml.SequenceNode):
            for i, item_node in enumerate(node.value):
                child = path + (i,)
                self._map[child] = item_node.start_mark.line + 1
                self._walk(item_node, child)

    def get(self, *path: str | int) -> int | None:
        return self._map.get(path)


def _run(content: str, ctx: _Context) -> None:
    """Top-level pipeline: parse → structure → header → sequences → cross-refs."""
    # Pass 1 — YAML parsing
    try:
        nodes = list(yaml.compose_all(content))
        docs: list[Any] = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        ctx.error(
            field="yaml",
            message=f"YAML parsing error: {exc}",
            hint=(
                "The file is not valid YAML. Common causes: inconsistent "
                "indentation, a colon without a space after it, or an "
                "unquoted special character such as ':' or '#' inside a value."
            ),
        )
        return

    if not docs:
        ctx.error(
            field="file",
            message="The file is empty or contains no YAML documents.",
            hint=(
                "A recipe needs at least a header document (starting with "
                "'name:') and one sequence document (starting with "
                "'sequence_name:'), separated by '---'."
            ),
        )
        return

    # Pass 2 — each document must be a mapping
    valid: list[tuple[dict[str, Any], yaml.Node]] = []
    for i, (doc, node) in enumerate(zip(docs, nodes)):
        if not isinstance(doc, dict):
            ctx.error(
                field=f"document[{i}]",
                message=f"Document {i + 1} is not a YAML mapping.",
                hint=(
                    "Every document in a recipe must be a mapping (key: value "
                    "pairs). Check for a stray '---' separator or a bare value "
                    "at the top level."
                ),
                line=node.start_mark.line + 1,
            )
        else:
            valid.append((doc, node))

    if not valid:
        return

    header_doc, header_node = valid[0]
    sequence_pairs = valid[1:]

    # Confirm the first document is the header and not a sequence
    has_name = "name" in header_doc
    has_seq = "sequence_name" in header_doc
    if has_seq and not has_name:
        ctx.error(
            field="document[0]",
            message="The first document looks like a sequence, not a header.",
            hint=(
                "The first document must be the recipe header and start with "
                "'name:'. Sequence documents follow after '---', each starting "
                "with 'sequence_name:'."
            ),
            line=header_node.start_mark.line + 1,
        )
        return
    if not has_name and not has_seq:
        ctx.error(
            field="document[0]",
            message="Cannot identify the first document as a recipe header.",
            hint=(
                "The first document must start with 'name: <recipe name>'. "
                "Sequence documents start with 'sequence_name: <name>'."
            ),
            line=header_node.start_mark.line + 1,
        )
        return

    if not sequence_pairs:
        ctx.error(
            field="file",
            message="The recipe has a header but no sequence documents.",
            hint=(
                "Add at least one sequence after the header, separated by "
                "'---'.\nExample:\n"
                "  ---\n"
                "  sequence_name: Main\n"
                "  steps:\n"
                "    - steptype: Wait\n"
                "      step_name: Pause\n"
                "      wait_time: 1"
            ),
        )

    # Pass 3 — header content
    header_lm = _LineMap(header_node)
    _check_header(header_doc, header_lm, ctx)

    # Pass 4 — sequence content
    seq_names: list[str] = []
    for seq_idx, (seq_doc, seq_node) in enumerate(sequence_pairs):
        seq_lm = _LineMap(seq_node)
        name = _check_sequence(seq_doc, seq_lm, seq_idx, ctx)
        if name:
            seq_names.append(name)

    # Pass 5 — cross-document references
    _check_cross_references(header_doc, seq_names, ctx)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _check_header(doc: dict[str, Any], lm: _LineMap, ctx: _Context) -> None:
    # Required fields
    for field in rules.HEADER_REQUIRED:
        line = lm.get(field)
        value = doc.get(field)
        if value is None:
            ctx.error(
                field=f"header.{field}",
                message=f"Missing required field '{field}'.",
                hint=_header_required_hint(field),
                line=line,
            )
            continue

        # `version: 0.2` is a float in YAML; the parser accepts it via str().
        # We do the same: scalars are fine, non-scalars are not.
        if isinstance(value, (dict, list)):
            ctx.error(
                field=f"header.{field}",
                message=(
                    f"'{field}' must be a scalar value (string or number), "
                    f"got {type(value).__name__}."
                ),
                hint=f"Example:  {field}: My Recipe",
                line=line,
            )
        elif not str(value).strip():
            ctx.warning(
                field=f"header.{field}",
                message=f"'{field}' is empty.",
                hint=f"Give the recipe a meaningful {field}.",
                line=line,
            )
        elif field == "version" and not isinstance(value, str):
            ctx.warning(
                field=f"header.{field}",
                message=(
                    f"'version' is written as a number ({value}). "
                    f"PyPTS accepts it, but quoting avoids ambiguity."
                ),
                hint=f"Example:  version: '0.2'  or  version: \"0.2\"",
                line=line,
            )

    # Optional — description
    _check_optional_str(doc, "description", "header.description", lm, ctx)

    # Optional — main_sequence
    if "main_sequence" in doc and doc["main_sequence"] is not None:
        v = doc["main_sequence"]
        if not isinstance(v, str):
            ctx.error(
                field="header.main_sequence",
                message=(
                    f"'main_sequence' must be a string (the name of the "
                    f"sequence to run first), got {type(v).__name__}."
                ),
                hint=(
                    "Example:  main_sequence: Main\n"
                    "If omitted the first sequence in the file is used."
                ),
                line=lm.get("main_sequence"),
            )

    # Optional — globals
    if "globals" in doc and doc["globals"] is not None:
        v = doc["globals"]
        if not isinstance(v, dict):
            ctx.error(
                field="header.globals",
                message=(
                    f"'globals' must be a mapping of variable names to "
                    f"initial values, got {type(v).__name__}."
                ),
                hint=(
                    "Example:\n"
                    "  globals:\n"
                    "    serial_number: ''\n"
                    "    voltage: 0"
                ),
                line=lm.get("globals"),
            )

    # Optional — report_metadata
    if "report_metadata" in doc and doc["report_metadata"] is not None:
        rm = doc["report_metadata"]
        rm_line = lm.get("report_metadata")
        if not isinstance(rm, list):
            ctx.error(
                field="header.report_metadata",
                message=(
                    f"'report_metadata' must be a list of global variable "
                    f"names, got {type(rm).__name__}."
                ),
                hint="Example:  report_metadata: [serial_number, lot_number]",
                line=rm_line,
            )
        else:
            for i, entry in enumerate(rm):
                if not isinstance(entry, str) or not entry.strip():
                    ctx.error(
                        field=f"header.report_metadata[{i}]",
                        message=f"report_metadata[{i}] is not a non-empty string.",
                        hint=(
                            "Each entry must be the name of a globals variable "
                            "whose value is stamped on every row of the report."
                        ),
                        line=lm.get("report_metadata", i),
                    )


def _header_required_hint(field: str) -> str:
    return {
        "name": (
            "Every recipe needs a unique name so the operator and the report "
            "can identify what was run.\nExample:  name: Output Voltage Test"
        ),
        "version": (
            "Every recipe must declare which PyPTS version it targets. The "
            "framework warns when they differ.\nExample:  version: 0.2"
        ),
    }.get(field, f"Add '{field}' to the recipe header.")


# ---------------------------------------------------------------------------
# Sequence
# ---------------------------------------------------------------------------

def _check_sequence(
    doc: dict[str, Any],
    lm: _LineMap,
    seq_idx: int,
    ctx: _Context,
) -> str:
    """Check one sequence document. Returns the sequence name (or '')."""
    raw_name = doc.get("sequence_name")
    seq_label = f"sequences[{seq_idx}]" if raw_name is None else f"sequence '{raw_name}'"

    # Required — sequence_name
    if raw_name is None:
        ctx.error(
            field=f"sequences[{seq_idx}].sequence_name",
            message="Missing required field 'sequence_name'.",
            hint=(
                "Each sequence document must begin with "
                "'sequence_name: <name>'. The first document is the recipe "
                "header (starts with 'name:'); every document after it is a "
                "sequence."
            ),
            line=lm.document_line,
        )
    elif not isinstance(raw_name, str) or not str(raw_name).strip():
        ctx.error(
            field=f"sequences[{seq_idx}].sequence_name",
            message="'sequence_name' must be a non-empty string.",
            hint="Example:  sequence_name: Main",
            line=lm.get("sequence_name"),
        )

    seq_name = str(raw_name) if isinstance(raw_name, str) and raw_name else ""

    # Required — steps
    if "steps" not in doc:
        ctx.error(
            field=f"{seq_label}.steps",
            message="Missing required field 'steps'.",
            hint=(
                "A sequence must contain at least one step.\nExample:\n"
                "  steps:\n"
                "    - steptype: Wait\n"
                "      step_name: Pause\n"
                "      wait_time: 1"
            ),
            line=lm.document_line,
        )
    elif not isinstance(doc["steps"], list):
        ctx.error(
            field=f"{seq_label}.steps",
            message=(
                f"'steps' must be a list of step mappings, "
                f"got {type(doc['steps']).__name__}."
            ),
            hint="Each entry under 'steps' starts with 'steptype:' and 'step_name:'.",
            line=lm.get("steps"),
        )
    elif not doc["steps"]:
        ctx.error(
            field=f"{seq_label}.steps",
            message="'steps' is empty — a sequence must contain at least one step.",
            hint="Add at least one step mapping under 'steps'.",
            line=lm.get("steps"),
        )
    else:
        _check_step_list(doc["steps"], lm, "steps", seq_label, ctx)

    # Optional — teardown_steps
    if "teardown_steps" in doc and doc["teardown_steps"] is not None:
        td = doc["teardown_steps"]
        if not isinstance(td, list):
            ctx.error(
                field=f"{seq_label}.teardown_steps",
                message=(
                    f"'teardown_steps' must be a list of step mappings, "
                    f"got {type(td).__name__}."
                ),
                hint=(
                    "teardown_steps runs after the sequence finishes, even "
                    "after an abort. Its steps are structured like 'steps'."
                ),
                line=lm.get("teardown_steps"),
            )
        elif td:
            _check_step_list(td, lm, "teardown_steps", seq_label, ctx)

    # Optional — description
    _check_optional_str(doc, "description", f"{seq_label}.description", lm, ctx)

    # Removed keys — specific, actionable warnings
    for old_key, hint in _REMOVED_SEQUENCE_KEYS.items():
        if old_key in doc:
            ctx.warning(
                field=f"{seq_label}.{old_key}",
                message=f"'{old_key}' is not part of the current recipe format.",
                hint=hint,
                line=lm.get(old_key),
            )

    # Truly unknown keys
    known_all = _KNOWN_SEQUENCE_KEYS | frozenset(_REMOVED_SEQUENCE_KEYS)
    for key in doc:
        if key not in known_all:
            ctx.warning(
                field=f"{seq_label}.{key}",
                message=f"Unknown sequence key '{key}' — it will be ignored.",
                hint=(
                    f"Known sequence keys: "
                    f"{', '.join(sorted(_KNOWN_SEQUENCE_KEYS))}."
                ),
                line=lm.get(key),
            )

    return seq_name


# ---------------------------------------------------------------------------
# Step list and individual steps
# ---------------------------------------------------------------------------

def _check_step_list(
    steps: list[Any],
    lm: _LineMap,
    list_key: str,
    seq_label: str,
    ctx: _Context,
) -> None:
    """Validate every step in a list (steps or teardown_steps)."""
    for idx, step_data in enumerate(steps):
        path_prefix = (list_key, idx)
        step_line = lm.get(*path_prefix)
        step_field = f"{seq_label}.{list_key}[{idx}]"

        if not isinstance(step_data, dict):
            ctx.error(
                field=step_field,
                message=f"Step {idx + 1} is not a mapping.",
                hint=(
                    "Each step must be a YAML mapping starting with "
                    "'steptype:' and 'step_name:'. A missing '-' before the "
                    "step or wrong indentation is a common cause."
                ),
                line=step_line,
            )
            continue

        step_name_val = step_data.get("step_name")
        if step_name_val and isinstance(step_name_val, str):
            step_display = f"step '{step_name_val}'"
        else:
            step_display = f"step {idx + 1}"

        _check_step(step_data, lm, path_prefix, step_field, step_display, ctx)


def _check_step(
    step_data: dict[str, Any],
    lm: _LineMap,
    path_prefix: tuple,
    step_field: str,
    step_display: str,
    ctx: _Context,
) -> None:
    """All checks for one step mapping."""
    step_line = lm.get(*path_prefix)

    def field_line(*keys: str | int) -> int | None:
        return lm.get(*path_prefix, *keys)

    # ── Common required: steptype ───────────────────────────────────────────
    steptype_raw = step_data.get("steptype")
    if steptype_raw is None:
        ctx.error(
            field=f"{step_field}.steptype",
            message=f"{step_display.capitalize()}: missing required field 'steptype'.",
            hint=(
                f"Every step must name its type. "
                f"Available: {', '.join(sorted(rules.STEP_TYPE_REQUIRED))}.\n"
                f"Example:  steptype: Wait"
            ),
            line=step_line,
        )
    elif not isinstance(steptype_raw, str):
        ctx.error(
            field=f"{step_field}.steptype",
            message=(
                f"{step_display.capitalize()}: 'steptype' must be a string, "
                f"got {type(steptype_raw).__name__}."
            ),
            hint=(
                f"Available: {', '.join(sorted(rules.STEP_TYPE_REQUIRED))}."
            ),
            line=field_line("steptype"),
        )

    # ── Common required: step_name ──────────────────────────────────────────
    if step_data.get("step_name") is None:
        ctx.error(
            field=f"{step_field}.step_name",
            message=f"Step {_ordinal(path_prefix)}: missing required field 'step_name'.",
            hint=(
                "Every step needs a name that appears in the step table and "
                "the report.\nExample:  step_name: Measure output voltage"
            ),
            line=step_line,
        )
    elif not isinstance(step_data["step_name"], str) or not step_data["step_name"].strip():
        ctx.error(
            field=f"{step_field}.step_name",
            message=(
                f"{step_display.capitalize()}: 'step_name' must be a "
                f"non-empty string."
            ),
            hint="Example:  step_name: Measure output voltage",
            line=field_line("step_name"),
        )

    # Stop early if steptype is not a usable string
    if not isinstance(steptype_raw, str):
        return

    steptype = steptype_raw.lower()

    # ── steptype must be known ──────────────────────────────────────────────
    if steptype not in rules.STEP_TYPE_REQUIRED:
        known = ", ".join(sorted(rules.STEP_TYPE_REQUIRED))
        ctx.error(
            field=f"{step_field}.steptype",
            message=(
                f"{step_display.capitalize()}: unknown step type "
                f"'{steptype_raw}'. Available: {known}."
            ),
            hint=_unknown_steptype_hint(steptype_raw),
            line=field_line("steptype"),
        )
        return

    # ── Type-specific required fields ───────────────────────────────────────
    for field in rules.STEP_TYPE_REQUIRED[steptype]:
        if step_data.get(field) is None:
            ctx.error(
                field=f"{step_field}.{field}",
                message=(
                    f"{step_display.capitalize()}: missing required field "
                    f"'{field}' (required for {steptype_raw} steps)."
                ),
                hint=_step_field_hint(steptype, field),
                line=field_line(field) or step_line,
            )

    # ── Common optional: skip ───────────────────────────────────────────────
    if "skip" in step_data and step_data["skip"] is not None:
        if not isinstance(step_data["skip"], bool):
            ctx.error(
                field=f"{step_field}.skip",
                message=(
                    f"{step_display.capitalize()}: 'skip' must be true or "
                    f"false, got {type(step_data['skip']).__name__}."
                ),
                hint="Example:  skip: true",
                line=field_line("skip"),
            )

    # ── Common optional: continue_on_error ─────────────────────────────────
    if "continue_on_error" in step_data and step_data["continue_on_error"] is not None:
        if not isinstance(step_data["continue_on_error"], bool):
            ctx.error(
                field=f"{step_field}.continue_on_error",
                message=(
                    f"{step_display.capitalize()}: 'continue_on_error' must "
                    f"be true or false, got "
                    f"{type(step_data['continue_on_error']).__name__}."
                ),
                hint=(
                    "continue_on_error: false means an ERROR or FAIL on this "
                    "step ends the run and every subsequent step is SKIP."
                ),
                line=field_line("continue_on_error"),
            )

    # ── Indexed — delegate to the canonical checker ─────────────────────────
    if steptype == "indexed":
        _check_indexed_step(step_data, lm, path_prefix, step_field, step_display, ctx)
        return

    # ── inputs / outputs vocabulary ─────────────────────────────────────────
    _check_inputs(step_data, lm, path_prefix, step_field, step_display, ctx)
    _check_outputs(step_data, lm, path_prefix, step_field, step_display, ctx)

    # ── Unknown keys ────────────────────────────────────────────────────────
    type_valid = _STEP_TYPE_VALID.get(steptype, frozenset())
    all_valid = _STEP_COMMON_VALID | type_valid
    for key in step_data:
        if key not in all_valid:
            ctx.warning(
                field=f"{step_field}.{key}",
                message=(
                    f"{step_display.capitalize()}: unknown key '{key}' for a "
                    f"{steptype_raw} step — it will be ignored."
                ),
                hint=(
                    f"Valid keys for a {steptype_raw} step: "
                    f"{', '.join(sorted(all_valid))}."
                ),
                line=field_line(key),
            )


def _check_indexed_step(
    step_data: dict[str, Any],
    lm: _LineMap,
    path_prefix: tuple,
    step_field: str,
    step_display: str,
    ctx: _Context,
) -> None:
    """Indexed-step-specific checks via the canonical indexed_step module."""
    step_line = lm.get(*path_prefix)

    for problem in indexed_step.check_indexed_step(step_data):
        ctx.error(
            field=step_field,
            message=f"{step_display.capitalize()}: {problem}.",
            hint=_indexed_hint(problem),
            line=step_line,
        )

    # Validate the template as an ordinary step
    template = step_data.get(indexed_step.TEMPLATE_KEY)
    if isinstance(template, dict):
        template_prefix = path_prefix + (indexed_step.TEMPLATE_KEY,)
        template_field = f"{step_field}.{indexed_step.TEMPLATE_KEY}"
        # Give the template a synthetic step_name so required-field checks work
        probe = dict(template)
        if probe.get("step_name") is None:
            probe["step_name"] = (
                step_data.get("step_name") or "<indexed template>"
            )
        _check_step(
            probe, lm, template_prefix, template_field, "indexed template", ctx
        )


# ---------------------------------------------------------------------------
# inputs / outputs
# ---------------------------------------------------------------------------

def _check_inputs(
    step_data: dict[str, Any],
    lm: _LineMap,
    path_prefix: tuple,
    step_field: str,
    step_display: str,
    ctx: _Context,
) -> None:
    inputs = step_data.get("inputs")
    if inputs is None:
        return
    inputs_line = lm.get(*path_prefix, "inputs")
    if not isinstance(inputs, dict):
        ctx.error(
            field=f"{step_field}.inputs",
            message=(
                f"{step_display.capitalize()}: 'inputs' must be a mapping of "
                f"argument names to values, got {type(inputs).__name__}."
            ),
            hint=(
                "Example:\n"
                "  inputs:\n"
                "    voltage: 5.0\n"
                "    source: {type: global, global_name: supply_voltage}"
            ),
            line=inputs_line,
        )
        return

    for entry_name, config in inputs.items():
        entry_field = f"{step_field}.inputs.{entry_name}"
        entry_line = lm.get(*path_prefix, "inputs", entry_name)

        if not isinstance(config, dict):
            # A bare scalar is a valid literal input — nothing to check.
            continue

        declared = config.get("type")
        if declared is None:
            known = ", ".join(sorted(rules.INPUT_TYPES))
            ctx.error(
                field=entry_field,
                message=(
                    f"Input '{entry_name}': a mapping must name a 'type' "
                    f"({known})."
                ),
                hint=(
                    f"A literal value is written directly: "
                    f"`{entry_name}: <value>`.\n"
                    f"To read a run variable: `{entry_name}: "
                    f"{{type: global, global_name: <var>}}`."
                ),
                line=entry_line,
            )
            continue

        declared_lower = str(declared).lower()
        required_keys = rules.INPUT_TYPES.get(declared_lower)
        if required_keys is None:
            known = ", ".join(sorted(rules.INPUT_TYPES))
            ctx.error(
                field=entry_field,
                message=(
                    f"Input '{entry_name}': unknown type '{declared}'. "
                    f"Available: {known}."
                ),
                hint=(
                    f"The only mapping input type is 'global' (reads a run "
                    f"variable). A literal value does not need a type: "
                    f"`{entry_name}: 42`."
                ),
                line=entry_line,
            )
            continue

        for key in required_keys:
            if config.get(key) is None:
                ctx.error(
                    field=f"{entry_field}.{key}",
                    message=(
                        f"Input '{entry_name}': a '{declared}' entry needs "
                        f"'{key}'."
                    ),
                    hint=_input_type_hint(declared_lower, entry_name, key),
                    line=entry_line,
                )


def _check_outputs(
    step_data: dict[str, Any],
    lm: _LineMap,
    path_prefix: tuple,
    step_field: str,
    step_display: str,
    ctx: _Context,
) -> None:
    outputs = step_data.get("outputs")
    if outputs is None:
        return
    outputs_line = lm.get(*path_prefix, "outputs")
    if not isinstance(outputs, dict):
        ctx.error(
            field=f"{step_field}.outputs",
            message=(
                f"{step_display.capitalize()}: 'outputs' must be a mapping of "
                f"output names to type configurations, "
                f"got {type(outputs).__name__}."
            ),
            hint=(
                "Example:\n"
                "  outputs:\n"
                "    voltage: {type: range, min: 4.9, max: 5.1}\n"
                "    result: {type: global, global_name: measured_voltage}"
            ),
            line=outputs_line,
        )
        return

    for entry_name, config in outputs.items():
        entry_field = f"{step_field}.outputs.{entry_name}"
        entry_line = lm.get(*path_prefix, "outputs", entry_name)

        if not isinstance(config, dict):
            ctx.error(
                field=entry_field,
                message=(
                    f"Output '{entry_name}': must be a mapping naming a 'type'."
                ),
                hint=(
                    f"Every output entry says what to do with the returned "
                    f"value.\nExample:  {entry_name}: {{type: equals, value: 5}}"
                ),
                line=entry_line,
            )
            continue

        declared = config.get("type")
        if declared is None:
            known = ", ".join(sorted(rules.OUTPUT_TYPES))
            ctx.error(
                field=entry_field,
                message=(
                    f"Output '{entry_name}': missing 'type'. "
                    f"Available: {known}."
                ),
                hint=_output_no_type_hint(entry_name),
                line=entry_line,
            )
            continue

        declared_lower = str(declared).lower()
        required_keys = rules.OUTPUT_TYPES.get(declared_lower)
        if required_keys is None:
            known = ", ".join(sorted(rules.OUTPUT_TYPES))
            ctx.error(
                field=entry_field,
                message=(
                    f"Output '{entry_name}': unknown type '{declared}'. "
                    f"Available: {known}."
                ),
                hint=_output_unknown_type_hint(entry_name, str(declared)),
                line=entry_line,
            )
            continue

        for key in required_keys:
            if config.get(key) is None:
                ctx.error(
                    field=f"{entry_field}.{key}",
                    message=(
                        f"Output '{entry_name}': a '{declared}' entry needs "
                        f"'{key}'."
                    ),
                    hint=_output_type_hint(declared_lower, entry_name, key),
                    line=entry_line,
                )


# ---------------------------------------------------------------------------
# Cross-document references
# ---------------------------------------------------------------------------

def _check_cross_references(
    header: dict[str, Any],
    seq_names: list[str],
    ctx: _Context,
) -> None:
    # Duplicate sequence names
    seen: set[str] = set()
    for name in seq_names:
        if name in seen:
            ctx.error(
                field="sequences",
                message=f"Duplicate sequence name '{name}'.",
                hint=(
                    "Each sequence in a recipe must have a unique name. "
                    "Rename one of the duplicates."
                ),
            )
        seen.add(name)

    # main_sequence must name an existing sequence
    main = header.get("main_sequence")
    if isinstance(main, str) and main.strip() and seq_names:
        if main not in seq_names:
            available = ", ".join(f"'{n}'" for n in seq_names)
            ctx.error(
                field="header.main_sequence",
                message=(
                    f"'main_sequence' is '{main}' but no such sequence exists "
                    f"in this file."
                ),
                hint=(
                    f"Available sequences: {available}.\n"
                    f"Fix the name, or remove 'main_sequence' to use the "
                    f"first sequence."
                ),
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_optional_str(
    doc: dict[str, Any],
    key: str,
    field: str,
    lm: _LineMap,
    ctx: _Context,
) -> None:
    """Warn if an optional string field is present but not a string."""
    if key in doc and doc[key] is not None:
        if not isinstance(doc[key], str):
            ctx.error(
                field=field,
                message=(
                    f"'{key}' must be a string, "
                    f"got {type(doc[key]).__name__}."
                ),
                hint=f"Example:  {key}: A brief description.",
                line=lm.get(key),
            )


def _ordinal(path_prefix: tuple) -> str:
    """The step index as a human-readable ordinal for error messages."""
    idx = path_prefix[-1] if path_prefix else 0
    if isinstance(idx, int):
        return str(idx + 1)
    return str(idx)


# ---------------------------------------------------------------------------
# Hint strings
# ---------------------------------------------------------------------------

def _header_required_hint(field: str) -> str:
    return {
        "name": (
            "Every recipe needs a unique name so the operator and the report "
            "can identify what was run.\nExample:  name: Output Voltage Test"
        ),
        "version": (
            "Every recipe must declare which PyPTS version it targets. The "
            "framework warns when they differ.\nExample:  version: 0.2"
        ),
    }.get(field, f"Add '{field}' to the recipe header.")


def _unknown_steptype_hint(steptype_raw: str) -> str:
    known = ", ".join(sorted(rules.STEP_TYPE_REQUIRED))
    guesses: dict[str, str] = {
        "userinteractionstep": "userinteraction",
        "waitstep": "wait",
        "pythonmodulestep": "pythonmodule",
        "userwritestep": "userwrite",
        "userloadingstep": "userloading",
        "sshconnectstep": "(SSH steps are not yet available in this version)",
        "sshclosestep": "(SSH steps are not yet available in this version)",
        "sequencestep": "(SequenceStep is dropped; put sub-sequences in-line)",
    }
    suggestion = guesses.get(steptype_raw.lower(), "")
    hint = f"Available step types: {known}."
    if suggestion:
        hint += f"\n'{steptype_raw}' was renamed or removed. {suggestion}"
    return hint


def _step_field_hint(steptype: str, field: str) -> str:
    hints: dict[tuple[str, str], str] = {
        ("wait", "wait_time"): (
            "A Wait step pauses the run for a fixed duration in seconds.\n"
            "Example:  wait_time: 2"
        ),
        ("pythonmodule", "module"): (
            "A PythonModule step calls a function from a Python file. "
            "Specify the file with 'module'.\n"
            "Example:  module: my_tests.py"
        ),
        ("pythonmodule", "method_name"): (
            "A PythonModule step needs 'method_name': the function inside "
            "the module to call.\nExample:  method_name: measure_voltage"
        ),
        ("userinteraction", "message"): (
            "A UserInteraction step needs 'message': the question shown to "
            "the operator.\nExample:  message: Connect the unit to J1, then continue."
        ),
        ("userinteraction", "options"): (
            "A UserInteraction step needs 'options': the list of button "
            "labels the operator can press.\nExample:  options: [Continue, Abort]"
        ),
        ("userwrite", "message"): (
            "A UserWrite step needs 'message': the prompt shown before the "
            "operator types their input.\n"
            "Example:  message: Scan or type the serial number."
        ),
        ("userloading", "message"): (
            "A UserLoading step needs 'message': the prompt shown while the "
            "operator chooses a file or a folder ('select: file' or "
            "'select: folder', file by default).\n"
            "Example:  message: Select the calibration file for this unit."
        ),
        ("indexed", "template"): (
            "An Indexed step needs 'template': the step mapping used as a "
            "base for each generated step.\n"
            "Example:\n"
            "  template:\n"
            "    steptype: PythonModule\n"
            "    module: my_tests.py\n"
            "    method_name: add"
        ),
        ("indexed", "parameter_sets"): (
            "An Indexed step needs 'parameter_sets': a list of input/expect "
            "sets, one per generated step.\n"
            "Example:\n"
            "  parameter_sets:\n"
            "    - inputs: {a: 1, b: 2}\n"
            "      expect: {sum: 3}"
        ),
    }
    return hints.get(
        (steptype, field),
        f"A {steptype} step requires '{field}'.",
    )


def _indexed_hint(problem: str) -> str:
    if "inputs" in problem or "outputs" in problem:
        return (
            "Put 'inputs' and 'outputs' on the 'template', not on the "
            "indexed step wrapper. The wrapper only carries 'template', "
            "'parameter_sets', and the common step fields."
        )
    if "parameter_sets" in problem:
        return (
            "Each entry in 'parameter_sets' may carry 'inputs' (direct "
            "values merged into the template's inputs) and 'expect' "
            "(shorthand equals checks merged into outputs)."
        )
    return "See the Indexed step documentation in step/step.md."


def _input_type_hint(type_name: str, entry_name: str, missing_key: str) -> str:
    if type_name == "global" and missing_key == "global_name":
        return (
            f"A 'global' input reads a run variable. Specify which one:\n"
            f"  {entry_name}: {{type: global, global_name: my_variable}}"
        )
    return f"A '{type_name}' input needs '{missing_key}'."


def _output_no_type_hint(entry_name: str) -> str:
    known = ", ".join(sorted(rules.OUTPUT_TYPES))
    return (
        f"Every output entry says what to do with the returned value via "
        f"'type'. Available types: {known}.\n"
        f"Examples:\n"
        f"  {entry_name}: {{type: equals, value: 5}}\n"
        f"  {entry_name}: {{type: range, min: 4.9, max: 5.1}}\n"
        f"  {entry_name}: {{type: global, global_name: my_var}}\n"
        f"  {entry_name}: {{type: passfail}}\n"
        f"  {entry_name}: {{type: pass}}"
    )


def _output_unknown_type_hint(entry_name: str, declared: str) -> str:
    known = ", ".join(sorted(rules.OUTPUT_TYPES))
    return (
        f"'{declared}' is not a valid output type. Available: {known}.\n"
        f"  equals   — pass if the returned value equals 'value'\n"
        f"  range    — pass if the value is between 'min' and 'max'\n"
        f"  passfail — pass if the value is truthy\n"
        f"  pass     — always DONE, no judgement\n"
        f"  global   — store the value in a run variable"
    )


def _output_type_hint(type_name: str, entry_name: str, missing_key: str) -> str:
    hints: dict[tuple[str, str], str] = {
        ("equals", "value"): (
            f"An 'equals' output checks that the returned value matches "
            f"'value' exactly.\n"
            f"  {entry_name}: {{type: equals, value: 5}}"
        ),
        ("range", "min"): (
            f"A 'range' output needs both 'min' and 'max'.\n"
            f"  {entry_name}: {{type: range, min: 4.9, max: 5.1}}"
        ),
        ("range", "max"): (
            f"A 'range' output needs both 'min' and 'max'.\n"
            f"  {entry_name}: {{type: range, min: 4.9, max: 5.1}}"
        ),
        ("global", "global_name"): (
            f"A 'global' output stores the returned value into a run "
            f"variable. Specify which one:\n"
            f"  {entry_name}: {{type: global, global_name: my_var}}"
        ),
    }
    return hints.get(
        (type_name, missing_key),
        f"A '{type_name}' output needs '{missing_key}'.",
    )
