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
special_node_position_timestamps = {}  # node_id -> set of rxTime values to deduplicate retransmitted positions
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
    """Check if a node_id is in the special nodes list."""
    return node_id in config.SPECIAL_NODES

def _has_power_sensor(node_id):
    """Check if a node has external power monitoring hardware (INA260/INA219)."""
    if node_id not in config.SPECIAL_NODES:
        return False
    return config.SPECIAL_NODES[node_id].get('has_power_sensor', False)

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

def _get_battery_value_for_history(node_id):
    """
    Get battery value for history storage.
    For power sensor nodes: returns voltage in volts
    For regular nodes: returns battery percentage

    Args:
        node_id: Node ID to get battery value for

    Returns:
        Battery value (voltage or percentage) or None
    """
    if _has_power_sensor(node_id):
        return _get_node_voltage(node_id)
    else:
        return nodes_data[node_id].get("battery")

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

def _update_history_entry(entry, rssi, snr, battery_value):
    """
    Update an existing history entry with best signal values.
    Only updates if new value is better (higher) than existing.

    Args:
        entry: History entry dict to update
        rssi: New RSSI value (or None)
        snr: New SNR value (or None)
        battery_value: New battery value (or None)
    """
    # Update RSSI if better (RSSI is negative dBm, higher value = better signal, e.g. -50 > -90)
    if rssi is not None and (entry.get('rssi') is None or rssi > entry['rssi']):
        entry['rssi'] = rssi

    # Update SNR if better (SNR in dB, higher is better)
    if snr is not None and (entry.get('snr') is None or snr > entry['snr']):
        entry['snr'] = snr

    # Always update battery with latest value
    if battery_value is not None:
        entry['battery'] = battery_value

def _add_telemetry_to_history(node_id, json_data):
    """
    Add or update telemetry data in special node history.
    Creates new history entry or updates existing one if within 2-second window.

    Args:
        node_id: Node ID to add history for
        json_data: Full MQTT packet data
    """
    # Guard clause: Not a special node? Skip.
    if not _is_special_node(node_id):
        return

    # Guard clause: No valid position? Skip.
    lat = nodes_data[node_id].get("lat")
    lon = nodes_data[node_id].get("lon")
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return

    # Ensure history structure exists
    _ensure_history_struct(node_id)

    # Extract telemetry values
    current_ts = time.time()
    battery_value = _get_battery_value_for_history(node_id)
    rssi = json_data.get("rx_rssi")
    snr = json_data.get("rx_snr")

    # Check if we have a recent entry to update
    recent_entry = _find_recent_history_entry(node_id, current_ts)

    if recent_entry:
        # Update existing entry with best values
        _update_history_entry(recent_entry, rssi, snr, battery_value)
        logger.debug(f'Updated telemetry history for {node_id}: battery={recent_entry["battery"]}, rssi={recent_entry["rssi"]}, snr={recent_entry["snr"]}')
    else:
        # Create new history entry
        entry = {
            "ts": current_ts,
            "lat": lat,
            "lon": lon,
            "alt": nodes_data[node_id].get("alt", 0),
            "battery": battery_value,  # voltage for power sensor nodes, % for others
            "rssi": rssi,
            "snr": snr
        }
        special_history[node_id].append(entry)
        logger.debug(f'Added telemetry to history for {node_id}: battery={entry["battery"]}, rssi={entry["rssi"]}, snr={entry["snr"]}')

    # Prune old history entries
    _prune_history(node_id, now_ts=current_ts)

def _check_battery_alert(node_id):
    """
    Check if battery alert should be sent for a special node.
    Uses voltage threshold for power sensor nodes, percentage for others.

    Args:
        node_id: Node ID to check
    """
    # Only check alerts for special nodes
    if not _is_special_node(node_id):
        return

    # Power sensor nodes: use voltage threshold (< 3.5V = low)
    if _has_power_sensor(node_id):
        voltage = _get_node_voltage(node_id)
        if voltage is not None and voltage < 3.5:
            from . import alerts
            node_data = nodes_data[node_id]
            alerts.send_battery_alert(node_id, node_data, voltage)
    else:
        # Regular nodes: use battery percentage threshold
        battery_level = nodes_data[node_id].get("battery")
        if battery_level is not None and battery_level < config.LOW_BATTERY_THRESHOLD:
            from . import alerts
            node_data = nodes_data[node_id]
            alerts.send_battery_alert(node_id, node_data, battery_level)

# Track best packets by ID for deduplication
_packet_id_tracking = {}  # {node_id: {packet_id: {best_packet_info, stored_index}}}

def _get_signal_quality_score(json_data):
    """Calculate signal quality score for a packet.
    Higher score = better signal quality.
    
    Scoring logic:
    1. Direct-hop packets (hop_start == hop_limit) score higher than relayed packets
    2. Among same hop type: higher SNR score (max 15)
    3. Among same SNR: higher RSSI score (in range -120 to -80 dBm)
    """
    score = 0
    
    # Primary factor: is this a direct-hop packet (not retransmitted through mesh)?
    hop_start = json_data.get('hop_start')
    hop_limit = json_data.get('hop_limit')
    is_direct_hop = (hop_start is not None and hop_limit is not None and hop_start == hop_limit)
    
    if is_direct_hop:
        score += 1000  # Direct-hop packets score 1000+ (all direct-hops beat all relayed)
    
    # Secondary factor: SNR (signal-to-noise ratio)
    snr = json_data.get('rx_snr')
    if snr is not None:
        # SNR typically ranges -20 to +10, we'll normalize to 0-50 scale
        score += max(0, min(50, int((snr + 20) * 2.5)))
    
    # Tertiary factor: RSSI (received signal strength indicator)
    rssi = json_data.get('rx_rssi')
    if rssi is not None:
        # RSSI typically ranges -120 to -80 dBm (higher is better, so normalize inversely)
        # -80 dBm → 40 points, -120 dBm → 0 points
        score += max(0, min(40, int((rssi + 120))))
    
    return score

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
            'long_name': payload.get('long_name'),
            'short_name': payload.get('short_name')
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

