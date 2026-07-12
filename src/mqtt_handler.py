"""
Meshtastic MQTT Handler for Buoy Tracker
Uses paho-mqtt directly with meshtastic protobuf libraries for clean decoding.
Extracts channel names from MQTT topic paths.
Tracks node positions, names, and last seen timestamps.
"""

import paho.mqtt.client as mqtt_client
import base64
import time
import logging
import json
import threading
from collections import deque
from pathlib import Path
import os
import math
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from google.protobuf.json_format import MessageToJson

# Import Meshtastic protobuf definitions
from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2

from . import config
from . import alerts
from . import storage
from .topics import sanitize_display_text, channel_from_topic, gateway_id_from_topic
from .movement import (
    _haversine_m,
    _get_signal_quality_score,
    _validate_position_precision,
    _add_copy_to_alert_buffer,
    _check_expired_alert_buffers,
    _evaluate_alert_buffer,
    _update_homecoming,
    _pending_movement_alerts,
    _homecoming_progress,
    _ALERT_WINDOW_S,
)

# Back-compat aliases: existing call sites use the old private names
_sanitize_display_text = sanitize_display_text
_extract_channel_from_mqtt_topic = channel_from_topic
_extract_gateway_node_id_from_topic = gateway_id_from_topic

logger = logging.getLogger(__name__)

# MQTT client
client = None
mqtt_was_connected = False  # Track if we were previously connected (to detect reconnections)

# Dictionary to store node data: {node_id: {name, long_name, position, telemetry, last_seen}}
nodes_data = {}
# Track if we've received any messages (more reliable than client.is_connected())
message_received = False
packets_received = False  # Track when we've received actual MQTT packets with data
last_message_time = 0
last_packet_time = 0  # Timestamp of last received MQTT packet (for detecting stale connections)

# Staleness thresholds - different for all-nodes vs special-nodes-only mode
PACKET_STALENESS_THRESHOLD_ALL_NODES = 300      # 5 minutes - when subscribed to all nodes
PACKET_STALENESS_THRESHOLD_SPECIAL_ONLY = 3600  # 60 minutes - when subscribed to special nodes only

# Special nodes history: node_id -> deque of {ts, lat, lon, alt}
special_history = {}

# Store MQTT topic per node to extract channel name
node_topics = {}

# Special nodes packet tracking: store ALL packets for special nodes (no limit)
special_node_packets = {}  # node_id -> list of ALL packets with details
special_node_last_packet = {}  # node_id -> timestamp of last packet (any type, even encrypted)
special_node_channels = {}  # node_id -> channel_name from topic (for routing packets)
special_node_position_timestamps = {}  # node_id -> set of rxTime values (legacy; kept for restart clears)

# Lean storage (v2.1): one history entry + one DB row per BROADCAST, not per
# gateway copy. A broadcast's gateway copies share the packet id; ~20-25
# gateways around the bay each uplink a copy, and recording them all inflated
# the store ~23x with data no one reads. The consensus alert buffer still
# sees every copy through its own path.
_seen_broadcasts = {}  # node_id -> (set of packet_ids, deque for eviction)
_SEEN_BROADCASTS_MAX = 300


def _is_new_broadcast(node_id, packet_id):
    if packet_id is None:
        return True  # can't identify the broadcast; accept rather than drop
    entry = _seen_broadcasts.get(node_id)
    if entry is None:
        entry = (set(), deque())
        _seen_broadcasts[node_id] = entry
    ids, order = entry
    if packet_id in ids:
        return False
    ids.add(packet_id)
    order.append(packet_id)
    if len(order) > _SEEN_BROADCASTS_MAX:
        ids.discard(order.popleft())
    return True
_last_channel_save = 0  # Track when we last saved channel data
_last_packet_save = 0  # Track when we last saved packet history

# Gateway detection
node_is_gateway = {}  # node_id -> bool (True if node is a gateway)

# Gateway connections: special_node_id -> {gateway_node_id: {name, lat, lon, rssi, snr, last_seen}}
# Tracks which gateways received packets from which special nodes
special_node_gateways = {}

# Gateway reliability cache: gateway_id -> {score, detection_count, avg_rssi, last_updated}
# Updated when gateway connections change, used by get_nodes() for O(1) lookup
gateway_reliability_cache = {}

# Gateway node IDs cache: set of all node IDs that appear in any special node's gateways
# Updated when gateway connections change, used by get_nodes() for O(1) is_gateway check
all_gateway_node_ids = set()

# Gateway info cache: gateway_id -> {name, lat, lon, rssi, snr, last_seen}
# Stores most recent gateway info across all special nodes for quick lookup
gateway_info_cache = {}

def _is_special_node(node_id):
    """Check if a node_id is in the special nodes list. All special nodes are power-sensor buoys."""
    return node_id in config.SPECIAL_NODES

def _get_node_voltage(node_id):
    """
    Get battery voltage for a node based on configured voltage_channel.

    For power sensor nodes (INA260/INA219):
    - ONLY use power_metrics (ch3_voltage for battery, ch1_voltage for input)
    - IGNORE device_metrics voltage/battery_level (meaningless ~100% reading)

    For regular nodes:
    - Use device_metrics voltage

    Returns None if configured voltage source is not available.
    """
    if node_id not in nodes_data:
        return None

    telemetry = nodes_data[node_id].get('telemetry', {})
    if not isinstance(telemetry, dict):
        return None

    # Get voltage channel from config (defaults to 'ch3_voltage' for power sensors, 'device_voltage' for others)
    voltage_channel = 'device_voltage'  # Default for non-special nodes
    if node_id in config.SPECIAL_NODES:
        voltage_channel = config.SPECIAL_NODES[node_id].get('voltage_channel', 'device_voltage')

    # Get voltage from the configured channel ONLY
    # No fallbacks - if the configured source isn't available, return None
    if voltage_channel == 'device_voltage':
        device_metrics = telemetry.get('device_metrics', {})
        return device_metrics.get('voltage')
    elif voltage_channel == 'ch3_voltage':
        # Power sensor battery voltage - ignore device_metrics completely
        power_metrics = telemetry.get('power_metrics', {})
        return power_metrics.get('ch3_voltage')
    elif voltage_channel == 'ch1_voltage':
        # Power sensor input voltage - ignore device_metrics completely
        power_metrics = telemetry.get('power_metrics', {})
        return power_metrics.get('ch1_voltage')
    else:
        # Unknown channel, return None
        return None

def _estimate_battery_from_voltage(voltage):
    """
    Estimate battery percentage from voltage using linear approximation.
    LiPo/Li-ion cells: ~2.8V = 0%, ~4.25V = 100%

    Args:
        voltage: Battery voltage in volts

    Returns:
        Battery percentage (0-100) or None if voltage is None
    """
    if voltage is None or not isinstance(voltage, (int, float)):
        return None

    if voltage >= 4.25:
        return 100
    elif voltage <= 2.8:
        return 0
    else:
        # Linear approximation: map 2.8V-4.25V to 0-100%
        battery = int(((voltage - 2.8) / (4.25 - 2.8)) * 100)
        return max(0, min(100, battery))  # Clamp to 0-100

def _get_voltage_for_history(node_id):
    """Get latest voltage for a special node, used as the canonical history sample."""
    return _get_node_voltage(node_id)

def _find_recent_history_entry(node_id, current_ts, window_seconds=2):
    """
    Find the most recent history entry within a time window.

    Args:
        node_id: Node ID to search history for
        current_ts: Current timestamp
        window_seconds: Time window in seconds (default: 2)

    Returns:
        Most recent history entry dict if found within window, else None
    """
    if node_id not in special_history or len(special_history[node_id]) == 0:
        return None

    most_recent = special_history[node_id][-1]
    if abs(most_recent['ts'] - current_ts) < window_seconds:
        return most_recent
    return None

def _update_history_entry(entry, rssi, snr, voltage):
    """Update an existing history entry. Keeps the best (highest) RSSI/SNR; replaces voltage with the latest sample."""
    if rssi is not None and (entry.get('rssi') is None or rssi > entry['rssi']):
        entry['rssi'] = rssi

    if snr is not None and (entry.get('snr') is None or snr > entry['snr']):
        entry['snr'] = snr

    if voltage is not None:
        entry['voltage'] = voltage

