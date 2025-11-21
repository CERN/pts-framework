import os
import tempfile
import shutil
import configparser
import platform

def ensure_folder_exists(folder_path: str):
    os.makedirs(folder_path, exist_ok=True)

def create_config_from_template(app_name="pypts", subfolder="config", template_file="config_template.ini", target_file="config.ini"):
    """
    Creates or updates config.ini file in the user's temp directory from a template file.
    Updates OS info on first creation or if file exists.
    """
    base_temp = tempfile.gettempdir()
    config_dir = os.path.join(base_temp, app_name, subfolder)
    ensure_folder_exists(config_dir)

    this_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(this_dir, template_file)
    target_path = os.path.join(config_dir, target_file)

    # Copy template if target config file doesn't exist
    if not os.path.exists(target_path):
        shutil.copy2(template_path, target_path)

    # Load config file
    config = configparser.ConfigParser()
    config.read(target_path)

    # Update OS information section dynamically
    config["OperatingSystem"] = {
        "name": platform.system(),
        "version": platform.version(),
        "architecture": platform.machine(),
        "kernel": platform.release(),
    }

    # Write back the updated config
    with open(target_path, "w", encoding="utf-8") as configfile:
        config.write(configfile)

    return target_path



def read_config_key(section, key, app_name="pypts", subfolder="config", template_file="config_template.ini"):
    """
    Reads a key from config; creates config folders and file from template if missing.
    Returns the string value of the key or None if not found.
    """
    config_path = create_config_from_template(app_name, subfolder, template_file)

    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')

    if config.has_section(section) and config.has_option(section, key):
        return config.get(section, key)
    else:
        return None

def get_template_config_contents(template_file="config_template.ini"):
    """
    Returns the contents of the template config file as a string.
    """
    this_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(this_dir, template_file)

    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()
