"""
Recipe verificator: validate a recipe YAML file or string and return every
problem found in one pass, with line-numbered diagnostics and a fix hint each.

The public surface is two functions:

    verify_file(path)    -> list[ValidationIssue]
    verify_string(text)  -> list[ValidationIssue]

The verdict is the framework's. Errors come from the same Pydantic models the
framework loads a recipe with (recipe_parser.validate_document against
pypts.recipe.recipe_schema), worded exactly as the framework words them; once
those pass, the framework's real load (recipe_parser.parse_recipe) runs and
anything it still refuses - a `select` that is neither file nor folder, a call
of a sequence that does not exist - is an error too. So a recipe verifies
without errors exactly when the framework would load it.

What is this file's own: the line of every issue, the hint on how to fix it,
and the warnings about what loads but looks wrong (a removed key, a version
written as a number).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pypts.helper_applications.recipe_creator.issue import ValidationIssue
from pypts.recipe import recipe_parser
from pypts.recipe.recipe import RecipeError
from pypts.recipe.recipe_parser import SchemaProblem
from pypts.recipe.recipe_schema import (
    INDEXED_STEP_REFUSED_KEYS,
    INPUT_TYPES,
    OUTPUT_TYPES,
    SEQUENCE_STEP_REFUSED_KEYS,
    STEP_SCHEMAS,
    STEP_TYPE_REQUIRED,
    HeaderSchema,
    SequenceSchema,
)

# ---------------------------------------------------------------------------
# Keys that existed in the old recipe format and were deliberately removed.
# A sequence document is allowed unknown keys - the framework ignores them -
# so these load, and a recipe that still carries them gets a targeted warning
# rather than a generic "unknown key" one.
# ---------------------------------------------------------------------------
_REMOVED_SEQUENCE_KEYS: dict[str, str] = {
    "setup_steps": (
        "'setup_steps' was removed. Steps that belonged in setup_steps go at "
        "the front of 'steps' instead."
    ),
    "parameters": (
        "'parameters' was removed. A sequence declares no call interface: a "
        "Sequence step calls it and it shares the run's globals. Remove this key."
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

#: A text field refuses a YAML boolean, a date or a list - the cure is quoting.
_QUOTE_HINT = (
    "This field takes text (a number is read as its text). YAML reads yes/no/"
    "on/off/true/false as a boolean and 2024-01-01 as a date: quote the value.\n"
    "Example:  message: 'yes'"
)


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

    def error(self, field: str, message: str, hint: str, line: int | None = None) -> None:
        self.issues.append(ValidationIssue("error", field, message, hint, line))

    def warning(self, field: str, message: str, hint: str, line: int | None = None) -> None:
        self.issues.append(ValidationIssue("warning", field, message, hint, line))

    def has_errors(self) -> bool:
        return any(issue.is_error for issue in self.issues)


def _lower_path(path: tuple) -> tuple:
    """The same path with its string components lowercased."""
    return tuple(part.lower() if isinstance(part, str) else part for part in path)


class _LineMap:
    """Maps YAML key paths (tuples) to 1-based line numbers."""

    def __init__(self, node: yaml.Node) -> None:
        self._map: dict[tuple, int] = {}
        # The documents are normalized before they are checked, because the
        # recipe language is case-insensitive - but the YAML node keeps the
        # case the author wrote. Without this second map a lookup for
        # `step_name` would not find `Step_Name:` and every issue in a
        # mixed-case recipe would lose its line number.
        #
        # Exact matches are tried first, so `inputs`/`outputs` entry names -
        # which keep their case, unlike the language's own keys - are
        # unaffected. On a collision the first occurrence wins.
        self._lower_map: dict[tuple, int] = {}
        self.document_line: int = node.start_mark.line + 1
        # An alias is the node of its anchor, met again. Walking it twice adds
        # no line of its own, and an anchor that contains its own alias
        # (`g: &a [*a]` - legal YAML, and the framework loads it) never ends.
        self._walked: set[int] = set()
        self._walk(node, ())

    def _walk(self, node: yaml.Node, path: tuple) -> None:
        if id(node) in self._walked:
            return
        self._walked.add(id(node))
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = key_node.value
                child = path + (key,)
                self._record(child, key_node.start_mark.line + 1)
                self._walk(value_node, child)
        elif isinstance(node, yaml.SequenceNode):
            for i, item_node in enumerate(node.value):
                child = path + (i,)
                self._record(child, item_node.start_mark.line + 1)
                self._walk(item_node, child)

    def _record(self, path: tuple, line: int) -> None:
        self._map[path] = line
        self._lower_map.setdefault(_lower_path(path), line)

    def get(self, *path: str | int) -> int | None:
        line = self._map.get(path)
        if line is not None:
            return line
        return self._lower_map.get(_lower_path(path))

    def nearest(self, doc: dict[str, Any], path: tuple) -> int:
        """
        The line of `path` in `doc`, or of the closest thing around it that is
        in the file: a missing field points at the step or document it is
        missing from.
        """
        keys = _line_map_keys(doc, path)
        while keys:
            line = self.get(*keys)
            if line is not None:
                return line
            keys = keys[:-1]
        return self.document_line


def _line_map_keys(doc: dict[str, Any], path: tuple) -> tuple:
    """
    `path` as the line map spells it. The map records a mapping key as the text
    the author wrote, so a key YAML read as a number (`1:`) is looked up as
    "1" - but a list position stays a position. The document says which is which.
    """
    keys: list[str | int] = []
    container: Any = doc
    for part in path:
        if isinstance(container, list) or isinstance(part, str):
            keys.append(part)
        else:
            keys.append(str(part))
        if isinstance(container, dict):
            container = container.get(part)
        elif isinstance(container, list) and isinstance(part, int) and 0 <= part < len(container):
            container = container[part]
        else:
            container = None
    return tuple(keys)


def _run(content: str, ctx: _Context) -> None:
    """parse -> structure -> header -> sequences -> cross-refs -> the framework's load."""
    # Pass 1 - YAML parsing
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

    # Pass 2 - each document must be a mapping. `number` counts every document
    # from 1, header included, as the framework's messages do. The first one is
    # the header, and without it the framework stops - so does this check:
    # the next mapping is not the header, and checking it as one says nothing.
    if not isinstance(docs[0], dict):
        ctx.error(
            field="document 1",
            message="Document 1 is not a YAML mapping.",
            hint=(
                "The first document is the recipe header, a mapping that starts "
                "with 'name:'. Sequence documents follow after '---'."
            ),
            line=nodes[0].start_mark.line + 1,
        )
        return

    valid: list[tuple[int, dict[str, Any], yaml.Node]] = []
    for i, (doc, node) in enumerate(zip(docs, nodes)):
        if not isinstance(doc, dict):
            ctx.error(
                field=f"document {i + 1}",
                message=f"Document {i + 1} is not a YAML mapping.",
                hint=(
                    "Every document in a recipe must be a mapping (key: value "
                    "pairs). Check for a stray '---' separator or a bare value "
                    "at the top level."
                ),
                line=node.start_mark.line + 1,
            )
        else:
            valid.append((i + 1, doc, node))

    # The recipe language is case-insensitive: the framework lowercases every
    # mapping key before it validates anything (recipe_parser._lowercase_keys),
    # so `Step_Name:` loads and runs exactly as `step_name:` does. Normalize
    # with the parser's own helpers rather than repeating the rule here - a
    # second copy of it is what drifted in the first place.
    #
    # This has to happen before the header is identified below, which is itself
    # a raw-key test: a header written `Name:` was rejected as "not a header"
    # before a single field was looked at.
    header_doc = recipe_parser.normalize_header(valid[0][1])
    header_node = valid[0][2]
    sequences = [
        (number, recipe_parser.normalize_sequence(doc), node) for number, doc, node in valid[1:]
    ]

    # Confirm the first document is the header and not a sequence
    has_name = "name" in header_doc
    has_seq = "sequence_name" in header_doc
    if has_seq and not has_name:
        ctx.error(
            field="document 1",
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
            field="document 1",
            message="Cannot identify the first document as a recipe header.",
            hint=(
                "The first document must start with 'name: <recipe name>'. "
                "Sequence documents start with 'sequence_name: <name>'."
            ),
            line=header_node.start_mark.line + 1,
        )
        return

    if not sequences:
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

    # Pass 3 - the header, against the framework's model
    header_lm = _LineMap(header_node)
    header_problems, _ = recipe_parser.validate_document(header_doc, HeaderSchema, "header")
    _report_problems(header_problems, header_doc, header_lm, ctx)
    _warn_about_header(header_doc, header_lm, header_problems, ctx)

    # Pass 4 - every sequence, against the framework's model
    # Every sequence name, with the line it is written on.
    seq_names: list[tuple[str, int | None]] = []
    for number, seq_doc, seq_node in sequences:
        seq_lm = _LineMap(seq_node)
        context = recipe_parser.sequence_context(seq_doc, number)
        problems, _ = recipe_parser.validate_document(seq_doc, SequenceSchema, context)
        _report_problems(problems, seq_doc, seq_lm, ctx)
        _warn_about_sequence(seq_doc, seq_lm, context, ctx)
        # A number is a sequence name too: the framework reads it as its text.
        name = seq_doc.get("sequence_name")
        name_line = seq_lm.get("sequence_name")
        if isinstance(name, str) and name:
            seq_names.append((name, name_line))
        elif isinstance(name, (int, float)) and not isinstance(name, bool):
            seq_names.append((str(name), name_line))

    # Pass 5 - cross-document references
    _check_cross_references(header_doc, header_lm, seq_names, ctx)

    # Pass 6 - the framework's own load. Only once everything above is clean:
    # it stops at its first problem, and every one before it is already named.
    if not ctx.has_errors():
        _check_full_load(content, ctx)


