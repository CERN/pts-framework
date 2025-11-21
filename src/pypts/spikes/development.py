from pypts.utilities.config_handler import create_config_from_template, read_config_key

def main():
    # Create or update the config from template with OS info
    # config_path = create_config_from_template()
    # print(f"Config file created/updated at: {config_path}")

    # Read some keys to verify
    os_name = read_config_key("OperatingSystem", "name")
    os_version = read_config_key("OperatingSystem", "version")
    logs_dir = read_config_key("Paths", "logs_dir")
    log_level = read_config_key("Application", "log_level")

    print("Operating System Name:", os_name)
    print("Operating System Version:", os_version)
    print("Logs Directory:", logs_dir)
    print("Log Level:", log_level)

if __name__ == "__main__":
    main()
