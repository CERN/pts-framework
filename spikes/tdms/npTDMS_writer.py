from nptdms import TdmsWriter, RootObject, GroupObject, ChannelObject
import numpy as np

root_object = RootObject(properties={
    "prop1": "foo",
    "prop2": 3,
})
group_object = GroupObject("group_1", properties={
    "prop1": 1.2345,
    "prop2": False,
})
data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
channel_object = ChannelObject("group_1", "channel_1", data, properties={})

with TdmsWriter("my_file.tdms") as tdms_writer:
    # Write first segment
    tdms_writer.write_segment([
        root_object,
        group_object,
        channel_object])
    # Write another segment with more data for the same channel
    more_data = np.array([6.0, 7.0, 8.0, 9.0, 10.0])
    channel_object = ChannelObject("group_1", "channel_1", more_data, properties={})
    tdms_writer.write_segment([channel_object])