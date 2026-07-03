"""Simulation / debug packet injection (PROPOSAL_V2.0.md §7).

Injects synthetic packets at the same seam real MQTT traffic uses: the decoded
json_packet dict that _route_message_to_handler() hands to on_position() /
on_telemetry() / on_nodeinfo(). Everything downstream — precision validation,
dedup, the coord-consensus alert buffer, cooldowns, emails, history, the live
UI — runs exactly as it would for real traffic.

Only reachable when [debug] enable_simulation = true (endpoints 404 otherwise).
All injected packets carry simulated=True.
"""

import json
import logging
import random
import threading
import time
from pathlib import Path

from . import config
from . import mqtt_handler

logger = logging.getLogger(__name__)

# Fixture files for /api/debug/replay must live here (no arbitrary paths)
FIXTURES_DIR = Path(__file__).parent.parent / 'fixtures'

_SIM_GATEWAYS = ['!51a70001', '!51a70002', '!51a70003', '!51a70004', '!51a70005']

# Rough meters-per-degree of latitude; fine for generating test offsets
_M_PER_DEG_LAT = 111320.0


def _next_packet_id():
    return random.randint(10_000_000, 2_000_000_000)


def _home_of(node_id):
    """Best-known home position: config home, else learned origin, else map center."""
    sn = config.SPECIAL_NODES.get(node_id) or {}
    lat, lon = sn.get('home_lat'), sn.get('home_lon')
    if lat is None or lon is None:
        nd = mqtt_handler.nodes_data.get(node_id, {})
        lat, lon = nd.get('origin_lat'), nd.get('origin_lon')
    if lat is None or lon is None:
        lat, lon = config.DEFAULT_LAT, config.DEFAULT_LON
    return lat, lon


def _envelope(node_id, payload, gateway_hex, packet_id, rssi, snr, hop_start, hop_limit):
    """Common json_packet fields shared by all packet types."""
    return {
        'from': node_id,
        'to': 4294967295,
        'id': packet_id or _next_packet_id(),
        'channel': 0,
        'channel_name': config.MQTT_CHANNEL_NAME,
        'mqtt_topic': f'{config.MQTT_ROOT_TOPIC}{config.MQTT_CHANNEL_NAME}/{gateway_hex}',
        'rx_rssi': rssi,
        'rx_snr': snr,
        'hop_start': hop_start,
        'hop_limit': hop_limit,
        'simulated': True,
        'decoded': {'payload': payload},
    }


def build_position_packet(node_id, lat, lon, gateway_hex='!51a70001', packet_id=None,
                          rssi=-95, snr=2.0, hop_start=3, hop_limit=3,
                          precision_bits=32, gps_time=None):
    payload = {
        'latitude_i': int(lat * 1e7),
        'longitude_i': int(lon * 1e7),
        'precision_bits': precision_bits,
        'time': int(gps_time or time.time()),
    }
    return _envelope(node_id, payload, gateway_hex, packet_id, rssi, snr, hop_start, hop_limit)


def build_telemetry_packet(node_id, voltage, gateway_hex='!51a70001', packet_id=None,
                           rssi=-95, snr=2.0, hop_start=3, hop_limit=3):
    voltage_channel = config.SPECIAL_NODES.get(node_id, {}).get('voltage_channel', 'ch3_voltage')
    payload = {'power_metrics': {voltage_channel: float(voltage)}}
    return _envelope(node_id, payload, gateway_hex, packet_id, rssi, snr, hop_start, hop_limit)


def inject(packet_type, packet):
    """Dispatch one synthetic packet through the real handler."""
    packet.setdefault('simulated', True)
    if packet_type == 'position':
        mqtt_handler.on_position(packet)
    elif packet_type == 'telemetry':
        mqtt_handler.on_telemetry(packet)
    elif packet_type == 'nodeinfo':
        mqtt_handler.on_nodeinfo(packet)
    else:
        raise ValueError(f'unknown packet type: {packet_type}')
    logger.info(f'[SIM] injected {packet_type} for node {packet.get("from")} (packet_id={packet.get("id")})')


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def scenario_drift(node_id, distance_m=250.0, copies=4):
    """A real drift event: N gateway copies of one broadcast, all agreeing on a
    position distance_m north of home. The consensus vote should FIRE."""
    home_lat, home_lon = _home_of(node_id)
    lat = home_lat + distance_m / _M_PER_DEG_LAT
    pid = _next_packet_id()
    gps_time = time.time()
    for i in range(copies):
        pkt = build_position_packet(
            node_id, lat, home_lon,
            gateway_hex=_SIM_GATEWAYS[i % len(_SIM_GATEWAYS)],
            packet_id=pid, rssi=-88 - 4 * i, snr=4.0 - i, gps_time=gps_time,
        )
        inject('position', pkt)
    return {
        'scenario': 'drift', 'node_id': node_id, 'packet_id': pid,
        'copies': copies, 'distance_m': distance_m,
        'expect': f'[ALERT_FIRE] after the {mqtt_handler._ALERT_WINDOW_S:.0f}s buffer window closes',
    }