def _add_telemetry_to_history(node_id, json_data):
    """
    Add or update telemetry data in special node history.
    Creates new history entry or updates existing one if within 2-second window.

    special_history entries double as both the map's position trail and the
    battery-history chart's data source, but a telemetry packet carries no
    position of its own — it only ever reports whatever position was last
    known (possibly none yet, for a brand-new node). Position-less entries
    are valid: the battery chart never reads lat/lon; only the map-trail
    renderer needs a real fix, and it filters for that itself.

    Args:
        node_id: Node ID to add history for
        json_data: Full MQTT packet data
    """
    # Guard clause: Not a special node? Skip.
    if not _is_special_node(node_id):
        return

    lat = nodes_data[node_id].get("latitude")
    lon = nodes_data[node_id].get("longitude")
    if lat == 0 and lon == 0:
        lat = lon = None

    # Ensure history structure exists
    _ensure_history_struct(node_id)

    current_ts = time.time()
    voltage = _get_voltage_for_history(node_id)
    rssi = json_data.get("rx_rssi")
    snr = json_data.get("rx_snr")

    recent_entry = _find_recent_history_entry(node_id, current_ts)

    if recent_entry:
        _update_history_entry(recent_entry, rssi, snr, voltage)
        logger.debug(f'Updated telemetry history for {node_id}: voltage={recent_entry.get("voltage")}, rssi={recent_entry["rssi"]}, snr={recent_entry["snr"]}')
    else:
        entry = {
            "ts": current_ts,
            "lat": lat,
            "lon": lon,
            "alt": nodes_data[node_id].get("alt", 0),
            "voltage": voltage,
            "rssi": rssi,
            "snr": snr,
        }
        special_history[node_id].append(entry)
        logger.debug(f'Added telemetry to history for {node_id}: voltage={entry["voltage"]}, rssi={entry["rssi"]}, snr={entry["snr"]}')

    # Prune old history entries
    _prune_history(node_id, now_ts=current_ts)

def rebuild_history_from_db():
    """Rebuild in-memory position trail AND battery history from the durable
    store at startup.

    Replaces the old special_nodes.json persistence: trails survive restarts
    without any JSON snapshotting because every accepted position is already
    a row in the positions table.

    Found 2026-07-12 (SYCP report — card 4.12V/91% but the battery history
    chart stuck at an older 4.108V/90% for over an hour after a restart):
    this used to rebuild only from positions, never from telemetry. Any
    telemetry-only sample between the last position fix and a restart was
    permanently missing from the chart afterward, until the next telemetry
    packet happened to arrive post-restart — every restart during today's
    release cycle reproduced exactly this symptom. Positions and telemetry
    are now merged by timestamp."""
    hours = getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
    since = time.time() - hours * 3600
    total = 0
    for node_id in getattr(config, 'SPECIAL_NODE_IDS', []):
        try:
            pos_rows = storage.get_positions_since(node_id, since)
            tel_rows = storage.get_telemetry_since(node_id, since)
        except Exception as e:
            logger.error(f'Trail rebuild failed for {node_id}: {e}')
            continue
        rows = sorted(pos_rows + tel_rows, key=lambda r: r['ts'])
        if not rows:
            continue
        _ensure_history_struct(node_id)
        for r in rows:
            special_history[node_id].append({
                'ts': r['ts'], 'lat': r['lat'], 'lon': r['lon'], 'alt': r['alt'],
                'voltage': r.get('voltage'), 'rssi': r['rssi'], 'snr': r['snr'],
            })
        total += len(rows)
    if total:
        logger.info(f'Rebuilt {total} trail point(s) from durable store ({hours}h window)')

    # Warm-start current state from the last known real readings so cards show
    # battery/position/age immediately after a restart (ages stay honest: they
    # are computed from the recorded timestamps, not from "now").
    warmed = 0
    for node_id in getattr(config, 'SPECIAL_NODE_IDS', []):
        try:
            st = storage.get_latest_state(node_id)
        except Exception as e:
            logger.error(f'Warm-start failed for {node_id}: {e}')
            continue
        if not st:
            continue
        nd = nodes_data.setdefault(node_id, {})
        sn = config.SPECIAL_NODES.get(node_id, {})
        if sn.get('home_lat') is not None:
            nd.setdefault('origin_lat', sn['home_lat'])
            nd.setdefault('origin_lon', sn['home_lon'])
        if st.get('pos_ts'):
            nd.setdefault('latitude', st['lat'])
            nd.setdefault('longitude', st['lon'])
            nd.setdefault('altitude', st['alt'])
            nd.setdefault('last_position_update', st['pos_ts'])
            o_lat, o_lon = nd.get('origin_lat'), nd.get('origin_lon')
            if o_lat is not None and st['lat'] is not None:
                dist = _haversine_m(o_lat, o_lon, st['lat'], st['lon'])
                if dist is not None:
                    nd.setdefault('distance_from_origin_m', dist)
                    nd.setdefault('moved_far', bool(
                        dist >= getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0)))
        if st.get('tel_ts'):
            nd.setdefault('voltage', st['voltage'])
            nd.setdefault('battery_pct', st['battery_pct'])
            # The API reads voltage via _get_node_voltage() from the telemetry
            # payload structure, so reconstruct it the way a real packet would
            if st['voltage'] is not None:
                vc = sn.get('voltage_channel', 'ch3_voltage')
                nd.setdefault('telemetry', {}).setdefault(
                    'power_metrics', {}).setdefault(vc, st['voltage'])
        seen = max(st.get('pos_ts') or 0, st.get('tel_ts') or 0)
        if seen:
            nd.setdefault('last_seen', seen)
        warmed += 1
    if warmed:
        logger.info(f'Warm-started last-known state for {warmed} special node(s)')


def _append_position_history(node_id, lat, lon, alt, json_data):
    """Append one accepted position to the in-memory trail and the durable store."""
    _ensure_history_struct(node_id)
    entry = {
        "ts": time.time(),
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "voltage": _get_node_voltage(node_id),
        "rssi": json_data.get("rx_rssi"),
        "snr": json_data.get("rx_snr"),
    }
    special_history[node_id].append(entry)
    _prune_history(node_id, now_ts=entry['ts'])

    try:
        topic = json_data.get('mqtt_topic')
        storage.record_position(
            node_id, entry['ts'], lat, lon, alt=alt, voltage=entry['voltage'],
            distance_from_home_m=nodes_data.get(node_id, {}).get('distance_from_origin_m'),
            packet_id=json_data.get('id'),
            gateway_id=_extract_gateway_node_id_from_topic(topic) if topic else None,
            rssi=entry['rssi'], snr=entry['snr'],
            simulated=bool(json_data.get('simulated')),
        )
    except Exception as db_err:
        logger.error(f'Failed to record position for {node_id}: {db_err}')


def _check_battery_alert(node_id, simulated=False):
    """Fire a low-battery alert if voltage drops below 3.5 V."""
    if not _is_special_node(node_id):
        return

    voltage = _get_node_voltage(node_id)
    if voltage is not None and voltage < 3.5:
        from . import alerts
        storage.record_alert_event('battery_low', node_id,
                                   details={'voltage': voltage},
                                   simulated=simulated)
        alerts.send_battery_alert(node_id, nodes_data[node_id])

# Track best packets by ID for deduplication
_packet_id_tracking = {}  # {node_id: {packet_id: {best_packet_info, stored_index}}}


def _build_packet_info(node_id, packet_type, json_data, current_time):
    """Build packet info dictionary with all relevant fields."""
    packet_info = {
        'timestamp': current_time,
        'packet_type': packet_type,
        'id': json_data.get('id'),
        'channel': json_data.get('channel'),
        'channel_name': json_data.get('channel_name', 'Unknown'),
        'portnum_name': json_data.get('portnum_name', 'Unknown'),
        'hop_start': json_data.get('hop_start'),
        'hop_limit': json_data.get('hop_limit'),
        'rx_rssi': json_data.get('rx_rssi'),
        'rx_snr': json_data.get('rx_snr'),
        'mqtt_topic': json_data.get('mqtt_topic')
    }
    
    # Extract detailed info based on packet type
    payload = json_data.get('decoded', {}).get('payload', {})
    
    if packet_type == 'NODEINFO_APP':
        packet_info.update({
            'role': payload.get('role'),
            'hw_model': payload.get('hw_model'),
            'long_name': _sanitize_display_text(payload.get('long_name')),
            'short_name': _sanitize_display_text(payload.get('short_name'))
        })
    elif packet_type == 'POSITION_APP':
        lat_i = payload.get('latitude_i')
        lon_i = payload.get('longitude_i')
        if lat_i and lon_i:
            packet_info.update({
                'lat': lat_i / 1e7,
                'lon': lon_i / 1e7,
                'altitude': payload.get('altitude')
            })
    elif packet_type == 'TELEMETRY_APP':
        device_metrics = payload.get('device_metrics', {})
        power_metrics = payload.get('power_metrics', {})
        packet_info.update({
            'battery_level': device_metrics.get('battery_level'),
            'voltage': device_metrics.get('voltage'),
            'channel_utilization': device_metrics.get('channel_utilization'),
            'air_util_tx': device_metrics.get('air_util_tx'),
            'power_voltage': power_metrics.get('ch3_voltage') or power_metrics.get('ch1_voltage'),
            'power_current': power_metrics.get('ch3_current')
        })
    elif packet_type == 'MAP_REPORT_APP':
        packet_info.update({
            'modem_preset': payload.get('modem_preset'),
            'region': payload.get('region'),
            'firmware_version': payload.get('firmware_version')
        })
    
    return packet_info

