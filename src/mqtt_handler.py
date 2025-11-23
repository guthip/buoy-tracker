"""
Meshtastic MQTT Handler for Buoy Tracker
Uses meshtastic_mqtt_json library for MQTT connection and decryption
Tracks node positions, names, and last seen timestamps
"""

from meshtastic_mqtt_json import MeshtasticMQTT
import time
import logging
import json
from collections import deque
from . import config
from . import alerts
from pathlib import Path
import os
import math
import re

logger = logging.getLogger(__name__)

# MQTT client
client = None

# Dictionary to store node data: {node_id: {name, long_name, position, telemetry, last_seen}}
nodes_data = {}
# Ring buffer for recent raw messages for debugging
recent_messages = deque(maxlen=config.RECENT_MESSAGE_BUFFER_SIZE)
# Track if we've received any messages (more reliable than client.is_connected())
message_received = False
packets_received = False  # Track when we've received actual MQTT packets with data
last_message_time = 0

# Special nodes history: node_id -> deque of {ts, lat, lon, alt}
special_history = {}
_last_history_save = 0

# Store MQTT topic per node to extract channel name
node_topics = {}

# Special nodes packet tracking: store ALL packets for special nodes (no limit)
special_node_packets = {}  # node_id -> list of ALL packets with details
special_node_last_packet = {}  # node_id -> timestamp of last packet (any type, even encrypted)
special_node_channels = {}  # node_id -> channel_name from topic (for routing packets)
special_node_position_timestamps = {}  # node_id -> set of rxTime values to deduplicate retransmitted positions
_last_channel_save = 0  # Track when we last saved channel data
_last_packet_save = 0  # Track when we last saved packet history

def _is_special_node(node_id):
    """Check if a node_id is in the special nodes list."""
    return node_id in config.SPECIAL_NODES

def _track_special_node_packet(node_id, packet_type, json_data):
    """Track all packets from special nodes with detailed information."""
    if not _is_special_node(node_id):
        return
    
    if node_id not in special_node_packets:
        special_node_packets[node_id] = []  # Store ALL packets (no limit)
    
    packet_info = {
        'timestamp': time.time(),
        'packet_type': packet_type,
        'channel': json_data.get('channel'),
        'channel_name': json_data.get('channel_name', 'Unknown'),
        'portnum_name': json_data.get('portnum_name', 'Unknown')
    }
    
    # Extract detailed info based on packet type
    payload = json_data.get('decoded', {}).get('payload', {})
    
    if packet_type == 'NODEINFO_APP':
        packet_info.update({
            'role': payload.get('role'),
            'hw_model': payload.get('hwModel'),
            'long_name': payload.get('longName'),
            'short_name': payload.get('shortName')
        })
    elif packet_type == 'POSITION_APP':
        lat_i = payload.get('latitudeI')
        lon_i = payload.get('longitudeI')
        if lat_i and lon_i:
            packet_info.update({
                'lat': lat_i / 1e7,
                'lon': lon_i / 1e7,
                'altitude': payload.get('altitude')
            })
    elif packet_type == 'TELEMETRY_APP':
        device_metrics = payload.get('deviceMetrics', {})
        power_metrics = payload.get('powerMetrics', {})
        packet_info.update({
            'battery_level': device_metrics.get('batteryLevel'),
            'voltage': device_metrics.get('voltage'),
            'channel_utilization': device_metrics.get('channelUtilization'),
            'air_util_tx': device_metrics.get('airUtilTx'),
            'power_voltage': power_metrics.get('ch3Voltage'),
            'power_current': power_metrics.get('ch3Current')
        })
    elif packet_type == 'MAP_REPORT_APP':
        packet_info.update({
            'modem_preset': payload.get('modemPreset'),
            'region': payload.get('region'),
            'firmware_version': payload.get('firmwareVersion')
        })
    
    special_node_packets[node_id].append(packet_info)
    
    # Log special node packet arrival
    logger.info(f'SPECIAL NODE PACKET: {config.SPECIAL_NODES.get(node_id, node_id)} - {packet_type} on {packet_info["channel_name"]}')

def _extract_channel_name_from_topic(topic):
    """
    Extract channel name from MQTT topic path.
    Topic format: msh/US/bayarea/2/e/MediumFast/!nodeid
    Returns channel name (e.g., "MediumFast") or None if not found.
    """
    try:
        parts = topic.split('/')
        # Find the /e/ marker
        if 'e' in parts:
            e_index = parts.index('e')
            # Channel name should be right after 'e'
            if e_index + 1 < len(parts):
                channel_name = parts[e_index + 1]
                # It should not start with '!' (that's the node ID)
                if not channel_name.startswith('!'):
                    return channel_name
    except Exception as e:
        logger.debug(f"Failed to extract channel name from topic {topic}: {e}")
    return None


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