def scenario_mutation(node_id, copies=4, outlier_distance_m=2349000.0):
    """The 2026-05-26 failure mode: one relay path mutates the coordinates of a
    single copy while the other gateway copies agree on the true (home)
    position. The consensus vote should SUPPRESS the alert."""
    home_lat, home_lon = _home_of(node_id)
    bad_lat = min(home_lat + outlier_distance_m / _M_PER_DEG_LAT, 89.9)
    pid = _next_packet_id()
    gps_time = time.time()

    # Outlier first: its far position opens the alert buffer so the honest
    # copies that follow are collected as "close" votes in the same window.
    inject('position', build_position_packet(
        node_id, bad_lat, home_lon, gateway_hex=_SIM_GATEWAYS[0],
        packet_id=pid, rssi=-110, snr=-6.0, gps_time=gps_time))
    for i in range(1, copies):
        inject('position', build_position_packet(
            node_id, home_lat, home_lon, gateway_hex=_SIM_GATEWAYS[i % len(_SIM_GATEWAYS)],
            packet_id=pid, rssi=-90 - 2 * i, snr=3.0, gps_time=gps_time))
    return {
        'scenario': 'mutation', 'node_id': node_id, 'packet_id': pid,
        'copies': copies, 'outlier_distance_m': outlier_distance_m,
        'expect': f'[ALERT_SUPPRESSED] after the {mqtt_handler._ALERT_WINDOW_S:.0f}s buffer window closes',
    }


def scenario_battery_drain(node_id, start_v=3.9, end_v=3.3, steps=6, interval_s=2.0):
    """Voltage ramp crossing the 3.5 V low-battery threshold. Runs in a
    background thread; the low-battery email fires (dry-run in sim mode)."""
    def _run():
        for i in range(steps):
            v = start_v + (end_v - start_v) * i / max(1, steps - 1)
            inject('telemetry', build_telemetry_packet(node_id, round(v, 3)))
            time.sleep(interval_s)
    threading.Thread(target=_run, daemon=True, name='sim-battery-drain').start()
    return {
        'scenario': 'battery_drain', 'node_id': node_id,
        'start_v': start_v, 'end_v': end_v, 'steps': steps, 'interval_s': interval_s,
        'expect': 'low-battery alert once voltage < 3.5V (subject to cooldown)',
    }


def scenario_gap(node_id, hours=4.0):
    """Backdate the node's last_seen / last_position_update to exercise the
    LPU/SoL staleness colors without waiting hours. State-only manipulation."""
    nd = mqtt_handler.nodes_data.setdefault(node_id, {})
    shift = hours * 3600.0
    now = time.time()
    nd['last_seen'] = now - shift
    if nd.get('last_position_update'):
        nd['last_position_update'] = nd['last_position_update'] - shift
    else:
        nd['last_position_update'] = now - shift
    return {
        'scenario': 'gap', 'node_id': node_id, 'hours': hours,
        'expect': 'LPU/SoL indicators show staleness colors for the shifted age',
    }


SCENARIOS = {
    'drift': scenario_drift,
    'mutation': scenario_mutation,
    'battery_drain': scenario_battery_drain,
    'gap': scenario_gap,
}


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay_file(filename, speed=60.0):
    """Replay a JSONL fixture (one packet per line) with time compression.

    Line format: {"type": "position", "delay_s": 2.0, "packet": {...}}
    delay_s is the gap to the previous packet in real time; it is divided by
    `speed` during replay. Files must live in fixtures/ (no path traversal).
    """
    path = (FIXTURES_DIR / Path(filename).name).resolve()
    if not str(path).startswith(str(FIXTURES_DIR.resolve())) or not path.exists():
        raise FileNotFoundError(f'fixture not found: {Path(filename).name}')

    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def _run():
        for entry in lines:
            delay = float(entry.get('delay_s', 0)) / max(0.001, speed)
            if delay > 0:
                time.sleep(delay)
            try:
                inject(entry.get('type', 'position'), entry['packet'])
            except Exception as e:
                logger.error(f'[SIM] replay error: {e}')
        logger.info(f'[SIM] replay of {path.name} complete ({len(lines)} packets)')

    threading.Thread(target=_run, daemon=True, name='sim-replay').start()
    return {'file': path.name, 'packets': len(lines), 'speed': speed}


# ---------------------------------------------------------------------------
# State snapshot (for asserting scenario outcomes)
# ---------------------------------------------------------------------------

def get_state():
    """Internal-state snapshot for the debug UI / assertions."""
    from . import alerts, storage
    pending = {
        str(nid): {
            'copies': len(info.get('copies', [])),
            'open_for_s': round(time.time() - info.get('first_seen_ts', 0), 1),
        }
        for nid, info in mqtt_handler._pending_movement_alerts.items()
    }
    return {
        'simulation_enabled': True,
        'alert_window_s': mqtt_handler._ALERT_WINDOW_S,
        'alert_cooldown_s': config.ALERT_COOLDOWN,
        'emails': 'real' if getattr(config, 'DEBUG_SEND_REAL_EMAILS', False) else 'dry-run',
        'pending_movement_alerts': pending,
        'alert_cooldowns': {str(k): int(v) for k, v in alerts.last_alert_sent.items()},
        'homecoming_progress': {str(k): v for k, v in mqtt_handler._homecoming_progress.items()},
        'mutes': storage.get_all_mutes(),
    }