def _track_special_node_packet(node_id, packet_type, json_data):
    """Track all packets from special nodes with deduplication by packet ID.
    
    When same packet ID seen multiple times:
    - Prefer direct-hop (hop_start == hop_limit) over relayed packets
    - Among same hop type: keep packet with best SNR/RSSI signal quality
    - Store only the best copy, discarding duplicates with worse signal
    
    This preserves gateway detection from all mesh paths while keeping best signal data.
    """
    if not _is_special_node(node_id):
        return
    
    # Ensure tracking dicts exist for this node
    if node_id not in special_node_packets:
        special_node_packets[node_id] = []
    if node_id not in _packet_id_tracking:
        _packet_id_tracking[node_id] = {}
    
    # Get packet ID for deduplication
    packet_id = json_data.get('id')
    if not packet_id:
        logger.debug(f'Packet missing ID field, skipping dedup: {packet_type}')
        return
    
    # Log hop info for diagnostic purposes
    hop_start = json_data.get('hop_start')
    hop_limit = json_data.get('hop_limit')
    hops_traveled = (hop_start - hop_limit) if (hop_start is not None and hop_limit is not None) else None
    logger.info(f'📦 PACKET HOP INFO: {config.SPECIAL_NODES.get(node_id, node_id)} - {packet_type} - hop_start={hop_start}, hop_limit={hop_limit}, hops_traveled={hops_traveled}')
    
    current_time = time.time()
    new_signal_score = _get_signal_quality_score(json_data)
    
    # Check if we've seen this packet ID before
    if packet_id in _packet_id_tracking[node_id]:
        old_info = _packet_id_tracking[node_id][packet_id]
        old_index = old_info.get('stored_index')
        
        # Get old packet's signal score
        if old_index is not None and old_index < len(special_node_packets[node_id]):
            old_packet = special_node_packets[node_id][old_index]
            old_signal_data = {
                'hop_start': old_packet.get('hop_start'),
                'hop_limit': old_packet.get('hop_limit'),
                'rx_snr': old_packet.get('rx_snr'),
                'rx_rssi': old_packet.get('rx_rssi')
            }
            old_signal_score = _get_signal_quality_score(old_signal_data)
        else:
            old_signal_score = 0
        
        # Keep new packet only if it has better signal quality
        if new_signal_score > old_signal_score:
            logger.debug(f'Packet {packet_id}: Replacing old (score {old_signal_score}) with new (score {new_signal_score})')
            # Update the existing packet info in-place
            if old_index is not None and old_index < len(special_node_packets[node_id]):
                special_node_packets[node_id][old_index] = _build_packet_info(node_id, packet_type, json_data, current_time)
        else:
            logger.debug(f'Packet {packet_id}: Keeping old (score {old_signal_score}) over new (score {new_signal_score})')
            return  # Don't process further, keep old packet
    else:
        # New packet ID - add it
        logger.debug(f'Packet {packet_id}: New packet, adding (score {new_signal_score})')
        stored_index = len(special_node_packets[node_id])
        packet_info = _build_packet_info(node_id, packet_type, json_data, current_time)
        special_node_packets[node_id].append(packet_info)
        _packet_id_tracking[node_id][packet_id] = {'stored_index': stored_index, 'signal_score': new_signal_score}
    
    # Extract gateway info AFTER dedup, using the best-signal copy
    if _is_special_node(node_id):
        _extract_gateway_from_packet(node_id, json_data)
    
    # Log special node packet arrival
    logger.info(f'SPECIAL NODE PACKET: {config.SPECIAL_NODES.get(node_id, node_id)} - {packet_type} (ID: {packet_id}, score: {new_signal_score})')


# Note: All packet decryption and protobuf parsing is handled automatically
# by the meshtastic_mqtt_json library. The MQTT callbacks below receive
# pre-decoded packets with all fields already parsed.

def _ensure_history_struct(node_id):
    if node_id not in special_history:
        # unbounded deque; prune by time on append
        special_history[node_id] = deque()


def _prune_history(node_id, now_ts=None):
    """Prune old position history entries for a special node."""
    if node_id not in special_history:
        return
    if now_ts is None:
        now_ts = time.time()
    cutoff = now_ts - (config.SPECIAL_HISTORY_HOURS * 3600)
    dq = special_history[node_id]
    # pop from left while too old (oldest first)
    while dq and dq[0]['ts'] < cutoff:
        dq.popleft()