# ---------------------------------------------------------------------------
# Validation problems -> issues
# ---------------------------------------------------------------------------


def _report_problems(
    problems: list[SchemaProblem], doc: dict[str, Any], lm: _LineMap, ctx: _Context
) -> None:
    """Each problem the framework's model found, as an error at its line."""
    for problem in problems:
        ctx.error(
            field=problem.where,
            message=problem.message,
            hint=_hint(problem, doc),
            line=lm.nearest(doc, problem.path),
        )


def _check_full_load(content: str, ctx: _Context) -> None:
    """What only building the recipe finds: a step constructor's refusal, a bad call."""
    try:
        recipe_parser.parse_recipe(content, check_version=False)
    except RecipeError as error:
        ctx.error(
            field="recipe",
            message=str(error),
            hint=(
                "Every field is valid, but the framework refused the recipe while "
                "building it. The message names the sequence and the step, counted "
                "from 1 with every Indexed step already expanded."
            ),
        )


# ---------------------------------------------------------------------------
# Warnings - what loads, but looks wrong
# ---------------------------------------------------------------------------


def _warn_about_header(
    doc: dict[str, Any], lm: _LineMap, problems: list[SchemaProblem], ctx: _Context
) -> None:
    refused = {problem.path[0] for problem in problems if problem.path}
    for field in ("name", "version"):
        value = doc.get(field)
        if value is None or field in refused:
            continue
        if not str(value).strip():
            ctx.warning(
                field=f"header.{field}",
                message=f"'{field}' is empty.",
                hint=f"Give the recipe a meaningful {field}.",
                line=lm.get(field),
            )
        elif field == "version" and not isinstance(value, str):
            ctx.warning(
                field="header.version",
                message=(
                    f"'version' is written as a number ({value}). "
                    f"PyPTS accepts it, but quoting avoids ambiguity."
                ),
                hint="Example:  version: '0.2'  or  version: \"0.2\"",
                line=lm.get(field),
            )


