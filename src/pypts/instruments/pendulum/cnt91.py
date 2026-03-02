# SPDX-FileCopyrightText: 2025 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

"""
Pendulum CNT-91 frequency counter — pypts extension.

This module provides :class:`CNT91`, a subclass of the upstream
``pymeasure.instruments.pendulum.CNT91`` driver.  All standard CNT-91
behaviour (SCPI commands, gate-time control, buffered frequency measurements,
etc.) is inherited unchanged from pymeasure.

Only two features that are not (yet) in upstream pymeasure are added here:

* **trigger_level** — optional input-level threshold passed to
  :meth:`buffer_frequency_time_series`, which writes ``:INPn:LEV <v>`` to
  the instrument before starting the acquisition.
* **configure_pulse_output** — configures the rear-panel TTL pulse output
  (period, width, source).

If either feature is accepted into pymeasure upstream this file can shrink
or disappear entirely.
"""

from pymeasure.instruments.pendulum import CNT91 as _UpstreamCNT91


class CNT91(_UpstreamCNT91):
    """Pendulum CNT-91 frequency counter with pypts-specific extensions.

    Inherits the full upstream driver from
    :class:`pymeasure.instruments.pendulum.CNT91`.  Refer to the pymeasure
    documentation for the complete API.

    :param adapter: VISA resource string, integer GPIB address, or
        :class:`~pymeasure.adapters.Adapter` instance.
    :param name: Human-readable label used in log messages.
    :param \\**kwargs: Forwarded to :class:`~pymeasure.instruments.Instrument`
        and :class:`~pymeasure.adapters.VISAAdapter`.
    """

    def buffer_frequency_time_series(
        self,
        channel,
        n_samples,
        sample_rate=None,
        gate_time=None,
        trigger_source=None,
        back_to_back=True,
        trigger_level=None,
    ):
        """Record a buffered frequency time-series, optionally setting a
        trigger level first.

        This method extends the upstream implementation by accepting an
        optional *trigger_level* argument.  When supplied, the command
        ``:INPn:LEV <trigger_level>`` is written to the instrument before
        the acquisition is configured, where *n* is the VISA channel number
        corresponding to *channel* (``A`` → 1, ``B`` → 2).

        :param channel: Measurement channel (``'A'`` or ``'B'``).
        :param int n_samples: Number of samples (4 – 10 000).
        :param gate_time: Gate time in seconds.
        :param trigger_source: External arming source
            (``'A'``, ``'B'``, ``'E'``, or ``'IMM'``).
        :param bool back_to_back: If ``True``, perform back-to-back
            measurements.
        :param float trigger_level: Input trigger level in volts.  Only
            channels ``'A'`` and ``'B'`` support a trigger level; passing
            any other channel together with *trigger_level* raises
            :class:`ValueError`.
        :param sample_rate: Deprecated.  Use *gate_time* instead.
        :raises ValueError: If *trigger_level* is given for a channel other
            than ``'A'`` or ``'B'``.
        """
        if trigger_level is not None:
            channel_map = {"A": 1, "B": 2}
            try:
                ch = channel_map[channel]
            except KeyError:
                raise ValueError(
                    f"trigger_level is only supported on channels 'A' and 'B', "
                    f"got '{channel}'."
                )
            self.write(f":INP{ch}:LEV {trigger_level}")

        super().buffer_frequency_time_series(
            channel=channel,
            n_samples=n_samples,
            sample_rate=sample_rate,
            gate_time=gate_time,
            trigger_source=trigger_source,
            back_to_back=back_to_back,
        )

    def configure_pulse_output(
        self,
        enabled=True,
        period=1.0,
        width=0.01,
        source="TIME",
    ):
        """Configure the rear-panel TTL pulse output.

        :param bool enabled: Enable (``True``) or disable (``False``) the
            pulse output.
        :param float period: Pulse period in seconds.
        :param float width: Pulse width in seconds.  Must be strictly less
            than *period*.
        :param str source: Pulse source (``'TIME'``, ``'MEAS'``, etc.
            — depends on firmware).
        :raises ValueError: If *width* is not strictly less than *period*.
        """
        if width >= period:
            raise ValueError(
                f"Pulse width ({width} s) must be strictly less than "
                f"pulse period ({period} s)."
            )
        self.write(f"OUTP:PULS:STAT {'ON' if enabled else 'OFF'}")
        self.write(f"OUTP:PULS:SOUR {source}")
        self.write(f"OUTP:PULS:PER {period}")
        self.write(f"OUTP:PULS:WIDT {width}")
