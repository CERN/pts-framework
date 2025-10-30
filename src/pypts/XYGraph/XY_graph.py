import sys, os
import random, time
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import QDateTime
from pyqtgraph import PlotWidget, plot
import pyqtgraph as pg
from datetime import datetime
import csv
from pypts.XYGraph.StreamContainer import *
from pypts.XYGraph.simulated_signals import *

global container

class SignalSpawner(QtWidgets.QMainWindow):
    def __init__(self, *args, **kwargs):
        super(SignalSpawner, self).__init__(*args, **kwargs)
        self.signal_dictionary = {}

        # Main widget and layout
        self.setWindowTitle("Signal Management")
        self.setGeometry(1000, 100, 400, 300)
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QHBoxLayout(central_widget)  # Split: left (controls), right (list)

        # LEFT side: controls
        control_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(control_layout)

        self.signal_name = QtWidgets.QLineEdit()
        self.signal_name.setText("Signal1")
        control_layout.addWidget(self.signal_name)

        self.startButton = QtWidgets.QPushButton("Start signal generation")
        self.startButton.clicked.connect(self.start_simulated_acquisition)
        control_layout.addWidget(self.startButton)

        self.stopButton = QtWidgets.QPushButton("Stop signal generation")
        self.stopButton.clicked.connect(self.stop_simulated_acquisition)
        control_layout.addWidget(self.stopButton)

        # Add "Open File" button
        self.openFileButton = QtWidgets.QPushButton("Open file")
        self.openFileButton.clicked.connect(self.open_file_dialog)
        control_layout.addWidget(self.openFileButton)

        control_layout.addStretch()

        # RIGHT side: list of active signals
        self.signal_list = QtWidgets.QListWidget()
        main_layout.addWidget(self.signal_list)

        # Double-click on a signal in the list to stop it
        self.signal_list.itemDoubleClicked.connect(self.select_signal_from_the_list)

    def open_file_dialog(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select a file",
            "",  # start directory
            "All Files (*)"  # filter
        )

        if file_path:
            file_name_no_ext = os.path.splitext(os.path.basename(file_path))[0]
            self.signal_name.setText(file_name_no_ext)
            self.load_stream_from_file(file_name=file_name_no_ext, file_path=file_path)

    def load_stream_from_file(self, file_name, file_path):
        new_signal = Stream(file_name, file_path)
        self.signal_dictionary[file_name] = new_signal

        # Add to list widget
        self.signal_list.addItem(file_name)

    def select_signal_from_the_list(self, item):
        self.signal_name.setText(item.text())

    def start_simulated_acquisition(self):
        name = self.signal_name.text()
        if name in self.signal_dictionary:
            QtWidgets.QMessageBox.warning(self, "Warning", f"Signal '{name}' already exists!")
            return

        new_signal = Simulated_sine_wave(randomize=True, name=name)
        self.signal_dictionary[name] = new_signal
        new_signal.start_acquisition()

        # Add to list widget
        self.signal_list.addItem(name)


    def stop_simulated_acquisition(self):
        name = self.signal_name.text()
        if name in self.signal_dictionary:
            self.signal_dictionary[name].stop_acquisition()
            del self.signal_dictionary[name]

            # Remove from list widget
            items = self.signal_list.findItems(name, QtCore.Qt.MatchFlag.MatchExactly)
            for item in items:
                self.signal_list.takeItem(self.signal_list.row(item))

class plottable_data():
    def __init__(self):
        self.timestamps = None
        self.datapoints = None

