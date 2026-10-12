#!/bin/sh
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

set -eu

Xvfb "$DISPLAY" -screen 0 "${RESOLUTION}x24" -nolisten tcp &

until xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; do
    sleep 0.1
done

openbox >/dev/null 2>&1 &
x11vnc -display "$DISPLAY" -localhost -forever -shared -nopw -quiet >/dev/null 2>&1 &
websockify --web /usr/share/novnc "$NOVNC_PORT" localhost:5900 >/dev/null 2>&1 &

if [ "$*" = "python -m pypts" ]; then
    echo "Open http://localhost:${NOVNC_PORT}/vnc.html?autoconnect=true&resize=scale in a browser"
fi

exec "$@"