def _extract_node_name_from_payload(payload):
    """
    Extract node name from nodeinfo payload (handles various formats).

    Args:
        payload: Nodeinfo payload (dict or string)

    Returns:
        str: Extracted name or None
    """
    # dict-like payloads
    if isinstance(payload, dict):
        # Try common name fields first
        for k in ("longName", "longname", "long_name", "name", "deviceName", "displayName"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Search nested values for a likely name
        for v in payload.values():
            if isinstance(v, str) and len(v.strip()) > 1 and any(c.isalpha() for c in v):
                return v.strip()
        return None

    # string payloads: try JSON decode, fallback to simple parse
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            return _extract_node_name_from_payload(parsed)  # Recurse with parsed dict
        except Exception:
            # try common delimiter
            if ":" in payload:
                return payload.split(":", 1)[1].strip()
            return payload.strip()
    return None


def _extract_modem_preset(obj):
    """Try to extract a human-friendly modem preset name from diverse payload shapes.
    Returns a string like 'Medium Slow' or None if not found.
    """
    try:
        if isinstance(obj, dict):
            # Common keys that might carry preset
            for k in ("modemPreset", "modem_preset", "loraModemPreset", "preset"):
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            # Sometimes nested under configs
            for k in ("lora", "radio", "channel", "channelConfig", "deviceConfig", "moduleConfig"):
                sub = obj.get(k)
                if isinstance(sub, dict):
                    val = _extract_modem_preset(sub)
                    if val:
                        return val
        # Strings: look for human words
        if isinstance(obj, str):
            low = obj.lower()
            for name in ("medium slow", "medium fast", "long slow", "long fast", "long moderate", "short slow", "short fast"):
                if name in low:
                    # capitalize words
                    return " ".join(w.capitalize() for w in name.split())
    except Exception:
        pass
    return None


def _extract_channel_from_topic(node_id):
    """Extract channel name from stored topic path for this node.

    Found by pylint's duplicate-code check (2026-07-12): this used to
    re-parse the topic itself instead of calling _extract_channel_from_mqtt_topic
    (the topics.channel_from_topic import, already aliased just above and
    already in use one call site over) — same parsing logic, pasted a
    second time a few lines from the working alias.
    """
    if node_id not in node_topics:
        return "Unknown"
    return _extract_channel_from_mqtt_topic(node_topics[node_id])


def _initialize_special_node_home_position(node_id):
    """
    Initialize special node position from configured home location if not yet set.

    For special nodes without a GPS fix yet, this sets their initial position
    to their configured home coordinates.

    Args:
        node_id: Special node ID to initialize
    """
    if "latitude" not in nodes_data[node_id] or nodes_data[node_id].get("latitude") is None:
        special_node_config = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
        home_lat = special_node_config.get('home_lat')
        home_lon = special_node_config.get('home_lon')
        if home_lat is not None and home_lon is not None:
            nodes_data[node_id]["latitude"] = home_lat
            nodes_data[node_id]["longitude"] = home_lon
            nodes_data[node_id]["origin_lat"] = home_lat
            nodes_data[node_id]["origin_lon"] = home_lon
            logger.debug(f'Initialized {node_id} position from home: {home_lat:.4f}, {home_lon:.4f}')


def _store_node_names(node_id, payload, extracted_name):
    """
    Store node name information (long_name, short_name, hw_model) in nodes_data.

    Args:
        node_id: Node ID to update
        payload: Decoded payload (dict or other)
        extracted_name: Name extracted from payload using _extract_node_name_from_payload()
    """
    short = None
    if extracted_name:
        # produce a short name if not explicit
        if " " in extracted_name:
            short = extracted_name.split()[0]
        else:
            short = extracted_name[:8]

    # Safely extract fields from payload (might be dict or string)
    if isinstance(payload, dict):
        nodes_data[node_id]["long_name"] = _sanitize_display_text(extracted_name or payload.get("long_name") or "Unknown")
        nodes_data[node_id]["short_name"] = _sanitize_display_text(short or payload.get("short_name") or "?")
        nodes_data[node_id]["hw_model"] = payload.get("hw_model") or "Unknown"
    else:
        nodes_data[node_id]["long_name"] = _sanitize_display_text(extracted_name or "Unknown")
        nodes_data[node_id]["short_name"] = _sanitize_display_text(short or "?")
        nodes_data[node_id]["hw_model"] = "Unknown"


def on_nodeinfo(json_data):
    """Process node info messages - update node names."""
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()
    
    try:
        logger.debug(f'on_nodeinfo callback fired - processing message')
        node_id = json_data.get("from")
        channel = json_data.get("channel")
        payload = json_data["decoded"]["payload"]

        # Extract channel name once
        channel_name = _extract_channel_from_topic(node_id) if node_id else "Unknown"
        if channel_name == "Unknown":
            channel_name = json_data.get("channel_name", "Unknown")

        # Check if special node once
        is_special = _is_special_node(node_id) if node_id else False

        # IMPORTANT: Track and save packet IMMEDIATELY, before any processing that might fail
        # This ensures we never lose packet data due to processing errors
        if is_special:
            special_node_last_packet[node_id] = time.time()
            # Update channel name if different
            if special_node_channels.get(node_id) != channel_name:
                special_node_channels[node_id] = channel_name
            # Track packet FIRST, before any other processing
            _track_special_node_packet(node_id, 'NODEINFO_APP', json_data)
        
        role = payload.get("role") if isinstance(payload, dict) else None
        
        if node_id:
            if node_id not in nodes_data:
                nodes_data[node_id] = {}
            
            if channel is not None:
                nodes_data[node_id]["channel"] = channel
            if role:
                nodes_data[node_id]["role"] = role
            
            # For special nodes: initialize position from home if not yet set
            if is_special:
                _initialize_special_node_home_position(node_id)
            
            # Store channel name from topic
            nodes_data[node_id]["channel_name"] = channel_name
            
            # Try to capture modem preset if present (though unlikely to be in packets)
            preset = _extract_modem_preset(payload)
            if preset:
                nodes_data[node_id]["modem_preset"] = preset
            
            # Extract and store node name information
            name = _extract_node_name_from_payload(payload)
            _store_node_names(node_id, payload, name)
            nodes_data[node_id]["last_seen"] = time.time()
            
            # Best RSSI/SNR within a rolling window — same helper on_position uses.
            _update_best_signal(node_id, json_data)
            
            logger.info(f'Updated nodeinfo for {node_id}: {nodes_data[node_id]["long_name"]}')

            # If this node is a gateway, update its name in all gateway connections and cache
            updated_name = nodes_data[node_id].get("long_name")
            _update_gateway_names_in_connections(node_id, updated_name)

            # Also update gateway info cache if this is a gateway
            if node_is_gateway.get(node_id, False) and node_id in gateway_info_cache:
                gateway_info_cache[node_id]["name"] = updated_name

    except Exception as e:
        logger.error(f'❌ Error processing nodeinfo: {e}', exc_info=True)


def _process_special_movement(node_id, payload, json_data):
    """Movement pipeline for one special-node position copy: resolve origin
    (config home, else first fix), compute distance-from-home, run the
    homecoming auto-unmute counter, and submit the copy to the buffered
    consensus alert (movement.py decides at window close)."""
    try:
        lat = payload["latitude_i"] / 1e7
        lon = payload["longitude_i"] / 1e7

        special_node_config = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
        home_lat = special_node_config.get('home_lat')
        home_lon = special_node_config.get('home_lon')
        if home_lat is not None and home_lon is not None:
            nodes_data[node_id]["origin_lat"] = home_lat
            nodes_data[node_id]["origin_lon"] = home_lon
        elif nodes_data[node_id].get("origin_lat") is None:
            nodes_data[node_id]["origin_lat"] = lat
            nodes_data[node_id]["origin_lon"] = lon

        o_lat = nodes_data[node_id].get("origin_lat")
        o_lon = nodes_data[node_id].get("origin_lon")
        if o_lat is None or o_lon is None:
            return
        dist = _haversine_m(o_lat, o_lon, lat, lon)
        nodes_data[node_id]["distance_from_origin_m"] = dist
        threshold_m = getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0)
        moved_far = bool(dist is not None and dist >= threshold_m)

        try:
            _update_homecoming(node_id, json_data.get('id'), moved_far)
        except Exception as hc_err:
            logger.error(f'Homecoming check failed for {node_id}: {hc_err}')

        # Buffered, not immediate: every copy (far or close) joins the open
        # buffer so close copies vote against a mutated far outlier.
        if moved_far or node_id in _pending_movement_alerts:
            try:
                _add_copy_to_alert_buffer(
                    node_id, json_data, payload, dist,
                    lat, lon, o_lat, o_lon, threshold_m, moved_far
                )
            except Exception as buf_err:
                logger.error(f'Failed to buffer movement copy for {node_id}: {buf_err}')

        nodes_data[node_id]["moved_far"] = moved_far
    except Exception as e:
        logger.debug(f"Error processing movement alerts for {node_id}: {e}")


def _update_node_position(node_id, payload):
    """Write the decoded coordinates and freshness timestamps. Returns (lat, lon, alt)."""
    lat = payload["latitude_i"] / 1e7
    lon = payload["longitude_i"] / 1e7
    alt = payload.get("altitude", 0)
    nodes_data[node_id]["latitude"] = lat
    nodes_data[node_id]["longitude"] = lon
    nodes_data[node_id]["altitude"] = alt
    nodes_data[node_id]["last_seen"] = time.time()
    nodes_data[node_id]["last_position_update"] = time.time()
    return lat, lon, alt


def _update_best_signal(node_id, json_data):
    """Keep the best RSSI/SNR seen in a rolling 1-hour window (gateway copies
    arrive with varying signal; last-received would be arbitrary). Used
    internally by gateway scoring; not displayed since v2.0."""
    _SIGNAL_WINDOW = 3600
    now_sig = time.time()
    for field, ts_field in (("rx_rssi", "rx_rssi_ts"), ("rx_snr", "rx_snr_ts")):
        new_val = json_data.get(field)
        if new_val is None:
            continue
        prev = nodes_data[node_id].get(field)
        prev_age = now_sig - nodes_data[node_id].get(ts_field, 0)
        if prev is None or prev_age > _SIGNAL_WINDOW or new_val > prev:
            nodes_data[node_id][field] = new_val
            nodes_data[node_id][ts_field] = now_sig


def _sync_gateway_position(node_id, lat, lon):
    """When a gateway reports its own position, refresh it in every special
    node's connection record and in the gateway info cache."""
    if not node_is_gateway.get(node_id, False):
        return
    for special_id, gw_dict in special_node_gateways.items():
        if node_id in gw_dict:
            gw_dict[node_id]["lat"] = lat
            gw_dict[node_id]["lon"] = lon
            gw_dict[node_id]["last_seen"] = time.time()
    if node_id in gateway_info_cache:
        gateway_info_cache[node_id]["lat"] = lat
        gateway_info_cache[node_id]["lon"] = lon


def _record_special_position(node_id, lat, lon, alt, json_data):
    """One history entry + one DB row per broadcast (lean storage)."""
    pid = json_data.get('id')
    if _is_new_broadcast(node_id, pid):
        _append_position_history(node_id, lat, lon, alt, json_data)
        logger.debug(f'Added new position to history for {node_id} (packet {pid})')
    else:
        logger.debug(f'Skipped gateway copy of position broadcast {pid} for {node_id}')


