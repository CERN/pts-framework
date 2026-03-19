# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""Handles the generation of incremental CSV reports for pypts recipe execution."""
import json
import csv
from typing import List, Dict, Any
from pathlib import Path
import logging
from pypts.recipe import StepResult, ResultType, Step
import argparse
import html # Added for HTML escaping
from datetime import datetime # Added for timestamp
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import h5py
import glob
import os
from itertools import groupby
from operator import itemgetter

logger = logging.getLogger(__name__)


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
    """Converts a StepResult object into a dictionary suitable for reporting.

    Handles potential serialization errors for inputs and outputs.
    Does not recursively process subresults for flat structures.
    """
    # Simplified: Does not handle subresults recursively for flat structure.
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
        # Add metadata fields
        "recipe_name": getattr(result, 'recipe_name', None),
        "recipe_file_name": getattr(result, 'recipe_file_name', None),
        "serial_number": getattr(result, 'serial_number', None),
        "sequence_name": getattr(result, 'sequence_name', None),
        "pypts_version": getattr(result, 'pypts_version', 'unknown'),
        # "subresults": ... Removed for flattening
    }

def _flatten_single_result(result_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Flattens a single result dictionary for CSV writing.

    Extracts nested step information and serializes complex fields like inputs/outputs to JSON.
    """ 
    if not result_dict: return None
    return {
        # Add metadata fields
        "recipe_name": result_dict.get("recipe_name", "N/A"),
        "recipe_file_name": result_dict.get("recipe_file_name", "N/A"),
        "sequence_name": result_dict.get("sequence_name", "N/A"),
        "serial_number": result_dict.get("serial_number", "N/A"),
        "pypts_version": result_dict.get("pypts_version", "unknown"),
        # Step info
        "step_name": result_dict.get("step", {}).get("name", "N/A") if result_dict.get("step") else "N/A",
        "step_id": result_dict.get("step", {}).get("id", "N/A") if result_dict.get("step") else "N/A",
        "step_type": result_dict.get("step", {}).get("type", "N/A") if result_dict.get("step") else "N/A",
        # Result info
        "result": result_dict.get("result"),
        "inputs": json.dumps(result_dict.get("inputs", {})), # Serialize complex structures
        "outputs": json.dumps(result_dict.get("outputs", {})), # Serialize complex structures
        "error_info": result_dict.get("error_info"),
        # Note: subresults are not directly represented in the flat CSV row for the parent
    }


class Report:
    """
    Manages incremental CSV report generation during PTS execution.
    Writes results to a CSV file (report.csv) in the specified directory
    as they become available via the `add_step_result` method.
    """
    _CSV_HEADERS = ["recipe_name", "recipe_file_name", "sequence_name", "serial_number", "pypts_version", "step_name", "step_id", "step_type", "result", "inputs", "outputs", "error_info"]

    def __init__(self, output_dir: str | Path, timestamp, overwrite=True):
        """
        Initializes the Report manager for CSV output.

        Args:
            output_dir (str | Path): The directory where report files will be saved.
            overwrite (bool): When true, previous report is overwritten with
                new test results. When false, new test results are appended to
                the report.
        """
        self.output_dir = Path(output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.timestamp = timestamp

        self._csv_file_handle = None
        self._csv_writer: csv.DictWriter | None = None

        self._init_csv(overwrite)
        logger.info(f"CSV Report initialized. Output directory: {self.output_dir}")

    def _init_csv(self, overwrite):
        """Initializes the CSV file and writer."""
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
                except: pass # Ignore errors during cleanup
            self._csv_writer = None

    def add_step_result(self, result: StepResult):
        """
        Adds a StepResult and writes it to the CSV report file.

        Args:
            result (StepResult): The result object to add.
        """
        if not isinstance(result, StepResult):
            logger.warning(f"Attempted to add non-StepResult to report: {type(result)}")
            return

        result_dict = _result_to_dict(result) # Convert once

        if not result_dict: # Skip if conversion failed
            return

        # --- Update incremental formats ---
        # CSV
        if self._csv_writer and self._csv_file_handle:
            flat_item = _flatten_single_result(result_dict)
            # Note: Subresults within the result_dict are not flattened here.
            # They will be added as separate rows when their own StepResult arrives.
            if flat_item:
                try:
                    self._csv_writer.writerow(flat_item)
                    self._csv_file_handle.flush() # Ensure it's written to disk
                except Exception as e:
                    logger.error(f"Failed to write row to CSV: {e}")

    def finish_reports(self):
        """
        Closes the CSV report file handle.
        """
        logger.info("Finishing reports...")

        # Close handles for incremental files
        if self._csv_file_handle:
            try:
                self._csv_file_handle.close()
                logger.debug("Closed CSV file handle")
            except Exception as e:
                logger.error(f"Error closing CSV file handle: {e}")
        else:
            logger.debug("CSV file handle already closed or never opened.")

        self._csv_writer = None # Clear writer reference
        self._csv_file_handle = None # Clear handle reference
        logger.info("Report finishing complete.")

# --- Listener Function ---
from queue import SimpleQueue # Keep queue import here
import time # For demonstration/potential sleep

# Sentinel object to signal the listener to stop
# Using a dedicated object instance avoids confusion with None if None could be valid data
STOP_LISTENER = object()
LISTENER_RUNNING = False

def report_listener(result_queue: SimpleQueue, output_dir: str, overwrite: bool):
    """
    Listens to a queue for StepResult objects and generates reports incrementally.

    Instantiates a Report manager to handle file writing.
    Exits gracefully when the STOP_LISTENER sentinel object is received on the queue.

    Args:
        result_queue (SimpleQueue): Queue to receive StepResult objects or STOP_LISTENER.
        output_dir (str): The directory for report output.
        overwrite (bool): When enabled, overwrites the existing report with the new data.
    """
    timestamp = datetime.now().strftime('%Y-%m-%d_%Hh%M')
    report_manager = Report(output_dir=output_dir, timestamp=timestamp, overwrite=overwrite)
    logger.info(f"Report listener started. Output dir: {output_dir}. Waiting for results...")
    active = True
    while active:
        try:
            item = result_queue.get() # Blocks until an item is available
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
             # Optional: add a small delay to prevent rapid looping on persistent errors
             # time.sleep(0.5)

    # Loop finished, finalize reports
    try:
        report_manager.finish_reports()
        # --- Generate HTML Report after CSV is finalized ---
        
        csv_report_path = report_manager.output_dir / f'report_{timestamp}.csv'
        html_report_path = report_manager.output_dir / f'report_{timestamp}.html'
        if csv_report_path.exists():
            logger.info(f"Generating HTML report from {csv_report_path}...")
            # Generate HDF5 plots before HTML report
            generate_hdf5_plots(report_manager.output_dir, csv_report_path)
            generate_html_report(csv_path=csv_report_path, html_path=html_report_path, output_dir=report_manager.output_dir)
        else:
            logger.warning(f"CSV report not found at {csv_report_path}, cannot generate HTML report.")
        # ----------------------------------------------------
    except Exception as e:
        logger.error(f"Error during final report generation: {e}", exc_info=True)
    finally:
        logger.info("Report listener finished.")


# --- HDF5 Data Processing and Plotting ---

def _verify_hdf5_serial_number(h5_file_path: Path, expected_serial_number: str) -> bool:
    """Verifies that an HDF5 file contains the expected serial number in its attributes."""
    try:
        with h5py.File(h5_file_path, 'r') as f:
            file_serial_number = f.attrs.get("Serial_Number")
            if file_serial_number == expected_serial_number:
                logger.debug(f"HDF5 file {h5_file_path.name} serial number verified: {file_serial_number}")
                return True
            else:
                logger.debug(f"HDF5 file {h5_file_path.name} serial number mismatch. Expected: {expected_serial_number}, Found: {file_serial_number}")
                return False
    except Exception as e:
        logger.warning(f"Could not read HDF5 file {h5_file_path.name} for serial number verification: {e}")
        return False

def generate_hdf5_plots(output_dir: Path, csv_path: Path = None):
    """Generates matplotlib plots for HDF5 files that match the current test run's serial number."""
    # Create img directory
    img_dir = output_dir / "img"
    img_dir.mkdir(exist_ok=True)

    # Get the serial number from the CSV report
    test_serial_number = None
    if csv_path and csv_path.exists():
        try:
            with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                first_row = next(reader, None)
                if first_row:
                    test_serial_number = first_row.get('serial_number')
                    logger.debug(f"Found test serial number from CSV: {test_serial_number}")
        except Exception as e:
            logger.warning(f"Could not read serial number from CSV report: {e}")

    if not test_serial_number or test_serial_number == 'N/A':
        logger.warning("No valid serial number found in CSV report - cannot match HDF5 files.")
        return

    # Find HDF5 files that match the serial number
    h5_files_to_plot = []

    for h5_file in output_dir.glob("*.h5"):
        if test_serial_number in h5_file.name:
            if _verify_hdf5_serial_number(h5_file, test_serial_number):
                h5_files_to_plot.append(h5_file)
                logger.debug(f"Matched HDF5 file: {h5_file.name}")
            else:
                logger.debug(f"HDF5 file {h5_file.name} has serial number in filename but not in attributes")
        else:
            logger.debug(f"HDF5 file {h5_file.name} does not contain serial number {test_serial_number}")

    if not h5_files_to_plot:
        logger.info(f"No HDF5 files found matching serial number {test_serial_number}.")
        return

    logger.info(f"Found {len(h5_files_to_plot)} HDF5 files matching serial number {test_serial_number}.")

    for h5_file in h5_files_to_plot:
        try:
            logger.info(f"Generating plot for {h5_file.name}")
            plot_path = generate_single_hdf5_plot(h5_file, img_dir)
            if plot_path:
                logger.info(f"Plot saved: {plot_path}")
        except Exception as e:
            logger.error(f"Error generating plot for {h5_file.name}: {e}")

def generate_single_hdf5_plot(h5_file_path: Path, img_dir: Path) -> Path:
    """Generates a plot for a single HDF5 file and returns the plot path."""
    try:
        with h5py.File(h5_file_path, 'r') as f:
            time_data = None
            amplitude_data = None
            grp = None

            if "Sinewave_Test" in f:
                grp = f["Sinewave_Test"]
                if "Time" in grp and "Amplitude" in grp:
                    time_data = grp["Time"][:]
                    amplitude_data = grp["Amplitude"][:]

            if time_data is None or amplitude_data is None:
                logger.error(f"Could not find suitable time/amplitude data in {h5_file_path.name}")
                return None

            root_props = dict(f.attrs)
            group_props = dict(grp.attrs)

            # Create the plot
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

            # Time domain plot
            ax1.plot(time_data, amplitude_data, 'b-', linewidth=1)
            ax1.set_xlabel('Time (s)')
            ax1.set_ylabel('Amplitude (V)')
            ax1.set_title(f'Sinewave - Time Domain')
            ax1.grid(True, alpha=0.3)

            # Add statistics text
            stats_text = f'Mean: {np.mean(amplitude_data):.6f} V\n'
            stats_text += f'RMS: {np.sqrt(np.mean(amplitude_data**2)):.6f} V\n'
            stats_text += f'Peak-to-Peak: {np.ptp(amplitude_data):.6f} V'
            ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes,
                    verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

            # Frequency domain plot
            if len(amplitude_data) > 1:
                sample_rate = 1.0 / (time_data[1] - time_data[0])
                fft_result = np.fft.fft(amplitude_data)
                fft_freq = np.fft.fftfreq(len(amplitude_data), 1/sample_rate)

                # Only positive frequencies
                magnitude = np.abs(fft_result[:len(fft_result)//2])
                freq_bins = fft_freq[:len(fft_freq)//2]

                ax2.plot(freq_bins, magnitude, 'r-', linewidth=1)
                ax2.set_xlabel('Frequency (Hz)')
                ax2.set_ylabel('Magnitude')
                ax2.set_title('Frequency Domain (FFT)')
                ax2.grid(True, alpha=0.3)

                # Find and mark peak frequency
                peak_index = np.argmax(magnitude)
                peak_freq = abs(freq_bins[peak_index])
                ax2.axvline(peak_freq, color='red', linestyle='--', alpha=0.7)
                ax2.text(peak_freq * 1.1, magnitude[peak_index] * 0.9,
                        f'Peak: {peak_freq:.1f} Hz',
                        verticalalignment='top', color='red')

            # Add test metadata to the plot
            metadata_text = ""
            if "Expected_Frequency_Hz" in root_props:
                metadata_text += f'Expected: {root_props["Expected_Frequency_Hz"]:.1f} Hz\n'
            if "Detected_Frequency_Hz" in root_props:
                metadata_text += f'Detected: {root_props["Detected_Frequency_Hz"]:.1f} Hz\n'
            if "Test_Passed" in root_props:
                test_result = "PASS" if root_props["Test_Passed"] else "FAIL"
                metadata_text += f'Result: {test_result}'

            if metadata_text:
                fig.text(0.02, 0.02, metadata_text, fontsize=10,
                        bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))

            plt.tight_layout()
            plt.subplots_adjust(bottom=0.15)  # Make room for metadata

            # Save the plot
            plot_filename = f"{h5_file_path.stem}_plot.png"
            plot_path = img_dir / plot_filename
            plt.savefig(plot_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

            return plot_path

    except Exception as e:
        logger.error(f"Error processing HDF5 file {h5_file_path}: {e}")
        return None

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
        # Optionally create a basic HTML file indicating no results
        # For now, just return
        return

    # --- HTML Structure ---
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
    .status-error { background-color: #f8d7da; color: #721c24; } /* Same as fail for now */
    .status-skip { background-color: #fff3cd; color: #856404; }
    .status-unknown { background-color: #e2e3e5; color: #383d41; }
    pre { white-space: pre-wrap; word-wrap: break-word; background-color: #f8f9fa; padding: 5px; border: 1px solid #eee; margin: 0; }
    .details { display: none; }
    .toggle:hover { cursor: pointer; text-decoration: underline; color: blue; }
</style>
<script>
    function toggleDetails(id) {
        var element = document.getElementById(id);
        if (element.style.display === "none") {
            element.style.display = "block";
        } else {
            element.style.display = "none";
        }
    }
</script>
</head>
<body>
"""

    # --- Header ---
    html_content += f"<h1>pypts Test Report</h1>"
    html_content += f"<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"

    # --- Group results by tested device serial number ---
    results_by_serial = {
        serial: list(results)
        for serial, results in groupby(all_results, key=itemgetter('serial_number'))
    }

    for results in results_by_serial.values():
        # --- Run Context ---
        if results: # Ensure we have results before accessing
            first_row = results[0]
            recipe_name = html.escape(first_row.get('recipe_name', 'N/A'))
            recipe_file = html.escape(first_row.get('recipe_file_name', 'N/A'))
            serial_num = html.escape(first_row.get('serial_number', 'N/A'))
            pypts_version = html.escape(first_row.get('pypts_version', 'unknown')) # Get version
            html_content += f"<h2>Run Context</h2>"
            html_content += f"<p><strong>Recipe:</strong> {recipe_name}<br>"
            html_content += f"<strong>File:</strong> {recipe_file}<br>"
            html_content += f"<strong>Serial Number:</strong> {serial_num}<br>"
            html_content += f"<strong>pypts Version:</strong> {pypts_version}</p>" # Display version
        else:
            html_content += "<p><strong>Run Context:</strong> No results data found.</p>"

        # --- Summary (Basic) ---
        # TODO: Add a more detailed summary (Pass/Fail counts)
        total_steps = len(results)
        html_content += f"<h2>Summary</h2>"
        html_content += f"<p>Total steps: {total_steps}</p>"

        # --- Results Table ---
        html_content += "<h2>Details</h2>"
        html_content += "<table>"
        # Revert header, keep Sequence Name
        html_content += "<thead><tr><th>Sequence</th><th>Step Name</th><th>Status</th><th>Inputs</th><th>Outputs</th><th>Error Info</th></tr></thead>"
        html_content += "<tbody>"

        for i, row in enumerate(results):
            status = str(row.get('result', 'Unknown')).split('.')[-1].lower() # Extract status like 'pass'
            css_class = f"status-{status}" if status in ['pass', 'fail', 'error', 'skip'] else "status-unknown"

            html_content += f'<tr class="{css_class}">'
            # Revert cells, keep Sequence Name
            html_content += f"<td>{html.escape(row.get('sequence_name', 'N/A'))}</td>"
            html_content += f"<td>{html.escape(row.get('step_name', 'N/A'))}</td>"
            html_content += f"<td>{html.escape(status.upper())}</td>"

            # Inputs/Outputs/Error Info with toggles for large content
            for col in ['inputs', 'outputs', 'error_info']:
                content = row.get(col, '')
                escaped_content = html.escape(content) # Escape potential HTML in the data
                # Try to format if it looks like JSON
                formatted_content = escaped_content
                if content and content.strip().startswith(('{', '[')):
                    try:
                        # Basic JSON pretty print attempt within <pre>
                        import json
                        parsed = json.loads(content)
                        formatted_content = f'<pre>{html.escape(json.dumps(parsed, indent=2))}</pre>'
                    except json.JSONDecodeError:
                        formatted_content = f'<pre>{escaped_content}</pre>' # Fallback to preformatted escaped
                elif content: # Handle non-empty, non-JSON content
                    formatted_content = f'<pre>{escaped_content}</pre>'
                else:
                    formatted_content = "" # Empty content if nothing

                if col == 'outputs' and formatted_content:
                    summary = f"Show output ({len(content)} chars)"
                    cell_html = (
                        "<details>"
                        f"<summary>{summary}</summary>"
                        f"{formatted_content}"
                        "</details>"
                    )
                else:
                    cell_html = formatted_content

                html_content += f"<td>{cell_html}</td>"

            html_content += "</tr>"

        html_content += "</tbody></table>"

    # --- Add HDF5 Plots Section ---
    if output_dir:
        img_dir = output_dir / "img"
        if img_dir.exists():
            plot_files = list(img_dir.glob("*_plot.png"))
            if plot_files:
                html_content += "<h2>Test Data Plots</h2>"
                for plot_file in plot_files:
                    relative_path = f"img/{plot_file.name}"
                    # Extract test info from filename
                    test_name = plot_file.stem.replace("_plot", "")
                    html_content += f"<h3>{html.escape(test_name)}</h3>"
                    html_content += f'<img src="{relative_path}" alt="{html.escape(test_name)} plot" style="max-width: 100%; height: auto; border: 1px solid #ddd; margin: 10px 0;">'
                    html_content += "<br><br>"

    html_content += "</body></html>"

    # --- Write HTML File ---
    try:
        with open(html_path, 'w', encoding='utf-8') as htmlfile:
            htmlfile.write(html_content)
        logger.info(f"HTML report generated successfully: {html_path}")
    except Exception as e:
        logger.error(f"Error writing HTML file {html_path}: {e}")


if __name__ == "__main__":
    import uuid
    from datetime import datetime
    from pypts.recipe import Step, StepResult, ResultType # Ensure these are importable

    pre_timestamp = datetime.now().strftime('%Y-%m-%d_%Hh%M')

    # --- Argument Parsing ---
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

    # --- Configuration ---
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    print(f"Example report will be generated in: {output_directory.resolve()}")

    # --- Simulate Recipe Execution ---
    report_manager = Report(output_dir=output_directory, timestamp=timestamp) # Use the parsed output directory

    # Simulate some steps (minimal Step objects for reporting)
    step1 = Step(step_name="Run Other Test", id=uuid.uuid4(), description="First step")
    step2 = Step(step_name="Run Simple Output Test", id=uuid.uuid4(), description="Second step")
    step3 = Step(step_name="Run Range Test (Fail)", id=uuid.uuid4(), description="Third step, expected fail")
    step4 = Step(step_name="Generate Error", id=uuid.uuid4(), description="Fourth step, error")


    # Simulate results
    result1 = StepResult(step=step1)
    # Add dummy metadata for example
    result1.recipe_name = "SampleRecipe"
    result1.recipe_file_name = "sample_recipe.yaml"
    result1.serial_number = "DUMMY_SN_12345"
    result1.sequence_name = "Main"
    result1.pypts_version = "0.1.0-dummy" # Dummy version
    result1.set_result(
        result_type=ResultType.PASS,
        inputs={"arg1": 10},
        outputs={"some_return": True, "value": "abc"}
    )
    report_manager.add_step_result(result1)

    result2 = StepResult(step=step2, parent=result1.uuid) # Example of parent linking
    result2.recipe_name = "SampleRecipe"
    result2.recipe_file_name = "sample_recipe.yaml"
    result2.serial_number = "DUMMY_SN_12345"
    result2.sequence_name = "Main"
    result2.pypts_version = "0.1.0-dummy" # Dummy version
    result2.set_result(
        result_type=ResultType.PASS,
        inputs={"value": "abc"},
        outputs={"my_output": "calculated_abc"}
    )
    report_manager.add_step_result(result2)


    result3 = StepResult(step=step3, parent=result1.uuid) # Example of parent linking
    result3.recipe_name = "SampleRecipe"
    result3.recipe_file_name = "sample_recipe.yaml"
    result3.serial_number = "DUMMY_SN_12345"
    result3.sequence_name = "Main"
    result3.pypts_version = "0.1.0-dummy" # Dummy version
    result3.set_result(
        result_type=ResultType.FAIL,
        inputs={"value": 25, "min": 10, "max": 20},
        outputs={"compare": False}
    )
    report_manager.add_step_result(result3)

    # Simulate an error result
    try:
        raise ValueError("Something went wrong deliberately")
    except Exception as e:
        result4 = StepResult(step=step4, parent=result1.uuid) # Example of parent linking
        result4.recipe_name = "SampleRecipe"
        result4.recipe_file_name = "sample_recipe.yaml"
        result4.serial_number = "DUMMY_SN_12345"
        result4.sequence_name = "Main"
        result4.pypts_version = "0.1.0-dummy" # Dummy version
        result4.set_error(
            error_info=f"{type(e).__name__}: {e}",
            inputs={}
        )
        report_manager.add_step_result(result4)


    # --- Finalize ---
    report_manager.finish_reports()

    report_name = f"report_{timestamp}"
    csv_report_path = report_manager.output_dir / f"{report_name}.csv"
    html_report_path = report_manager.output_dir / f"{report_name}.html"
    print(f"Sample report generated: {csv_report_path}")
    print("Review the contents of the CSV file.")

    # --- Generate HTML Report ---
    if csv_report_path.exists():
        # Generate HDF5 plots before HTML report
        generate_hdf5_plots(report_manager.output_dir, csv_report_path)
        generate_html_report(csv_path=csv_report_path, html_path=html_report_path, output_dir=report_manager.output_dir)
        print(f"HTML report generated: {html_report_path}")
    else:
        print(f"CSV report not found at {csv_report_path}, skipping HTML generation.")