def _record_gateway_connection(special_node_id, gateway_node_id, json_data, confidence="direct"):
    """
    Record that a gateway received a packet from a special node.
    Tracks gateways with confidence level (direct vs partial hop data).
    Updates "best gateway" based on strongest RSSI.
    Also marks the gateway node itself as a gateway in nodes_data.
    
    Args:
        special_node_id: The special node that sent the packet
        gateway_node_id: The node that received it (ideally directly, may have incomplete hop data)
        json_data: The packet data with RSSI/SNR info
        confidence: "direct" (hop_start==hop_limit) or "partial" (hop data missing/incomplete)
    """
    if special_node_id not in special_node_gateways:
        special_node_gateways[special_node_id] = {}
    
    # Mark this node as a gateway (it received a packet from a special node)
    if gateway_node_id not in nodes_data:
        nodes_data[gateway_node_id] = {}
    nodes_data[gateway_node_id]["is_gateway"] = True
    node_is_gateway[gateway_node_id] = True
    logger.debug(f"Node {gateway_node_id} marked as gateway (received from special node {special_node_id}, confidence={confidence})")

    # Get gateway info from nodes_data AFTER ensuring it exists
    gateway_info = nodes_data.get(gateway_node_id, {})

    # Use field names that match frontend expectations (app.js line 1394-1397)
    connection_info = {
        "id": gateway_node_id,
        "name": gateway_info.get("long_name") or gateway_info.get("longName") or "Unknown",
        "lat": gateway_info.get("latitude"),
        "lon": gateway_info.get("longitude"),
        "rssi": json_data.get("rx_rssi"),
        "snr": json_data.get("rx_snr"),
        "last_seen": time.time(),
        "confidence": confidence,  # Track whether this is direct or partial detection
        "hop_start": json_data.get("hop_start"),  # Store hop data for reliability analysis
        "hop_limit": json_data.get("hop_limit"),  # Store hop data for reliability analysis
    }
    
    # Store/update this gateway connection
    special_node_gateways[special_node_id][gateway_node_id] = connection_info

    # Update the gateway's own node_data with latest signal and timestamp
    nodes_data[gateway_node_id]["last_seen"] = time.time()
    if json_data.get("rx_rssi") is not None:
        nodes_data[gateway_node_id]["rx_rssi"] = json_data["rx_rssi"]
    if json_data.get("rx_snr") is not None:
        nodes_data[gateway_node_id]["rx_snr"] = json_data["rx_snr"]

    # Track best gateway: the one with strongest RSSI for this special node
    # rssi is negative, so higher (less negative) = stronger
    # Prefer direct-hop detections over partial detections
    current_best = nodes_data.get(special_node_id, {}).get("best_gateway", {})
    current_best_rssi = current_best.get("rssi", -200) or -200
    current_best_confidence = current_best.get("confidence", "partial")
    incoming_rssi = json_data.get("rx_rssi", -200) or -200
    
    # Update best gateway if:
    # 1. Incoming is direct and current is partial, OR
    # 2. Same confidence level and incoming RSSI is stronger
    should_update = False
    if confidence == "direct" and current_best_confidence == "partial":
        should_update = True
    elif confidence == current_best_confidence and incoming_rssi > current_best_rssi:
        should_update = True
    
    if should_update:
        # Ensure node exists in nodes_data before updating
        if special_node_id not in nodes_data:
            nodes_data[special_node_id] = {}
        # This is the strongest gateway so far
        nodes_data[special_node_id]["best_gateway"] = {
            "id": gateway_node_id,
            "name": connection_info["name"],
            "lat": connection_info["lat"],
            "lon": connection_info["lon"],
            "rssi": incoming_rssi,
            "snr": connection_info["snr"],
        }
        nodes_data[special_node_id]["best_gateway_rssi"] = incoming_rssi
        logger.debug(f"Best gateway updated for {special_node_id}: {gateway_node_id} ({connection_info['name']}) RSSI={incoming_rssi}dBm")
    else:
        logger.debug(f"Gateway connection: {special_node_id} → {gateway_node_id} ({connection_info['name']}) RSSI={incoming_rssi} (not best)")

    # Update gateway reliability cache for this gateway
    _update_gateway_reliability_cache_for_gateway(gateway_node_id)

