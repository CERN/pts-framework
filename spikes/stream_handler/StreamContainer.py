class GlobalContainer:
    """Per-process singleton container for streams.

    NOTE: this singleton is scoped to the current Python process. Under
    multiprocessing (spawn on Windows, and spawn on Linux from 3.14+), each
    subprocess re-imports this module and gets its own independent container.
    If cross-process stream sharing is required, use multiprocessing.Manager
    or an explicit IPC queue instead.
    """
    _instance = None
    def __new__(cls, *args, **kwargs):

        print("Something is creating the container object")
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.streamlist = []
        return cls._instance

    def remove_stream(self, Stream):
        self.streamlist.remove(Stream)

    def add_stream(self, Stream):
        self.streamlist.append(Stream)

    def get_stream(self, key):
        return self.streamlist[key]

    def get_all_streams(self):
        return list(self.streamlist)

    def get_streams_info(self):
        streams_info = ""
        print(f"container object inside the streams_info: {container}")
        for stream in self.streamlist:
            streams_info = streams_info + (f"Retrieved registered stream {stream.name}. Stream is tied with {stream.hook} hook.\n")
        return streams_info

global container
container = GlobalContainer()

class Stream:
    def __init__(self, name, hook, description=None, unit=None, frequency=None):
        self.name = name
        self.hook = hook
        self.description = description
        self.unit = unit
        self.frequency = frequency
        container.add_stream(self)

    def kill(self):
        container.remove_stream(self)
        del(self)
#
# if __name__ == "__main__":
#     stream1 = Stream(name = "PT100 probe", hook = "file1.csv")
#     stream2 = Stream(name = "oscilloscope", hook = "file2.csv")
#
#     # container = GlobalContainer()
#     # print("Adding 1st stream")
#     # container.add_stream(stream1)
#     # print(container.get_streams_info())
#     # print("Adding 2nd stream")
#     # container.add_stream(stream2)
#     # print(container.get_streams_info())
#
#     import time
#     while True:
#         time.sleep(1)
#         streamlist = container.get_all_streams()
#         for stream in streamlist:
#             print(f"Retrieved registered stream {stream.name}. Stream is tied with {stream.hook} hook.")