class PlotWindow(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super(PlotWindow, self).__init__(*args, **kwargs)
        self.selected_stream = None
        self.stream_list = []
        self.plottable_signal = plottable_data()
        # Main widget and layout
        central_widget = QtWidgets.QWidget()
        # self.setCentralWidget(central_widget)
        self.main_layout = QtWidgets.QHBoxLayout(self)
        # Create three vertical layouts the main
        self.vertical_layout_1 = QtWidgets.QVBoxLayout()
        self.vertical_layout_2 = QtWidgets.QVBoxLayout()
        self.vertical_layout_3 = QtWidgets.QVBoxLayout()
        # Add the vertical layouts to the main horizontal layout
        self.main_layout.addLayout(self.vertical_layout_1)
        self.main_layout.addLayout(self.vertical_layout_2)
        self.main_layout.addLayout(self.vertical_layout_3)


        # Default maximum data points shown
        self.max_points = 10000

        self.setup_plot_area()

        self.first_plot = self.graphWidget.plot([], [], pen=pg.mkPen('r', width=2))
        self.setup_stream_selector()
        # Data points knob and label
        self.points_label = QtWidgets.QLabel(f"Data Points: {self.max_points}")
        self.setup_timestamp_knob()
        self.setup_autoscale_checkbox()
        self.setup_show_all_data_checkbox()
        self.setup_config_button()
        self.setup_timer()
        self.setup_datetime_label()

        self.vertical_layout_1.addWidget(self.graphWidget)
        self.vertical_layout_2.addWidget(self.plot_selector)
        self.vertical_layout_2.addWidget(self.points_label)
        self.vertical_layout_2.addWidget(self.dial)
        self.vertical_layout_2.addWidget(self.autoscale_Y_checkbox)
        self.vertical_layout_2.addWidget(self.autoscale_X_checkbox)
        self.vertical_layout_2.addWidget(self.show_all_checkbox)
        self.vertical_layout_2.addWidget(self.config_button)
        self.vertical_layout_2.addStretch()
        self.vertical_layout_2.addWidget(self.datetime_label)

# GUI related setup methods
    def setup_plot_area(self):
        # Create the plot widget and add it to the vertical1 layout
        self.graphWidget = pg.PlotWidget()
        self.graphWidget.showGrid(x=True, y=True, alpha=20)
        self.graphWidget.setBackground('w')

    def setup_stream_selector(self):
        # Drop-down menu to select one plot
        self.plot_selector = QtWidgets.QComboBox()
        self.plot_selector.setEditable(True)
        self.plot_selector.setFixedWidth(200)
        self.plot_selector.setCurrentIndex(-1)
        # self.plot_selector.currentIndexChanged.connect(self.select_plot)
        self.plot_selector.activated.connect(self.select_plot)

    def setup_autoscale_checkbox(self):
        # Autoscale checkbox Y
        self.autoscale_Y_checkbox = QtWidgets.QCheckBox("Autoscale Y-Axis")
        self.autoscale_Y_checkbox.setChecked(True)
        self.autoscale_Y_checkbox.stateChanged.connect(self.toggle_autoscale_Y)
        # Autoscale checkbox X
        self.autoscale_X_checkbox = QtWidgets.QCheckBox("Autoscale X-Axis")
        self.autoscale_X_checkbox.setChecked(True)
        self.autoscale_X_checkbox.stateChanged.connect(self.toggle_autoscale_X)

    def setup_show_all_data_checkbox(self):
        # Show all data checkbox
        self.show_all_checkbox = QtWidgets.QCheckBox("Show All Data")
        self.show_all_checkbox.setChecked(False)
        self.show_all_checkbox.stateChanged.connect(self.toggle_show_all)

    def setup_config_button(self):
        # Configuration button
        self.config_button = QtWidgets.QPushButton("Configuration")
        self.config_button.setDisabled(True)

    def setup_datetime_label(self):
        # datetime refresh label
        self.datetime_label = QtWidgets.QLabel()
        self.datetime_label.setStyleSheet("font-size: 8px; font-weight: bold;")

    def setup_timestamp_knob(self):
        #TODO - store those values in config
        self.dial = QtWidgets.QDial()
        self.dial.setRange(10, self.max_points)
        self.dial.setValue(self.max_points)
        self.dial.setSingleStep(5)
        self.dial.valueChanged.connect(self.update_points_label)

    def setup_timer(self):
        # Timer updating every 100ms
        self.timer100 = QtCore.QTimer()
        self.timer100.setInterval(100)
        self.timer100.timeout.connect(self.update_plot_data)
        self.timer100.start()

        # Timer updating every 1000ms
        self.timer1000 = QtCore.QTimer()
        self.timer1000.setInterval(1000)
        self.timer1000.timeout.connect(self.update_datetime)
        self.timer1000.timeout.connect(self.find_registered_streams)
        self.timer1000.start()

        # Freeze button
        self.freeze_button = QtWidgets.QPushButton("Freeze")
        self.freeze_button.setCheckable(True)  # Make it toggleable
        self.freeze_button.clicked.connect(self.toggle_freeze)
        self.vertical_layout_2.addWidget(self.freeze_button)
        self.is_frozen = False

# GUI action methods
    def toggle_freeze(self):
        self.is_frozen = self.freeze_button.isChecked()
        if self.is_frozen:
            self.freeze_button.setText("Resume")
        else:
            self.freeze_button.setText("Freeze")

    def toggle_autoscale_Y(self):
        # Enable or disable Y-axis autoscaling
        if self.autoscale_Y_checkbox.isChecked():
            self.graphWidget.enableAutoRange(axis=pg.ViewBox.YAxis)
        else:
            self.graphWidget.disableAutoRange(axis=pg.ViewBox.YAxis)

    def toggle_autoscale_X(self):
        # Enable or disable X-axis autoscaling
        if self.autoscale_X_checkbox.isChecked():
            self.graphWidget.enableAutoRange(axis=pg.ViewBox.XAxis)
        else:
            self.graphWidget.disableAutoRange(axis=pg.ViewBox.XAxis)

    def toggle_show_all(self):
        # Refresh plot to show all data or apply max_points
        self.update_plot_data()

    def update_plot_data(self):
        if self.selected_stream == None:
            return # do nothing if no plot is selected

        if self.is_frozen:
            return  # Do nothing if frozen

        timestamps, datapoints = self.load_csv_data(self.selected_stream)
        self.plottable_signal.timestamps = self.timestamps_to_seconds(timestamps)
        self.plottable_signal.datapoints = datapoints

        if self.show_all_checkbox.isChecked():
            self.first_plot.setData(self.plottable_signal.timestamps, self.plottable_signal.datapoints)
        else:
            self.first_plot.setData(self.plottable_signal.timestamps[-self.max_points:],
                                    self.plottable_signal.datapoints[-self.max_points:])

    def select_plot(self):
        if (self.plot_selector.currentText() == ""):
            pass
        else:
            self.selected_stream = self.find_stream_by_name(self.plot_selector.currentText())

    def update_points_label(self, value):
        # Update data points label and limit the data displayed
        self.max_points = value
        self.points_label.setText(f"Data Points: {value}")
        self.update_plot_data()

    def update_plot_selector_combobox(self):
        current_text = self.plot_selector.currentText()
        self.plot_selector.clear()
        for stream in self.stream_list:
            self.plot_selector.addItem(stream.name)

        index = self.plot_selector.findText(current_text)
        if index != -1:
            self.plot_selector.setCurrentIndex(index)

# Stream handling related methods
    def load_csv_data(self, stream):
        file_path = stream.hook
        timestamps = []
        signals = []
        with open(file_path, 'r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                timestamps.append(datetime.strptime(row['Timestamp'], "%Y-%m-%d %H:%M:%S.%f"))
                signals.append(float(row['Signal']))
        return timestamps, signals
    
    def update_datetime(self):
        current_datetime = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.datetime_label.setText(f"{current_datetime}")

    def timestamps_to_seconds(self, timestamps):
        start_time = timestamps[0]
        return [(ts - start_time).total_seconds() for ts in timestamps]

    def find_stream_by_name(self, stream_name):
        for stream in self.stream_list:
            if stream.name == stream_name:
                return stream
        return None

    def find_registered_streams(self):
        self.stream_list = container.get_all_streams()
        if (self.did_registered_streams_changed):
            self.update_plot_selector_combobox()

        if (self.stream_list):
            if (self.selected_stream == None):
                self.select_plot()
        else:
            self.plot_selector.setCurrentText("")
            self.selected_stream = None

    def did_registered_streams_changed(self):
        current_steamlist = self.stream_list
        new_streamlist = container.get_all_streams()

        if len(current_steamlist) != len(new_streamlist):
            return True
        for x in range (0, len(current_steamlist)):
            if current_steamlist[x].name != new_streamlist[x].name:
                return True
            if current_steamlist[x].hook != new_streamlist[x].hook:
                return True
        return False


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    XYGraph = PlotWindow()
    tools = SignalSpawner()

    XYGraph.show()
    tools.show()

    sys.exit(app.exec())

# todo 1.1 - the plots shall be somehow contained within class. so I we could access their parameters like the data/colours/scales etc
# todo 1.1 - Add possibility to change the max X scale
# todo 1.1 - change the colour of a signal
# todo 1.1 - Add possibility to dynamically register multiple plots and show them on one graph