def _extract_gateway_from_packet(special_node_id, json_data):
    """
    Extract first-hop receiver node ID from MQTT topic in packets from a special node.
    
    MESHTASTIC PROTOCOL SPECIFICATION:
    Per mesh.proto and Router.cpp (Meshtastic firmware):
    - hop_start: Initial hop limit when packet was sent by originator
    - hop_limit: Remaining hops available (decrements with each relay)
    - DIRECT RECEPTION (first-hop): hop_start == hop_limit (packet not relayed yet)
    - RELAYED PACKET: hop_start > hop_limit (packet consumed hops in transit)
    - hops_traveled: hop_start - hop_limit (distance in hops from originator)
    
    This function identifies which node received the special node's packet DIRECTLY,
    without going through relays. Only direct receivers can be considered gateways
    for the purpose of tracking which parts of the network have direct coverage.
    
    Detection criteria (Meshtastic spec compliant):
    - ONLY: hop_start == hop_limit (packet received without relay, per spec)
    
    Args:
        special_node_id: The special node that sent the packet
        json_data: The packet data containing mqtt_topic and hop info
    """
    if not _is_special_node(special_node_id):
        return
    
    mqtt_topic = json_data.get("mqtt_topic")
    if not mqtt_topic:
        logger.debug(f"Gateway extraction: No mqtt_topic in packet from {special_node_id}")
        return
    
    # Get hop data to determine if this is a direct reception
    hop_start = json_data.get("hop_start")
    hop_limit = json_data.get("hop_limit")
    rx_rssi = json_data.get("rx_rssi")
    
    # PRIMARY RULE (Meshtastic Spec): Direct reception = hop_start == hop_limit
    # This means the packet has NOT been relayed; it was received directly from the sender.
    is_direct_hop = (hop_start is not None and hop_limit is not None and hop_start == hop_limit)
    
    if not is_direct_hop:
        # Packet was relayed (hops consumed in transit)
        hops_traveled = (hop_start - hop_limit) if (hop_start is not None and hop_limit is not None) else None
        logger.debug(f"Rejecting relayed packet: hop_start={hop_start}, hop_limit={hop_limit}, hops_traveled={hops_traveled} for special_node={special_node_id}")
        return
    
    # This is a legitimate direct reception (hop_start == hop_limit per Meshtastic spec)
    logger.debug(f"Accepting direct reception: hop_start={hop_start}, hop_limit={hop_limit}, rssi={rx_rssi} for special_node={special_node_id}")
    
    # Extract gateway node ID from MQTT topic
    gateway_node_id = _extract_gateway_node_id_from_topic(mqtt_topic)
    logger.debug(f"Gateway extraction: mqtt_topic={mqtt_topic}, extracted_id={gateway_node_id}, hop_start={hop_start}, hop_limit={hop_limit}, rssi={rx_rssi}")
    if gateway_node_id:
        # Ensure first-hop receiver entry exists in nodes_data
        if gateway_node_id not in nodes_data:
            nodes_data[gateway_node_id] = {}
        # Record the gateway as direct reception (only type we accept)
        _record_gateway_connection(special_node_id, gateway_node_id, json_data, confidence="direct")
        logger.debug(f"Gateway detected: {gateway_node_id} received direct from special_node={special_node_id}")
    else:
        logger.debug(f"Failed to extract gateway node ID from topic: {mqtt_topic}")


def _calculate_gateway_reliability_score(gateway_detections):
    """
    Calculate a reliability score (0-100) for a gateway based on:
    - Confidence level (direct > partial)
    - Number of detections (more = more consistent)
    - Signal strength (stronger RSSI = better)
    
    Args:
        gateway_detections: List of detection records for this gateway
        
    Returns:
        dict with keys: score (0-100), detection_count, avg_rssi, confidence_level
    """
    if not gateway_detections:
        return {"score": 0, "detection_count": 0, "avg_rssi": None, "confidence_level": "none"}
    
    detection_count = len(gateway_detections)
    
    # Determine highest confidence level seen
    has_direct = any(d.get("confidence") == "direct" for d in gateway_detections)
    confidence_level = "direct" if has_direct else "partial"
    
    # Calculate average RSSI
    rssi_values = [d.get("rssi") for d in gateway_detections if d.get("rssi") is not None]
    avg_rssi = sum(rssi_values) / len(rssi_values) if rssi_values else None
    
    # Calculate score components
    score = 0
    
    # Factor 1: Confidence level (0-40 points)
    if confidence_level == "direct":
        score += 40
    else:
        score += 20
    
    # Factor 2: Detection count (0-30 points)
    # 1 detection = 5 pts, 2 = 10 pts, 3 = 15 pts, 4+ = 30 pts
    if detection_count >= 4:
        score += 30
    else:
        score += min(30, detection_count * 10)
    
    # Factor 3: Signal strength (0-30 points)
    # -80 dBm (excellent) = 30 pts, -120 dBm (poor) = 0 pts
    if avg_rssi is not None:
        # Normalize RSSI: -80 is max (30pts), -120 is min (0pts)
        rssi_score = max(0, min(30, int((avg_rssi + 120))))
        score += rssi_score
    
    return {
        "score": int(score),
        "detection_count": detection_count,
        "avg_rssi": avg_rssi,
        "confidence_level": confidence_level
    }

def _update_gateway_reliability_cache_for_gateway(gateway_id):
    """
    Update cached reliability score and info for a specific gateway.
    Called when gateway connection data changes.

    Args:
        gateway_id: The gateway node ID to update cache for
    """
    global gateway_reliability_cache, all_gateway_node_ids, gateway_info_cache

    # Collect all detections of this gateway across all special nodes
    # Also find the most recent gateway info
    all_detections = []
    most_recent_info = None
    for special_id, connections in special_node_gateways.items():
        if gateway_id in connections:
            gw_info = connections[gateway_id]
            all_detections.append(gw_info)
            # Keep the most recently seen gateway info
            if most_recent_info is None or gw_info.get("last_seen", 0) > most_recent_info.get("last_seen", 0):
                most_recent_info = gw_info

    # Calculate reliability score
    reliability = _calculate_gateway_reliability_score(all_detections)

    # Cache the reliability result
    gateway_reliability_cache[gateway_id] = {
        "score": reliability["score"],
        "detection_count": reliability["detection_count"],
        "avg_rssi": reliability["avg_rssi"],
        "confidence_level": reliability.get("confidence_level"),
        "last_updated": time.time()
    }

    # Cache the most recent gateway info
    if most_recent_info:
        gateway_info_cache[gateway_id] = most_recent_info

    # Update gateway node IDs set
    all_gateway_node_ids.add(gateway_id)

    logger.debug(f"Updated gateway reliability cache for {gateway_id}: score={reliability['score']}, detections={reliability['detection_count']}")


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