def on_position(json_data):
    """Process a position packet: validate, track, run the movement pipeline,
    update state, and record history. Orchestration only — each step lives in
    its own helper."""
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()

    # Close any pending alert buffers whose window has elapsed.
    try:
        _check_expired_alert_buffers()
    except Exception as e:
        logger.debug(f'_check_expired_alert_buffers failed: {e}')

    try:
        node_id = json_data.get("from")
        channel = json_data.get("channel")
        payload = json_data["decoded"]["payload"]

        # Reject corrupted / relay-quantized packets before any processing
        if not _validate_position_precision(payload, node_id=node_id):
            logger.info(f'Skipped position packet for node {node_id} due to insufficient precision')
            return

        channel_name = _extract_channel_from_topic(node_id) if node_id else "Unknown"
        if channel_name == "Unknown":
            channel_name = json_data.get("channel_name", "Unknown")

        is_special = _is_special_node(node_id) if node_id else False

        # Track the packet FIRST so it is never lost to a later processing error
        if is_special:
            special_node_last_packet[node_id] = time.time()
            if special_node_channels.get(node_id) != channel_name:
                special_node_channels[node_id] = channel_name
            _track_special_node_packet(node_id, 'POSITION_APP', json_data)

        if node_id and "latitude_i" in payload and "longitude_i" in payload:
            if node_id not in nodes_data:
                nodes_data[node_id] = {}
            if channel is not None:
                nodes_data[node_id]["channel"] = channel
            nodes_data[node_id]["channel_name"] = channel_name

            if is_special:
                _process_special_movement(node_id, payload, json_data)

            lat, lon, alt = _update_node_position(node_id, payload)
            _update_best_signal(node_id, json_data)
            _sync_gateway_position(node_id, lat, lon)

            if is_special:
                _record_special_position(node_id, lat, lon, alt, json_data)

            logger.info(f'Updated position for {node_id}: {lat:.4f}, {lon:.4f}')
    except Exception as e:
        logger.error(f'❌ Error processing position: {e}', exc_info=True)


def _extract_battery_and_voltage_from_telemetry(node_id, payload):
    """
    Extract voltage and battery percentage from a just-merged telemetry payload.

    Voltage always comes from _get_node_voltage() — the one place that knows
    which channel a node uses — rather than re-deriving channel selection
    here. (A prior version read payload["power_metrics"] directly for every
    special node regardless of its configured voltage_channel, and silently
    disagreed with _get_node_voltage() for any special node configured with
    voltage_channel="device_voltage".) This runs after _merge_telemetry_payload
    in on_telemetry, so nodes_data[node_id]["telemetry"] already reflects
    this packet. Battery percentage is always derived from voltage via
    _estimate_battery_from_voltage when voltage is available, so the card
    and the chart can never disagree.

    Returns:
        tuple: (battery_pct, voltage)
            - battery_pct: int 0-100 or None
            - voltage: float or None
    """
    voltage = None
    battery_pct = None

    try:
        voltage = _get_node_voltage(node_id)

        if voltage is not None and isinstance(voltage, (int, float)):
            voltage = float(voltage)
            battery_pct = _estimate_battery_from_voltage(voltage)
        else:
            voltage = None
            # No voltage at all: regular (non-special) nodes may still report
            # a raw device battery_level percentage directly.
            if not _is_special_node(node_id) and isinstance(payload, dict):
                device_metrics = payload.get("device_metrics", {})
                if isinstance(device_metrics, dict):
                    battery_pct = device_metrics.get("battery_level")

        if isinstance(battery_pct, str) and battery_pct.isdigit():
            battery_pct = int(battery_pct)
        if isinstance(battery_pct, (float, int)):
            battery_pct = max(0, min(100, int(battery_pct)))
        else:
            battery_pct = None

    except Exception as e:
        logger.debug(f"Error extracting battery/voltage for {node_id}: {e}")
        return (None, None)

    return (battery_pct, voltage)


def _merge_telemetry_payload(node_id, payload):
    """
    Merge telemetry payload into node's stored telemetry data.

    Power sensor nodes send device_metrics and power_metrics in separate packets,
    so we merge them instead of overwriting to preserve all data.

    Args:
        node_id: Node ID to update telemetry for
        payload: Telemetry payload dictionary to merge
    """
    if "telemetry" not in nodes_data[node_id]:
        nodes_data[node_id]["telemetry"] = {}

    # Update timestamp
    if "time" in payload:
        nodes_data[node_id]["telemetry"]["time"] = payload["time"]

    # Merge device_metrics if present
    if "device_metrics" in payload:
        if "device_metrics" not in nodes_data[node_id]["telemetry"]:
            nodes_data[node_id]["telemetry"]["device_metrics"] = {}
        nodes_data[node_id]["telemetry"]["device_metrics"].update(payload["device_metrics"])

    # Merge power_metrics if present (preserve across packets)
    if "power_metrics" in payload:
        if "power_metrics" not in nodes_data[node_id]["telemetry"]:
            nodes_data[node_id]["telemetry"]["power_metrics"] = {}
        nodes_data[node_id]["telemetry"]["power_metrics"].update(payload["power_metrics"])


def on_telemetry(json_data):
    """Process telemetry messages - battery level, etc."""
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()

    try:
        node_id = json_data.get("from")
        payload = json_data["decoded"]["payload"]

        # Extract channel name ONCE (used throughout)
        channel_name = _extract_channel_from_topic(node_id) if node_id else "Unknown"
        if channel_name == "Unknown":
            channel_name = json_data.get("channel_name", "Unknown")

        # Check if special node ONCE (used throughout)
        is_special = _is_special_node(node_id) if node_id else False

        # IMPORTANT: Track and save packet IMMEDIATELY for special nodes, before any processing that might fail
        # This ensures we never lose packet data due to processing errors
        if node_id and is_special:
            special_node_last_packet[node_id] = time.time()
            # Update channel name if different
            if special_node_channels.get(node_id) != channel_name:
                special_node_channels[node_id] = channel_name
            # Track packet FIRST, before any other processing
            _track_special_node_packet(node_id, 'TELEMETRY_APP', json_data)

        # NOW do the rest of the processing (which might have errors)
        if node_id:
            if node_id not in nodes_data:
                nodes_data[node_id] = {}
            
            # Store channel name from topic
            nodes_data[node_id]["channel_name"] = channel_name

            # Merge telemetry payload (preserves power_metrics across multiple packets)
            _merge_telemetry_payload(node_id, payload)

            nodes_data[node_id]["last_seen"] = time.time()

            battery_pct, voltage = _extract_battery_and_voltage_from_telemetry(node_id, payload)
            nodes_data[node_id]["battery_pct"] = battery_pct
            nodes_data[node_id]["voltage"] = voltage

            logger.info(f'Updated telemetry for {node_id}: voltage={voltage}V, battery_pct={battery_pct}%')

            if (_is_special_node(node_id)
                    and (voltage is not None or battery_pct is not None)
                    and _is_new_broadcast(node_id, json_data.get('id'))):
                try:
                    storage.record_telemetry(
                        node_id, time.time(), voltage=voltage, battery_pct=battery_pct,
                        rssi=json_data.get('rx_rssi'), snr=json_data.get('rx_snr'),
                        simulated=bool(json_data.get('simulated')),
                    )
                except Exception as db_err:
                    logger.error(f'Failed to record telemetry for {node_id}: {db_err}')
            
            # Best RSSI/SNR within a rolling window — same helper on_position uses.
            _update_best_signal(node_id, json_data)

            # Add telemetry to special node history (if applicable)
            _add_telemetry_to_history(node_id, json_data)

            # Check for low battery alert
            _check_battery_alert(node_id, simulated=bool(json_data.get('simulated')))

    except Exception as e:
        logger.error(f'❌ Error processing telemetry: {e}', exc_info=True)


def on_neighborinfo(json_data):
    """Process neighbor info messages."""
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()
    
    try:
        payload = json_data["decoded"]["payload"]
        logger.debug(f'Received neighborinfo: {payload}')
    except Exception as e:
        logger.error(f'Error processing neighborinfo: {e}')


