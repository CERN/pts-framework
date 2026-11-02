import csv

from PySide6.QtWidgets import QWidget

from pyrade_xy_graph.core.data_store import DataStore


def save_screenshot(widget: QWidget, path: str):
    """Saves the current rendered view as a PNG."""
    widget.grab().save(path, "PNG")


def export_signal_csv(data_store: DataStore, path: str, columns: list[str] | None = None):
    """
    Exports raw buffered data for the given columns (default: all) as CSV.
    Covers only what's resident in DataStore.max_len - for full-history
    export, record to disk during acquisition instead
    (start_live_acquisition(..., record_path=...)).
    """
    cols = columns if columns is not None else data_store.columns
    if not cols:
        return

    arrays = {col: data_store[col] for col in cols}
    n = min(len(arr) for arr in arrays.values())

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for i in range(n):
            writer.writerow([arrays[col][i] for col in cols])


def _default_signal_columns(data_store: DataStore) -> list[str]:
    return [c for c in data_store.columns if not data_store.is_x_column(c)]


def export_signal_hdf5(data_store: DataStore, path: str, columns: list[str] | None = None):
    """
    Exports raw buffered data as HDF5, one dataset per column under a
    top-level 'data' group - the layout core.binary_results reads and
    writes, so an exported file can be reopened via Open File. Each
    signal keeps its own length (no shared-row-count truncation like
    CSV), since channels can have independent x-axis keys.
    """
    import h5py

    cols = columns if columns is not None else _default_signal_columns(data_store)
    if not cols:
        return

    with h5py.File(path, 'w') as f:
        group = f.create_group('data')
        written_x_keys = set()
        for col in cols:
            x_key = data_store.get_x_key(col)
            if x_key not in written_x_keys and x_key in data_store:
                group.create_dataset(x_key, data=data_store[x_key])
                written_x_keys.add(x_key)
            group.create_dataset(col, data=data_store[col])
            unit = data_store.get_unit(col)
            if unit:
                group[col].attrs['unit'] = unit


def export_signal_tdms(data_store: DataStore, path: str, columns: list[str] | None = None):
    """Exports raw buffered data as TDMS, all channels in one 'DataGroup'."""
    from nptdms import ChannelObject, TdmsWriter

    cols = columns if columns is not None else _default_signal_columns(data_store)
    if not cols:
        return

    channels = []
    written_x_keys = set()
    for col in cols:
        x_key = data_store.get_x_key(col)
        if x_key not in written_x_keys and x_key in data_store:
            channels.append(ChannelObject('DataGroup', x_key, data_store[x_key]))
            written_x_keys.add(x_key)
        channels.append(ChannelObject('DataGroup', col, data_store[col]))

    with TdmsWriter(path, mode='w') as writer:
        writer.write_segment(channels)


def export_signal_data(data_store: DataStore, path: str, columns: list[str] | None = None):
    """Dispatches to the CSV/HDF5/TDMS exporter matching path's extension."""
    ext = path.lower().rsplit('.', 1)[-1] if '.' in path else ''
    if ext in ('csv', 'txt'):
        export_signal_csv(data_store, path, columns)
    elif ext in ('h5', 'hdf5'):
        export_signal_hdf5(data_store, path, columns)
    elif ext == 'tdms':
        export_signal_tdms(data_store, path, columns)
    else:
        raise ValueError(f"Unsupported export format: .{ext}")