def _haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in meters between two lat/lon points."""
    try:
        # convert degrees to radians
        rlat1 = math.radians(lat1)
        rlon1 = math.radians(lon1)
        rlat2 = math.radians(lat2)
        rlon2 = math.radians(lon2)
        dlat = rlat2 - rlat1
        dlon = rlon2 - rlon1
        a = math.sin(dlat/2.0)**2 + math.cos(rlat1)*math.cos(rlat2)*math.sin(dlon/2.0)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return 6371000.0 * c
    except Exception:
        return None

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

def _load_gateways_from_saved_data(node_id, gateways_dict):
    """
    Load gateway connections for a special node from saved data.
    Updates special_node_gateways, node_is_gateway, and nodes_data.

    Args:
        node_id: The special node ID
        gateways_dict: Dictionary of gateway data from saved file
    """
    if not isinstance(gateways_dict, dict):
        return

    # Convert string keys to int keys for consistency with runtime gateway detection
    gateways_with_int_keys = {}
    for gateway_id_str, gw_info in gateways_dict.items():
        gw_id_int = int(gateway_id_str)
        gateways_with_int_keys[gw_id_int] = gw_info
        node_is_gateway[gw_id_int] = True

        # Create nodes_data entry for gateway so it appears in get_nodes()
        if gw_id_int not in nodes_data:
            nodes_data[gw_id_int] = {}
        nodes_data[gw_id_int]["is_gateway"] = True

        # Store gateway connection info in nodes_data for display
        if isinstance(gw_info, dict):
            nodes_data[gw_id_int]["rx_rssi"] = gw_info.get("rssi")
            nodes_data[gw_id_int]["rx_snr"] = gw_info.get("snr")
            nodes_data[gw_id_int]["last_seen"] = gw_info.get("last_seen", time.time())

        logger.debug(f"Restored gateway {gateway_id_str} for special node {node_id}")

    special_node_gateways[node_id] = gateways_with_int_keys

    # Update gateway caches for all loaded gateways
    for gw_id in gateways_with_int_keys.keys():
        _update_gateway_reliability_cache_for_gateway(gw_id)




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
    """Extract channel name from stored topic path for this node."""
    if node_id not in node_topics:
        return "Unknown"
    
    topic = node_topics[node_id]
    try:
        # Topic format: msh/US/bayarea/2/e/CHANNEL_NAME/!nodeid/...
        parts = topic.split('/')
        if 'e' in parts:
            e_idx = parts.index('e')
            if e_idx + 1 < len(parts):
                channel = parts[e_idx + 1]
                # Make sure it's not a node id part (starts with !)
                if not channel.startswith('!'):
                    return channel
    except Exception as e:
        logger.debug(f"Error extracting channel from topic {topic}: {e}")

    return "Unknown"


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


def _update_gateway_names_in_connections(node_id, updated_name):
    """
    Update gateway name in all special node gateway connections.

    When a gateway sends its NODE_INFO, propagate the name to all
    special nodes that have this gateway in their connections.

    Args:
        node_id: Gateway node ID
        updated_name: Updated name for the gateway
    """
    if not updated_name or updated_name == "Unknown":
        return

    for special_id, gw_dict in special_node_gateways.items():
        if node_id in gw_dict:
            gw_dict[node_id]["name"] = updated_name
            logger.debug(f'Updated gateway name in connection: {node_id} -> {updated_name}')


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
        nodes_data[node_id]["long_name"] = extracted_name or payload.get("long_name") or "Unknown"
        nodes_data[node_id]["short_name"] = short or payload.get("short_name") or "?"
        nodes_data[node_id]["hw_model"] = payload.get("hw_model") or "Unknown"
    else:
        nodes_data[node_id]["long_name"] = extracted_name or "Unknown"
        nodes_data[node_id]["short_name"] = short or "?"
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
            
            # Store signal quality metrics if available
            if "rx_rssi" in json_data:
                nodes_data[node_id]["rx_rssi"] = json_data["rx_rssi"]
            if "rx_snr" in json_data:
                nodes_data[node_id]["rx_snr"] = json_data["rx_snr"]
            
            logger.info(f'Updated nodeinfo for {node_id}: {nodes_data[node_id]["long_name"]}')

            # If this node is a gateway, update its name in all gateway connections and cache
            updated_name = nodes_data[node_id].get("long_name")
            _update_gateway_names_in_connections(node_id, updated_name)

            # Also update gateway info cache if this is a gateway
            if node_is_gateway.get(node_id, False) and node_id in gateway_info_cache:
                gateway_info_cache[node_id]["name"] = updated_name

    except Exception as e:
        logger.error(f'❌ Error processing nodeinfo: {e}', exc_info=True)


def on_position(json_data):
    """Process position messages - update node coordinates."""
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()
    
    try:
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
            _track_special_node_packet(node_id, 'POSITION_APP', json_data)
        
        if node_id and "latitude_i" in payload and "longitude_i" in payload:
            if node_id not in nodes_data:
                nodes_data[node_id] = {}
            
            # Store channel if available
            if channel is not None:
                nodes_data[node_id]["channel"] = channel
            
            # Store channel name from topic
            nodes_data[node_id]["channel_name"] = channel_name
            
            # For movement alerts on special nodes, track origin and distance
            try:
                if is_special:
                    lat = payload["latitude_i"] / 1e7
                    lon = payload["longitude_i"] / 1e7
                    
                    # Get home position from config if defined, otherwise use first position seen
                    special_node_config = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
                    home_lat = special_node_config.get('home_lat')
                    home_lon = special_node_config.get('home_lon')
                    
                    # If home position is defined in config, use it
                    if home_lat is not None and home_lon is not None:
                        nodes_data[node_id]["origin_lat"] = home_lat
                        nodes_data[node_id]["origin_lon"] = home_lon
                    # Otherwise, use first position seen as origin
                    elif "origin_lat" not in nodes_data[node_id] or nodes_data[node_id].get("origin_lat") is None:
                        nodes_data[node_id]["origin_lat"] = lat
                        nodes_data[node_id]["origin_lon"] = lon
                    
                    # Compute distance from origin (home or first position)
                    o_lat = nodes_data[node_id].get("origin_lat")
                    o_lon = nodes_data[node_id].get("origin_lon")
                    if o_lat is not None and o_lon is not None:
                        dist = _haversine_m(o_lat, o_lon, lat, lon)
                        nodes_data[node_id]["distance_from_origin_m"] = dist
                        moved_far = bool(dist is not None and dist >= getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0))
                        
                        # Send email alert if node is outside threshold (cooldown prevents spam)
                        if moved_far and getattr(config, 'ALERT_ENABLED', False):
                            try:
                                alerts.send_movement_alert(node_id, nodes_data[node_id], dist)
                            except Exception as alert_err:
                                logger.error(f"Failed to send movement alert for {node_id}: {alert_err}")
                        
                        nodes_data[node_id]["moved_far"] = moved_far
            except Exception as e:
                logger.debug(f"Error processing movement alerts for {node_id}: {e}")
            
            # Convert from integer coordinates to decimal degrees
            lat = payload["latitude_i"] / 1e7
            lon = payload["longitude_i"] / 1e7
            alt = payload.get("altitude", 0)
            
            nodes_data[node_id]["latitude"] = lat
            nodes_data[node_id]["longitude"] = lon
            nodes_data[node_id]["altitude"] = alt
            nodes_data[node_id]["last_seen"] = time.time()
            nodes_data[node_id]["last_position_update"] = time.time()  # Track position updates separately

            # Store signal quality metrics if available
            if "rx_rssi" in json_data:
                nodes_data[node_id]["rx_rssi"] = json_data["rx_rssi"]
            if "rx_snr" in json_data:
                nodes_data[node_id]["rx_snr"] = json_data["rx_snr"]

            # If this is a gateway, update its position in all special node connections
            if node_is_gateway.get(node_id, False):
                for special_id, gw_dict in special_node_gateways.items():
                    if node_id in gw_dict:
                        gw_dict[node_id]["lat"] = lat
                        gw_dict[node_id]["lon"] = lon
                        gw_dict[node_id]["last_seen"] = time.time()

                # Update gateway info cache
                if node_id in gateway_info_cache:
                    gateway_info_cache[node_id]["lat"] = lat
                    gateway_info_cache[node_id]["lon"] = lon

            # Record history for special nodes (deduplicate by rxTime to avoid retransmitted packets)
            if is_special:
                # Extract rxTime from the packet to deduplicate retransmissions
                rx_time = json_data.get("rxTime")
                
                # Initialize deduplication set for this node if needed
                if node_id not in special_node_position_timestamps:
                    special_node_position_timestamps[node_id] = set()
                
                # Only add to history if we haven't seen this rxTime before
                if rx_time is not None and rx_time not in special_node_position_timestamps[node_id]:
                    _ensure_history_struct(node_id)
                    # For nodes with power sensors, store voltage instead of battery %
                    if _has_power_sensor(node_id):
                        battery_value = _get_node_voltage(node_id)
                    else:
                        battery_value = nodes_data[node_id].get("battery")

                    entry = {
                        "ts": time.time(),
                        "lat": lat,
                        "lon": lon,
                        "alt": alt,
                        "battery": battery_value,  # voltage for power sensor nodes, % for others
                        "rssi": json_data.get("rx_rssi"),
                        "snr": json_data.get("rx_snr")
                    }
                    special_history[node_id].append(entry)
                    special_node_position_timestamps[node_id].add(rx_time)
                    _prune_history(node_id, now_ts=entry['ts'])

                    logger.debug(f'Added new position to history for {node_id} (rxTime: {rx_time})')
                elif rx_time is not None:
                    logger.debug(f'Skipped duplicate position for {node_id} (rxTime: {rx_time} already seen)')
                else:
                    # No rxTime available, add anyway (shouldn't happen but be safe)
                    _ensure_history_struct(node_id)
                    # For nodes with power sensors, store voltage instead of battery %
                    if _has_power_sensor(node_id):
                        battery_value = _get_node_voltage(node_id)
                    else:
                        battery_value = nodes_data[node_id].get("battery")

                    entry = {
                        "ts": time.time(),
                        "lat": lat,
                        "lon": lon,
                        "alt": alt,
                        "battery": battery_value,  # voltage for power sensor nodes, % for others
                        "rssi": json_data.get("rx_rssi"),
                        "snr": json_data.get("rx_snr")
                    }
                    special_history[node_id].append(entry)
                    _prune_history(node_id, now_ts=entry['ts'])

            logger.info(f'Updated position for {node_id}: {lat:.4f}, {lon:.4f}')
    except Exception as e:
        logger.error(f'❌ Error processing position: {e}', exc_info=True)


def _extract_battery_and_voltage_from_telemetry(node_id, payload):
    """
    Extract battery percentage and voltage from telemetry payload.

    Handles both power sensor nodes (INA260/INA219) and regular nodes.
    Returns normalized values ready for storage.

    Args:
        node_id: Node ID to extract telemetry for
        payload: Telemetry payload dictionary

    Returns:
        tuple: (battery_percent, voltage) where:
            - battery_percent: int 0-100 or None
            - voltage: float or None
    """
    battery = None
    voltage = None

    try:
        if not isinstance(payload, dict):
            return (None, None)

        # Check if this is a power sensor node
        if _has_power_sensor(node_id):
            # Power sensor nodes: extract voltage from power_metrics ONLY
            power_metrics = payload.get("power_metrics", {})
            if isinstance(power_metrics, dict):
                # Get configured voltage channel (ch3 for battery, ch1 for input)
                voltage_channel = config.SPECIAL_NODES[node_id].get('voltage_channel', 'ch3_voltage')
                if voltage_channel == 'ch3_voltage':
                    voltage = power_metrics.get('ch3_voltage')
                elif voltage_channel == 'ch1_voltage':
                    voltage = power_metrics.get('ch1_voltage')

                # Estimate battery percentage from voltage
                if voltage is not None:
                    battery = _estimate_battery_from_voltage(voltage)
        else:
            # Regular nodes: extract battery percentage from device_metrics
            device_metrics = payload.get("device_metrics", {})
            if isinstance(device_metrics, dict):
                battery = device_metrics.get("battery_level")
                voltage = device_metrics.get("voltage")

                # If we have voltage but no battery, estimate it
                if battery is None and voltage is not None:
                    battery = _estimate_battery_from_voltage(voltage)

        # Normalize battery to int and clamp to 0-100
        if isinstance(battery, str) and battery.isdigit():
            battery = int(battery)
        if isinstance(battery, (float, int)):
            battery = int(battery)
            battery = max(0, min(100, battery))
        else:
            battery = None

        # Normalize voltage
        if voltage is not None and isinstance(voltage, (int, float)):
            voltage = float(voltage)
        else:
            voltage = None

    except Exception as e:
        logger.debug(f"Error extracting battery/voltage for {node_id}: {e}")
        return (None, None)

    return (battery, voltage)


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

            # Extract battery and voltage using helper (handles both power sensor and regular nodes)
            battery, voltage = _extract_battery_and_voltage_from_telemetry(node_id, payload)
            nodes_data[node_id]["battery"] = battery
            nodes_data[node_id]["voltage"] = voltage

            logger.info(f'Updated telemetry for {node_id}: battery={battery}%')
            
            # Store signal quality metrics if available
            if "rx_rssi" in json_data:
                nodes_data[node_id]["rx_rssi"] = json_data["rx_rssi"]
            if "rx_snr" in json_data:
                nodes_data[node_id]["rx_snr"] = json_data["rx_snr"]

            # Add telemetry to special node history (if applicable)
            _add_telemetry_to_history(node_id, json_data)

            # Check for low battery alert
            _check_battery_alert(node_id)

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
                nodes_data[node_id]["long_name"] = payload.get("longName") or payload.get("long_name")
            if "shortName" in payload or "short_name" in payload:
                nodes_data[node_id]["short_name"] = payload.get("shortName") or payload.get("short_name")
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


def _extract_channel_from_mqtt_topic(topic: str) -> str:
    """
    Extract channel name from MQTT topic path.
    Topic format: msh/US/bayarea/2/e/CHANNEL_NAME/!nodeid/...
    Returns channel name or "Unknown" if not found.
    """
    try:
        parts = topic.split('/')
        if 'e' in parts:
            e_idx = parts.index('e')
            if e_idx + 1 < len(parts):
                channel = parts[e_idx + 1]
                if not channel.startswith('!'):
                    return channel
    except Exception as e:
        logger.debug(f"Error extracting channel from topic {topic}: {e}")
    return "Unknown"


def _extract_gateway_node_id_from_topic(topic: str) -> int:
    """
    Extract the gateway node ID from MQTT topic path.
    Topic format: msh/US/bayarea/2/e/CHANNEL_NAME/!nodeid/...
    The node ID after the '!' is the gateway that the message came through.
    Returns the node ID (int) or None if not found.
    """
    try:
        parts = topic.split('/')
        for part in parts:
            if part.startswith('!'):
                # Extract hex node ID (e.g., "!4049c6f4" -> 0x4049c6f4)
                hex_id = part[1:]  # Remove the '!'
                node_id = int(hex_id, 16)
                return node_id
    except Exception as e:
        logger.debug(f"Error extracting gateway node ID from topic {topic}: {e}")
    return None


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
        portnum_name = portnums_pb2.PortNum.Name(portnum)
        
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


def _calculate_node_status(time_since_seen):
    """Determine node status color based on time since last seen."""
    if time_since_seen < config.STATUS_BLUE_THRESHOLD:
        return "blue"
    elif time_since_seen < config.STATUS_ORANGE_THRESHOLD:
        return "orange"
    else:
        return "red"


def _get_special_node_metadata(node_id, is_special):
    """Extract special node symbol and label from config."""
    if not is_special:
        return None, None

    info = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
    special_symbol = info.get('symbol', getattr(config, 'SPECIAL_NODE_SYMBOL', '⭐'))
    special_label = info.get('label')
    return special_symbol, special_label


def _get_node_channel_name(node_id, data, is_special):
    """Get channel name, preferring routing packets for special nodes."""
    if is_special and node_id in special_node_channels:
        return special_node_channels[node_id]
    return data.get("channel_name")


def _get_origin_coordinates(node_id, data, is_special):
    """Get origin coordinates with config fallback for special nodes."""
    origin_lat = data.get("origin_lat")
    origin_lon = data.get("origin_lon")

    if is_special and (origin_lat is None or origin_lon is None):
        special_info = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
        if origin_lat is None:
            origin_lat = special_info.get('home_lat')
        if origin_lon is None:
            origin_lon = special_info.get('home_lon')

    return origin_lat, origin_lon


def _build_gateway_connections_list(node_id):
    """Build list of gateway connections with reliability scores for a special node."""
    gateway_connections = []
    for gw_id, gw_info in special_node_gateways[node_id].items():
        cached_reliability = gateway_reliability_cache.get(gw_id, {})
        gw_info_with_score = dict(gw_info)
        gw_info_with_score["reliability_score"] = cached_reliability.get("score", 0)
        gw_info_with_score["detection_count"] = cached_reliability.get("detection_count", 0)
        gw_info_with_score["avg_rssi"] = cached_reliability.get("avg_rssi")
        gateway_connections.append(gw_info_with_score)
    return gateway_connections


def _build_node_info_from_data(node_id, data, is_special, current_time):
    """Build complete node_info dictionary from node data."""
    last_seen = data.get("last_seen", current_time)
    time_since_seen = current_time - last_seen

    status = _calculate_node_status(time_since_seen)
    special_symbol, special_label = _get_special_node_metadata(node_id, is_special)
    stale = time_since_seen > getattr(config, 'STALE_AFTER_SECONDS', config.STATUS_ORANGE_THRESHOLD)
    channel_name = _get_node_channel_name(node_id, data, is_special)
    origin_lat, origin_lon = _get_origin_coordinates(node_id, data, is_special)
    node_name = data.get("long_name") or data.get("longName")

    # Build base node info dictionary
    node_info = {
        "id": node_id,
        "name": node_name,
        "short": data.get("short_name") or data.get("shortName") or "?",
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "alt": data.get("altitude"),
        "hw_model": data.get("hw_model", "Unknown"),
        "channel": data.get("channel"),
        "channel_name": channel_name,
        "modem_preset": data.get("modem_preset"),
        "role": data.get("role"),
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "status": status,
        "is_special": is_special,
        "has_power_sensor": _has_power_sensor(node_id) if is_special else False,
        "stale": stale,
        "has_fix": (data.get("latitude") is not None and data.get("longitude") is not None),
        "special_symbol": special_symbol,
        "special_label": special_label,
        "time_since_seen": time_since_seen,
        "last_seen": last_seen,
        "last_position_update": data.get("last_position_update"),
        "battery": data.get("battery") if data.get("battery") is not None else None,
        "age_min": int(time_since_seen / 60),
        "moved_far": data.get("moved_far", False),
        "distance_from_origin_m": data.get("distance_from_origin_m"),
        "voltage": _get_node_voltage(node_id),
        "rx_rssi": data.get("rx_rssi"),
        "rx_snr": data.get("rx_snr"),
    }

    # Add power current for power sensor nodes
    telemetry = data.get("telemetry", {})
    if isinstance(telemetry, dict):
        power_metrics = telemetry.get("power_metrics", {})
        node_info["power_current"] = power_metrics.get("ch3_current")

    # Check for low battery
    battery_level = node_info.get("battery")
    node_info["battery_low"] = (
        battery_level is not None and
        battery_level < getattr(config, 'LOW_BATTERY_THRESHOLD', 50)
    )

    # Add gateway connections for special nodes
    if is_special and node_id in special_node_gateways:
        node_info["gateway_connections"] = _build_gateway_connections_list(node_id)
    else:
        node_info["gateway_connections"] = []

    # Add best gateway info for special nodes
    if is_special and "best_gateway" in data:
        node_info["best_gateway"] = data["best_gateway"]

    # Determine if this node is a gateway
    is_gw = node_is_gateway.get(node_id, False) or node_id in all_gateway_node_ids
    node_info["is_gateway"] = is_gw

    # Set name fallback based on gateway status
    if not node_name:
        node_info["name"] = f"Gateway {node_id}" if is_gw else "Unknown"

    # Add last packet time for special nodes
    if is_special and node_id in special_node_last_packet:
        node_info["last_packet_time"] = special_node_last_packet[node_id]

    return node_info


def _build_gateway_only_node(gateway_id, current_time):
    """Build node_info dictionary for gateway that hasn't sent its own data."""
    gw_info = gateway_info_cache.get(gateway_id)
    if gw_info is None:
        return None

    cached_reliability = gateway_reliability_cache.get(gateway_id, {})

    return {
        "id": gateway_id,
        "name": gw_info.get("name", "Unknown Gateway"),
        "short": "GW",
        "lat": gw_info.get("lat"),
        "lon": gw_info.get("lon"),
        "alt": None,
        "hw_model": "Gateway",
        "channel": None,
        "channel_name": None,
        "modem_preset": None,
        "role": "ROUTER",
        "origin_lat": None,
        "origin_lon": None,
        "status": "orange",
        "is_special": False,
        "stale": True,
        "has_fix": (gw_info.get("lat") is not None and gw_info.get("lon") is not None),
        "special_symbol": None,
        "special_label": None,
        "time_since_seen": current_time - gw_info.get("last_seen", current_time),
        "last_seen": gw_info.get("last_seen"),
        "last_position_update": None,
        "battery": None,
        "age_min": int((current_time - gw_info.get("last_seen", current_time)) / 60),
        "moved_far": False,
        "distance_from_origin_m": None,
        "voltage": None,
        "power_current": None,
        "rx_rssi": gw_info.get("rssi"),
        "rx_snr": gw_info.get("snr"),
        "is_gateway": True,
        "gateway_connections": [],
        "reliability_score": cached_reliability.get("score", 0),
        "detection_count": cached_reliability.get("detection_count", 0),
        "avg_rssi": cached_reliability.get("avg_rssi"),
        "confidence_level": cached_reliability.get("confidence_level", "none"),
    }