def on_mapreport(json_data):
    """
    Process MAP_REPORT_APP messages (portnum 73).
    These packets contain modem_preset, region, firmware_version, and other metadata.
    This is the PRIMARY source of modem preset information!
    """
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()

    try:
        payload = json_data["decoded"]["payload"]
        node_id = json_data.get("from")
        # Try to get channel_name from our extracted topic mapping first
        channel_name = _extract_channel_from_topic(node_id) if node_id else "Unknown"
        # Fallback to what the library provides (usually "Unknown")
        if channel_name == "Unknown":
            channel_name = json_data.get("channel_name", "Unknown")
        
        # Track special node packets and channel info
        if node_id:
            if _is_special_node(node_id):
                special_node_last_packet[node_id] = time.time()
                # Update channel name if different
                if special_node_channels.get(node_id) != channel_name:
                    special_node_channels[node_id] = channel_name
                # Track packet (only for special nodes)
                _track_special_node_packet(node_id, 'MAP_REPORT_APP', json_data)
        
        if node_id and isinstance(payload, dict):
            if node_id not in nodes_data:
                nodes_data[node_id] = {}
            
            nodes_data[node_id]["last_seen"] = time.time()
            
            # Extract modem preset - THIS IS WHAT WE NEED!
            # Reference values from Meshtastic protobufs:
            # LONG_FAST = 0, LONG_SLOW = 1, VERY_LONG_SLOW = 2,
            # MEDIUM_SLOW = 3, MEDIUM_FAST = 4, SHORT_SLOW = 5,
            # SHORT_FAST = 6, LONG_MODERATE = 7, SHORT_TURBO = 8
            modem_preset_value = payload.get("modemPreset") or payload.get("modem_preset")
            if modem_preset_value is not None:
                # Map numeric values to human-readable names
                preset_names = {
                    0: "LongFast",
                    1: "LongSlow",
                    2: "VeryLongSlow",
                    3: "MediumSlow",
                    4: "MediumFast",
                    5: "ShortSlow",
                    6: "ShortFast",
                    7: "LongModerate",
                    8: "ShortTurbo"
                }
                if isinstance(modem_preset_value, int):
                    channel_name = preset_names.get(modem_preset_value, f"Preset{modem_preset_value}")
                else:
                    channel_name = str(modem_preset_value)
                
                nodes_data[node_id]["channel_name"] = channel_name
                nodes_data[node_id]["modem_preset"] = channel_name
                logger.info(f'Updated modem preset for {node_id}: {channel_name}')
            
            # Also extract other useful info from MAP_REPORT
            if "longName" in payload or "long_name" in payload:
                nodes_data[node_id]["long_name"] = _sanitize_display_text(payload.get("longName") or payload.get("long_name"))
            if "shortName" in payload or "short_name" in payload:
                nodes_data[node_id]["short_name"] = _sanitize_display_text(payload.get("shortName") or payload.get("short_name"))
            if "hwModel" in payload or "hw_model" in payload:
                nodes_data[node_id]["hw_model"] = payload.get("hwModel") or payload.get("hw_model")
            if "firmwareVersion" in payload or "firmware_version" in payload:
                nodes_data[node_id]["firmware_version"] = payload.get("firmwareVersion") or payload.get("firmware_version")
            if "region" in payload:
                nodes_data[node_id]["region"] = payload.get("region")
            if "hasDefaultChannel" in payload or "has_default_channel" in payload:
                nodes_data[node_id]["has_default_channel"] = payload.get("hasDefaultChannel") or payload.get("has_default_channel")
            
            logger.info(f'Processed MAP_REPORT for {node_id}')
            
    except Exception as e:
        logger.error(f'Error processing mapreport: {e}')


def _decrypt_message_packet(mp, key_bytes):
    """
    Decrypt an encrypted Meshtastic message packet.
    Uses AES-CTR with nonce derived from packet ID and sender ID.
    """
    try:
        # Extract the nonce from the packet
        nonce_packet_id = getattr(mp, 'id').to_bytes(8, 'little')
        nonce_from_node = getattr(mp, 'from').to_bytes(8, 'little')
        nonce = nonce_packet_id + nonce_from_node

        # Decrypt the message
        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(mp, 'encrypted')) + decryptor.finalize()
        
        # Parse the decrypted message
        data = mesh_pb2.Data()
        try:
            data.ParseFromString(decrypted_bytes)
        except:
            return None

        mp.decoded.CopyFrom(data)
        return mp

    except Exception as e:
        logger.debug(f'Error decrypting message: {e}')
        return None


def _protobuf_to_json(proto_obj):
    """
    Convert a protobuf message to JSON-serializable dict.
    Handles NaN values by removing them.
    """
    try:
        json_str = MessageToJson(proto_obj, preserving_proto_field_name=True)
        data = json.loads(json_str)
        
        # Remove empty values and NaN
        def clean_dict(d):
            if isinstance(d, dict):
                return {k: clean_dict(v) for k, v in d.items() 
                       if str(v) not in ('None', 'nan', '', 'null', 'NaN')}
            elif isinstance(d, list):
                return [clean_dict(v) for v in d 
                       if str(v) not in ('None', 'nan', '', 'null', 'NaN')]
            return d
        
        return clean_dict(data)
    except Exception as e:
        logger.debug(f"Error converting protobuf to JSON: {e}")
        return {}


def _on_mqtt_subscribe(client_obj, userdata, mid, reason_code_list, properties):
    """
    MQTT subscribe callback - called when broker confirms subscription.
    Logs the confirmation to verify subscriptions were accepted.
    """
    logger.info(f"[MQTT] Broker confirmed subscription (mid={mid}, count={len(reason_code_list)})")
    for i, reason_code in enumerate(reason_code_list):
        if reason_code >= 128:
            logger.error(f"[MQTT] Subscription #{i+1} FAILED with reason code: {reason_code}")
        else:
            logger.info(f"[MQTT] Subscription #{i+1} accepted with QoS: {reason_code}")


def _on_mqtt_connect(client_obj, userdata, flags, reason_code, properties):
    """
    MQTT connect callback - called when connection is established.
    Subscribe to topics after successful connection.
    """
    global message_received, last_message_time, mqtt_was_connected

    if reason_code == 0:
        # Detect if this is a reconnection
        if mqtt_was_connected:
            logger.warning('🔄 RECONNECTED to MQTT broker (connection was restored)')
        else:
            logger.info('✅ Connected to MQTT broker')
            mqtt_was_connected = True

        # Subscribe to all nodes on the channel
        # NOTE: We always subscribe to the wildcard regardless of show_gateways setting
        # because special nodes transmit via LoRa and are forwarded by gateways to MQTT.
        # The MQTT topic is the gateway's node ID, not the special node's ID.
        # Filtering happens in the app based on the packet payload's 'from' field.
        base_topic = config.MQTT_ROOT_TOPIC.rstrip('/') + '/' + config.MQTT_CHANNEL_NAME
        subscribe_topic = base_topic + '/#'
        result, mid = client_obj.subscribe(subscribe_topic, qos=0)
        logger.info(f"✅ Subscribed to: {subscribe_topic} (result={result}, mid={mid})")

        # Mark as connected
        message_received = True
        last_message_time = time.time()
    else:
        logger.error(f'❌ Connection failed with code: {reason_code}')


def _on_mqtt_disconnect(client_obj, userdata, disconnect_flags, reason_code, properties):
    """
    MQTT disconnect callback - called when broker connection is lost.
    Paho-mqtt will automatically reconnect via loop_start().
    We just log the disconnection for monitoring.
    """
    global last_packet_time
    logger.warning(f'⚠️ [MQTT] DISCONNECTED from broker: {reason_code} ({disconnect_flags})')

    # Reset packet tracking on disconnect
    last_packet_time = 0

    # Paho-mqtt's loop_start() will automatically attempt reconnection
    logger.warning('[MQTT] Attempting automatic reconnection... (watch for RECONNECTED message)')