def _warn_about_sequence(
    doc: dict[str, Any], lm: _LineMap, context: str, ctx: _Context
) -> None:
    """A sequence document's unknown keys load and are ignored - worth a word."""
    known = set(SequenceSchema.model_fields)
    for key in doc:
        if key in known:
            continue
        removed = _REMOVED_SEQUENCE_KEYS.get(key)
        if removed is not None:
            ctx.warning(
                field=f"{context}.{key}",
                message=f"'{key}' is not part of the current recipe format.",
                hint=removed,
                line=lm.get(key),
            )
        else:
            ctx.warning(
                field=f"{context}.{key}",
                message=f"Unknown sequence key '{key}' - it will be ignored.",
                hint=f"Known sequence keys: {', '.join(sorted(known))}.",
                line=lm.get(key),
            )


# ---------------------------------------------------------------------------
# Cross-document references
# ---------------------------------------------------------------------------


def _check_cross_references(
    header: dict[str, Any],
    header_lm: _LineMap,
    seq_names: list[tuple[str, int | None]],
    ctx: _Context,
) -> None:
    # Duplicate sequence names. The parser compares them lowercased
    # (recipe_parser.parse_recipe): a sequence name keeps its case for display
    # but must be unique without it, so that a case-insensitive main_sequence
    # lookup can never be ambiguous. Compared exactly here, `Main` and `main`
    # looked like two sequences and the recipe verified clean - then the
    # framework refused to load it.
    seen: set[str] = set()
    for name, line in seq_names:
        lowered = name.lower()
        if lowered in seen:
            ctx.error(
                field="sequences",
                message=f"Duplicate sequence name '{name}'.",
                hint=(
                    "Each sequence in a recipe must have a unique name, "
                    "regardless of case. Rename one of the duplicates."
                ),
                line=line,
            )
        seen.add(lowered)

    # main_sequence must name an existing sequence. The parser resolves it
    # case-insensitively, so `main_sequence: main` against a sequence called
    # `Main` runs - matched exactly here, it was reported as a broken reference.
    main = header.get("main_sequence")
    if isinstance(main, str) and main.strip() and seq_names:
        if main.lower() not in {name.lower() for name, _ in seq_names}:
            available = ", ".join(f"'{name}'" for name, _ in seq_names)
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
                line=header_lm.get("main_sequence"),
            )