def get_nodes():
    """Return list of all tracked nodes with status."""
    result = []
    current_time = time.time()

    for node_id, data in nodes_data.items():
        is_special = node_id in getattr(config, 'SPECIAL_NODE_IDS', [])

        # Skip non-special, non-gateway nodes when show_all_nodes is disabled
        if not getattr(config, 'SHOW_ALL_NODES', False):
            if not is_special:
                is_gateway_check = node_is_gateway.get(node_id, False) or node_id in all_gateway_node_ids
                if not is_gateway_check:
                    continue

        # Build complete node info dictionary using helper
        node_info = _build_node_info_from_data(node_id, data, is_special, current_time)
        result.append(node_info)

    # Add gateways that aren't already in result
    result_ids = {n['id'] for n in result}
    for gateway_id in all_gateway_node_ids:
        if gateway_id not in result_ids:
            gateway_node = _build_gateway_only_node(gateway_id, current_time)
            if gateway_node:
                result.append(gateway_node)

    return result


def get_special_history(node_id: int, hours: int = None):
    """
    Get deduplicated position history for a special node.
    
    Deduplication reduces redundant data for slow-moving nodes by keeping only
    the most recent position within each time window defined by
    config.special_nodes_settings.data_limit_time (default: 1 hour).
    
    For example with data_limit_time=1.0:
    - Raw data: 700+ points over 24 hours
    - Returned: ~24 points (one per hour)
    - Bandwidth: 84% reduction
    
    Args:
        node_id: The node's numeric ID
        hours: History window in hours (default from config.SPECIAL_HISTORY_HOURS)
    
    Returns:
        List of position dictionaries with ts, lat, lon, alt, battery, rssi, snr
    """
    hours = hours or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
    cutoff = time.time() - (hours * 3600)

    # Get position history from in-memory cache
    dq = special_history.get(node_id, deque())
    filtered = [e for e in dq if e['ts'] >= cutoff]

    # Deduplicate to one per data_limit_time window for slow-moving special nodes
    return _deduplicate_by_hour(filtered)