def _load_special_nodes_data():
    """
    Load unified special node data from single JSON file.
    Structure: {node_id: {info: {...}, position_history: [...], packets: [...]}}
    """
    logger.info("===== Loading unified special nodes data =====")
    path = Path(config.SPECIAL_HISTORY_PERSIST_PATH).parent / 'special_nodes.json'
    
    # Try new unified file first
    if path.exists():
        try:
            with path.open('r') as f:
                data = json.load(f)
            
            loaded_nodes = 0
            total_history = 0
            total_packets = 0
            
            for k, node_data in data.items():
                try:
                    node_id = int(k)
                    if not _is_special_node(node_id):
                        continue
                    
                    # Load position history
                    if 'position_history' in node_data:
                        dq = deque()
                        for e in node_data['position_history']:
                            if all(x in e for x in ('ts', 'lat', 'lon')):
                                dq.append({'ts': float(e['ts']), 'lat': float(e['lat']), 'lon': float(e['lon']), 'alt': e.get('alt')})
                        special_history[node_id] = dq
                        total_history += len(dq)
                    
                    # Load node info
                    if 'info' in node_data and isinstance(node_data['info'], dict):
                        nodes_data[node_id] = node_data['info']
                        
                        # Recalculate origin and movement based on CURRENT config
                        special_node_config = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
                        home_lat = special_node_config.get('home_lat')
                        home_lon = special_node_config.get('home_lon')
                        
                        if home_lat is not None and home_lon is not None:
                            nodes_data[node_id]["origin_lat"] = home_lat
                            nodes_data[node_id]["origin_lon"] = home_lon
                            
                            lat = nodes_data[node_id].get("latitude")
                            lon = nodes_data[node_id].get("longitude")
                            if lat is not None and lon is not None:
                                dist = _haversine_m(home_lat, home_lon, lat, lon)
                                nodes_data[node_id]["distance_from_origin_m"] = dist
                                nodes_data[node_id]["moved_far"] = bool(dist >= getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0))
                        
                        # Restore channel if present
                        if 'channel_name' in node_data['info']:
                            special_node_channels[node_id] = node_data['info']['channel_name']
                        
                        # Restore last_position_update from history if missing
                        if nodes_data[node_id].get("last_position_update") is None:
                            if node_id in special_history and len(special_history[node_id]) > 0:
                                most_recent = max(special_history[node_id], key=lambda x: x['ts'])
                                nodes_data[node_id]["last_position_update"] = most_recent['ts']
                                logger.info(f"Restored last_position_update for node {node_id} from history: {most_recent['ts']}")
                        
                        # Estimate battery from voltage if needed
                        if nodes_data[node_id].get("battery") is None:
                            voltage = None
                            telemetry = nodes_data[node_id].get("telemetry", {})
                            if telemetry and 'powerMetrics' in telemetry:
                                voltage = telemetry['powerMetrics'].get('ch3Voltage') or telemetry['powerMetrics'].get('ch1Voltage')
                            if voltage and 3.0 < voltage < 4.2:
                                battery = int(((voltage - 3.0) / 1.2) * 100)
                                nodes_data[node_id]["battery"] = battery
                    
                    # Load ALL packets (no limit)
                    if 'packets' in node_data and isinstance(node_data['packets'], list):
                        special_node_packets[node_id] = node_data['packets']
                        total_packets += len(node_data['packets'])
                        
                        if node_data['packets']:
                            special_node_last_packet[node_id] = node_data['packets'][-1].get('timestamp', 0)
                    
                    loaded_nodes += 1
                    
                except Exception as e:
                    logger.warning(f"Error loading data for node {k}: {e}")
                    continue
            
            logger.info(f"✅ Loaded unified data: {loaded_nodes} nodes, {total_history} history points, {total_packets} packets")
            return
            
        except Exception as e:
            logger.error(f"❌ Failed to load unified special nodes data from {path}")
            logger.error(f"   Error: {type(e).__name__}: {e}")
            if isinstance(e, json.JSONDecodeError):
                logger.error(f"   JSON error at line {e.lineno}, column {e.colno}")
                try:
                    with path.open('r') as f:
                        lines = f.readlines()
                        if e.lineno - 1 < len(lines):
                            logger.error(f"   Line {e.lineno}: {lines[e.lineno - 1].rstrip()}")
                except:
                    pass
            logger.warning(f"   Starting fresh with empty data")
            # Continue with empty data structures
            logger.info("Starting with empty data - unified file will be created on first save")

