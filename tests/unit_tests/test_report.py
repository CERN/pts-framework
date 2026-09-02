# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Unit tests for the Report module (src/pypts/report/).

The Report is driven exactly as CORE drives it: messages on the real inbox,
one turn of poll_core(). The assertions are on disk - the CSV growing row by
row and the HTML appearing in the same run folder - because artefacts are the
module's whole output.
"""

import csv
import json
import queue

from pypts.messages import QueueWrapper
from pypts.messages.common_messages import ModuleError, ResultType, StepOutcome
from pypts.messages.core_report_communication import (
    GenerateReport,
    ReportGenerated,
    ReportStopped,
    StopReport,
)
from pypts.messages.run_events import (
    RunFinished,
    RunMetadata,
    RunStarted,
    SequenceStarted,
    StepExecuted,
)
from pypts.report.report import Report, rows_from_csv
from pypts.step.wait_step import WaitStep

A_RUN = RunStarted(recipe_name="Wait demo", recipe_description="Two short waits")


def build_report(tmp_path):
    """A Report told where to write, with no thread behind it."""
    return Report(
        to_core=QueueWrapper(queue.Queue()),
        from_core=QueueWrapper(queue.Queue()),
        output_dir=tmp_path,
    )


def drive(report, *messages):
    """Deliver messages the way CORE does: through the inbox and the loop."""
    for message in messages:
        report.inbox.send(message)
    report.poll_core()


def sent_to_core(report):
    """Everything the Report put on its outbox, in order."""
    return list(report.core.receive())


def a_step_executed(step_name="First wait", result=ResultType.DONE):
    step = WaitStep(step_name=step_name, wait_time="0")
    return StepExecuted(
        outcome=StepOutcome(step_id=step.id, step_name=step_name, result=result),
        step_type="WaitStep",
        inputs={"wait_time": "0.5"},
        outputs={"voltage": 3.3},
        started_at=1_760_000_000.5,
        duration_s=0.5,
    )


def csv_rows(run_dir):
    with open(run_dir / "report.csv", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


# --------------------------------------------------------------------------
# The incremental CSV
# --------------------------------------------------------------------------

def test_run_started_creates_the_run_folder_and_the_csv(tmp_path):
    """One folder per run, created the moment the run starts, CSV inside."""
    report = build_report(tmp_path)

    drive(report, A_RUN)

    run_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "report.csv").is_file()
    # The recipe's name is in the folder name, so a shelf of runs is readable.
    assert "Wait_demo" in run_dirs[0].name


def test_results_are_written_incrementally_not_only_at_the_end(tmp_path):
    """A run that dies mid-sequence must still leave the results it produced.

    Asserted by reading the file from disk after one step, with no RunFinished
    anywhere in sight - the row must already be there, flushed.
    """
    report = build_report(tmp_path)

    drive(report, A_RUN, SequenceStarted(sequence_name="Main"), a_step_executed())

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    rows = csv_rows(run_dir)
    assert len(rows) == 1
    row = rows[0]
    assert row["recipe_name"] == "Wait demo"
    assert row["sequence_name"] == "Main"
    assert row["step_name"] == "First wait"
    assert row["step_type"] == "WaitStep"
    assert row["result"] == "DONE"
    assert json.loads(row["inputs"]) == {"wait_time": "0.5"}
    assert json.loads(row["outputs"]) == {"voltage": 3.3}
    assert row["duration_s"] == "0.5"


def test_each_step_appends_one_row(tmp_path):
    report = build_report(tmp_path)

    drive(
        report,
        A_RUN,
        SequenceStarted(sequence_name="Main"),
        a_step_executed("First wait"),
        a_step_executed("Second wait", result=ResultType.FAIL),
    )

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    rows = csv_rows(run_dir)
    assert [row["step_name"] for row in rows] == ["First wait", "Second wait"]
    assert [row["result"] for row in rows] == ["DONE", "FAIL"]


# --------------------------------------------------------------------------
# The HTML report
# --------------------------------------------------------------------------

def test_generate_produces_html_and_answers_report_generated(tmp_path):
    report = build_report(tmp_path)

    drive(
        report,
        A_RUN,
        SequenceStarted(sequence_name="Main"),
        a_step_executed(),
        RunFinished(result=ResultType.DONE),
        GenerateReport(),
    )

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    html_path = run_dir / "report.html"
    assert html_path.is_file()
    html_text = html_path.read_text(encoding="utf-8")
    assert "Wait demo" in html_text
    assert "First wait" in html_text
    assert "DONE" in html_text

    generated = [m for m in sent_to_core(report) if isinstance(m, ReportGenerated)]
    assert len(generated) == 1
    assert generated[0].report_path == str(html_path)


def test_artifacts_are_grouped_in_one_run_folder(tmp_path):
    """Report and raw data per run, in a single traceable folder."""
    report = build_report(tmp_path)

    drive(report, A_RUN, a_step_executed(), RunFinished(result=ResultType.DONE), GenerateReport())

    run_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    assert sorted(path.name for path in run_dirs[0].iterdir()) == ["report.csv", "report.html"]


def test_html_escapes_what_the_recipe_wrote(tmp_path):
    """Step data is untrusted text; a value must not become markup."""
    report = build_report(tmp_path)
    step = WaitStep(step_name="sneaky", wait_time="0")
    outcome = StepOutcome(step_id=step.id, step_name="<script>x</script>", result=ResultType.DONE)
    executed = StepExecuted(
        outcome=outcome,
        step_type="WaitStep",
        inputs={},
        outputs={},
        started_at=1_760_000_000.5,
        duration_s=0.0,
    )

    drive(report, A_RUN, executed, RunFinished(result=ResultType.DONE), GenerateReport())

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    html_text = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "<script>x</script>" not in html_text
    assert "&lt;script&gt;" in html_text


# --------------------------------------------------------------------------
# Run boundaries and robustness
# --------------------------------------------------------------------------

def test_two_runs_get_two_folders(tmp_path):
    """Two runs in the same second must not overwrite each other."""
    report = build_report(tmp_path)

    drive(report, A_RUN, RunFinished(result=ResultType.DONE))
    drive(report, A_RUN, RunFinished(result=ResultType.DONE))

    run_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(run_dirs) == 2


def test_a_step_outside_a_run_is_survived(tmp_path):
    """A record with nowhere to go is dropped with a warning, never a crash.

    @catch_and_report_errors() would turn a crash into a ModuleError on the
    outbox, so "no ModuleError" is what asserts the drop was graceful.
    """
    report = build_report(tmp_path)

    drive(report, a_step_executed())

    assert [path for path in tmp_path.iterdir() if path.is_dir()] == []
    assert not [m for m in sent_to_core(report) if isinstance(m, ModuleError)]


def test_generate_without_a_run_answers_nothing(tmp_path):
    report = build_report(tmp_path)

    drive(report, GenerateReport())

    sent = sent_to_core(report)
    assert not [m for m in sent if isinstance(m, ReportGenerated)]
    assert not [m for m in sent if isinstance(m, ModuleError)]


def test_a_failed_run_dir_does_not_resurrect_the_previous_run(tmp_path, monkeypatch):
    """A run folder that cannot be created must not hand the run to the previous one.

    @catch_and_report_errors() swallows the failure, so if start_run() left the
    old run_dir/run_info/rows in place, this run's verdict would be stamped on
    the previous run and its report.html rewritten in the previous run's folder.
    """
    report = build_report(tmp_path)

    drive(
        report,
        A_RUN,
        SequenceStarted(sequence_name="Main"),
        a_step_executed(),
        RunFinished(result=ResultType.DONE),
        GenerateReport(),
    )
    first_run_dir = report.run_dir
    first_html = (first_run_dir / "report.html").read_text(encoding="utf-8")
    sent_to_core(report)  # drain what the first run said, so what follows is new

    def refuse_to_make_a_run_dir(recipe_name):
        raise OSError("disk says no")

    monkeypatch.setattr(report, "make_run_dir", refuse_to_make_a_run_dir)

    drive(
        report,
        RunStarted(recipe_name="Second recipe", recipe_description="After the failure"),
        SequenceStarted(sequence_name="Main"),
        a_step_executed("Step of the second run"),
        RunFinished(result=ResultType.FAIL),
        GenerateReport(),
    )

    assert report.run_dir is None
    assert (first_run_dir / "report.html").read_text(encoding="utf-8") == first_html
    sent = sent_to_core(report)
    # The decorator reports the OSError; nothing announces a report to the operator.
    assert [m for m in sent if isinstance(m, ModuleError)]
    assert not [m for m in sent if isinstance(m, ReportGenerated)]


def test_run_dir_name_is_capped_and_never_empty(tmp_path):
    """A pathological recipe name must still produce a folder that can be created.

    Non-ASCII letters pass isalnum() and survive the sanitising pass; only the
    length and the existence of the folder are asserted.
    """
    names = ["", "!!!", "x" * 250, "Wärme Prüfung"]
    for index, recipe_name in enumerate(names):
        output_dir = tmp_path / f"case_{index}"
        output_dir.mkdir()
        report = build_report(output_dir)

        drive(report, RunStarted(recipe_name=recipe_name, recipe_description=""))

        run_dirs = [path for path in output_dir.iterdir() if path.is_dir()]
        assert len(run_dirs) == 1
        assert len(run_dirs[0].name) <= len("YYYYMMDD_HHMMSS_") + 60
        assert (run_dirs[0] / "report.csv").is_file()


def test_stop_closes_the_csv_and_answers_report_stopped(tmp_path):
    report = build_report(tmp_path)

    drive(report, A_RUN, StopReport())

    assert report.csv_file is None
    assert report.running is False
    assert isinstance(sent_to_core(report)[-1], ReportStopped)


def test_report_output_path_comes_from_the_config_handler(tmp_path, monkeypatch):
    """Also: generated HTML must not land in the repository."""

    class FakeConfigHandler:
        def get_parameter(self, key):
            assert key == "paths.reports_dir"
            return tmp_path

    monkeypatch.setattr("pypts.report.report.ConfigHandler", FakeConfigHandler)

    report = Report(
        to_core=QueueWrapper(queue.Queue()),
        from_core=QueueWrapper(queue.Queue()),
    )

    assert report.output_dir == tmp_path


# --------------------------------------------------------------------------
# Run metadata: report.csv is the whole record of a run
# --------------------------------------------------------------------------

A_RUN_WITH_METADATA = RunStarted(
    recipe_name="Wait demo",
    recipe_description="Two short waits",
    recipe_version="1.2",
    pypts_version="0.2.2",
    metadata_names=("serial_number",),
)


def test_the_metadata_names_become_columns_from_the_first_row(tmp_path):
    """The names are known at run start even though the values are not."""
    report = build_report(tmp_path)

    drive(report, A_RUN_WITH_METADATA, a_step_executed())

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    rows = csv_rows(run_dir)
    assert "serial_number" in rows[0]
    # Nothing has set it yet, so it is blank rather than absent.
    assert rows[0]["serial_number"] == ""


def test_the_run_level_facts_are_on_every_row(tmp_path):
    """There is no second file, so a row carries everything about its run."""
    report = build_report(tmp_path)

    drive(
        report,
        A_RUN_WITH_METADATA,
        RunMetadata(values=(("serial_number", "SN-0042"),)),
        a_step_executed(step_name="First wait"),
        a_step_executed(step_name="Second wait"),
        RunFinished(result=ResultType.DONE),
    )

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    for row in csv_rows(run_dir):
        assert row["recipe_name"] == "Wait demo"
        assert row["recipe_description"] == "Two short waits"
        assert row["recipe_version"] == "1.2"
        assert row["pypts_version"] == "0.2.2"
        assert row["serial_number"] == "SN-0042"
        assert row["run_result"] == "DONE"
        assert row["run_started_at"]


def test_rows_written_before_the_serial_was_known_are_backfilled(tmp_path):
    """The blanks are the price of writing as the run goes; this is the pass
    that fills them, and why the CSV needs no companion file."""
    report = build_report(tmp_path)

    drive(report, A_RUN_WITH_METADATA, a_step_executed(step_name="get_serial_number"))
    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    assert csv_rows(run_dir)[0]["serial_number"] == ""

    drive(
        report,
        RunMetadata(values=(("serial_number", "SN-0042"),)),
        a_step_executed(step_name="Measure"),
        RunFinished(result=ResultType.PASS),
    )

    rows = csv_rows(report.run_dir)
    assert [row["serial_number"] for row in rows] == ["SN-0042", "SN-0042"]
    assert [row["run_result"] for row in rows] == ["PASS", "PASS"]


def test_a_metadata_name_the_recipe_never_sets_stays_blank(tmp_path):
    """A convention, not a requirement: a run that ignores it is not an error."""
    report = build_report(tmp_path)

    drive(
        report,
        A_RUN_WITH_METADATA,
        a_step_executed(),
        RunFinished(result=ResultType.DONE),
    )

    rows = csv_rows(report.run_dir)
    assert rows[0]["serial_number"] == ""
    assert [m for m in sent_to_core(report) if isinstance(m, ModuleError)] == []


def test_the_run_folder_is_renamed_with_the_metadata(tmp_path):
    """The folder is made before any step runs, so the serial can only join it here."""
    report = build_report(tmp_path)

    drive(
        report,
        A_RUN_WITH_METADATA,
        RunMetadata(values=(("serial_number", "SN-0042"),)),
        a_step_executed(),
        RunFinished(result=ResultType.DONE),
    )

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    assert run_dir.name.endswith("_SN_0042")
    assert report.run_dir == run_dir
    assert (run_dir / "report.csv").is_file()


def test_a_run_folder_that_cannot_be_renamed_is_kept(tmp_path, monkeypatch):
    """Losing a run over a cosmetic name would be a poor trade."""
    report = build_report(tmp_path)
    drive(report, A_RUN_WITH_METADATA, RunMetadata(values=(("serial_number", "SN-1"),)))
    original = report.run_dir

    def refuse(self, target):
        raise OSError("the folder is open in another window")

    monkeypatch.setattr("pathlib.Path.rename", refuse)
    drive(report, a_step_executed(), RunFinished(result=ResultType.DONE))

    assert report.run_dir == original
    assert original.is_dir()
    assert csv_rows(original)[0]["serial_number"] == "SN-1"


def test_the_html_header_shows_the_metadata(tmp_path):
    report = build_report(tmp_path)

    drive(
        report,
        A_RUN_WITH_METADATA,
        RunMetadata(values=(("serial_number", "SN-0042"),)),
        a_step_executed(),
        RunFinished(result=ResultType.DONE),
        GenerateReport(),
    )

    html_text = (report.run_dir / "report.html").read_text(encoding="utf-8")
    assert "serial_number" in html_text
    assert "SN-0042" in html_text
    assert "0.2.2" in html_text


def test_the_html_can_be_rebuilt_from_the_csv_alone(tmp_path):
    """One CSV, one report: no side-car file has to survive with it."""
    report = build_report(tmp_path)
    drive(
        report,
        A_RUN_WITH_METADATA,
        RunMetadata(values=(("serial_number", "SN-0042"),)),
        a_step_executed(step_name="First wait"),
        RunFinished(result=ResultType.DONE),
        GenerateReport(),
    )
    csv_path = report.run_dir / "report.csv"

    # A fresh Report, told nothing about that run but where its CSV is.
    rebuilt = build_report(tmp_path)
    rebuilt.rows = rows_from_csv(csv_path)
    rebuilt.run_info = RunStarted(
        recipe_name="", recipe_description="", metadata_names=("serial_number",)
    )
    html_text = rebuilt.render_html()

    assert "Wait demo" in html_text
    assert "SN-0042" in html_text
    assert "First wait" in html_text
    assert "DONE" in html_text
