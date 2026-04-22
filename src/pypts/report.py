# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Handles the generation of incremental CSV reports for pypts recipe execution."""
import json
import csv
import shutil
from typing import List, Dict, Any
from pathlib import Path
import logging
from pypts.recipe import StepResult, ResultType, Step
import argparse
import html
from datetime import datetime
from itertools import groupby
from operator import itemgetter

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.tiff', '.webp'}


def _serialize_step(step: Step) -> Dict[str, Any]:
    """Helper to serialize a Step object minimally for the report."""
    if step:
        return {
            "name": step.name,
            "id": str(step.id),
            "description": step.description,
            "type": step.__class__.__name__
        }
    return None

def _result_to_dict(result: StepResult) -> Dict[str, Any]:
    """Converts a StepResult object into a dictionary suitable for reporting."""
    if not isinstance(result, StepResult):
        logger.warning(f"Expected StepResult, got {type(result)}. Skipping.")
        return None

    try:
        inputs_serializable = json.loads(json.dumps(result.inputs, default=str))
    except (TypeError, OverflowError) as e:
        logger.warning(f"Could not serialize inputs for step {result.step.name if result.step else 'N/A'}: {e}")
        inputs_serializable = {"error": "Could not serialize inputs"}

    try:
        outputs_serializable = json.loads(json.dumps(result.outputs, default=str))
    except (TypeError, OverflowError) as e:
        logger.warning(f"Could not serialize outputs for step {result.step.name if result.step else 'N/A'}: {e}")
        outputs_serializable = {"error": "Could not serialize outputs"}

    return {
        "step": _serialize_step(result.step),
        "result": str(result.result) if result.result else None,
        "inputs": inputs_serializable,
        "outputs": outputs_serializable,
        "error_info": result.error_info,
        "recipe_name": getattr(result, 'recipe_name', None),
        "recipe_file_name": getattr(result, 'recipe_file_name', None),
        "serial_number": getattr(result, 'serial_number', None),
        "sequence_name": getattr(result, 'sequence_name', None),
        "pypts_version": getattr(result, 'pypts_version', 'unknown'),
        "image_paths": getattr(result, 'image_paths', []),
    }