def _save_special_nodes_data(force=False):
    """
    Save unified special node data to single JSON file.
    Structure: {node_id: {info: {...}, position_history: [...], packets: [...]}}
    Only saves when force=True or when data has changed (with 5s minimum throttle to batch updates).
    """
    global _last_history_save
    now_ts = time.time()
    
    # Throttle to at minimum once every 5s to batch rapid updates
    if not force and (now_ts - _last_history_save) < 5:
        return
    
    try:
        path = Path(config.SPECIAL_HISTORY_PERSIST_PATH).parent / 'special_nodes.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 7-day retention: cutoff timestamp for old packets
        retention_days = 7
        cutoff_time = now_ts - (retention_days * 24 * 3600)
        
        data = {}
        total_removed = 0
        
        for node_id in config.SPECIAL_NODE_IDS:
            node_data = {}
            
            # Save node info
            if node_id in nodes_data:
                node_data['info'] = nodes_data[node_id]
            elif node_id in special_node_channels:
                node_data['info'] = {'channel_name': special_node_channels[node_id]}
            
            # Save position history with retention cleanup
            if node_id in special_history:
                history_list = list(special_history[node_id])
                before_count = len(history_list)
                # Keep only recent position history
                recent_history = [h for h in history_list if h.get('ts', 0) >= cutoff_time]
                node_data['position_history'] = recent_history
                removed = before_count - len(recent_history)
                if removed > 0:
                    total_removed += removed
                    # Update in-memory structure
                    special_history[node_id] = deque(recent_history, maxlen=10000)
            
            # Save packets with 7-day retention
            if node_id in special_node_packets:
                before_count = len(special_node_packets[node_id])
                # Keep only packets from last 7 days
                recent_packets = [p for p in special_node_packets[node_id] if p.get('timestamp', 0) >= cutoff_time]
                node_data['packets'] = recent_packets
                removed = before_count - len(recent_packets)
                if removed > 0:
                    total_removed += removed
                    # Update in-memory structure
                    special_node_packets[node_id] = recent_packets
            
            if node_data:  # Only save if we have some data
                data[str(node_id)] = node_data
        
        # Atomic write: write to temp file first, then rename to prevent corruption on crash
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, suffix='.tmp') as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = tmp.name
        
        # Atomic rename (overwrites destination on POSIX systems)
        Path(tmp_path).replace(path)
        
        _last_history_save = now_ts
        
        # Count totals for logging
        total_history = sum(len(node_data.get('position_history', [])) for node_data in data.values())
        total_packets = sum(len(node_data.get('packets', [])) for node_data in data.values())
        if total_removed > 0:
            logger.info(f"✅ Saved unified data: {len(data)} nodes, {total_history} history points, {total_packets} packets (removed {total_removed} old entries)")
        else:
            logger.debug(f"✅ Saved unified data: {len(data)} nodes, {total_history} history points, {total_packets} packets")
        
    except Exception as e:
        logger.warning(f"Failed to save unified special nodes data: {e}")

# Legacy load functions (for migration from old format)
# Load any existing data on import using unified loader
print("***** About to call _load_special_nodes_data() *****")
_load_special_nodes_data()
print("***** All load functions completed *****")


def add_recent(json_data):
    try:
        global message_received, packets_received, last_message_time
        message_received = True
        packets_received = True  # We've received an actual MQTT packet
        last_message_time = time.time()
        # store a lightweight copy with timestamp
        recent_messages.appendleft({
            "ts": time.time(),
            "msg": json_data
        })
    except Exception:
        # be defensive: ignore any non-serializable parts
        try:
            recent_messages.appendleft({"ts": time.time(), "msg": str(json_data)})
        except Exception:
            pass


def get_recent_messages(limit=100):
    """Return recent messages as a list (most-recent first)."""
    out = []
    for item in list(recent_messages)[:limit]:
        out.append({"ts": item["ts"], "msg": item["msg"]})
    return out


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


