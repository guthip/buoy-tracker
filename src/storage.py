"""SQLite persistence layer for Buoy Tracker.

Single durable store per PROPOSAL_V2.0.md §6: data/buoy_tracker.db (WAL mode).
Phase 1 scope: node_settings (per-node movement-alert mutes).
Phase 3 extends this module with time-series tables and app_settings.

Design rule: the DB is the system of record for durable data; memory stays the
hot path. Mute state is cached in memory and refreshed on writes, so packet
handlers never touch SQLite on the receive path.
"""

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, Union

from . import config

logger = logging.getLogger(__name__)

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()
_mute_cache: Dict[int, Dict[str, Any]] = {}  # node_id -> {'muted_at': int, 'note': str}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS node_settings (
    node_id               INTEGER PRIMARY KEY,
    movement_alerts_muted INTEGER NOT NULL DEFAULT 0,
    muted_at              INTEGER,
    note                  TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id                   INTEGER PRIMARY KEY,
    node_id              INTEGER NOT NULL,
    ts                   INTEGER NOT NULL,
    lat                  REAL,
    lon                  REAL,
    alt                  REAL,
    voltage              REAL,
    distance_from_home_m REAL,
    packet_id            INTEGER,
    gateway_id           INTEGER,
    rssi                 REAL,
    snr                  REAL,
    simulated            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_positions_node_ts ON positions(node_id, ts);

CREATE TABLE IF NOT EXISTS telemetry (
    id          INTEGER PRIMARY KEY,
    node_id     INTEGER NOT NULL,
    ts          INTEGER NOT NULL,
    voltage     REAL,
    battery_pct INTEGER,
    rssi        REAL,
    snr         REAL,
    simulated   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_telemetry_node_ts ON telemetry(node_id, ts);

CREATE TABLE IF NOT EXISTS alert_events (
    id         INTEGER PRIMARY KEY,
    ts         INTEGER NOT NULL,
    node_id    INTEGER,
    kind       TEXT NOT NULL,
    distance_m REAL,
    details    TEXT,
    simulated  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alert_events_ts ON alert_events(ts);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS nodes (
    node_id    INTEGER PRIMARY KEY,
    label      TEXT,
    home_lat   REAL,
    home_lon   REAL,
    updated_at INTEGER
);
"""

# Measurement tables subject to time-based retention (settings/registry are kept)
_RETENTION_TABLES = ('positions', 'telemetry', 'alert_events')
_PRUNE_INTERVAL_S = 6 * 3600  # re-check retention a few times a day
_last_prune_ts = 0.0


def init(db_path: Union[str, Path, None] = None) -> None:
    """Open (or create) the database and load caches. Idempotent."""
    global _conn
    with _lock:
        if _conn is not None:
            return
        path = Path(db_path) if db_path else Path(config.DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.execute('PRAGMA journal_mode=WAL')
        _conn.executescript(_SCHEMA)
        # Migration for pre-release dev DBs created before positions.voltage
        try:
            _conn.execute('ALTER TABLE positions ADD COLUMN voltage REAL')
        except sqlite3.OperationalError:
            pass  # column already exists
        _conn.commit()
        _load_mute_cache_locked()
        _sync_nodes_registry_locked()
        _prune_locked()
    if _mute_cache:
        logger.warning(
            f'[MUTE] {len(_mute_cache)} node(s) have movement alerts muted: {sorted(_mute_cache)}'
        )
    logger.info(f'Storage initialized: {path}')


def close() -> None:
    """Close the database and drop caches (used by tests and shutdown)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        _mute_cache.clear()


def _load_mute_cache_locked() -> None:
    """Reload the mute cache from the DB. Caller must hold _lock."""
    _mute_cache.clear()
    rows = _conn.execute(
        'SELECT node_id, muted_at, note FROM node_settings WHERE movement_alerts_muted = 1'
    )
    for node_id, muted_at, note in rows:
        _mute_cache[node_id] = {'muted_at': muted_at, 'note': note}


def is_movement_muted(node_id: int) -> bool:
    """True if movement-alert emails are muted for this node. Memory-only read."""
    return node_id in _mute_cache


def get_all_mutes() -> Dict[str, Dict[str, Any]]:
    """All muted nodes as {node_id_str: {'muted_at': int, 'note': str}}."""
    return {str(nid): dict(v) for nid, v in _mute_cache.items()}


def set_movement_muted(node_id: int, muted: bool, note: Optional[str] = None) -> None:
    """Persist a node's movement-alert mute state and update the cache."""
    with _lock:
        if _conn is None:
            raise RuntimeError('storage.init() has not been called')
        now = int(time.time())
        _conn.execute(
            'INSERT INTO node_settings (node_id, movement_alerts_muted, muted_at, note) '
            'VALUES (?, ?, ?, ?) '
            'ON CONFLICT(node_id) DO UPDATE SET '
            '  movement_alerts_muted = excluded.movement_alerts_muted, '
            '  muted_at = excluded.muted_at, '
            '  note = excluded.note',
            (node_id, 1 if muted else 0, now if muted else None, note),
        )
        _conn.commit()
        if muted:
            _mute_cache[node_id] = {'muted_at': now, 'note': note}
        else:
            _mute_cache.pop(node_id, None)
    logger.warning(
        f'[MUTE] Movement alerts {"MUTED" if muted else "UNMUTED"} for node {node_id}'
        + (f' ({note})' if note else '')
    )


# ---------------------------------------------------------------------------
# Time-series recording (positions, telemetry, alert events)
# All writes are append-only and happen off the receive hot path only in the
# sense of being single INSERTs under WAL — microseconds at this data rate.
# ---------------------------------------------------------------------------

def record_position(node_id, ts, lat, lon, alt=None, voltage=None,
                    distance_from_home_m=None, packet_id=None, gateway_id=None,
                    rssi=None, snr=None, simulated=False) -> None:
    with _lock:
        if _conn is None:
            return
        _conn.execute(
            'INSERT INTO positions (node_id, ts, lat, lon, alt, voltage,'
            ' distance_from_home_m, packet_id, gateway_id, rssi, snr, simulated)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (node_id, int(ts), lat, lon, alt, voltage, distance_from_home_m,
             packet_id, gateway_id, rssi, snr, 1 if simulated else 0),
        )
        _conn.commit()
        _maybe_prune_locked()


def record_telemetry(node_id, ts, voltage=None, battery_pct=None,
                     rssi=None, snr=None, simulated=False) -> None:
    with _lock:
        if _conn is None:
            return
        _conn.execute(
            'INSERT INTO telemetry (node_id, ts, voltage, battery_pct, rssi, snr, simulated)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?)',
            (node_id, int(ts), voltage, battery_pct, rssi, snr, 1 if simulated else 0),
        )
        _conn.commit()
        _maybe_prune_locked()


def record_alert_event(kind, node_id=None, distance_m=None, details=None,
                       simulated=False) -> None:
    """Append one alert-pipeline decision (movement_fired / movement_suppressed /
    movement_muted / battery_low / ...). `details` may be any JSON-serializable value."""
    import json as _json
    with _lock:
        if _conn is None:
            return
        _conn.execute(
            'INSERT INTO alert_events (ts, node_id, kind, distance_m, details, simulated)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (int(time.time()), node_id, kind, distance_m,
             _json.dumps(details) if details is not None else None,
             1 if simulated else 0),
        )
        _conn.commit()


