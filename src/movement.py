"""Movement detection and the buffered coord-consensus alert decision.

A special-node position broadcast arrives as many near-simultaneous
gateway-published copies of one packet_id. Copies are collected in a per-node
buffer for _ALERT_WINDOW_S seconds; at window close the copies of each
packet_id vote by coordinate group. The largest group is the consensus; a
mutated single-path copy gets outvoted ([ALERT_SUPPRESSED]) while a genuine
drift — all copies agreeing on a far position — fires ([ALERT_FIRE]).

Also owns position-precision validation (rejects relay-quantized packets)
and the homecoming auto-unmute counter.
"""

import logging
import math
import time
from collections import defaultdict

from . import alerts
from . import config
from . import storage
from .topics import gateway_id_from_topic

logger = logging.getLogger(__name__)

# Window length: covers a full broadcast burst. Debug configs may shrink it
# via [debug] alert_window_s so simulation cycles don't wait a full minute.
_ALERT_WINDOW_S = getattr(config, 'DEBUG_ALERT_WINDOW_S', 0.0) or 60.0

# node_id -> {first_seen_ts, threshold_m, home_lat, home_lon, copies: [...]}
_pending_movement_alerts = {}

# Auto-unmute on homecoming: a muted node that reports _HOMECOMING_UNMUTE_COUNT
# consecutive distinct in-home broadcasts clears its own mute — being re-moored
# is the natural end of a maintenance window. Gateway copies of one broadcast
# share a packet_id and count once.
_HOMECOMING_UNMUTE_COUNT = 3
_homecoming_progress = {}  # node_id -> {'count': int, 'last_packet_id': int}