def on_nodeinfo(json_data):
    """Process node info messages - update node names."""
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()
    
    try:
        logger.debug(f'on_nodeinfo callback fired - processing message')
        add_recent(json_data)
        payload = json_data["decoded"]["payload"]
        node_id = json_data.get("from")
        channel = json_data.get("channel")
        channel_name = json_data.get("channel_name", "Unknown")
        
        # Track special node packets and channel info
        if node_id:
            if _is_special_node(node_id):
                special_node_last_packet[node_id] = time.time()
                # Update channel name if different
                if special_node_channels.get(node_id) != channel_name:
                    special_node_channels[node_id] = channel_name
                    _save_special_nodes_data()
            _track_special_node_packet(node_id, 'NODEINFO_APP', json_data)
            _save_special_nodes_data()  # Save packet history after tracking
        
        role = payload.get("role") if isinstance(payload, dict) else None
        
        if node_id:
            if node_id not in nodes_data:
                nodes_data[node_id] = {}
            
            if channel is not None:
                nodes_data[node_id]["channel"] = channel
            if role:
                nodes_data[node_id]["role"] = role
            
            # Store channel name from topic
            nodes_data[node_id]["channel_name"] = channel_name
            
            # Try to capture modem preset if present (though unlikely to be in packets)
            preset = _extract_modem_preset(payload)
            if preset:
                nodes_data[node_id]["modem_preset"] = preset
            
            # Flexible extraction for name fields - payload shapes vary across nodes
            def extract_name(p):
                # dict-like payloads
                if isinstance(p, dict):
                    for k in ("longName", "longname", "long_name", "name", "deviceName", "displayName", "shortName", "short_name"):
                        v = p.get(k)
                        if isinstance(v, str) and v.strip():
                            return v.strip()
                    # search nested values for a likely name
                    for v in p.values():
                        if isinstance(v, str) and len(v.strip()) > 1 and any(c.isalpha() for c in v):
                            return v.strip()
                    return None
                # string payloads: try JSON decode, fallback to simple parse
                if isinstance(p, str):
                    try:
                        parsed = json.loads(p)
                        return extract_name(parsed)
                    except Exception:
                        # try common delimiter
                        if ":" in p:
                            return p.split(":", 1)[1].strip()
                        return p.strip()
                return None

            name = extract_name(payload)
            short = None
            if name:
                # produce a short name if not explicit
                if " " in name:
                    short = name.split()[0]
                else:
                    short = name[:8]

            # Safely extract fields from payload (might be dict or string)
            if isinstance(payload, dict):
                nodes_data[node_id]["long_name"] = name or payload.get("longName") or "Unknown"
                nodes_data[node_id]["short_name"] = short or payload.get("shortName") or "?"
                nodes_data[node_id]["hw_model"] = payload.get("hwModel", "Unknown")
            else:
                nodes_data[node_id]["long_name"] = name or "Unknown"
                nodes_data[node_id]["short_name"] = short or "?"
                nodes_data[node_id]["hw_model"] = "Unknown"
            nodes_data[node_id]["last_seen"] = time.time()
            
            logger.info(f'Updated nodeinfo for {node_id}: {nodes_data[node_id]["long_name"]}')
            
            # Save node data if it's a special node
            if _is_special_node(node_id):
                _save_special_nodes_data()
    except Exception as e:
        logger.error(f'Error processing nodeinfo: {e}')


def on_position(json_data):
    """Process position messages - update node coordinates."""
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()
    
    try:
        logger.debug(f'on_position callback fired - processing message')
        add_recent(json_data)
        payload = json_data["decoded"]["payload"]
        node_id = json_data.get("from")
        channel = json_data.get("channel")
        channel_name = json_data.get("channel_name", "Unknown")
        
        # Track special node packets and channel info
        if node_id:
            if _is_special_node(node_id):
                special_node_last_packet[node_id] = time.time()
                # Update channel name if different
                if special_node_channels.get(node_id) != channel_name:
                    special_node_channels[node_id] = channel_name
                    _save_special_nodes_data()
            _track_special_node_packet(node_id, 'POSITION_APP', json_data)
            _save_special_nodes_data()  # Save packet history after tracking
        
        if node_id and "latitudeI" in payload and "longitudeI" in payload:
            if node_id not in nodes_data:
                nodes_data[node_id] = {}
            
            # Store channel if available
            if channel is not None:
                nodes_data[node_id]["channel"] = channel
            
            # Store channel name from topic
            nodes_data[node_id]["channel_name"] = channel_name
            
            # For movement alerts on special nodes, track origin and distance
            try:
                if node_id in getattr(config, 'SPECIAL_NODE_IDS', []):
                    lat = payload["latitudeI"] / 1e7
                    lon = payload["longitudeI"] / 1e7
                    
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
            except Exception:
                pass
            
            # Convert from integer coordinates to decimal degrees
            lat = payload["latitudeI"] / 1e7
            lon = payload["longitudeI"] / 1e7
            alt = payload.get("altitude", 0)
            
            nodes_data[node_id]["latitude"] = lat
            nodes_data[node_id]["longitude"] = lon
            nodes_data[node_id]["altitude"] = alt
            nodes_data[node_id]["last_seen"] = time.time()
            nodes_data[node_id]["last_position_update"] = time.time()  # Track position updates separately
            
            # Record history for special nodes (deduplicate by rxTime to avoid retransmitted packets)
            if node_id in getattr(config, 'SPECIAL_NODE_IDS', []):
                # Extract rxTime from the packet to deduplicate retransmissions
                rx_time = json_data.get("rxTime")
                
                # Initialize deduplication set for this node if needed
                if node_id not in special_node_position_timestamps:
                    special_node_position_timestamps[node_id] = set()
                
                # Only add to history if we haven't seen this rxTime before
                if rx_time is not None and rx_time not in special_node_position_timestamps[node_id]:
                    _ensure_history_struct(node_id)
                    entry = {"ts": time.time(), "lat": lat, "lon": lon, "alt": alt}
                    special_history[node_id].append(entry)
                    special_node_position_timestamps[node_id].add(rx_time)
                    _prune_history(node_id, now_ts=entry['ts'])
                    _save_special_nodes_data()
                    logger.debug(f'Added new position to history for {node_id} (rxTime: {rx_time})')
                elif rx_time is not None:
                    logger.debug(f'Skipped duplicate position for {node_id} (rxTime: {rx_time} already seen)')
                else:
                    # No rxTime available, add anyway (shouldn't happen but be safe)
                    _ensure_history_struct(node_id)
                    entry = {"ts": time.time(), "lat": lat, "lon": lon, "alt": alt}
                    special_history[node_id].append(entry)
                    _prune_history(node_id, now_ts=entry['ts'])
                    _save_special_nodes_data()
            
            logger.info(f'Updated position for {node_id}: {lat:.4f}, {lon:.4f}')
    except Exception as e:
        logger.error(f'Error processing position: {e}')