def _deduplicate_by_hour(points):
    """Keep only the most recent point per time window for slow-moving special nodes.
    
    Time window configured via config.special_nodes_settings.data_limit_time (in hours).
    """
    if not points:
        return []
    
    # Get deduplication window from config (in hours, default 1.0)
    time_window_hours = config.special_nodes_settings.get('data_limit_time', 1.0)
    time_window_seconds = time_window_hours * 3600
    
    time_buckets = {}
    for point in points:
        time_key = int(point['ts'] / time_window_seconds)  # Group by time window
        # Keep the most recent point in each time window
        if time_key not in time_buckets:
            time_buckets[time_key] = point
        elif point['ts'] > time_buckets[time_key]['ts']:
            time_buckets[time_key] = point
    
    # Sort by timestamp and return
    result = sorted(time_buckets.values(), key=lambda x: x['ts'])
    return result

def get_signal_history(node_id: int, hours: int = None):
    """Alias for get_special_history() - returns battery, RSSI, SNR history for a node."""
    return get_special_history(node_id, hours)

def get_all_gateways():
    """
    Return all known gateways with their metadata.
    
    Returns list of gateway objects with:
    - id: gateway node ID
    - name: long name
    - latitude/longitude: position if available (null if no position)
    - is_online: whether recently heard from
    - signal_strength: from last heard packet (if available)
    - receiving_from: list of special node IDs that use this gateway
    """
    gateways = {}
    
    # Iterate all nodes that are marked as gateways
    for node_id, node_info in nodes_data.items():
        if node_info.get("is_gateway"):
            gateways[node_id] = {
                "id": node_id,
                "name": node_info.get("long_name", "Unknown Gateway"),
                "latitude": node_info.get("latitude"),
                "longitude": node_info.get("longitude"),
                "is_online": bool(node_info.get("last_seen")),
                "last_seen_ts": node_info.get("last_seen"),
                "signal_strength": node_info.get("rx_rssi"),
                "snr": node_info.get("rx_snr"),
                "receiving_from": [],
            }
    
    # Track which special nodes use which gateways
    for special_node_id, connections in special_node_gateways.items():
        for gateway_id in connections.keys():
            if gateway_id in gateways:
                gateways[gateway_id]["receiving_from"].append(special_node_id)
    
    return list(gateways.values())

