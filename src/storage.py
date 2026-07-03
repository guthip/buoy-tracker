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
"""


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
        _conn.commit()
        _load_mute_cache_locked()
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