# ---------------------------------------------------------------------------
# Hints - chosen by where the problem is and what kind it is
# ---------------------------------------------------------------------------

#: Hints for the header's and a sequence document's own fields.
_DOCUMENT_FIELD_HINTS: dict[str, str] = {
    "name": (
        "Every recipe needs a unique name so the operator and the report "
        "can identify what was run.\nExample:  name: Output Voltage Test"
    ),
    "version": (
        "Every recipe must declare which PyPTS version it targets. The "
        "framework warns when they differ.\nExample:  version: '0.2'"
    ),
    "main_sequence": (
        "The name of the sequence to run.\nExample:  main_sequence: Main\n"
        "If omitted the first sequence in the file is used."
    ),
    "globals": (
        "A mapping of variable names to initial values.\nExample:\n"
        "  globals:\n"
        "    serial_number: ''\n"
        "    voltage: 0"
    ),
    "report_metadata": (
        "A list of globals variable names, each stamped on every row of the "
        "report. Each entry is a name written as text; a number is not a name.\n"
        "Example:  report_metadata: [serial_number, lot_number]"
    ),
    "sequence_name": (
        "Each sequence document must begin with 'sequence_name: <name>'. The "
        "first document is the recipe header (starts with 'name:'); every "
        "document after it is a sequence."
    ),
    "steps": (
        "A sequence must contain at least one step.\nExample:\n"
        "  steps:\n"
        "    - steptype: Wait\n"
        "      step_name: Pause\n"
        "      wait_time: 1"
    ),
    "teardown_steps": (
        "teardown_steps runs after the sequence finishes, even after an abort. "
        "Its steps are structured like 'steps'."
    ),
}


def _hint(problem: SchemaProblem, doc: dict[str, Any]) -> str:
    """The hint for one problem, from the document it was found in."""
    path = problem.path
    if len(path) >= 2 and path[0] in ("steps", "teardown_steps") and isinstance(path[1], int):
        steps = doc.get(str(path[0]))
        step: Any = None
        if isinstance(steps, list) and path[1] < len(steps):
            step = steps[path[1]]
        return _step_hint(problem, step, path[2:])

    field = str(path[0]) if path else ""
    # report_metadata entries are names, not text fields: a number is refused there.
    if problem.kind == "string_type" and field != "report_metadata":
        return _QUOTE_HINT
    return _DOCUMENT_FIELD_HINTS.get(field, "See recipe_guide.html for the recipe format.")