def get_positions_since(node_id, since_ts, include_simulated=False):
    """Position rows for one node since a timestamp, oldest first.
    Used to rebuild in-memory trails at startup."""
    with _lock:
        if _conn is None:
            return []
        sim_clause = '' if include_simulated else ' AND simulated = 0'
        rows = _conn.execute(
            f'SELECT ts, lat, lon, alt, voltage, rssi, snr FROM positions'
            f' WHERE node_id = ? AND ts >= ?{sim_clause} ORDER BY ts',
            (node_id, int(since_ts)),
        ).fetchall()
    return [
        {'ts': ts, 'lat': lat, 'lon': lon, 'alt': alt, 'voltage': voltage,
         'rssi': rssi, 'snr': snr}
        for ts, lat, lon, alt, voltage, rssi, snr in rows
    ]


# ---------------------------------------------------------------------------
# Runtime app settings (DB is master; config file supplies defaults at startup
# for keys with no override row — review decision Q9)
# ---------------------------------------------------------------------------

def get_setting(key: str) -> Optional[str]:
    with _lock:
        if _conn is None:
            return None
        row = _conn.execute('SELECT value FROM app_settings WHERE key = ?', (key,)).fetchone()
    return row[0] if row else None


def set_setting(key: str, value) -> None:
    with _lock:
        if _conn is None:
            raise RuntimeError('storage.init() has not been called')
        _conn.execute(
            'INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)'
            ' ON CONFLICT(key) DO UPDATE SET value = excluded.value,'
            ' updated_at = excluded.updated_at',
            (key, str(value), int(time.time())),
        )
        _conn.commit()
    logger.info(f'[SETTINGS] {key} = {value} (DB override)')


def all_settings() -> Dict[str, str]:
    with _lock:
        if _conn is None:
            return {}
        rows = _conn.execute('SELECT key, value FROM app_settings').fetchall()
    return dict(rows)


def reset_settings() -> int:
    """Delete all app_settings overrides (the Control Menu 'reset to config
    defaults' action). Returns the number of overrides removed."""
    with _lock:
        if _conn is None:
            return 0
        cur = _conn.execute('DELETE FROM app_settings')
        _conn.commit()
    logger.warning(f'[SETTINGS] {cur.rowcount} override(s) reset to config defaults')
    return cur.rowcount


# ---------------------------------------------------------------------------
# Node registry snapshot + retention
# ---------------------------------------------------------------------------

def _sync_nodes_registry_locked() -> None:
    """Mirror config.SPECIAL_NODES into the nodes table (for analysis JOINs)."""
    now = int(time.time())
    for node_id, sn in getattr(config, 'SPECIAL_NODES', {}).items():
        _conn.execute(
            'INSERT INTO nodes (node_id, label, home_lat, home_lon, updated_at)'
            ' VALUES (?, ?, ?, ?, ?)'
            ' ON CONFLICT(node_id) DO UPDATE SET label = excluded.label,'
            ' home_lat = excluded.home_lat, home_lon = excluded.home_lon,'
            ' updated_at = excluded.updated_at',
            (node_id, sn.get('label'), sn.get('home_lat'), sn.get('home_lon'), now),
        )
    _conn.commit()


def _prune_locked() -> None:
    """Enforce time-based retention on measurement tables. Caller holds _lock."""
    global _last_prune_ts
    retention_days = getattr(config, 'DB_RETENTION_DAYS', 90)
    cutoff = int(time.time() - retention_days * 86400)
    total = 0
    for table in _RETENTION_TABLES:
        cur = _conn.execute(f'DELETE FROM {table} WHERE ts < ?', (cutoff,))  # noqa: S608 — table names from module constant
        total += cur.rowcount
    _conn.commit()
    _last_prune_ts = time.time()
    if total:
        logger.info(f'[RETENTION] pruned {total} rows older than {retention_days} days')


def _maybe_prune_locked() -> None:
    if time.time() - _last_prune_ts >= _PRUNE_INTERVAL_S:
        _prune_locked()
