"""API view layer: builds the /api/nodes payload and history responses.

Pure read/aggregate functions over the tracker state owned by mqtt_handler
(accessed at call time via the module handle, so live state is always seen).
Moved out of mqtt_handler.py in the v2.0 refactor; mqtt_handler re-exports
these names so existing call sites and tests are unchanged.
"""

import logging
import time
from collections import deque

from . import config
from . import storage
from . import mqtt_handler as mh

logger = logging.getLogger(__name__)


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
    if is_special and node_id in mh.special_node_channels:
        return mh.special_node_channels[node_id]
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

# Anchoring-quality statistic: spread of the last week's fixes around their
# centroid. Cheap query, but no need to rerun it on every 10 s poll.
_ANCHOR_WINDOW_S = 7 * 86400
_ANCHOR_CACHE_TTL_S = 120
_anchor_cache = {}


def _get_anchor_spread_cached(node_id):
    now = time.time()
    hit = _anchor_cache.get(node_id)
    if hit and now - hit[0] < _ANCHOR_CACHE_TTL_S:
        return hit[1]
    spread = storage.get_anchor_spread(node_id, now - _ANCHOR_WINDOW_S)
    _anchor_cache[node_id] = (now, spread)
    return spread


def _gateway_reliability_fields(gateway_id):
    """The 4 gateway-reliability fields, in one place.

    Previously each of _build_node_info_from_data and _build_gateway_only_node
    read mh.gateway_reliability_cache and listed these fields independently;
    they'd already drifted (avg_rssi was gateway-only-exclusive, and a
    regular node that's also a gateway never got it) before this existed.
    """
    cached = mh.gateway_reliability_cache.get(gateway_id, {})
    return {
        "reliability_score": cached.get("score", 0),
        "detection_count": cached.get("detection_count", 0),
        "avg_rssi": cached.get("avg_rssi"),
        "confidence_level": cached.get("confidence_level", "none"),
    }


def _build_gateway_connections_list(node_id):
    """Build list of gateway connections with reliability scores for a special node."""
    gateway_connections = []
    for gw_id, gw_info in mh.special_node_gateways[node_id].items():
        cached_reliability = mh.gateway_reliability_cache.get(gw_id, {})
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
        "stale": stale,
        "has_fix": (data.get("latitude") is not None and data.get("longitude") is not None),
        "special_symbol": special_symbol,
        "special_label": special_label,
        "time_since_seen": time_since_seen,
        "last_seen": last_seen,
        "last_position_update": data.get("last_position_update"),
        "battery_pct": data.get("battery_pct"),
        "age_min": int(time_since_seen / 60),
        "moved_far": data.get("moved_far", False),
        "distance_from_origin_m": data.get("distance_from_origin_m"),
        "movement_alerts_muted": storage.is_movement_muted(node_id) if is_special else False,
        "voltage": mh._get_node_voltage(node_id),
    }

    # Add power current for special (power-sensor) nodes
    telemetry = data.get("telemetry", {})
    if isinstance(telemetry, dict):
        power_metrics = telemetry.get("power_metrics", {})
        node_info["power_current"] = power_metrics.get("ch3_current")

    battery_pct = node_info.get("battery_pct")
    node_info["battery_low"] = (
        battery_pct is not None and
        battery_pct < getattr(config, 'LOW_BATTERY_THRESHOLD', 50)
    )

    # Anchoring quality for special nodes (shown alongside distance-to-home
    # while the statistic is being evaluated)
    if is_special:
        spread = _get_anchor_spread_cached(node_id)
        node_info["anchor_spread_m"] = round(spread["spread_m"], 1) if spread else None
        node_info["anchor_spread_n"] = spread["count"] if spread else 0

    # Add gateway connections for special nodes
    if is_special and node_id in mh.special_node_gateways:
        node_info["gateway_connections"] = _build_gateway_connections_list(node_id)
    else:
        node_info["gateway_connections"] = []

    # Add best gateway info for special nodes
    if is_special and "best_gateway" in data:
        node_info["best_gateway"] = data["best_gateway"]

    # Determine if this node is a gateway
    is_gw = mh.node_is_gateway.get(node_id, False) or node_id in mh.all_gateway_node_ids
    node_info["is_gateway"] = is_gw

    # Reliability summary for the gateway details view (gateway-only nodes
    # get the same fields, from the same helper, in _build_gateway_only_node)
    if is_gw:
        node_info.update(_gateway_reliability_fields(node_id))

    # Set name fallback based on gateway status
    if not node_name:
        node_info["name"] = f"Gateway {node_id}" if is_gw else "Unknown"

    # Add last packet time for special nodes
    if is_special and node_id in mh.special_node_last_packet:
        node_info["last_packet_time"] = mh.special_node_last_packet[node_id]

    return node_info

def _build_gateway_only_node(gateway_id, current_time):
    """Build node_info dictionary for a gateway that hasn't sent its own data.

    Field set is meant to match _build_node_info_from_data's output for an
    equivalent non-special node (frontend code doesn't special-case which
    builder produced a given node). The two have already drifted apart
    more than once without a test to catch it — see
    tests/test_api_views.py::test_gateway_only_node_matches_regular_node_schema.
    """
    gw_info = mh.gateway_info_cache.get(gateway_id)
    if gw_info is None:
        return None

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
        "battery_pct": None,
        "battery_low": False,
        "age_min": int((current_time - gw_info.get("last_seen", current_time)) / 60),
        "moved_far": False,
        "distance_from_origin_m": None,
        "movement_alerts_muted": False,
        "voltage": None,
        "power_current": None,
        "is_gateway": True,
        "gateway_connections": [],
        **_gateway_reliability_fields(gateway_id),
    }

def get_nodes():
    """Return list of all tracked nodes with status."""
    result = []
    current_time = time.time()

    for node_id, data in mh.nodes_data.items():
        is_special = node_id in getattr(config, 'SPECIAL_NODE_IDS', [])

        # Skip non-special, non-gateway nodes when show_all_nodes is disabled
        if not getattr(config, 'SHOW_ALL_NODES', False):
            if not is_special:
                is_gateway_check = mh.node_is_gateway.get(node_id, False) or node_id in mh.all_gateway_node_ids
                if not is_gateway_check:
                    continue

        # Build complete node info dictionary using helper
        node_info = _build_node_info_from_data(node_id, data, is_special, current_time)
        result.append(node_info)

    # Add gateways that aren't already in result
    result_ids = {n['id'] for n in result}
    for gateway_id in mh.all_gateway_node_ids:
        if gateway_id not in result_ids:
            gateway_node = _build_gateway_only_node(gateway_id, current_time)
            if gateway_node:
                result.append(gateway_node)

    return result

def get_special_history(node_id: int, hours: int = None):
    """
    Get deduplicated position history for a special node.

    Each returned point carries both `voltage` (raw sample) and `battery_pct`
    (derived from voltage via the single mh._estimate_battery_from_voltage curve),
    so clients never need to recompute percentages.

    Returns:
        List of dicts: {ts, lat, lon, alt, voltage, battery_pct}
    """
    hours = hours or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
    cutoff = time.time() - (hours * 3600)

    dq = mh.special_history.get(node_id, deque())
    filtered = [e for e in dq if e['ts'] >= cutoff]
    deduped = _deduplicate_by_hour(filtered)

    result = []
    for e in deduped:
        v = e.get('voltage')
        result.append({
            'ts': e['ts'],
            'lat': e.get('lat'),
            'lon': e.get('lon'),
            'alt': e.get('alt'),
            'voltage': v,
            'battery_pct': mh._estimate_battery_from_voltage(v) if v is not None else None,
        })
    return result

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