def get_all_special_history(hours: int = None):
    """Return history for all special nodes as dict node_id -> list of points."""
    hours = hours or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
    out = {}
    for nid in getattr(config, 'SPECIAL_NODE_IDS', []):
        out[nid] = get_special_history(nid, hours)
    return out


def get_gateway_connections(special_node_id: int = None):
    """
    Return gateway connections for special nodes.
    
    If special_node_id is provided, return gateways connected to that node.
    Otherwise, return all gateway connections as dict special_node_id -> {gateway_node_id: connection_info}.
    
    Connection info includes gateway name, location, RSSI, SNR for drawing lines on map.
    """
    if special_node_id is not None:
        return special_node_gateways.get(special_node_id, {})
    
    return special_node_gateways


def get_special_node_packets(node_id=None, limit=50):
    """Return recent packets for special nodes.
    If node_id is None, return all special node packets.
    If node_id is provided, return packets for that specific node only.
    If limit is None, return all packets."""
    if node_id is not None:
        packets = special_node_packets.get(node_id, [])
        if limit is None:
            return list(packets)
        return list(packets)[-limit:]
    
    # Return all special node packets
    result = {}
    for nid, packets in special_node_packets.items():
        if limit is None:
            result[nid] = list(packets)
        else:
            result[nid] = list(packets)[-limit:]
    return result


