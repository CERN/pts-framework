#!/bin/sh
# SPDX-FileCopyrightText: 2026 CERN <home.cern>
#
# SPDX-License-Identifier: LGPL-2.1-or-later

set -eu

image="$1"
port="${2:-6080}"
url="http://127.0.0.1:${port}/vnc.html"

container=$(docker run --detach --publish "127.0.0.1:${port}:6080" "$image")
trap 'docker logs "$container"; docker rm --force "$container" >/dev/null' EXIT

i=0
until curl --fail --silent --output /dev/null "$url"; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "noVNC did not become reachable at ${url}" >&2
        exit 1
    fi
    sleep 1
done

i=0
until docker exec "$container" xwininfo -display :0 -root -tree | grep -q '"pypts"'; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "The pypts window did not appear on the virtual display" >&2
        exit 1
    fi
    sleep 1
done

echo "Smoke test passed"
