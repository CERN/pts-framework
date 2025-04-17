import logging
import sys

# Import the package itself to access launch_gui
import pypts

# Keep logger configuration if desired for standalone execution
logger = logging.getLogger(__name__)
log_format = '%(levelname)s : %(name)s : %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_format)
logging.getLogger("paramiko.transport").setLevel("WARN")


if __name__ == '__main__':
    """Main entry point for the PTS application when run as a script.
    
    Simply calls the launch_gui function from the pypts package.
    Command-line arguments for recipe loading could be added here later using argparse.
    """
    # Directly call the launch function from the package
    # No recipe path is provided, so it starts in the default mode (user selects file)
    exit_code = pypts.launch_gui()
    sys.exit(exit_code)