def _haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in meters between two lat/lon points."""
    try:
        rlat1 = math.radians(lat1)
        rlon1 = math.radians(lon1)
        rlat2 = math.radians(lat2)
        rlon2 = math.radians(lon2)
        dlat = rlat2 - rlat1
        dlon = rlon2 - rlon1
        a = math.sin(dlat / 2.0) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return 6371000.0 * c
    except Exception:
        return None


def _get_signal_quality_score(json_data):
    """Calculate signal quality score for a packet. Higher = better.

    1. Direct-hop packets (hop_start == hop_limit) beat all relayed packets
    2. Among same hop type: higher SNR (max 50 points)
    3. Then higher RSSI (max 40 points, -120 to -80 dBm range)
    """
    score = 0

    hop_start = json_data.get('hop_start')
    hop_limit = json_data.get('hop_limit')
    if hop_start is not None and hop_limit is not None and hop_start == hop_limit:
        score += 1000  # all direct-hops beat all relayed

    snr = json_data.get('rx_snr')
    if snr is not None:
        score += max(0, min(50, int((snr + 20) * 2.5)))

    rssi = json_data.get('rx_rssi')
    if rssi is not None:
        score += max(0, min(40, int(rssi + 120)))

    return score


def _validate_position_precision(payload, node_id=None):
    """
    Reject a position packet only when it's lying about its own precision —
    not merely because it's coarse. There is no minimum precision_bits floor:
    a node broadcasting reduced precision on purpose (e.g. for location
    privacy) is trusted at face value, and the resulting uncertainty is
    surfaced to the UI via _precision_radius_m() instead of being hidden by
    an outright rejection.

    The one thing this still catches: a relay node that preserves the
    source's precision_bits claim but quantizes the coordinates further for
    privacy/efficiency. A 13-bit relay packet has 19 trailing zero bits in
    latitude_i/longitude_i even though the field still claims its original
    (higher) precision — that mismatch between claimed and actual bits, not
    any fixed bit count, is what this check catches.

    When a quantized packet is from a special node, an ERROR is logged to
    help identify which relay nodes are modifying our buoy position packets.

    Returns:
        True if the packet isn't misrepresenting its precision, False otherwise
    """
    # A relay that quantizes a packet typically drops at least 8 bits below
    # what it claims; a real GPS fix drifts by 1-4 bits of jitter. Tolerance
    # is relative to the packet's own claimed precision_bits, not a fixed
    # floor, so intentionally-reduced-precision broadcasts aren't penalized.
    MAX_PRECISION_DRIFT_BITS = 8

    precision_bits = payload.get('precision_bits', 0)
    if not isinstance(precision_bits, (int, float)) or isinstance(precision_bits, bool):
        logger.warning(f'Rejected position packet with non-numeric precision_bits: {precision_bits!r}')
        return False
    precision_bits = int(precision_bits)
    if precision_bits <= 0:
        # 0 (or missing, which defaults to 0) means "no fix" in Meshtastic's
        # own convention — not merely coarse, but nothing to show at all.
        logger.warning(f'Rejected position packet with precision_bits={precision_bits} (no fix)')
        return False

    # Check actual coordinate precision against what the packet itself claims.
    # latitude_i/longitude_i are 32-bit fields, so a claim above 32 can't
    # correspond to any more actual precision than a claim of exactly 32.
    claimed_bits = min(precision_bits, 32)
    lat_i = payload.get('latitude_i', 0)
    lon_i = payload.get('longitude_i', 0)
    if lat_i and lon_i:
        lat_trailing = (lat_i & -lat_i).bit_length() - 1
        lon_trailing = (lon_i & -lon_i).bit_length() - 1
        actual_bits = 32 - max(lat_trailing, lon_trailing)
        if claimed_bits - actual_bits > MAX_PRECISION_DRIFT_BITS:
            if node_id and node_id in getattr(config, 'SPECIAL_NODES', {}):
                precision_lost = claimed_bits - actual_bits
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
                logger.error(
                    f'[PRECISION] {timestamp} | node {node_id} | '
                    f'claims precision_bits={precision_bits} but actual={actual_bits} bits '
                    f'({precision_lost} bits lost) | lat_i={lat_i}, lon_i={lon_i}'
                )
            return False

    return True


_METERS_PER_DEGREE = 111320  # at the equator; used as a simple, conservative estimate


def _precision_radius_m(precision_bits):
    """Approximate ground-uncertainty radius in meters for a claimed
    precision_bits value, for display alongside a position (e.g. "±5.8 km").

    latitude_i/longitude_i are degrees * 1e7; each bit below the full 32
    doubles the edge length of the quantization grid the fix was snapped to.

    Returns None when precision_bits is missing or not a plausible number —
    "we don't know" is more honest than a fabricated figure.
    """
    if not isinstance(precision_bits, (int, float)) or isinstance(precision_bits, bool):
        return None
    bits = max(0, min(32, int(precision_bits)))
    grid_degrees = (2 ** (32 - bits)) * 1e-7
    return round(grid_degrees * _METERS_PER_DEGREE)


def _add_copy_to_alert_buffer(node_id, json_data, payload, distance_m,
                              observed_lat, observed_lon, home_lat, home_lon,
                              threshold_m, is_far):
    """Append one received copy to the pending alert buffer for this node.

    Opens a new buffer if none exists for this node. Each entry records the
    distance, position, signal-quality score, packet_id, and gateway/hop
    context — everything needed for cross-gateway dedup and the vote at
    window close.
    """
    if node_id not in _pending_movement_alerts:
        _pending_movement_alerts[node_id] = {
            'first_seen_ts': time.time(),
            'threshold_m': threshold_m,
            'home_lat': home_lat,
            'home_lon': home_lon,
            'copies': [],
        }
    topic = json_data.get('mqtt_topic')
    _pending_movement_alerts[node_id]['copies'].append({
        'ts': time.time(),
        'packet_id': json_data.get('id'),
        'distance_m': distance_m,
        'observed_lat': observed_lat,
        'observed_lon': observed_lon,
        'signal_score': _get_signal_quality_score(json_data),
        'is_far': is_far,
        'gateway_id': gateway_id_from_topic(topic) if topic else None,
        'mqtt_topic': topic,
        'hop_start': json_data.get('hop_start'),
        'hop_limit': json_data.get('hop_limit'),
        'rx_rssi': json_data.get('rx_rssi'),
        'rx_snr': json_data.get('rx_snr'),
        'payload_snapshot': payload,
        'simulated': bool(json_data.get('simulated')),
    })


def _check_expired_alert_buffers():
    """Close any buffers whose window has elapsed and decide alert/suppress."""
    now = time.time()
    expired = [
        nid for nid, info in _pending_movement_alerts.items()
        if now - info['first_seen_ts'] >= _ALERT_WINDOW_S
    ]
    for nid in expired:
        info = _pending_movement_alerts.pop(nid)
        _evaluate_alert_buffer(nid, info)


def _evaluate_alert_buffer(node_id, info):
    """Close one burst's buffer: for each packet_id, take coordinate consensus
    across gateway copies, then fire the alert if the consensus says "far."
    Outlier copies (single-path mutations) get outvoted by the consensus group.
    """
    copies = info.get('copies') or []
    if not copies:
        return

    # Process each packet_id separately (buffer usually contains 1, but handle multiple).
    fire_candidates = []   # [(packet_id, representative_copy, consensus_size, dissent_size)]
    suppressed_candidates = []
    for pid in {c['packet_id'] for c in copies if c.get('packet_id') is not None}:
        pcopies = [c for c in copies if c.get('packet_id') == pid]

        # Group by (lat_i, lon_i). All copies of one broadcast should share the
        # same coords; divergence means at least one relay/gateway path mutated
        # this copy. Largest group wins; ties broken by highest aggregate signal.
        coord_groups = defaultdict(list)
        for c in pcopies:
            payload = c.get('payload_snapshot') or {}
            key = (payload.get('latitude_i'), payload.get('longitude_i'))
            coord_groups[key].append(c)

        def _group_strength(group):
            return (len(group), sum(c['signal_score'] for c in group))
        consensus_key = max(coord_groups, key=lambda k: _group_strength(coord_groups[k]))
        consensus = coord_groups[consensus_key]
        dissent = [c for k, g in coord_groups.items() if k != consensus_key for c in g]
        rep = max(consensus, key=lambda c: c['signal_score'])

        if rep['is_far']:
            fire_candidates.append((pid, rep, len(consensus), len(dissent)))
        elif any(c['is_far'] for c in pcopies):
            # Consensus says close but some dissenters said far — a single-path
            # mutation being neutralized. Record it.
            most_far = max((c for c in pcopies if c['is_far']),
                           key=lambda c: c['distance_m'])
            suppressed_candidates.append((pid, rep, most_far, len(consensus), len(dissent)))

    ts = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())

    if fire_candidates:
        # Pick the best (highest signal) far representative across all packet_ids
        best_pid, best_rep, csize, dsize = max(
            fire_candidates, key=lambda x: x[1]['signal_score']
        )
        logger.error(
            f'[ALERT_FIRE] {ts} | node {node_id} | window={_ALERT_WINDOW_S:.0f}s'
            f' | packet_id={best_pid} | distance={int(best_rep["distance_m"])}m'
            f' | consensus={csize} gateway copies, dissent={dsize}'
            f' | best.gateway={best_rep["gateway_id"]}'
        )
        _sim = any(c.get('simulated') for c in copies)
        if storage.is_movement_muted(node_id):
            # Detection stands (the [ALERT_FIRE] record above is the audit trail);
            # only the email is suppressed while an admin mute is active.
            logger.warning(
                f'[ALERT_MUTED] {ts} | node {node_id} | movement email suppressed (admin mute)'
                f' | packet_id={best_pid} | distance={int(best_rep["distance_m"])}m'
            )
            storage.record_alert_event(
                'movement_muted', node_id, distance_m=best_rep['distance_m'],
                details={'packet_id': best_pid, 'consensus': csize, 'dissent': dsize},
                simulated=_sim)
        elif getattr(config, 'ALERT_ENABLED', False):
            storage.record_alert_event(
                'movement_fired', node_id, distance_m=best_rep['distance_m'],
                details={'packet_id': best_pid, 'consensus': csize, 'dissent': dsize,
                         'gateway': best_rep['gateway_id']},
                simulated=_sim)
            try:
                from .mqtt_handler import nodes_data
                alerts.send_movement_alert(node_id, nodes_data.get(node_id, {}), best_rep['distance_m'])
            except Exception as alert_err:
                logger.error(f"Failed to send movement alert for {node_id}: {alert_err}")

    elif suppressed_candidates:
        # Consensus said close, but dissenters tried to claim far → mutation caught.
        best_pid, rep, most_far, csize, dsize = max(
            suppressed_candidates, key=lambda x: x[3]   # rank by consensus_size
        )
        logger.warning(
            f'[ALERT_SUPPRESSED] {ts} | node {node_id} | reason=coord_outlier'
            f' | packet_id={best_pid}'
            f' | consensus={csize} copies @ {int(rep["distance_m"])}m (close)'
            f' | dissent={dsize} copies (one claimed {int(most_far["distance_m"])}m)'
            f' | suspected single-gateway mutation'
        )
        storage.record_alert_event(
            'movement_suppressed', node_id, distance_m=most_far['distance_m'],
            details={'packet_id': best_pid, 'consensus': csize, 'dissent': dsize,
                     'consensus_distance_m': rep['distance_m']},
            simulated=any(c.get('simulated') for c in copies))


def _update_homecoming(node_id, packet_id, moved_far):
    """Track consecutive in-home broadcasts for muted nodes; auto-unmute at N."""
    if not storage.is_movement_muted(node_id):
        _homecoming_progress.pop(node_id, None)
        return
    if moved_far:
        _homecoming_progress.pop(node_id, None)
        return
    prog = _homecoming_progress.get(node_id)
    if prog and packet_id is not None and prog.get('last_packet_id') == packet_id:
        return  # another gateway copy of the same broadcast — already counted
    count = (prog['count'] if prog else 0) + 1
    if count >= _HOMECOMING_UNMUTE_COUNT:
        _homecoming_progress.pop(node_id, None)
        storage.set_movement_muted(node_id, False, note='auto-unmute: homecoming')
        logger.warning(
            f'[MUTE] node {node_id} auto-unmuted after {count} consecutive in-home broadcasts'
        )
    else:
        _homecoming_progress[node_id] = {'count': count, 'last_packet_id': packet_id}
