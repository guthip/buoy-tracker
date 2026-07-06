"""Gateway tracking: connection recording, reliability scoring, name sync.

Which gateways hear which buoys, with what confidence. Feeds the map's
gateway circles/lines and the gateway detail views. Tracker state stays
owned by mqtt_handler and is accessed at call time via the module handle
(same pattern as api_views). Split out of mqtt_handler.py in v2.1.
"""

import logging
import time

from . import config
from . import mqtt_handler as mh
from .topics import gateway_id_from_topic

logger = logging.getLogger(__name__)


def _record_gateway_connection(special_node_id, gateway_node_id, json_data, confidence="direct"):
    """
    Record that a gateway received a packet from a special node.
    Tracks gateways with confidence level (direct vs partial hop data).
    Updates "best gateway" based on strongest RSSI.
    Also marks the gateway node itself as a gateway in mh.nodes_data.
    
    Args:
        special_node_id: The special node that sent the packet
        gateway_node_id: The node that received it (ideally directly, may have incomplete hop data)
        json_data: The packet data with RSSI/SNR info
        confidence: "direct" (hop_start==hop_limit) or "partial" (hop data missing/incomplete)
    """
    if special_node_id not in mh.special_node_gateways:
        mh.special_node_gateways[special_node_id] = {}
    
    # Mark this node as a gateway (it received a packet from a special node)
    if gateway_node_id not in mh.nodes_data:
        mh.nodes_data[gateway_node_id] = {}
    mh.nodes_data[gateway_node_id]["is_gateway"] = True
    mh.node_is_gateway[gateway_node_id] = True
    logger.debug(f"Node {gateway_node_id} marked as gateway (received from special node {special_node_id}, confidence={confidence})")

    # Get gateway info from mh.nodes_data AFTER ensuring it exists
    gateway_info = mh.nodes_data.get(gateway_node_id, {})

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
    mh.special_node_gateways[special_node_id][gateway_node_id] = connection_info

    # Update the gateway's own node_data with latest signal and timestamp
    mh.nodes_data[gateway_node_id]["last_seen"] = time.time()
    if json_data.get("rx_rssi") is not None:
        mh.nodes_data[gateway_node_id]["rx_rssi"] = json_data["rx_rssi"]
    if json_data.get("rx_snr") is not None:
        mh.nodes_data[gateway_node_id]["rx_snr"] = json_data["rx_snr"]

    # Track best gateway: the one with strongest RSSI for this special node
    # rssi is negative, so higher (less negative) = stronger
    # Prefer direct-hop detections over partial detections
    current_best = mh.nodes_data.get(special_node_id, {}).get("best_gateway", {})
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
        # Ensure node exists in mh.nodes_data before updating
        if special_node_id not in mh.nodes_data:
            mh.nodes_data[special_node_id] = {}
        # This is the strongest gateway so far
        mh.nodes_data[special_node_id]["best_gateway"] = {
            "id": gateway_node_id,
            "name": connection_info["name"],
            "lat": connection_info["lat"],
            "lon": connection_info["lon"],
            "rssi": incoming_rssi,
            "snr": connection_info["snr"],
        }
        mh.nodes_data[special_node_id]["best_gateway_rssi"] = incoming_rssi
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
    if not mh._is_special_node(special_node_id):
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
    gateway_node_id = gateway_id_from_topic(mqtt_topic)
    logger.debug(f"Gateway extraction: mqtt_topic={mqtt_topic}, extracted_id={gateway_node_id}, hop_start={hop_start}, hop_limit={hop_limit}, rssi={rx_rssi}")
    if gateway_node_id:
        # Ensure first-hop receiver entry exists in mh.nodes_data
        if gateway_node_id not in mh.nodes_data:
            mh.nodes_data[gateway_node_id] = {}
        # Record the gateway as direct reception (only type we accept)
        _record_gateway_connection(special_node_id, gateway_node_id, json_data, confidence="direct")
        logger.debug(f"Gateway detected: {gateway_node_id} received direct from special_node={special_node_id}")
    else:
        logger.debug(f"Failed to extract gateway node ID from topic: {mqtt_topic}")

def _calculate_gateway_reliability_score(gateway_detections):
    """
    Calculate a reliability score (0-100) for a gateway based on:
    - Confidence level (direct > partial) — dominant factor, since only
      hop-verified direct receptions are recorded in the first place
    - Number of detections (more = more consistent)
    - Signal strength (minor factor; weak RSSI is normal over water)
    
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

    # Factor 1: Confidence level (0-60 points)
    # _extract_gateway_from_packet only ever records direct (hop_start ==
    # hop_limit) receptions, so a listed gateway is already hop-verified —
    # score it accordingly. "partial" kept in case that gate ever loosens.
    if confidence_level == "direct":
        score += 60
    else:
        score += 30

    # Factor 2: Detection count (0-25 points)
    # 1 detection = 10 pts, 2 = 15, 3 = 20, 4+ = 25
    if detection_count >= 4:
        score += 25
    else:
        score += 5 + detection_count * 5

    # Factor 3: Signal strength (0-15 points)
    # Buoy-to-shore LoRa routinely works at -120 dBm; don't punish normal
    # links. -125 dBm = 0 pts, -95 dBm or better = 15 pts.
    if avg_rssi is not None:
        score += max(0, min(15, int((avg_rssi + 125) * 0.5)))
    else:
        score += 8  # unknown RSSI shouldn't drag a verified gateway down
    
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

    # Collect all detections of this gateway across all special nodes
    # Also find the most recent gateway info
    all_detections = []
    most_recent_info = None
    for special_id, connections in mh.special_node_gateways.items():
        if gateway_id in connections:
            gw_info = connections[gateway_id]
            all_detections.append(gw_info)
            # Keep the most recently seen gateway info
            if most_recent_info is None or gw_info.get("last_seen", 0) > most_recent_info.get("last_seen", 0):
                most_recent_info = gw_info

    # Calculate reliability score
    reliability = _calculate_gateway_reliability_score(all_detections)

    # Cache the reliability result
    mh.gateway_reliability_cache[gateway_id] = {
        "score": reliability["score"],
        "detection_count": reliability["detection_count"],
        "avg_rssi": reliability["avg_rssi"],
        "confidence_level": reliability.get("confidence_level"),
        "last_updated": time.time()
    }

    # Cache the most recent gateway info
    if most_recent_info:
        mh.gateway_info_cache[gateway_id] = most_recent_info

    # Update gateway node IDs set
    mh.all_gateway_node_ids.add(gateway_id)

    logger.debug(f"Updated gateway reliability cache for {gateway_id}: score={reliability['score']}, detections={reliability['detection_count']}")


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

    for special_id, gw_dict in mh.special_node_gateways.items():
        if node_id in gw_dict:
            gw_dict[node_id]["name"] = updated_name
            logger.debug(f'Updated gateway name in connection: {node_id} -> {updated_name}')
