#!/bin/bash
# Buoy Tracker entrypoint (v2.1)
#
# Rootful (docker default):  runs as root, re-numbers the app user to
#   PUID/PGID (default 1000:1000, linuxserver.io convention), chowns the
#   volume dirs, then drops privileges.
# Rootless (podman --userns=keep-id, or compose `user:`): starts non-root,
#   skips re-numbering/chown (PUID/PGID ignored), verifies writability,
#   and execs the app directly.

set -e

echo "=== Buoy Tracker Entrypoint ==="

# ---------------------------------------------------------------------------
# Config layout checks (v2.1 layered configs)
# ---------------------------------------------------------------------------
if [ -f /app/config/tracker.config ] && [ ! -f /app/config/site.config ]; then
    echo "✗ ERROR: legacy tracker.config found but v2.1 uses layered configs."
    echo "  Migrate once (on the host):"
    echo "    python3 tools/split_config.py config/tracker.config"
    echo "  or inside the container:"
    echo "    docker exec buoy-tracker python3 /app/tools/split_config.py /app/config/tracker.config"
    echo "  then restart. The legacy file is ignored afterwards."
    exit 1
fi

place_examples() {
    for name in site.config environment.config; do
        if [ ! -f "/app/config/$name" ] && [ ! -f "/app/config/$name.example" ]; then
            cp "/app/$name.example" "/app/config/$name.example" 2>/dev/null || true
            echo "ⓘ  No $name yet — example placed at config/$name.example (app runs on defaults until you create $name)"
        fi
    done
}

# ---------------------------------------------------------------------------
# Rootless mode: verify access and run as the invoking user
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    echo "ⓘ  Running as UID $(id -u):$(id -g) (rootless mode) — PUID/PGID env vars are ignored"
    for d in /app/config /app/data /app/logs; do
        mkdir -p "$d" 2>/dev/null || true
        if [ ! -w "$d" ]; then
            echo "✗ ERROR: $d is not writable by UID $(id -u)."
            echo "  Rootless podman: run with  --userns=keep-id"
            echo "  Otherwise: chown the mounted host directories to the mapped user."
            exit 1
        fi
    done
    place_examples
    echo "Starting Buoy Tracker..."
    exec python3 run.py
fi

# ---------------------------------------------------------------------------
# Rootful mode: PUID/PGID (linuxserver.io convention), then drop privileges
# ---------------------------------------------------------------------------
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
echo "ⓘ  PUID=${PUID} PGID=${PGID} (set these env vars to match your host user)"

groupmod -o -g "$PGID" app
usermod  -o -u "$PUID" app

mkdir -p /app/config /app/data /app/logs
chmod 775 /app/config /app/data /app/logs

place_examples

# chown volumes to the (re-numbered) app user; tolerate exotic filesystems
chown -R app:app /app/config /app/data /app/logs 2>/dev/null || true

echo "✓ Configuration ready in /app/config/"
echo "Starting Buoy Tracker as UID ${PUID}:${PGID}..."
exec setpriv --reuid app --regid app --init-groups python3 run.py
