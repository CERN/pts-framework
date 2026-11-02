"""
The HTML page of a run - one self-contained file built from the CSV rows.

Everything the page needs is inside it: the stylesheet, a few lines of script
for the collapsible rows and the result filters, and the CERN logo (the
watermark) as a data URI. It opens from a USB stick or an e-mail attachment
exactly as it does in the run folder.

Every value from the recipe or the test code goes through html.escape() before
it reaches the page, and the script only toggles classes and attributes - it
never writes markup - so recipe text can never become markup.
"""

import base64
import html
import json
import time
from importlib.resources import files

from pypts.logger.log import log
from pypts.messages.common_messages import ResultType

#: The step_type of a sequence's own row. It is written after the sequence's
#: steps, as their summary, so it is not counted as a step of its own.
SEQUENCE_STEP_TYPE = "SequenceStep"

#: The results the "Problems" tile counts and the "Problems only" button keeps.
PROBLEM_RESULTS = ("FAIL", "ERROR", "STOP")

#: The time format of the CSV's time cells.
CSV_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Where the watermark comes from: the GUI's copy of the logo, so there is one
#: file in the package rather than two.
LOGO_PACKAGE = "pypts.hmi.gui"
LOGO_PARTS = ("images", "CERN_Logo.png")

#: The Environment card's columns. A CSV written before they existed has none
#: of them, and the card then says so in one line instead of four dashes.
ENVIRONMENT_FIELDS = (
    ("Host", "host_name"),
    ("Platform", "platform"),
    ("Python", "python_version"),
    ("pypts", "pypts_version"),
)

Row = dict[str, str]


def logo_data_uri() -> str:
    """
    The CERN logo as a data URI, or "" if the package does not carry it.

    A missing logo costs the page its watermark and nothing else.
    """
    try:
        resource = files(LOGO_PACKAGE)
        for part in LOGO_PARTS:
            resource = resource / part
        data = resource.read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError) as error:
        log.debug("The report has no watermark: the logo could not be read (%s).", error)
        return ""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def format_duration(seconds: float) -> str:
    """A duration the way a person reads it: 12 ms, 3.45 s, 2 min 05 s, 1 h 02 min."""
    if seconds < 0:
        seconds = 0.0
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    whole = round(seconds)
    if whole < 3600:
        minutes, rest = divmod(whole, 60)
        return f"{minutes} min {rest:02d} s"
    hours, rest = divmod(whole, 3600)
    return f"{hours} h {rest // 60:02d} min"


def parse_seconds(text: str) -> float:
    """A duration_s cell as a number; an empty or broken cell counts as 0."""
    try:
        return float(text)
    except ValueError:
        return 0.0


def run_duration(started_at: str, finished_at: str) -> str:
    """The wall-clock length of the run, or "" when either end is unknown."""
    if not started_at or not finished_at:
        return ""
    # Both are local times of the same machine, so mktime() reads them alike.
    try:
        start = time.mktime(time.strptime(started_at, CSV_TIME_FORMAT))
        end = time.mktime(time.strptime(finished_at, CSV_TIME_FORMAT))
    except (ValueError, OverflowError):
        return ""
    return format_duration(end - start)


def result_class(result: str) -> str:
    """The CSS class of a result. Only the known names pass, so no cell can inject one."""
    if result in ResultType.__members__:
        return "r-" + result
    return "r-unknown"


def humanise(name: str) -> str:
    """A metadata name as a label: `serial_number` reads "Serial number"."""
    words = name.replace("_", " ").strip()
    if not words:
        return name
    return words[0].upper() + words[1:]


def display_type(step_type: str) -> str:
    """A step type without its class-name suffix: PythonModuleStep reads PythonModule."""
    if step_type.endswith("Step") and len(step_type) > len("Step"):
        return step_type[: -len("Step")]
    return step_type


