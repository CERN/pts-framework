import os
import tempfile
from datetime import datetime

def ensure_folder_exists(folder_path: str):
    """Create the folder if it does not exist."""
    os.makedirs(folder_path, exist_ok=True)

def create_folder_structure(app_name="pypts", subfolders=None):
    """
    Create specified subfolders under the app temp folder.
    Default subfolders: ['logs', 'config']
    """
    if subfolders is None:
        subfolders = ["logs", "config"]
    base_temp = tempfile.gettempdir()
    app_temp_dir = os.path.join(base_temp, app_name)
    ensure_folder_exists(app_temp_dir)  # Ensure master folder exists

    for subfolder in subfolders:
        path = os.path.join(app_temp_dir, subfolder)
        ensure_folder_exists(path)  # Ensure each subfolder exists

def get_log_file_path(app_name="pypts", subfolder="logs") -> str:
    """
    Ensure folder structure exists and return a full path for a timestamped log file.
    Creates folders if they don't exist.
    """
    # Ensure main folder structure (master + subfolders)
    create_folder_structure(app_name)

    base_temp = tempfile.gettempdir()
    log_dir = os.path.join(base_temp, app_name, subfolder)
    ensure_folder_exists(log_dir)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_name = f"{app_name}_{timestamp_str}.log"
    return os.path.join(log_dir, log_file_name)