def on_telemetry(json_data):
    """Process telemetry messages - battery level, etc."""
    global message_received, last_message_time
    message_received = True
    last_message_time = time.time()
    
    try:
        add_recent(json_data)
        payload = json_data["decoded"]["payload"]
        node_id = json_data.get("from")
        channel_name = json_data.get("channel_name", "Unknown")
        
        # Track special node packets and channel info
        if node_id:
            if _is_special_node(node_id):
                special_node_last_packet[node_id] = time.time()
                # Update channel name if different
                if special_node_channels.get(node_id) != channel_name:
                    special_node_channels[node_id] = channel_name
                    _save_special_nodes_data()
            _track_special_node_packet(node_id, 'TELEMETRY_APP', json_data)
            _save_special_nodes_data()  # Save packet history after tracking
        
        if node_id:
            if node_id not in nodes_data:
                nodes_data[node_id] = {}
            
            # Store channel name from topic
            nodes_data[node_id]["channel_name"] = channel_name
            
            nodes_data[node_id]["telemetry"] = payload
            nodes_data[node_id]["last_seen"] = time.time()
            # flexible battery extraction
            battery = None
            try:
                if isinstance(payload, dict):
                    # Try TELEMETRY_APP format first: deviceMetrics.batteryLevel
                    battery = payload.get("deviceMetrics", {}).get("batteryLevel")
                    
                    # Try ADMIN_APP format: deviceState.power.battery
                    if battery is None:
                        battery = payload.get("deviceState", {}).get("power", {}).get("battery")
                    
                    if battery is None:
                        battery = payload.get("battery") or payload.get("batt")
                    # some payloads put metrics under 'metrics' or 'device_metrics'
                    if battery is None:
                        battery = payload.get("metrics", {}).get("batteryLevel") or payload.get("device_metrics", {}).get("batteryLevel")
                    
                    # If no battery level found, try to estimate from voltage
                    # Priority: powerMetrics (SYCS), admin power metrics, deviceMetrics
                    if battery is None:
                        voltage = None
                        # SYCS priority: check powerMetrics ch3Voltage first (power monitoring data)
                        power_metrics = payload.get("powerMetrics", {})
                        if power_metrics:
                            voltage = power_metrics.get("ch3Voltage") or power_metrics.get("ch1Voltage")
                        
                        # If no powerMetrics, check admin power format voltage
                        if voltage is None:
                            admin_voltage = payload.get("deviceState", {}).get("power", {}).get("voltage")
                            if admin_voltage:
                                voltage = admin_voltage / 1000.0  # Admin format uses mV
                        
                        # Fall back to deviceMetrics voltage
                        if voltage is None:
                            device_metrics = payload.get("deviceMetrics", {})
                            voltage = device_metrics.get("voltage") if device_metrics else None
                        
                        # Estimate battery percentage from voltage (LiPo: 4.2V=100%, 3.0V=0%)
                        if voltage is not None and isinstance(voltage, (int, float)):
                            if voltage >= 4.2:
                                battery = 100
                            elif voltage <= 3.0:
                                battery = 0
                            else:
                                # Linear approximation between 3.0V and 4.2V
                                battery = int(((voltage - 3.0) / 1.2) * 100)
                
                # coerce to int if it's numeric string
                if isinstance(battery, str) and battery.isdigit():
                    battery = int(battery)
                if isinstance(battery, (float, int)):
                    nodes_data[node_id]["battery"] = int(battery)
                else:
                    # leave as-is or unknown
                    nodes_data[node_id]["battery"] = None
            except Exception:
                nodes_data[node_id]["battery"] = None
            logger.info(f'Updated telemetry for {node_id}: battery={nodes_data[node_id].get("battery")}%')
            
            # Check for battery alert if this is a special node
            if _is_special_node(node_id):
                battery_level = nodes_data[node_id].get("battery")
                if battery_level is not None and battery_level < config.LOW_BATTERY_THRESHOLD:
                    from . import alerts
                    node_data = nodes_data[node_id]
                    alerts.send_battery_alert(node_id, node_data, battery_level)
            
            # Save node data if it's a special node
            if _is_special_node(node_id):
                _save_special_nodes_data()
    except Exception as e:
        logger.error(f'Error processing telemetry: {e}')


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
        add_recent(json_data)
        payload = json_data["decoded"]["payload"]
        node_id = json_data.get("from")
        channel_name = json_data.get("channel_name", "Unknown")
        
        # Track special node packets and channel info
        if node_id:
            if _is_special_node(node_id):
                special_node_last_packet[node_id] = time.time()
                # Update channel name if different
                if special_node_channels.get(node_id) != channel_name:
                    special_node_channels[node_id] = channel_name
                    _save_special_nodes_data()
            _track_special_node_packet(node_id, 'MAP_REPORT_APP', json_data)
            _save_special_nodes_data()  # Save packet history after tracking
        
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