def inject_telemetry_data(node_id, battery_level, channel_name="TEST", from_name="Test Node", message_type="telemetry"):
    """
    Inject fake telemetry or admin data for testing.
    Simulates receiving MQTT messages as if they came from a real node.
    
    Args:
        node_id: The node ID (integer)
        battery_level: Battery percentage (0-100)
        channel_name: Channel name (default "TEST")
        from_name: Node name for display (default "Test Node")
        message_type: Type of message - "telemetry" (TELEMETRY_APP) or "admin" (ADMIN_APP) (default "telemetry")
    
    Returns:
        bool: True if successful
    """
    try:
        import time
        
        if message_type.lower() == "admin":
            # ADMIN_APP message with deviceState containing battery
            fake_json = {
                "from": node_id,
                "type": "ADMIN_APP",
                "channel": 0,
                "channel_name": channel_name,
                "decoded": {
                    "portnum": "ADMIN_APP",
                    "payload": {
                        "deviceState": {
                            "power": {
                                "battery": battery_level,
                                "chargingCurrent": 0,
                                "flags": 0,
                                "observedCurrent": 0,
                                "voltage": 4200 if battery_level > 50 else 3800
                            }
                        }
                    }
                },
                "timestamp": int(time.time()),
                "rxTime": int(time.time()),
                "rxRssi": -100,
                "rxSnr": 0,
                "from_name": from_name
            }
        else:
            # TELEMETRY_APP message with device_metrics (default) - using snake_case to match protobuf
            fake_json = {
                "from": node_id,
                "type": "TELEMETRY_APP",
                "channel": 0,
                "channel_name": channel_name,
                "decoded": {
                    "portnum": "TELEMETRY_APP",
                    "payload": {
                        "device_metrics": {
                            "battery_level": battery_level,
                            "voltage": 4.0 if battery_level > 50 else 3.8,
                            "channel_utilization": 0.0,
                            "air_util_tx": 0.0,
                            "uptime_seconds": 1000000
                        }
                    }
                },
                "timestamp": int(time.time()),
                "rxTime": int(time.time()),
                "rxRssi": -100,
                "rxSnr": 0,
                "from_name": from_name
            }
        
        # Call the appropriate handler
        if message_type.lower() == "admin":
            on_telemetry(fake_json)  # Admin messages with power info also trigger telemetry handlers
        else:
            on_telemetry(fake_json)
        
        logger.info(f"Injected fake {message_type} telemetry: {from_name} (ID: {node_id}) battery={battery_level}%")
        return True
        
    except Exception as e:
        logger.error(f"Failed to inject telemetry data: {e}", exc_info=True)
        return False