def error_headline(error_info: str) -> str:
    """
    The one line of an error a technician needs.

    For a traceback that is the exception, which Python prints last; for
    anything else it is the first line.
    """
    lines = [line.strip() for line in error_info.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    if lines[0].startswith("Traceback"):
        return lines[-1]
    return lines[0]


def pretty_json(text: str) -> str:
    """
    An inputs/outputs cell, indented for reading. Not JSON after all: as written.

    Returns "" for an empty object, so a step without values shows no block.
    """
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return text
    if value == {} or value == [] or value is None:
        return ""
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def detail_block(label: str, text: str, extra_class: str = "") -> str:
    """One labelled, preformatted block of the detail row, or "" for nothing to show."""
    if not text:
        return ""
    return (
        f'<div class="detail {extra_class}"><div class="detail-label">{label}</div>'
        f"<pre>{html.escape(text)}</pre></div>"
    )


def is_sequence_row(row: Row) -> bool:
    return row.get("step_type") == SEQUENCE_STEP_TYPE


def group_rows(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    """Consecutive rows that share a sequence name, as (name, rows), in run order."""
    groups: list[tuple[str, list[Row]]] = []
    for row in rows:
        name = row.get("sequence_name", "")
        if groups and groups[-1][0] == name:
            groups[-1][1].append(row)
        else:
            groups.append((name, [row]))
    return groups


def split_closing_row(name: str, rows: list[Row]) -> tuple[list[Row], Row | None]:
    """
    A group's steps, and the sequence's own row if it closes the group.

    The sequence's row comes after its steps; when it is the group's last row
    and names the group, its result and duration go on the group's header
    instead of a row of their own. Any other sequence row stays a row.
    """
    if len(rows) < 2:
        return rows, None
    last = rows[-1]
    if is_sequence_row(last) and last.get("step_name", "") == name:
        return rows[:-1], last
    return rows, None


def count_results(rows: list[Row]) -> dict[str, int]:
    """How many steps ended in each result. Sequence rows are summaries, not steps."""
    counts: dict[str, int] = {}
    for row in rows:
        if is_sequence_row(row):
            continue
        result = row.get("result", "")
        counts[result] = counts.get(result, 0) + 1
    return counts


def ordered_results(counts: dict[str, int]) -> list[str]:
    """The results present, worst first; any unknown name after the known ones."""
    known = [member.name for member in sorted(ResultType, reverse=True)]
    present = [name for name in known if name in counts]
    for name in sorted(counts):
        if name not in present:
            present.append(name)
    return present


def render_step(row: Row, index: int) -> str:
    """One step as a <tbody>: its summary line and, if it has any, its hidden details."""
    result = row.get("result", "")
    css = result_class(result)
    step_label = row.get("step_name", "")
    error_text = row.get("error_info", "")

    inputs_block = detail_block("Inputs", pretty_json(row.get("inputs", "")))
    outputs_block = detail_block("Outputs", pretty_json(row.get("outputs", "")))
    values = ""
    if inputs_block or outputs_block:
        values = f'<div class="io">{inputs_block}{outputs_block}</div>'
    details = detail_block("Error", error_text, "detail-error") + values

    body_classes = ["step", css]
    if is_sequence_row(row):
        body_classes.append("sequence-end")
    if details:
        body_classes.append("has-details")
        toggle = (
            f'<button type="button" class="toggle" aria-expanded="false" '
            f'aria-controls="d{index}" aria-label="Details of {html.escape(step_label)}">'
            '<span class="chevron" aria-hidden="true"></span></button>'
        )
    else:
        toggle = ""

    step_name = html.escape(step_label)
    if is_sequence_row(row):
        step_name = f'<span class="sequence-mark">Sequence finished:</span> {step_name}'
    # The error's headline goes on the summary, so a failure reads without opening it.
    headline = error_headline(error_text)
    error_hint = ""
    if headline:
        error_hint = (
            f'<div class="error-hint" title="{html.escape(headline)}">'
            f"{html.escape(headline)}</div>"
        )

    summary = (
        '<tr class="summary">'
        f'<td class="col-toggle">{toggle}</td>'
        f'<td class="col-result"><span class="badge {css}">{html.escape(result)}</span></td>'
        f'<td class="col-step">{step_name}{error_hint}</td>'
        f'<td class="col-type">{html.escape(display_type(row.get("step_type", "")))}</td>'
        f'<td class="col-duration">'
        f"{html.escape(format_duration(parse_seconds(row.get('duration_s', ''))))}</td>"
        "</tr>"
    )
    detail_row = ""
    if details:
        meta = (
            f'<div class="detail-meta">Started {html.escape(row.get("started_at", ""))}'
            f' &middot; step id {html.escape(row.get("step_id", ""))}</div>'
        )
        detail_row = (
            f'<tr class="details" id="d{index}" hidden><td></td>'
            f'<td colspan="4">{details}{meta}</td></tr>'
        )
    return (
        f'<tbody class="{" ".join(body_classes)}" data-result="{html.escape(result)}">'
        f"{summary}{detail_row}</tbody>"
    )


def render_group_header(name: str, steps: list[Row], closing: Row | None) -> str:
    """The header line of one sequence group: its name, its steps' results, its own."""
    counts = count_results(steps)
    parts = []
    for result in ordered_results(counts):
        parts.append(
            f'<span class="mini {result_class(result)}">{counts[result]} '
            f"{html.escape(result)}</span>"
        )
    label = html.escape(name) if name else "(no sequence)"
    outcome = ""
    if closing is not None:
        result = closing.get("result", "")
        duration = format_duration(parse_seconds(closing.get("duration_s", "")))
        outcome = (
            f'<span class="group-outcome"><span class="badge {result_class(result)}">'
            f"{html.escape(result)}</span>"
            f'<span class="group-duration">{html.escape(duration)}</span></span>'
        )
    return (
        '<tbody class="group"><tr><td colspan="5"><div class="group-line">'
        f'<span class="group-name">{label}</span>'
        f'<span class="group-counts">{"".join(parts)}</span>{outcome}'
        "</div></td></tr></tbody>"
    )


def render_report(
    rows: list[Row],
    first_row: Row,
    metadata: list[tuple[str, str]],
    generated_at: str,
) -> str:
    """
    The whole page.

    Args:
        rows: the run's CSV rows, in run order.
        first_row: where the run-level values are read - any row carries them
            all; a run with no rows passes what the Report holds instead.
        metadata: the recipe's report_metadata as (name, value), recipe order.
        generated_at: when the page is written, local time.
    """

    def run_value(column: str) -> str:
        return html.escape(first_row.get(column, ""))

    recipe_name = run_value("recipe_name")
    verdict_text = first_row.get("run_result", "") or "IN PROGRESS"
    verdict_class = result_class(verdict_text)
    started_at = first_row.get("run_started_at", "")
    finished_at = first_row.get("run_finished_at", "")

    counts = count_results(rows)
    step_total = sum(counts.values())
    problem_total = 0
    for result in PROBLEM_RESULTS:
        problem_total += counts.get(result, 0)
    step_time = 0.0
    for row in rows:
        if not is_sequence_row(row):
            step_time += parse_seconds(row.get("duration_s", ""))

    wall_time = run_duration(started_at, finished_at)
    if wall_time:
        time_label = "Wall time"
        time_value = wall_time
    else:
        # A run that never finished, or a CSV from before run_finished_at.
        time_label = "Time in steps"
        time_value = format_duration(step_time)

    if problem_total > 0:
        problem_class = "metric metric-problems"
    else:
        problem_class = "metric"

    chips = []
    for result in ordered_results(counts):
        css = result_class(result)
        chips.append(
            f'<label class="chip {css}"><input type="checkbox" checked '
            f'data-filter="{html.escape(result)}"><span class="chip-count">{counts[result]}'
            f'</span> <span class="chip-name">{html.escape(result)}</span></label>'
        )
    if chips:
        chips_html = "".join(chips)
    else:
        chips_html = '<span class="muted">No steps ran.</span>'

    # Who and what was tested, under the title: the first thing a technician looks for.
    identity_parts = []
    for name, value in metadata:
        if value:
            identity_parts.append(
                f'<span><span class="id-label">{html.escape(humanise(name))}</span> '
                f"<strong>{html.escape(value)}</strong></span>"
            )
    if started_at:
        identity_parts.append(
            f'<span><span class="id-label">Started</span> {html.escape(started_at)}</span>'
        )
    identity_html = ""
    if identity_parts:
        identity_html = f'<div class="identity">{"".join(identity_parts)}</div>'

    def fact(label: str, value: str) -> str:
        if not value:
            value = '<span class="muted">&mdash;</span>'
        return f"<div><dt>{label}</dt><dd>{value}</dd></div>"

    run_facts = [fact(html.escape(humanise(name)), html.escape(value)) for name, value in metadata]
    run_facts.append(fact("Recipe version", run_value("recipe_version")))
    run_facts.append(fact("Started", html.escape(started_at)))
    run_facts.append(fact("Finished", html.escape(finished_at)))
    run_facts_html = f'<dl>{"".join(run_facts)}</dl>'

    environment = []
    recorded = False
    for label, column in ENVIRONMENT_FIELDS:
        value = first_row.get(column, "")
        if value and column != "pypts_version":
            recorded = True
        environment.append(fact(label, html.escape(value)))
    if recorded:
        environment_html = f'<dl>{"".join(environment)}</dl>'
    else:
        environment_html = (
            '<p class="muted not-recorded">Not recorded - this report was built from a '
            "CSV written before pypts recorded the environment.</p>"
        )

    body_parts = []
    index = 0
    for name, group in group_rows(rows):
        steps, closing = split_closing_row(name, group)
        body_parts.append(render_group_header(name, steps, closing))
        for row in steps:
            body_parts.append(render_step(row, index))
            index += 1
    if body_parts:
        table_html = (
            '<div class="table-wrap"><table class="steps"><colgroup><col class="c-toggle">'
            '<col class="c-result"><col class="c-step"><col class="c-type">'
            '<col class="c-duration"></colgroup>'
            '<thead><tr><th><span class="sr-only">Details</span></th><th>Result</th>'
            '<th>Step</th><th>Type</th><th class="col-duration">Duration</th></tr></thead>'
            + "".join(body_parts)
            + "</table></div>"
        )
    else:
        table_html = '<p class="muted empty">No step was executed in this run.</p>'

    logo = logo_data_uri()
    if logo:
        logo_css = f":root {{ --logo: url({logo}); }}"
    else:
        logo_css = ":root { --logo: none; }"

    description = run_value("recipe_description")
    description_html = ""
    if description:
        description_html = f'<p class="description">{description}</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="pypts {run_value("pypts_version")}">
<title>{html.escape(verdict_text)} &middot; {recipe_name} &middot; pypts report</title>
<style>
{logo_css}
{PAGE_CSS}
</style>
</head>
<body>
<div class="watermark" aria-hidden="true"></div>
<main>
<header class="masthead {verdict_class}">
  <div class="title">
    <h1>{recipe_name}</h1>
    {identity_html}
    {description_html}
  </div>
  <div class="verdict">
    <div class="verdict-label">Result</div>
    <div class="verdict-value">{html.escape(verdict_text)}</div>
  </div>
</header>

<section class="metrics" aria-label="Run metrics">
  <div class="metric"><div class="metric-label">Steps</div>
    <div class="metric-value">{step_total}</div></div>
  <div class="{problem_class}"><div class="metric-label">Failed, error or stopped</div>
    <div class="metric-value">{problem_total}</div></div>
  <div class="metric"><div class="metric-label">{time_label}</div>
    <div class="metric-value">{time_value}</div></div>
  <div class="metric metric-chips"><div class="metric-label">Results &middot; click to filter</div>
    <div class="chips">{chips_html}</div></div>
</section>

<section class="facts">
  <div class="card"><h2>Run</h2>{run_facts_html}</div>
  <div class="card"><h2>Environment</h2>{environment_html}</div>
</section>

<section class="results">
  <div class="toolbar">
    <h2>Steps</h2>
    <div class="buttons">
      <button type="button" id="problems-only">Problems only</button>
      <button type="button" id="all-results">All results</button>
      <button type="button" id="expand-all">Show all details</button>
      <button type="button" id="collapse-all">Hide all details</button>
    </div>
  </div>
  {table_html}
</section>

<footer>Generated {html.escape(generated_at)} by pypts {run_value("pypts_version")}</footer>
</main>
<script>
{PAGE_SCRIPT}
</script>
</body>
</html>
"""


PAGE_CSS = """
:root {
  --ink: #1b2430; --muted: #5a6575; --line: #dfe4ea; --page: #f4f6f9; --card: #ffffff;
  --accent: #0033a0;
  --pass: #1e7b34; --pass-bg: #e3f3e6;
  --done: #2a6496; --done-bg: #e3eef8;
  --fail: #b3261e; --fail-bg: #fbe4e2;
  --error: #8a4500; --error-bg: #fdeed9;
  --skip: #4b5563; --skip-bg: #eef0f3;
  --stop: #6b3fa0; --stop-bg: #efe6f8;
  --unknown: #4b5563; --unknown-bg: #eef0f3;
}
* { box-sizing: border-box; }
html { background: var(--page); }
body { margin: 0; color: var(--ink); background: var(--page);
  font: 14px/1.45 "Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial,
  sans-serif; }
.watermark { position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background: var(--logo) no-repeat center / min(70vmin, 640px); opacity: 0.045; }
main { position: relative; z-index: 1; max-width: 1180px; margin: 0 auto;
  padding: 24px 20px 40px; }
h1, h2 { margin: 0; font-weight: 600; }
h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
pre { font-family: Consolas, "Cascadia Mono", "SFMono-Regular", Menlo, monospace; }
.muted { color: var(--muted); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; }

.masthead { display: flex; align-items: center; gap: 20px; padding: 18px 22px;
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  border-left: 6px solid var(--unknown); }
.masthead.r-PASS { border-left-color: var(--pass); }
.masthead.r-DONE { border-left-color: var(--done); }
.masthead.r-FAIL { border-left-color: var(--fail); }
.masthead.r-ERROR { border-left-color: var(--error); }
.masthead.r-SKIP { border-left-color: var(--skip); }
.masthead.r-STOP { border-left-color: var(--stop); }
.title { flex: 1; min-width: 0; }
.title h1 { font-size: 24px; line-height: 1.2; overflow-wrap: anywhere; }
.identity { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 14px; }
.id-label { color: var(--muted); }
.description { margin: 6px 0 0; color: var(--muted); }
.verdict { flex: none; text-align: center; min-width: 130px; padding: 10px 18px;
  border-radius: 8px; color: #fff; background: var(--unknown); }
.r-PASS .verdict { background: var(--pass); }
.r-DONE .verdict { background: var(--done); }
.r-FAIL .verdict { background: var(--fail); }
.r-ERROR .verdict { background: var(--error); }
.r-SKIP .verdict { background: var(--skip); }
.r-STOP .verdict { background: var(--stop); }
.verdict-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; }
.verdict-value { font-size: 26px; font-weight: 700; letter-spacing: 0.04em; }

.metrics { display: grid; grid-template-columns: repeat(3, minmax(130px, 1fr)) 2fr;
  gap: 12px; margin-top: 12px; }
.metric { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 10px 14px; }
.metric-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted); margin-bottom: 4px; }
.metric-value { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }
.metric-problems .metric-value { color: var(--fail); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { position: relative; display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 11px; border-radius: 999px; cursor: pointer; user-select: none;
  font-size: 13px; font-weight: 600; }
.chip input { position: absolute; opacity: 0; pointer-events: none; }
.chip:has(input:not(:checked)) { opacity: 0.4; text-decoration: line-through; }
.chip:has(input:focus-visible) { outline: 2px solid var(--accent); outline-offset: 2px; }
.chip-count { font-variant-numeric: tabular-nums; }

.facts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 16px; }
dl { margin: 8px 0 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 20px; }
dt { font-size: 12px; color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
.not-recorded { margin: 8px 0 0; }

.results { margin-top: 20px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  justify-content: space-between; margin-bottom: 8px; }
.buttons { display: flex; flex-wrap: wrap; gap: 8px; }
.buttons button { font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 6px;
  border: 1px solid var(--line); background: var(--card); color: var(--ink); cursor: pointer; }
.buttons button:hover { border-color: var(--accent); color: var(--accent); }
.buttons button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.table-wrap { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  overflow: clip; }
table.steps { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
col.c-toggle { width: 36px; } col.c-result { width: 88px; } col.c-type { width: 130px; }
col.c-duration { width: 100px; }
th { position: sticky; top: 0; z-index: 2; text-align: left; font-size: 12px; font-weight: 600;
  color: var(--muted); padding: 9px 10px; border-bottom: 1px solid var(--line);
  background: #fafbfc; }
td { padding: 7px 10px; vertical-align: top; border-bottom: 1px solid var(--line); }
.col-duration { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.col-type { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
.col-step { overflow-wrap: anywhere; }
.col-toggle { padding: 4px 0 0 6px; }

tbody.group td { background: #eef2f7; padding: 7px 10px; }
.group-line { display: flex; align-items: center; gap: 12px; }
.group-name { font-weight: 600; }
.group-counts { display: inline-flex; gap: 6px; flex: 1; }
.group-outcome { display: inline-flex; align-items: center; gap: 12px; }
.group-duration { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums;
  min-width: 80px; text-align: right; }
.mini { font-size: 12px; font-weight: 600; padding: 0 7px; border-radius: 999px; }

tbody.step.has-details tr.summary { cursor: pointer; }
tbody.step tr.summary:hover td { background: #f7f9fc; }
tbody.step.r-SKIP .col-step { color: var(--muted); }
tbody.sequence-end tr.summary td { color: var(--muted); font-size: 13px; }
.sequence-mark { font-style: italic; }

.toggle { width: 24px; height: 24px; padding: 0; border: 0; border-radius: 4px;
  background: transparent; cursor: pointer; }
.toggle:hover { background: var(--skip-bg); }
.toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 0; }
.chevron { display: inline-block; width: 8px; height: 8px;
  border-right: 2px solid var(--muted); border-bottom: 2px solid var(--muted);
  transform: rotate(-45deg); }
tbody.open .chevron { transform: rotate(45deg); }

.badge, .chip, .mini { color: var(--unknown); background: var(--unknown-bg); }
.badge { display: inline-block; min-width: 52px; text-align: center; font-size: 12px;
  font-weight: 700; letter-spacing: 0.03em; padding: 1px 7px; border-radius: 4px; }
.r-PASS.badge, .r-PASS.chip, .r-PASS.mini { color: var(--pass); background: var(--pass-bg); }
.r-DONE.badge, .r-DONE.chip, .r-DONE.mini { color: var(--done); background: var(--done-bg); }
.r-FAIL.badge, .r-FAIL.chip, .r-FAIL.mini { color: var(--fail); background: var(--fail-bg); }
.r-ERROR.badge, .r-ERROR.chip, .r-ERROR.mini { color: var(--error); background: var(--error-bg); }
.r-SKIP.badge, .r-SKIP.chip, .r-SKIP.mini { color: var(--skip); background: var(--skip-bg); }
.r-STOP.badge, .r-STOP.chip, .r-STOP.mini { color: var(--stop); background: var(--stop-bg); }

.error-hint { margin-top: 2px; font-size: 12px; color: var(--fail); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.r-ERROR .error-hint { color: var(--error); }
.r-STOP .error-hint { color: var(--stop); }
.r-SKIP .error-hint { color: var(--muted); }
tr.details td { background: #fbfcfd; padding: 2px 10px 12px; }
.detail { margin-top: 10px; min-width: 0; }
.io { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 0 12px; }
.detail-label { font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); margin-bottom: 4px; }
.detail pre { margin: 0; padding: 8px 12px; max-height: 360px; overflow: auto;
  background: #f3f5f8; border: 1px solid var(--line); border-radius: 6px; font-size: 12.5px;
  white-space: pre-wrap; overflow-wrap: anywhere; }
.detail-error pre { background: var(--fail-bg); border-color: #f1c2bd; color: #7a1a14; }
.detail-meta { margin-top: 8px; font-size: 11px; color: var(--muted); }
.empty { padding: 24px; text-align: center; background: var(--card);
  border: 1px dashed var(--line); border-radius: 10px; }
.filtered { display: none; }

footer { margin-top: 24px; text-align: center; font-size: 12px; color: var(--muted); }

@media (max-width: 820px) {
  .metrics { grid-template-columns: 1fr 1fr; }
  .metric-chips { grid-column: 1 / -1; }
  .facts { grid-template-columns: 1fr; }
  .masthead { flex-wrap: wrap; }
  col.c-type { width: 0; } .col-type { display: none; }
}
@media print {
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  html, body { background: #fff; }
  main { max-width: none; padding: 0; }
  .buttons, .toggle { display: none; }
  .table-wrap { overflow: visible; }
  th { position: static; }
  tr.details { display: table-row !important; }
  .detail pre { max-height: none; overflow: visible; }
  .card, .metric, .masthead { break-inside: avoid; }
  tbody.step { break-inside: avoid; }
}
"""

PAGE_SCRIPT = """
(function () {
  var PROBLEMS = ["FAIL", "ERROR", "STOP"];

  function setOpen(body, open) {
    var details = body.querySelector("tr.details");
    var toggle = body.querySelector("button.toggle");
    if (!details) { return; }
    details.hidden = !open;
    body.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    // A traceback ends with the exception: show that end first.
    var error = details.querySelector(".detail-error pre");
    if (open && error) { error.scrollTop = error.scrollHeight; }
  }
  document.querySelectorAll("tbody.step.has-details tr.summary").forEach(function (row) {
    // The toggle button's click (mouse or keyboard) bubbles up to here too.
    row.addEventListener("click", function () {
      // Selecting text in the row is not a request to open it.
      if (window.getSelection && String(window.getSelection()) !== "") { return; }
      var body = row.parentNode;
      setOpen(body, !body.classList.contains("open"));
    });
  });
  function setAll(open) {
    document.querySelectorAll("tbody.step.has-details").forEach(function (body) {
      if (!body.classList.contains("filtered")) { setOpen(body, open); }
    });
  }
  function on(id, handler) {
    var element = document.getElementById(id);
    if (element) { element.addEventListener("click", handler); }
  }
  on("expand-all", function () { setAll(true); });
  on("collapse-all", function () { setAll(false); });

  var boxes = document.querySelectorAll("input[data-filter]");
  function applyFilters() {
    var hidden = {};
    boxes.forEach(function (box) {
      if (!box.checked) { hidden[box.getAttribute("data-filter")] = true; }
    });
    document.querySelectorAll("tbody.step").forEach(function (body) {
      body.classList.toggle("filtered", hidden[body.getAttribute("data-result")] === true);
    });
    // A group whose every row is filtered out loses its header too.
    var header = null, visible = false;
    function closeGroup() { if (header) { header.classList.toggle("filtered", !visible); } }
    document.querySelectorAll("table.steps > tbody").forEach(function (body) {
      if (body.classList.contains("group")) {
        closeGroup(); header = body; visible = false;
      } else if (!body.classList.contains("filtered")) {
        visible = true;
      }
    });
    closeGroup();
  }
  boxes.forEach(function (box) { box.addEventListener("change", applyFilters); });
  on("problems-only", function () {
    boxes.forEach(function (box) {
      box.checked = PROBLEMS.indexOf(box.getAttribute("data-filter")) !== -1;
    });
    applyFilters();
  });
  on("all-results", function () {
    boxes.forEach(function (box) { box.checked = true; });
    applyFilters();
  });
})();
"""