def connect_mqtt():
    """Connect to MQTT broker using meshtastic_mqtt_json library.
    
    This library handles encryption/decryption automatically and provides
    callbacks for different message types.
    """
    global client
    
    # Don't create multiple connections
    if client is not None:
        logger.debug('MQTT client already exists, skipping connection')
        return
    
    def _do_connect():
        """Actually perform the MQTT connection (may block)."""
        global client, message_received, last_message_time
        try:
            # Create MeshtasticMQTT client
            logger.info('Creating MeshtasticMQTT client instance')
            client = MeshtasticMQTT()
            
            # Register callbacks for each message type
            logger.info('Registering MQTT callbacks')
            client.register_callback('NODEINFO_APP', on_nodeinfo)
            client.register_callback('POSITION_APP', on_position)
            client.register_callback('TELEMETRY_APP', on_telemetry)
            client.register_callback('NEIGHBORINFO_APP', on_neighborinfo)
            client.register_callback('MAP_REPORT_APP', on_mapreport)
            logger.info('Callbacks registered successfully')
            
            # Connect to broker and subscribe to all configured channels
            # The library will handle decryption automatically for each channel
            logger.info(f'Connecting to MQTT broker: {config.MQTT_BROKER}:{config.MQTT_PORT}')
            logger.info(f'Monitoring channels: {", ".join(config.MQTT_CHANNELS)}')
            
            # The MeshtasticMQTT library only handles one channel per connect() call
            # To receive from multiple channels, we need to manually subscribe to each
            # First, connect to the primary broker (sets up paho-mqtt client internally)
            first_channel = config.MQTT_CHANNELS[0] if config.MQTT_CHANNELS else 'MediumFast'
            logger.info(f'Primary channel: {first_channel}')
            client.connect(
                broker=config.MQTT_BROKER,
                port=config.MQTT_PORT,
                root=config.MQTT_ROOT_TOPIC.rstrip('/') + '/',
                channel=first_channel,
                username=config.MQTT_USERNAME if config.MQTT_USERNAME else None,
                password=config.MQTT_PASSWORD if config.MQTT_PASSWORD else None,
                key=config.MQTT_KEY if hasattr(config, 'MQTT_KEY') else 'AQ=='
            )
            logger.info('Primary channel connection established')
            
            # Manually subscribe to all channels (including first) to ensure we get all packets
            # Topic format: msh/region/area/channel_id/e/CHANNEL_NAME/#
            root = config.MQTT_ROOT_TOPIC.rstrip('/')
            for channel in config.MQTT_CHANNELS:
                topic = f"{root}/{channel}/#"
                try:
                    if hasattr(client, '_client') and client._client:
                        client._client.subscribe(topic)
                        logger.info(f"Subscribed to channel topic: {topic}")
                    else:
                        logger.warning(f"Client not ready for channel subscription: {channel}")
                except Exception as e:
                    logger.error(f"Failed to subscribe to channel {channel}: {e}")
            
            # Ensure background loop is running for paho-mqtt client
            # The MeshtasticMQTT wrapper uses paho-mqtt internally
            if hasattr(client._client, 'loop_start'):
                try:
                    client._client.loop_start()
                    logger.info('MQTT background loop started')
                except Exception as e:
                    logger.warning(f'Could not start explicit MQTT loop: {e}')
            
            logger.info('MQTT client connected and callbacks registered')
            
            # Mark as receiving messages (will be updated by callbacks)
            message_received = True
            last_message_time = time.time()
            
        except Exception as e:
            logger.error(f'Failed to connect to MQTT broker: {e}')
            client = None
            raise
    
    # Run the actual connection in the background to avoid blocking
    import threading
    thread = threading.Thread(target=_do_connect, daemon=True)
    thread.start()
    logger.info('MQTT connection thread started')


