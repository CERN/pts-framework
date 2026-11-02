"""
Registers a TDMS format in pyqtgraph's native right-click > Export...
dialog, alongside its built-in CSV/HDF5/Image/Matplotlib/SVG exporters.
Importing this module registers it, as a side effect.

Like pyqtgraph's own CSVExporter/HDF5Exporter, this only sees curves
registered on the selected PlotItem (self.item.curves) - left-axis
signals only (see ScopePlotWidget._add_item_to_axis). Secondary-axis
curves are invisible to every native exporter, not just this one.
"""

import numpy as np
from pyqtgraph import PlotItem
from pyqtgraph.exporters import Exporter
from pyqtgraph.parametertree import Parameter
from pyqtgraph.Qt import QtCore

translate = QtCore.QCoreApplication.translate


class TDMSExporter(Exporter):
    Name = "TDMS Export: plot (x,y)"
    allowCopy = False

    def __init__(self, item):
        super().__init__(item)
        self.params = Parameter.create(name='params', type='group', children=[
            {'name': 'Name', 'title': translate("Exporter", 'Name'), 'type': 'str', 'value': 'Export'},
        ])

    def parameters(self):
        return self.params

    def export(self, fileName=None):
        if not isinstance(self.item, PlotItem):
            raise Exception("Must have a PlotItem selected for TDMS export.")

        if fileName is None:
            self.fileSaveDialog(filter=["*.tdms"])
            return

        from nptdms import ChannelObject, TdmsWriter

        group_name = self.params['Name'] or 'Export'
        channels = []
        for i, curve in enumerate(self.item.curves):
            x, y = curve.getData()
            if x is None or y is None:
                continue
            name = curve.name() if curve.name() is not None else str(i)
            channels.append(ChannelObject(group_name, f"{name}_x", np.asarray(x, dtype=np.float64)))
            channels.append(ChannelObject(group_name, name, np.asarray(y, dtype=np.float64)))

        with TdmsWriter(fileName, mode='w') as writer:
            writer.write_segment(channels)


TDMSExporter.register()