def _on_mqtt_message(client_obj, userdata, msg):
    """
    Main paho-mqtt message callback.
    Receives raw encoded MQTT messages, decodes them, and routes to handlers.
    """
    global message_received, last_message_time, packets_received, last_packet_time

    logger.info(f'[MQTT] _on_mqtt_message CALLED: topic={msg.topic}')
    logger.debug(f'[DEBUG] Message details: topic={msg.topic}, payload_size={len(msg.payload)} bytes, qos={msg.qos}, retain={msg.retain}')

    # Check if this is a special node
    for node_id in config.SPECIAL_NODE_IDS:
        node_hex = f"!{node_id:08x}"
        if node_hex in msg.topic:
            node_label = config.SPECIAL_NODES.get(node_id, {}).get('label', node_hex)
            logger.info(f'[DEBUG] ⭐ SPECIAL NODE MESSAGE: {node_label} ({node_hex}) on topic {msg.topic}')
            break

    try:
        # Mark that we received a packet (update timestamp for staleness detection)
        last_packet_time = time.time()
        
        # Extract channel from MQTT topic path
        channel_name = _extract_channel_from_mqtt_topic(msg.topic)
        
        # Parse MQTT ServiceEnvelope protobuf
        service_envelope = mqtt_pb2.ServiceEnvelope()
        try:
            service_envelope.ParseFromString(msg.payload)
        except Exception as e:
            logger.debug(f"Error parsing ServiceEnvelope: {e}")
            return
        
        # Extract MeshPacket from envelope
        mp = service_envelope.packet
        
        # Handle encrypted packets
        if mp.HasField('encrypted'):
            mp = _decrypt_message_packet(mp, userdata['key_bytes'])
            if not mp:
                return
        
        # Extract portnum (message type) and get name
        portnum = mp.decoded.portnum
        try:
            portnum_name = portnums_pb2.PortNum.Name(portnum)
        except ValueError:
            # Handle unknown portnum values gracefully (e.g., new types not in our proto definitions)
            portnum_name = f"UNKNOWN_PORTNUM_{portnum}"
            logger.debug(f"Received packet with unknown PortNum value: {portnum}")
        
        # Convert to JSON for callbacks (preserving meshtastic_mqtt_json format)
        json_packet = _protobuf_to_json(mp)
        
        # Add channel name, topic, and from/to info
        json_packet['channel_name'] = channel_name
        json_packet['mqtt_topic'] = msg.topic  # Store the MQTT topic for gateway extraction
        if 'from' not in json_packet:
            json_packet['from'] = getattr(mp, 'from')
        if 'to' not in json_packet:
            json_packet['to'] = getattr(mp, 'to')
        if 'channel' not in json_packet:
            json_packet['channel'] = mp.channel
        
        # Extract signal quality metrics from MeshPacket
        if hasattr(mp, 'rx_rssi') and mp.rx_rssi != 0:
            json_packet['rx_rssi'] = mp.rx_rssi
        if hasattr(mp, 'rx_snr') and mp.rx_snr != 0:
            json_packet['rx_snr'] = mp.rx_snr

        # Mark as received
        message_received = True
        packets_received = True
        last_message_time = time.time()
        
        # Route to appropriate handler based on message type
        _route_message_to_handler(portnum, portnum_name, mp, json_packet)
        
    except Exception as e:
        logger.error(f"Error in MQTT message handler: {e}", exc_info=True)


def _route_message_to_handler(portnum, portnum_name, mp, json_packet):
    """
    Route decoded message to appropriate handler based on message type.
    Decodes payload based on app type, then calls the corresponding handler.
    """
    try:
        # Log all incoming packets to see what we're receiving
        from_id = json_packet.get('from')
        logger.info(f'MSG: portnum={portnum} ({portnum_name}), from={from_id}')
        
        # Ensure decoded payload structure
        if 'decoded' not in json_packet:
            json_packet['decoded'] = {}
        if 'payload' not in json_packet['decoded']:
            json_packet['decoded']['payload'] = {}
        
        # Decode payload based on message type
        try:
            if portnum == portnums_pb2.ADMIN_APP:
                data = mesh_pb2.Admin()
                data.ParseFromString(mp.decoded.payload)
                json_packet['decoded']['payload'] = _protobuf_to_json(data)
            
            elif portnum == portnums_pb2.POSITION_APP:
                logger.debug(f'📍 POSITION packet from {from_id}')
                data = mesh_pb2.Position()
                data.ParseFromString(mp.decoded.payload)
                json_packet['decoded']['payload'] = _protobuf_to_json(data)
                from_id = json_packet.get('from')
                try:
                    on_position(json_packet)
                    logger.debug(f'✅ Successfully processed POSITION from {from_id}')
                except Exception as pos_err:
                    logger.error(f'❌ Error processing POSITION from {from_id}: {pos_err}', exc_info=True)
                return
            
            elif portnum == portnums_pb2.NODEINFO_APP:
                logger.debug(f'ℹ️ NODEINFO packet from {from_id}')
                data = mesh_pb2.User()
                data.ParseFromString(mp.decoded.payload)
                json_packet['decoded']['payload'] = _protobuf_to_json(data)
                try:
                    on_nodeinfo(json_packet)
                    logger.debug(f'✅ Successfully processed NODEINFO from {from_id}')
                except Exception as node_err:
                    logger.error(f'❌ Error processing NODEINFO from {from_id}: {node_err}', exc_info=True)
                return
            
            elif portnum == portnums_pb2.TELEMETRY_APP:
                logger.debug(f'🔋 TELEMETRY packet from {from_id}')
                data = telemetry_pb2.Telemetry()
                data.ParseFromString(mp.decoded.payload)
                json_packet['decoded']['payload'] = _protobuf_to_json(data)
                try:
                    on_telemetry(json_packet)
                    logger.debug(f'✅ Successfully processed TELEMETRY from {from_id}')
                except Exception as tel_err:
                    logger.error(f'❌ Error processing TELEMETRY from {from_id}: {tel_err}', exc_info=True)
                return
            
            elif portnum == portnums_pb2.MAP_REPORT_APP:
                data = mesh_pb2.MapReport()
                data.ParseFromString(mp.decoded.payload)
                json_packet['decoded']['payload'] = _protobuf_to_json(data)
                on_mapreport(json_packet)
                return
            
            elif portnum == portnums_pb2.NEIGHBORINFO_APP:
                data = mesh_pb2.NeighborInfo()
                data.ParseFromString(mp.decoded.payload)
                json_packet['decoded']['payload'] = _protobuf_to_json(data)
                on_neighborinfo(json_packet)
                return
            
        except Exception as e:
            logger.debug(f"Error decoding payload for {portnum_name}: {e}")
    
    except Exception as e:
        logger.error(f"Error routing message {portnum_name}: {e}", exc_info=True)


def connect_mqtt():
    """
    Connect to MQTT broker using paho-mqtt with automatic reconnection.
    Subscribes to specific channel to receive packets only from that channel.
    Paho-mqtt handles reconnection automatically via loop_start().
    """
    global client, message_received, last_message_time

    # Don't create multiple connections
    if client is not None:
        logger.debug('MQTT client already exists, skipping connection')
        return True

    try:
        logger.info(f'Connecting to MQTT broker: {config.MQTT_BROKER}:{config.MQTT_PORT}')
        logger.info(f'Channel: {config.MQTT_CHANNEL_NAME}')

        # Create paho-mqtt client with automatic reconnection enabled
        client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            client_id='',
            clean_session=True,
            userdata=None
        )
        client.connect_timeout = 10

        # Set credentials if provided
        if config.MQTT_USERNAME:
            client.username_pw_set(
                username=config.MQTT_USERNAME,
                password=config.MQTT_PASSWORD
            )

        # Prepare encryption key
        key_str = getattr(config, 'MQTT_KEY', 'AQ==')
        if key_str == 'AQ==':
            key_str = '1PG7OiApB1nwvP+rz05pAQ=='

        # Decode and pad base64 key
        padded_key = key_str.ljust(len(key_str) + ((4 - (len(key_str) % 4)) % 4), '=')
        replaced_key = padded_key.replace('-', '+').replace('_', '/')
        try:
            key_bytes = base64.b64decode(replaced_key.encode('ascii'))
        except Exception as e:
            logger.error(f"Error decoding encryption key: {e}")
            client = None
            return False

        # Set callbacks and userdata
        client.on_message = _on_mqtt_message
        client.on_disconnect = _on_mqtt_disconnect
        client.on_connect = _on_mqtt_connect
        client.on_subscribe = _on_mqtt_subscribe
        client.user_data_set({'key_bytes': key_bytes})

        # Connect to broker (non-blocking, handled by loop_start)
        try:
            client.connect(config.MQTT_BROKER, config.MQTT_PORT, 60)
            logger.info('✅ Initiating connection to MQTT broker')
        except Exception as e:
            logger.error(f"Failed to initiate connection: {e}")
            client = None
            return False

        # Start the background network loop - handles reconnection automatically
        # This runs in its own thread and manages connection state
        client.loop_start()
        logger.info('✅ MQTT network loop started (automatic reconnection enabled)')

        # Mark that we attempted connection
        message_received = False  # Will be set to True on first message
        last_message_time = time.time()

        logger.info('✅ MQTT client ready - waiting for connection confirmation')

        # Pre-populate special nodes with home positions so they appear on map at startup
        _initialize_special_nodes_at_startup()

        return True

    except Exception as e:
        logger.error(f'Failed to setup MQTT client: {e}', exc_info=True)
        if client:
            try:
                client.loop_stop()
            except:
                pass
        client = None
        return False