def disconnect_mqtt():
    """Disconnect from MQTT broker."""
    global client
    try:
        if client:
            # Save all persisted data before disconnecting
            _save_special_nodes_data(force=True)
            client.disconnect()
            logger.info("Disconnected from MQTT broker")
    except Exception as e:
        logger.error(f'Error disconnecting from MQTT broker: {e}')


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
    """Check if MQTT client is connected with three stages.
    Returns 'receiving_packets' once we receive actual MQTT packets,
    'connected_to_server' once we receive the first MQTT message,
    'connecting' if client exists but no messages yet,
    'disconnected' otherwise."""
    try:
        # If we have received actual packets, we're fully connected
        if packets_received:
            return 'receiving_packets'
        
        # If we have received any messages at all, we're connected to server
        if message_received:
            return 'connected_to_server'
        
        # If client exists but no messages yet, we're connecting
        if client is not None:
            return 'connecting'
        
        # No client and no messages
        return 'disconnected'
    except Exception:
        return 'disconnected'


def get_nodes():
    """Return list of all tracked nodes with status."""
    result = []
    current_time = time.time()
    
    present_ids = set()
    for node_id, data in nodes_data.items():
        last_seen = data.get("last_seen", current_time)
        time_since_seen = current_time - last_seen
        
        # Determine status based on time since last seen (using config thresholds)
        if time_since_seen < config.STATUS_BLUE_THRESHOLD:
            status = "blue"  # Newly seen
        elif time_since_seen < config.STATUS_ORANGE_THRESHOLD:
            status = "orange"  # Seen recently
        else:
            status = "red"  # Not seen for a long time
        
        # Check if this is a special node (based on config)
        is_special = node_id in getattr(config, 'SPECIAL_NODE_IDS', [])
        special_symbol = None
        special_label = None
        if is_special:
            info = getattr(config, 'SPECIAL_NODES', {}).get(node_id, {})
            special_symbol = info.get('symbol', getattr(config, 'SPECIAL_NODE_SYMBOL', '⭐'))
            special_label = info.get('label')
        
        stale = time_since_seen > getattr(config, 'STALE_AFTER_SECONDS', config.STATUS_ORANGE_THRESHOLD)
        
        # Get channel name from MQTT topic and modem preset from packet
        # For special nodes, prefer channel from routing packets (special_node_channels) as it's more current
        if is_special and node_id in special_node_channels:
            channel_name = special_node_channels[node_id]
        else:
            channel_name = data.get("channel_name")
        modem_preset = data.get("modem_preset")

        node_info = {
            "id": node_id,
            "name": data.get("long_name") or data.get("longName") or "Unknown",
            "short": data.get("short_name") or data.get("shortName") or "?",
            "lat": data.get("latitude"),
            "lon": data.get("longitude"),
            "alt": data.get("altitude"),
            "hw_model": data.get("hw_model", "Unknown"),
            "channel": data.get("channel"),
            "channel_name": channel_name,
            "modem_preset": modem_preset,
            "role": data.get("role"),
            # origin location for movement circle (only present for special nodes after first fix)
            "origin_lat": data.get("origin_lat"),
            "origin_lon": data.get("origin_lon"),
            "status": status,
            "is_special": is_special,
            "stale": stale,
            "has_fix": (data.get("latitude") is not None and data.get("longitude") is not None),
            "special_symbol": special_symbol,
            "special_label": special_label,
            "time_since_seen": time_since_seen,
            "last_seen": last_seen,
            "last_position_update": data.get("last_position_update"),  # Separate timestamp for position updates
            # battery may have been normalized earlier
            "battery": data.get("battery") if data.get("battery") is not None else None,
            # human-friendly age in minutes
            "age_min": int(time_since_seen / 60),
            # movement alert fields (special nodes)
            "moved_far": data.get("moved_far", False),
            "distance_from_origin_m": data.get("distance_from_origin_m"),
        }
        
        # Extract voltage from telemetry (prefer powerMetrics over deviceMetrics)
        telemetry = data.get("telemetry", {})
        if isinstance(telemetry, dict):
            power_metrics = telemetry.get("powerMetrics", {})
            device_metrics = telemetry.get("deviceMetrics", {})
            # Prefer ch3Voltage from powerMetrics, fall back to voltage from deviceMetrics
            node_info["voltage"] = power_metrics.get("ch3Voltage") or device_metrics.get("voltage")
            node_info["power_current"] = power_metrics.get("ch3Current")
        
        # Check for low battery
        battery_level = node_info.get("battery")
        node_info["battery_low"] = (
            battery_level is not None and 
            battery_level < getattr(config, 'LOW_BATTERY_THRESHOLD', 50)
        )
        
        # Add last packet time for special nodes (any packet, even encrypted/routing)
        if is_special and node_id in special_node_last_packet:
            node_info["last_packet_time"] = special_node_last_packet[node_id]
        
        # Only include nodes with location data
        if node_info["lat"] is not None and node_info["lon"] is not None:
            result.append(node_info)
            present_ids.add(node_id)
    
    # Include offline special nodes at their home positions (if defined)
    if getattr(config, 'SPECIAL_SHOW_OFFLINE', True):
        for sid in getattr(config, 'SPECIAL_NODE_IDS', []):
            if sid not in present_ids:
                info = getattr(config, 'SPECIAL_NODES', {}).get(sid, {})
                home_lat = info.get('home_lat')
                home_lon = info.get('home_lon')
                node_dict = {
                    "id": sid,
                    "name": info.get('label') or f"Node {sid}",
                    "short": info.get('label') or "?",
                    "lat": home_lat,  # Show at home position
                    "lon": home_lon,  # Show at home position
                    "alt": None,
                    "hw_model": "Unknown",
                    "channel": None,
                    "channel_name": special_node_channels.get(sid),  # Use channel from routing packets
                    "modem_preset": None,
                    "role": None,
                    "origin_lat": home_lat,  # Home is the origin
                    "origin_lon": home_lon,
                    "status": "gray",
                    "is_special": True,
                    "stale": True,
                    "has_fix": False,  # No real GPS fix yet
                    "special_symbol": info.get('symbol', getattr(config, 'SPECIAL_NODE_SYMBOL', '⭐')),
                    "special_label": info.get('label'),
                    "time_since_seen": None,
                    "last_seen": None,
                    "battery": None,
                    "age_min": None,
                    "moved_far": False,
                    "distance_from_origin_m": None,
                }
                # Add last packet time if we've seen ANY packets
                if sid in special_node_last_packet:
                    node_dict["last_packet_time"] = special_node_last_packet[sid]
                result.append(node_dict)

    return result