def _step_hint(problem: SchemaProblem, step: Any, rest: tuple[int | str, ...]) -> str:
    """The hint for a problem inside one step; `rest` is the path within the step."""
    steptype = _steptype(step)

    # A problem inside an Indexed step's template is a problem of the step it becomes.
    if steptype == "indexed" and rest and rest[0] == "template":
        if len(rest) == 1:
            return _template_hint(problem, step.get("template"))
        step = step.get("template")
        steptype = _steptype(step)
        rest = rest[1:]

    if not rest:
        if problem.kind == "union_tag_invalid":
            return _unknown_steptype_hint(steptype)
        return (
            "Each step must be a YAML mapping starting with 'steptype:' and "
            "'step_name:'. A missing '-' before the step or wrong indentation "
            "is a common cause."
        )

    field = str(rest[0])
    if field == "steptype":
        return (
            f"Every step must name its type. "
            f"Available: {', '.join(sorted(STEP_TYPE_REQUIRED))}.\n"
            f"Example:  steptype: Wait"
        )
    if field in ("inputs", "outputs") and len(rest) >= 2:
        return _entry_hint(problem, step, field, rest[1], rest[2:])
    if steptype == "indexed" and (field == "parameter_sets" or field in INDEXED_STEP_REFUSED_KEYS):
        if problem.kind == "missing":
            return _step_field_hint(steptype, field)
        return _indexed_hint(field)
    if steptype == "sequence" and field in SEQUENCE_STEP_REFUSED_KEYS:
        return (
            "A Sequence step carries only 'sequence_name' and the common fields "
            "(description, skip, continue_on_error). It is named after the "
            "sequence it calls, which shares the run's globals."
        )
    if problem.kind == "missing":
        return _step_field_hint(steptype, field)
    if problem.kind == "extra_forbidden":
        return _valid_keys_hint(steptype)
    if field == "skip":
        return "Example:  skip: true"
    if field == "continue_on_error":
        return (
            "continue_on_error: false means an ERROR or FAIL on this step ends "
            "the run and every subsequent step is SKIP."
        )
    if problem.kind == "string_type":
        return _QUOTE_HINT
    return "See recipe_guide.html for this step type."


def _entry_hint(
    problem: SchemaProblem,
    step: Any,
    mapping_name: str,
    entry_name: int | str,
    rest: tuple[int | str, ...],
) -> str:
    """The hint for one `inputs` or `outputs` entry."""
    config: Any = None
    mapping = step.get(mapping_name) if isinstance(step, dict) else None
    if isinstance(mapping, dict):
        config = mapping.get(entry_name)
    declared = config.get("type") if isinstance(config, dict) else None
    entry = str(entry_name)

    if mapping_name == "inputs":
        if declared is None:
            return (
                f"A literal value is written directly: `{entry}: <value>`.\n"
                f"To read a run variable: `{entry}: {{type: global, global_name: <var>}}`."
            )
        required = INPUT_TYPES.get(str(declared))
        if required is None:
            return (
                f"The only mapping input type is 'global' (reads a run variable). "
                f"A literal value does not need a type: `{entry}: 42`."
            )
        missing = [key for key in required if config.get(key) is None]
        if missing:
            return _input_type_hint(str(declared), entry, missing[0])
        return f"A '{declared}' input: see recipe_guide.html."

    if problem.kind == "union_tag_not_found" or declared is None:
        return _output_no_type_hint(entry)
    if problem.kind == "union_tag_invalid":
        return _output_unknown_type_hint(entry, str(declared))
    if problem.kind == "missing" and rest:
        return _output_type_hint(str(declared), entry, str(rest[-1]))
    return _output_no_type_hint(entry)


def _steptype(step: Any) -> str:
    """A step mapping's (normalized, lowercase) steptype, or ""."""
    if isinstance(step, dict) and isinstance(step.get("steptype"), str):
        return step["steptype"]
    return ""


