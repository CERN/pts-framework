import json
import csv
from typing import List, Dict, Any
from pathlib import Path
import logging
from pypts.recipe import StepResult, ResultType, Step

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
    """Converts a StepResult object into a dictionary (without subresults for flattening)."""
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
        "uuid": str(result.uuid),
        "parent_uuid": str(result.parent) if result.parent else None,
        "step": _serialize_step(result.step),
        "result": str(result.result) if result.result else None,
        "inputs": inputs_serializable,
        "outputs": outputs_serializable,
        "error_info": result.error_info,
        # "subresults": ... Removed for flattening
    }

def _flatten_single_result(result_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Flattens a single result dictionary for CSV writing."""
    if not result_dict: return None
    return {
        "uuid": result_dict.get("uuid"),
        "parent_uuid": result_dict.get("parent_uuid"),
        "step_name": result_dict.get("step", {}).get("name", "N/A") if result_dict.get("step") else "N/A",
        "step_id": result_dict.get("step", {}).get("id", "N/A") if result_dict.get("step") else "N/A",
        "step_type": result_dict.get("step", {}).get("type", "N/A") if result_dict.get("step") else "N/A",
        "result": result_dict.get("result"),
        "inputs": json.dumps(result_dict.get("inputs", {})), # Serialize complex structures
        "outputs": json.dumps(result_dict.get("outputs", {})), # Serialize complex structures
        "error_info": result_dict.get("error_info"),
        # Note: subresults are not directly represented in the flat CSV row for the parent
    }


class Report:
    """
    Manages incremental CSV report generation during PTS execution.
    Writes results to a CSV file as they become available.
    """
    _CSV_HEADERS = ["uuid", "parent_uuid", "step_name", "step_id", "step_type", "result", "inputs", "outputs", "error_info"]

    def __init__(self, output_dir: str | Path):
        """
        Initializes the Report manager for CSV output.

        Args:
            output_dir (str | Path): The directory where report files will be saved.
        """
        self.output_dir = Path(output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._csv_file_handle = None
        self._csv_writer: csv.DictWriter | None = None

        self._init_csv()
        logger.info(f"CSV Report initialized. Output directory: {self.output_dir}")

    def _init_csv(self):
        """Initializes the CSV file and writer."""
        path = self.output_dir / "report.csv"
        try:
            # Use 'w' to start fresh each time
            self._csv_file_handle = open(path, 'w', newline='', encoding='utf-8')
            self._csv_writer = csv.DictWriter(self._csv_file_handle, fieldnames=self._CSV_HEADERS)
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

def report_listener(result_queue: SimpleQueue, output_dir: str):
    """
    Listens to a queue for StepResult objects and generates reports incrementally.

    Args:
        result_queue (SimpleQueue): Queue to receive StepResult objects or STOP_LISTENER.
        output_dir (str): The directory for report output.
    """
    report_manager = Report(output_dir=output_dir)
    logger.info(f"Report listener started. Output dir: {output_dir}. Waiting for results...")
    active = True
    while active:
        try:
            item = result_queue.get() # Blocks until an item is available

            if item is STOP_LISTENER:
                logger.info("Report listener received stop signal.")
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
    except Exception as e:
        logger.error(f"Error during final report generation: {e}", exc_info=True)
    finally:
        logger.info("Report listener finished.")