def get_special_history(node_id: int, hours: int = None):
    hours = hours or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
    dq = special_history.get(node_id, deque())
    if not dq:
        return []
    cutoff = time.time() - (hours * 3600)
    filtered = [e for e in dq if e['ts'] >= cutoff]
    # Limit to 100 most recent datapoints
    return filtered[-100:] if len(filtered) > 100 else filtered

def get_all_special_history(hours: int = None):
    """Return history for all special nodes as dict node_id -> list of points."""
    hours = hours or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
    out = {}
    for nid in getattr(config, 'SPECIAL_NODE_IDS', []):
        out[nid] = get_special_history(nid, hours)
    return out


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


def get_recent(limit=100):
    return get_recent_messages(limit)


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
                "timestamp": int(time.time() * 1000),
                "rxTime": int(time.time()),
                "rxRssi": -100,
                "rxSnr": 0,
                "from_name": from_name
            }
        else:
            # TELEMETRY_APP message with deviceMetrics (default)
            fake_json = {
                "from": node_id,
                "type": "TELEMETRY_APP",
                "channel": 0,
                "channel_name": channel_name,
                "decoded": {
                    "portnum": "TELEMETRY_APP",
                    "payload": {
                        "deviceMetrics": {
                            "batteryLevel": battery_level,
                            "voltage": 4.0 if battery_level > 50 else 3.8,
                            "channelUtilization": 0.0,
                            "airUtilTx": 0.0,
                            "uptimeSeconds": 1000000
                        }
                    }
                },
                "timestamp": int(time.time() * 1000),
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