def _valid_keys_hint(steptype: str) -> str:
    """Every key a steptype takes, read from its model."""
    model = STEP_SCHEMAS.get(steptype)
    if model is None:
        return "See recipe_guide.html for this step type."
    # A field typed None is declared only to be refused with its reason.
    keys = []
    for name, field in model.model_fields.items():
        if field.annotation is not type(None):
            keys.append(name)
    return f"Valid keys for a {steptype} step: {', '.join(sorted(keys))}."


def _unknown_steptype_hint(steptype: str) -> str:
    known = ", ".join(sorted(STEP_TYPE_REQUIRED))
    guesses: dict[str, str] = {
        "userinteractionstep": "userinteraction",
        "waitstep": "wait",
        "pythonmodulestep": "pythonmodule",
        "userwritestep": "userwrite",
        "userloadingstep": "userloading",
        "sequencestep": "sequence",
        "indexedstep": "indexed",
        "sshconnectstep": "(SSH steps are not yet available in this version)",
        "sshclosestep": "(SSH steps are not yet available in this version)",
    }
    suggestion = guesses.get(steptype.lower(), "")
    hint = f"Available step types: {known}."
    if suggestion:
        hint += f"\n'{steptype}' was renamed or removed. {suggestion}"
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
        ("sequence", "sequence_name"): (
            "A Sequence step calls another sequence of this recipe by its name.\n"
            "Example:  sequence_name: Calibrate"
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
    if field == "step_name":
        return (
            "Every step needs a name that appears in the step table and "
            "the report.\nExample:  step_name: Measure output voltage"
        )
    return hints.get((steptype, field), f"A {steptype} step requires '{field}'.")


def _template_hint(problem: SchemaProblem, template: Any) -> str:
    """A problem with an Indexed step's `template` as a whole."""
    if problem.kind == "missing":
        return _step_field_hint("indexed", "template")
    if problem.kind == "union_tag_invalid":
        return _unknown_steptype_hint(_steptype(template))
    return _indexed_hint("template")


def _indexed_hint(field: str) -> str:
    """A problem with one of an Indexed step's own keys, by the key."""
    if field in ("inputs", "outputs"):
        return (
            "Put 'inputs' and 'outputs' on the 'template', not on the "
            "indexed step wrapper. The wrapper only carries 'template', "
            "'parameter_sets', and the common step fields."
        )
    if field == "parameter_sets":
        return (
            "Each entry in 'parameter_sets' may carry 'inputs' (direct "
            "values merged into the template's inputs) and 'expect' "
            "(shorthand equals checks merged into outputs), and at least one of them."
        )
    if field == "id":
        return (
            "An indexed step becomes several steps, and each gets an id of its "
            "own. Remove 'id' here and from the template."
        )
    if field == "template":
        return (
            "The template is one ordinary step: not a Sequence step, not another "
            "Indexed step, and without an 'id' - each generated step gets its own."
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
    known = ", ".join(sorted(OUTPUT_TYPES))
    return (
        f"Every output entry is a mapping that says what to do with the returned "
        f"value via 'type'. Available types: {known}.\n"
        f"Examples:\n"
        f"  {entry_name}: {{type: equals, value: 5}}\n"
        f"  {entry_name}: {{type: range, min: 4.9, max: 5.1}}\n"
        f"  {entry_name}: {{type: global, global_name: my_var}}\n"
        f"  {entry_name}: {{type: passfail}}\n"
        f"  {entry_name}: {{type: pass}}"
    )


def _output_unknown_type_hint(entry_name: str, declared: str) -> str:
    known = ", ".join(sorted(OUTPUT_TYPES))
    return (
        f"'{declared}' is not a valid output type. Available: {known}.\n"
        f"  equals   - pass if the returned value equals 'value'\n"
        f"  range    - pass if the value is between 'min' and 'max'\n"
        f"  passfail - pass if the value is truthy\n"
        f"  pass     - always DONE, no judgement\n"
        f"  global   - store the value in a run variable"
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
