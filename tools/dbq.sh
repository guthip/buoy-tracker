#!/bin/sh
# Query the live Buoy Tracker database safely (read-only, inside the container).
# Usage: tools/dbq.sh "SELECT COUNT(*) FROM positions"
#        tools/dbq.sh            (no args: summary of all tables)
#
# Works even on images without the sqlite3 binary by using the container's
# Python. Never opens the mounted file from the host while the app writes.
SQL="${1:-}"
if [ -z "$SQL" ]; then
  docker exec buoy-tracker python3 -c "
import sqlite3
c = sqlite3.connect('file:/app/data/buoy_tracker.db?mode=ro', uri=True)
for t in ('positions', 'telemetry', 'alert_events', 'node_settings', 'app_settings', 'nodes'):
    print(f'{t}:', c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
"
else
  docker exec buoy-tracker python3 -c "
import sqlite3, sys
c = sqlite3.connect('file:/app/data/buoy_tracker.db?mode=ro', uri=True)
for row in c.execute(sys.argv[1]):
    print('|'.join('' if v is None else str(v) for v in row))
" "$SQL"
fi