def _flatten_single_result(result_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Flattens a single result dictionary for CSV writing."""
    if not result_dict: return None
    return {
        "recipe_name": result_dict.get("recipe_name", "N/A"),
        "recipe_file_name": result_dict.get("recipe_file_name", "N/A"),
        "sequence_name": result_dict.get("sequence_name", "N/A"),
        "serial_number": result_dict.get("serial_number", "N/A"),
        "pypts_version": result_dict.get("pypts_version", "unknown"),
        "step_name": result_dict.get("step", {}).get("name", "N/A") if result_dict.get("step") else "N/A",
        "step_id": result_dict.get("step", {}).get("id", "N/A") if result_dict.get("step") else "N/A",
        "step_type": result_dict.get("step", {}).get("type", "N/A") if result_dict.get("step") else "N/A",
        "result": result_dict.get("result"),
        "inputs": json.dumps(result_dict.get("inputs", {})),
        "outputs": json.dumps(result_dict.get("outputs", {})),
        "error_info": result_dict.get("error_info"),
        "image_paths": "",  # filled in by add_step_result after copying files
    }


class Report:
    """
    Manages incremental CSV report generation during PTS execution.
    Writes results to a CSV file in the specified directory as they become
    available via the `add_step_result` method.
    """
    _CSV_HEADERS = [
        "recipe_name", "recipe_file_name", "sequence_name", "serial_number",
        "pypts_version", "step_name", "step_id", "step_type",
        "result", "inputs", "outputs", "error_info", "image_paths",
    ]

    def __init__(self, output_dir: str | Path, timestamp, overwrite=True):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = timestamp
        self._csv_file_handle = None
        self._csv_writer: csv.DictWriter | None = None
        self._init_csv(overwrite)
        logger.info(f"CSV Report initialized. Output directory: {self.output_dir}")

    def _init_csv(self, overwrite):
        path = self.output_dir / f"report_{self.timestamp}.csv"
        try:
            open_mode = 'w' if overwrite else 'a'
            write_csv_header = overwrite or not path.is_file()
            self._csv_file_handle = open(path, open_mode, newline='', encoding='utf-8')
            self._csv_writer = csv.DictWriter(self._csv_file_handle, fieldnames=self._CSV_HEADERS)
            if write_csv_header:
                self._csv_writer.writeheader()
            logger.info(f"Initialized CSV report: {path}")
        except Exception as e:
            logger.error(f"Failed to initialize CSV report {path}: {e}")
            if self._csv_file_handle:
                try: self._csv_file_handle.close()
                except: pass
            self._csv_writer = None

    def add_step_result(self, result: StepResult):
        """Adds a StepResult and writes it to the CSV report file."""
        if not isinstance(result, StepResult):
            logger.warning(f"Attempted to add non-StepResult to report: {type(result)}")
            return

        result_dict = _result_to_dict(result)
        if not result_dict:
            return

        # Copy any image files returned by the step into the report img/ dir
        relative_image_paths = _copy_step_images(result, self.output_dir)

        if self._csv_writer and self._csv_file_handle:
            flat_item = _flatten_single_result(result_dict)
            if flat_item:
                flat_item["image_paths"] = ";".join(relative_image_paths)
                try:
                    self._csv_writer.writerow(flat_item)
                    self._csv_file_handle.flush()
                except Exception as e:
                    logger.error(f"Failed to write row to CSV: {e}")

    def finish_reports(self):
        """Closes the CSV report file handle."""
        logger.info("Finishing reports...")
        if self._csv_file_handle:
            try:
                self._csv_file_handle.close()
                logger.debug("Closed CSV file handle")
            except Exception as e:
                logger.error(f"Error closing CSV file handle: {e}")
        else:
            logger.debug("CSV file handle already closed or never opened.")
        self._csv_writer = None
        self._csv_file_handle = None
        logger.info("Report finishing complete.")


def _copy_step_images(result: StepResult, output_dir: Path) -> List[str]:
    """Copies image files from result.image_paths into output_dir/img/.

    Returns a list of relative paths (e.g. 'img/abc123_plot.png') for CSV storage.
    """
    relative_paths = []
    if not result.image_paths:
        return relative_paths

    img_dir = output_dir / "img"
    img_dir.mkdir(exist_ok=True)

    step_id = str(result.step.id) if result.step else "unknown"

    for src_path_str in result.image_paths:
        src = Path(src_path_str)
        if not src.exists():
            logger.warning(f"Image file not found, skipping: {src}")
            continue
        if src.suffix.lower() not in IMAGE_EXTENSIONS:
            logger.warning(f"File does not look like an image, skipping: {src}")
            continue
        dest_name = f"{step_id}_{src.name}"
        dest = img_dir / dest_name
        try:
            shutil.copy2(src, dest)
            relative_paths.append(f"img/{dest_name}")
            logger.debug(f"Copied image {src} -> {dest}")
        except Exception as e:
            logger.error(f"Failed to copy image {src}: {e}")

    return relative_paths


# --- Listener Function ---
from queue import SimpleQueue

STOP_LISTENER = object()
LISTENER_RUNNING = False

def report_listener(result_queue: SimpleQueue, output_dir: str, overwrite: bool):
    """
    Listens to a queue for StepResult objects and generates reports incrementally.

    Exits gracefully when the STOP_LISTENER sentinel object is received on the queue.
    """
    timestamp = datetime.now().strftime('%Y-%m-%d_%Hh%M')
    report_manager = Report(output_dir=output_dir, timestamp=timestamp, overwrite=overwrite)
    logger.info(f"Report listener started. Output dir: {output_dir}. Waiting for results...")
    active = True
    while active:
        try:
            item = result_queue.get()
            if item is STOP_LISTENER:
                logger.info("Report listener received stop signal.")
                global LISTENER_RUNNING
                LISTENER_RUNNING = False
                active = False
            elif isinstance(item, StepResult):
                logger.debug(f"Listener received StepResult: {item.step.name if item.step else 'N/A'}")
                report_manager.add_step_result(item)
            else:
                logger.warning(f"Listener received unexpected item: {type(item)} - {item!r}")
        except Exception as e:
            logger.error(f"Error in report listener loop: {e}", exc_info=True)

    try:
        report_manager.finish_reports()
        csv_report_path = report_manager.output_dir / f'report_{timestamp}.csv'
        html_report_path = report_manager.output_dir / f'report_{timestamp}.html'
        if csv_report_path.exists():
            logger.info(f"Generating HTML report from {csv_report_path}...")
            generate_html_report(csv_path=csv_report_path, html_path=html_report_path, output_dir=report_manager.output_dir)
        else:
            logger.warning(f"CSV report not found at {csv_report_path}, cannot generate HTML report.")
    except Exception as e:
        logger.error(f"Error during final report generation: {e}", exc_info=True)
    finally:
        logger.info("Report listener finished.")


# --- HTML Report Generation ---

def generate_html_report(csv_path: Path, html_path: Path, output_dir: Path = None):
    """Reads a CSV report and generates an HTML version."""
    all_results = []
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                all_results.append(row)
    except FileNotFoundError:
        logger.error(f"CSV file not found: {csv_path}")
        return
    except Exception as e:
        logger.error(f"Error reading CSV file {csv_path}: {e}")
        return

    if not all_results:
        logger.warning("No results found in CSV to generate HTML report.")
        return

    html_content = """
<!DOCTYPE html>
<html>
<head>
<title>pypts Test Report</title>
<meta charset="utf-8">
<style>
    body { font-family: sans-serif; margin: 20px; }
    h1, h2 { color: #333; }
    table { border-collapse: collapse; width: 100%; margin-top: 20px; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }
    th { background-color: #f2f2f2; }
    .status-pass { background-color: #d4edda; color: #155724; }
    .status-fail { background-color: #f8d7da; color: #721c24; }
    .status-error { background-color: #f8d7da; color: #721c24; }
    .status-skip { background-color: #fff3cd; color: #856404; }
    .status-unknown { background-color: #e2e3e5; color: #383d41; }
    pre { white-space: pre-wrap; word-wrap: break-word; background-color: #f8f9fa; padding: 5px; border: 1px solid #eee; margin: 0; }
    figure { display: inline-block; margin: 10px; vertical-align: top; max-width: 600px; border: 1px solid #ddd; padding: 8px; border-radius: 4px; }
    figure img { max-width: 100%; height: auto; display: block; }
    figcaption { margin-top: 6px; font-size: 0.9em; color: #555; }
</style>
</head>
<body>
"""

    html_content += "<h1>pypts Test Report</h1>"
    html_content += f"<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"

    results_by_serial = {
        serial: list(results)
        for serial, results in groupby(all_results, key=itemgetter('serial_number'))
    }

    for results in results_by_serial.values():
        if results:
            first_row = results[0]
            recipe_name = html.escape(first_row.get('recipe_name', 'N/A'))
            recipe_file = html.escape(first_row.get('recipe_file_name', 'N/A'))
            serial_num = html.escape(first_row.get('serial_number', 'N/A'))
            pypts_version = html.escape(first_row.get('pypts_version', 'unknown'))
            html_content += "<h2>Run Context</h2>"
            html_content += f"<p><strong>Recipe:</strong> {recipe_name}<br>"
            html_content += f"<strong>File:</strong> {recipe_file}<br>"
            html_content += f"<strong>Serial Number:</strong> {serial_num}<br>"
            html_content += f"<strong>pypts Version:</strong> {pypts_version}</p>"
        else:
            html_content += "<p><strong>Run Context:</strong> No results data found.</p>"

        total_steps = len(results)
        html_content += "<h2>Summary</h2>"
        html_content += f"<p>Total steps: {total_steps}</p>"

        html_content += "<h2>Details</h2>"
        html_content += "<table>"
        html_content += "<thead><tr><th>Sequence</th><th>Step Name</th><th>Status</th><th>Inputs</th><th>Outputs</th><th>Error Info</th></tr></thead>"
        html_content += "<tbody>"

        for row in results:
            status = str(row.get('result', 'Unknown')).split('.')[-1].lower()
            css_class = f"status-{status}" if status in ['pass', 'fail', 'error', 'skip'] else "status-unknown"

            html_content += f'<tr class="{css_class}">'
            html_content += f"<td>{html.escape(row.get('sequence_name', 'N/A'))}</td>"
            html_content += f"<td>{html.escape(row.get('step_name', 'N/A'))}</td>"
            html_content += f"<td>{html.escape(status.upper())}</td>"

            for col in ['inputs', 'outputs', 'error_info']:
                content = row.get(col, '')
                escaped_content = html.escape(content)
                formatted_content = escaped_content
                if content and content.strip().startswith(('{', '[')):
                    try:
                        parsed = json.loads(content)
                        formatted_content = f'<pre>{html.escape(json.dumps(parsed, indent=2))}</pre>'
                    except json.JSONDecodeError:
                        formatted_content = f'<pre>{escaped_content}</pre>'
                elif content:
                    formatted_content = f'<pre>{escaped_content}</pre>'
                else:
                    formatted_content = ""

                if col == 'outputs' and formatted_content:
                    cell_html = (
                        "<details>"
                        f"<summary>Show output ({len(content)} chars)</summary>"
                        f"{formatted_content}"
                        "</details>"
                    )
                else:
                    cell_html = formatted_content

                html_content += f"<td>{cell_html}</td>"

            html_content += "</tr>"

        html_content += "</tbody></table>"

        # --- Images section ---
        step_images = [
            (row.get('step_name', 'N/A'), row.get('result', 'Unknown'), row.get('image_paths', ''))
            for row in results
            if row.get('image_paths', '').strip()
        ]

        if step_images:
            html_content += "<h2>Images</h2>"
            for step_name, result_status, paths_str in step_images:
                status_label = str(result_status).split('.')[-1].upper()
                for rel_path in paths_str.split(';'):
                    rel_path = rel_path.strip()
                    if not rel_path:
                        continue
                    html_content += "<figure>"
                    html_content += f'<img src="{html.escape(rel_path)}" alt="{html.escape(step_name)}">'
                    html_content += (
                        f"<figcaption>"
                        f"<strong>Step:</strong> {html.escape(step_name)} &mdash; "
                        f"<strong>Result:</strong> {html.escape(status_label)}"
                        f"</figcaption>"
                    )
                    html_content += "</figure>"

    html_content += "</body></html>"

    try:
        with open(html_path, 'w', encoding='utf-8') as htmlfile:
            htmlfile.write(html_content)
        logger.info(f"HTML report generated successfully: {html_path}")
    except Exception as e:
        logger.error(f"Error writing HTML file {html_path}: {e}")


if __name__ == "__main__":
    import uuid
    from datetime import datetime
    from pypts.recipe import Step, StepResult, ResultType

    pre_timestamp = datetime.now().strftime('%Y-%m-%d_%Hh%M')

    parser = argparse.ArgumentParser(description="Generate a sample pypts report CSV.")
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default="./temp_report_output",
        help="Directory to save the report.csv file."
    )
    parser.add_argument(
        "-t", "--timestamp",
        type=str,
        default=pre_timestamp,
        help="Insert a given timestamp for report for individuality."
    )
    args = parser.parse_args()
    output_directory = Path(args.output_dir)
    timestamp = args.timestamp

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    print(f"Example report will be generated in: {output_directory.resolve()}")

    report_manager = Report(output_dir=output_directory, timestamp=timestamp)

    step1 = Step(step_name="Run Other Test", id=uuid.uuid4(), description="First step")
    step2 = Step(step_name="Run Simple Output Test", id=uuid.uuid4(), description="Second step")
    step3 = Step(step_name="Run Range Test (Fail)", id=uuid.uuid4(), description="Third step, expected fail")
    step4 = Step(step_name="Generate Error", id=uuid.uuid4(), description="Fourth step, error")

    result1 = StepResult(step=step1)
    result1.recipe_name = "SampleRecipe"
    result1.recipe_file_name = "sample_recipe.yaml"
    result1.serial_number = "DUMMY_SN_12345"
    result1.sequence_name = "Main"
    result1.pypts_version = "0.1.0-dummy"
    result1.set_result(
        result_type=ResultType.PASS,
        inputs={"arg1": 10},
        outputs={"some_return": True, "value": "abc"}
    )
    report_manager.add_step_result(result1)

    result2 = StepResult(step=step2, parent=result1.uuid)
    result2.recipe_name = "SampleRecipe"
    result2.recipe_file_name = "sample_recipe.yaml"
    result2.serial_number = "DUMMY_SN_12345"
    result2.sequence_name = "Main"
    result2.pypts_version = "0.1.0-dummy"
    result2.set_result(
        result_type=ResultType.PASS,
        inputs={"value": "abc"},
        outputs={"my_output": "calculated_abc"}
    )
    report_manager.add_step_result(result2)

    result3 = StepResult(step=step3, parent=result1.uuid)
    result3.recipe_name = "SampleRecipe"
    result3.recipe_file_name = "sample_recipe.yaml"
    result3.serial_number = "DUMMY_SN_12345"
    result3.sequence_name = "Main"
    result3.pypts_version = "0.1.0-dummy"
    result3.set_result(
        result_type=ResultType.FAIL,
        inputs={"value": 25, "min": 10, "max": 20},
        outputs={"compare": False}
    )
    report_manager.add_step_result(result3)

    try:
        raise ValueError("Something went wrong deliberately")
    except Exception as e:
        result4 = StepResult(step=step4, parent=result1.uuid)
        result4.recipe_name = "SampleRecipe"
        result4.recipe_file_name = "sample_recipe.yaml"
        result4.serial_number = "DUMMY_SN_12345"
        result4.sequence_name = "Main"
        result4.pypts_version = "0.1.0-dummy"
        result4.set_error(
            error_info=f"{type(e).__name__}: {e}",
            inputs={}
        )
        report_manager.add_step_result(result4)

    report_manager.finish_reports()

    report_name = f"report_{timestamp}"
    csv_report_path = report_manager.output_dir / f"{report_name}.csv"
    html_report_path = report_manager.output_dir / f"{report_name}.html"
    print(f"Sample report generated: {csv_report_path}")

    if csv_report_path.exists():
        generate_html_report(csv_path=csv_report_path, html_path=html_report_path, output_dir=report_manager.output_dir)
        print(f"HTML report generated: {html_report_path}")
    else:
        print(f"CSV report not found at {csv_report_path}, skipping HTML generation.")
