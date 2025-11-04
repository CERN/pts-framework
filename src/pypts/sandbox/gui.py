from hmi import *
import time

def gui_main(hmi: HMIInterface):
    while True:
        time.sleep(1)
        hmi.send_command_to_core("Hello core, from GUI")



if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG)  # Optional: Configure logging level

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())