def _initialize_special_nodes_at_startup():
    """
    Pre-populate nodes_data with special nodes from config.
    This allows special nodes to appear on the map before any packets are received.
    Nodes without home positions will be initialized with None lat/lon (no marker until first packet).
    """
    global nodes_data

    for node_id in getattr(config, 'SPECIAL_NODE_IDS', []):
        special_info = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
        home_lat = special_info.get('home_lat')
        home_lon = special_info.get('home_lon')
        label = special_info.get('label')

        # Don't overwrite if node already exists (from previous run or early packet)
        if node_id not in nodes_data:
            nodes_data[node_id] = {
                "node_id": node_id,
                "long_name": label or f"Node {node_id}",
                "short_name": label[:4] if label else f"{node_id}",
                "latitude": home_lat,  # Can be None
                "longitude": home_lon,  # Can be None
                "origin_lat": home_lat,  # Can be None - will be set on first position packet
                "origin_lon": home_lon,  # Can be None - will be set on first position packet
                "altitude": None,
                "battery_level": None,
                "voltage": None,
                "channel_utilization": None,
                "air_util_tx": None,
                "last_seen": 0,  # Never seen yet - will show as very stale
                "hw_model": None,
                "distance_from_origin_m": 0,
                "moved_far": False,
            }
            if home_lat is not None and home_lon is not None:
                logger.info(f"Initialized special node {node_id} ({label}) at home position: {home_lat:.4f}, {home_lon:.4f}")
            else:
                logger.info(f"Initialized special node {node_id} ({label}) without home position (will use first packet location)")


def disconnect_mqtt():
    """Disconnect from MQTT broker."""
    global client
    try:
        if client:
            client.loop_stop()
            client.disconnect()
            logger.info("Disconnected from MQTT broker")
    except Exception as e:
        logger.error(f'Error disconnecting from MQTT broker: {e}')
    finally:
        client = None


def reload_mqtt_subscriptions():
    """
    Reload MQTT subscriptions based on current config settings.
    Unsubscribes from all current topics and resubscribes based on show_all_nodes and show_gateways.
    This allows dynamic switching between all-nodes and special-nodes-only modes.
    """
    global client

    if not client:
        logger.warning("Cannot reload subscriptions: MQTT client not connected")
        return False

    try:
        # Use current in-memory config values (already updated by the endpoint)
        logger.info(f"Reloading MQTT subscriptions (show_all_nodes={config.SHOW_ALL_NODES}, show_gateways={config.SHOW_GATEWAYS})")

        # Unsubscribe from all current topics
        base_topic = config.MQTT_ROOT_TOPIC.rstrip('/') + '/' + config.MQTT_CHANNEL_NAME

        # Unsubscribe from wildcard (in case we were subscribed to all)
        try:
            client.unsubscribe(base_topic + '/#')
            logger.info(f"Unsubscribed from: {base_topic}/#")
        except Exception as e:
            logger.debug(f"Could not unsubscribe from wildcard: {e}")

        # Always subscribe to the channel wildcard
        # NOTE: We don't filter at the MQTT subscription level because special nodes
        # transmit via LoRa and are forwarded by gateways. The MQTT topic is the
        # gateway's node ID, not the special node's ID. Filtering happens in the app.
        subscribe_topic = base_topic + '/#'
        result, mid = client.subscribe(subscribe_topic, qos=0)
        logger.info(f"✅ Resubscribed to: {subscribe_topic} (result={result}, mid={mid})")

        return True

    except Exception as e:
        logger.error(f"Error reloading MQTT subscriptions: {e}", exc_info=True)
        return False


def update_special_nodes():
    """Update special nodes configuration from reloaded config.
    This allows adding/removing special nodes without restarting the server."""
    try:
        # Reload the config module to get updated values
        import importlib
        importlib.reload(config)
        
        # Log the updated special nodes
        special_count = len(getattr(config, 'SPECIAL_NODE_IDS', []))
        logger.info(f"Updated special nodes configuration: {special_count} special node(s)")
        
        # Recalculate origin coordinates and movement status for all special nodes based on new config
        for node_id in getattr(config, 'SPECIAL_NODE_IDS', []):
            if node_id in nodes_data:
                special_node_config = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
                home_lat = special_node_config.get('home_lat')
                home_lon = special_node_config.get('home_lon')
                
                # Update origin if home position is defined in config
                if home_lat is not None and home_lon is not None:
                    nodes_data[node_id]["origin_lat"] = home_lat
                    nodes_data[node_id]["origin_lon"] = home_lon
                    
                    # Recalculate distance and moved_far if we have a current position
                    lat = nodes_data[node_id].get("latitude")
                    lon = nodes_data[node_id].get("longitude")
                    if lat is not None and lon is not None:
                        dist = _haversine_m(home_lat, home_lon, lat, lon)
                        nodes_data[node_id]["distance_from_origin_m"] = dist
                        nodes_data[node_id]["moved_far"] = bool(dist >= getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0))
                        logger.info(f"Recalculated movement for node {node_id}: {dist:.1f}m from origin, moved_far={nodes_data[node_id]['moved_far']}")
        
        return True
    except Exception as e:
        logger.error(f'Error updating special nodes: {e}')
        return False


def is_connected():
    """Check if MQTT client is actively receiving packets.

    Returns status strings:
    - 'receiving_packets': Actively receiving packets (within threshold)
    - 'stale_data': Received packets before but none recently (over threshold)
    - 'connected_to_server': Connected but haven't received actual packet data yet
    - 'connecting': Client exists but no messages yet
    - 'disconnected': No client or no messages

    Uses dynamic staleness threshold:
    - 5 minutes when subscribed to all nodes (high traffic)
    - 60 minutes when subscribed to special nodes only (low traffic)
    """
    try:
        current_time = time.time()

        # Determine which staleness threshold to use based on subscription mode
        # If both show_all_nodes and show_gateways are false, we're in special-nodes-only mode
        if (not getattr(config, 'SHOW_ALL_NODES', False) and
            not getattr(config, 'SHOW_GATEWAYS', True)):
            staleness_threshold = PACKET_STALENESS_THRESHOLD_SPECIAL_ONLY
        else:
            staleness_threshold = PACKET_STALENESS_THRESHOLD_ALL_NODES

        # If we have received packets and the last one is recent (within threshold)
        if packets_received and last_packet_time > 0:
            time_since_last_packet = current_time - last_packet_time
            if time_since_last_packet < staleness_threshold:
                return 'receiving_packets'
            else:
                # We've received packets before but none recently - connection is stale
                logger.warning(f'MQTT connection stale: last packet {time_since_last_packet:.0f}s ago (threshold: {staleness_threshold}s)')
                return 'stale_data'
        
        # If we have received any messages at all (but not actual packets), we're connected to server
        if message_received:
            return 'connected_to_server'
        
        # If client exists but no messages yet, we're connecting
        if client is not None:
            return 'connecting'
        
        # No client and no messages
        return 'disconnected'
    except Exception:
        return 'disconnected'


# View layer moved to api_views.py (v2.0 refactor); re-exported for call sites
from .api_views import (  # noqa: E402  (must import after state is defined)
    _calculate_node_status,
    _get_special_node_metadata,
    _get_node_channel_name,
    _get_origin_coordinates,
    _build_gateway_connections_list,
    _build_node_info_from_data,
    _build_gateway_only_node,
    get_nodes,
    get_special_history,
    _deduplicate_by_hour,
    get_signal_history,
)


# Gateway tracking moved to gateways.py (v2.1); re-exported for call sites
from .gateways import (  # noqa: E402
    _record_gateway_connection,
    _extract_gateway_from_packet,
    _calculate_gateway_reliability_score,
    _update_gateway_reliability_cache_for_gateway,
    _update_gateway_names_in_connections,
)
