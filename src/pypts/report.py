import json
import csv
from typing import List, Dict, Any
from pathlib import Path
import logging
from pypts.recipe import StepResult, ResultType, Step 

logger = logging.getLogger(__name__)

class ReportGenerator:
    """
    Generates reports from PTS execution results.
    """
    def __init__(self, results: List[StepResult]):
        """
        Initializes the ReportGenerator with the execution results.

        Args:
            results (List[StepResult]): The list of top-level StepResult objects.
        """
        if not isinstance(results, list):
            raise TypeError("results must be a list of StepResult objects")
        self.results = results

    def _serialize_step(self, step: Step) -> Dict[str, Any]:
        """Helper to serialize a Step object minimally for the report."""
        if step:
            # Customize this based on what step information is needed in the report
            return {
                "name": step.name,
                "id": str(step.id), 
                "description": step.description,
                "type": step.__class__.__name__ 
            }
        return None

    def _result_to_dict(self, result: StepResult) -> Dict[str, Any]:
        """Recursively converts a StepResult object and its subresults into a dictionary."""
        if not isinstance(result, StepResult):
            logger.warning(f"Expected StepResult, got {type(result)}. Skipping.")
            return None

        # Basic serialization - can be expanded
        # Handle potential serialization issues for complex objects in inputs/outputs
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
            "step": self._serialize_step(result.step),
            "result": str(result.result) if result.result else None,
            "inputs": inputs_serializable,
            "outputs": outputs_serializable,
            "error_info": result.error_info,
            "subresults": [self._result_to_dict(sub) for sub in result.subresults if sub is not None]
        }

    def to_dict(self) -> List[Dict[str, Any]]:
        """Converts all results to a list of dictionaries."""
        return [self._result_to_dict(res) for res in self.results if res is not None]

    def to_json(self, filepath: str | Path):
        """
        Exports the results to a JSON file.

        Args:
            filepath (str | Path): The path to the output JSON file.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Exporting results to JSON: {path}")
        report_data = self.to_dict()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=4, ensure_ascii=False)
            logger.info(f"Successfully exported JSON report to {path}")
        except Exception as e:
            logger.error(f"Failed to export JSON report to {path}: {e}")
            raise

    def _flatten_results(self, results_list: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Flattens the hierarchical result structure for CSV export."""
        flat_list = []
        if results_list is None:
            results_list = self.to_dict() # Start with the dictionary representation

        for result_dict in results_list:
            if not result_dict: continue
            
            # Create a flat version of the current result, prefixing step info
            flat_item = {
                "uuid": result_dict.get("uuid"),
                "parent_uuid": result_dict.get("parent_uuid"),
                "step_name": result_dict.get("step", {}).get("name", "N/A") if result_dict.get("step") else "N/A",
                "step_id": result_dict.get("step", {}).get("id", "N/A") if result_dict.get("step") else "N/A",
                "step_type": result_dict.get("step", {}).get("type", "N/A") if result_dict.get("step") else "N/A",
                "result": result_dict.get("result"),
                # Serialize complex structures like inputs/outputs to JSON strings for CSV
                "inputs": json.dumps(result_dict.get("inputs", {})),
                "outputs": json.dumps(result_dict.get("outputs", {})),
                "error_info": result_dict.get("error_info"),
            }
            flat_list.append(flat_item)

            # Recursively flatten subresults
            if result_dict.get("subresults"):
                flat_list.extend(self._flatten_results(result_dict["subresults"]))
                
        return flat_list

    def to_csv(self, filepath: str | Path):
        """
        Exports the results to a CSV file. Note: Hierarchical structure is flattened.

        Args:
            filepath (str | Path): The path to the output CSV file.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Exporting results to CSV: {path}")
        
        flat_results = self._flatten_results()
        
        if not flat_results:
            logger.warning(f"No results to export to CSV for {path}.")
            # Create an empty file or a file with headers? Let's create with headers.
            headers = ["uuid", "parent_uuid", "step_name", "step_id", "step_type", "result", "inputs", "outputs", "error_info"]
        else:
            headers = flat_results[0].keys() # Get headers from the first item

        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(flat_results)
            logger.info(f"Successfully exported CSV report to {path}")
        except Exception as e:
            logger.error(f"Failed to export CSV report to {path}: {e}")
            raise

    def to_html(self, filepath: str | Path):
        """
        Exports the results to an HTML file. (Placeholder)

        Args:
            filepath (str | Path): The path to the output HTML file.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.warning(f"HTML report generation is not yet implemented. File created: {path}")
        # Basic placeholder implementation
        report_data_dict = self.to_dict()
        html_content = f"""<!DOCTYPE html>
<html>
<head>
<title>PTS Report</title>
<style>
  body {{ font-family: sans-serif; }}
  pre {{ background-color: #f4f4f4; padding: 10px; border: 1px solid #ddd; }}
</style>
</head>
<body>
<h1>PTS Execution Report</h1>
<pre>{json.dumps(report_data_dict, indent=2)}</pre>
</body>
</html>
"""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            # Consider using a templating engine like Jinja2 for a real implementation
            logger.info(f"Successfully exported basic HTML report to {path}")
        except Exception as e:
            logger.error(f"Failed to export HTML report to {path}: {e}")
            raise


# Example usage (optional, can be removed or placed under if __name__ == "__main__":)
def generate_report(results: List[StepResult], report_format: str, filepath: str):
    """
    Generates a report file from PTS results.

    Args:
        results (List[StepResult]): The list of top-level StepResult objects.
        report_format (str): The desired format ('json', 'csv', 'html').
        filepath (str): The path for the output report file.
    """
    generator = ReportGenerator(results)
    
    match report_format.lower():
        case "json":
            generator.to_json(filepath)
        case "csv":
            generator.to_csv(filepath)
        case "html":
            generator.to_html(filepath)
        case _:
            logger.error(f"Unsupported report format: {report_format}. Supported formats: json, csv, html.")
            raise ValueError(f"Unsupported report format: {report_format}")

# You might want to add a listener function here that consumes from the report_queue
# provided by PtsApi and generates reports, possibly based on specific events.
# e.g., def report_listener(report_queue: SimpleQueue, output_dir: str): ... 
