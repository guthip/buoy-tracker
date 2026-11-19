"""Tide-height and current-speed context from NOAA CO-OPS.

Free, unauthenticated NOAA CO-OPS Data API (api.tidesandcurrents.noaa.gov).
Both products used here are harmonic *predictions*, not live observations:
they don't change once published, so a periodic background refresh (default
every 6h — see config.TIDE_REFRESH_INTERVAL_S) is far more than enough, and
a single call covers the whole history+forecast window at once rather than
needing to be assembled from a live feed.

Tide height comes from the 'predictions' product at hourly resolution —
smooth and continuous. Current speed/direction, for this fleet's station,
is only available as discrete slack/max-flood/max-ebb *events* (the
'currents_predictions' product's MAX_SLACK interval) rather than a
continuous curve; _interpolate_current() approximates the curve between
known events with a raised-cosine ease, which is visually close to the true
tidal-current shape without needing this station's harmonic constituents.
The exact, labeled NOAA event times/speeds are always available alongside
the approximation (next_current_ts/type, current_events) for anyone who
wants the precise predicted moment rather than the interpolated curve.

Added 2026-10 after a mark's position briefly (and incorrectly — see
movement.py) appeared to drag anchor: the operator's first instinct was "go
check tide and current," which this module automates by attaching a
tide/current snapshot to every movement alert, and surfaces for ad hoc
comparison via the /api/tide/* endpoints.
"""

import logging
import math
import threading
import time
import zoneinfo
from datetime import datetime, timedelta

import requests

from . import config

logger = logging.getLogger(__name__)

_NOAA_BASE = 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter'
_REQUEST_TIMEOUT_S = 15
_SLACK_THRESHOLD_KT = 0.1  # |speed| below this reads as "slack" rather than a bare 0.0kt flood/ebb

# This fleet is a single, fixed South SF Bay location — a fixed zone is
# simpler and more robust than trusting the deployment host's local tz.
_FLEET_TZ = zoneinfo.ZoneInfo('America/Los_Angeles')

_lock = threading.Lock()
_tide_series = []      # [{'ts': epoch, 'height_ft': float}, ...] sorted by ts, hourly
_tide_hilo = []         # [{'ts': epoch, 'height_ft': float, 'type': 'H'|'L'}, ...]
_current_events = []   # [{'ts': epoch, 'speed_kt': signed float, 'type': 'slack'|'ebb'|'flood'}, ...]
_last_fetch_ts = 0.0
_last_fetch_ok = False


def _fetch_json(params):
    resp = requests.get(_NOAA_BASE, params=params, timeout=_REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and 'error' in data:
        raise RuntimeError(data['error'].get('message', 'NOAA API error'))
    return data


def _parse_noaa_time(t_str):
    """NOAA 'YYYY-MM-DD HH:MM' in station local clock time (we request
    time_zone=lst_ldt, i.e. what a boater reads off a tide table) -> epoch."""
    dt = datetime.strptime(t_str, '%Y-%m-%d %H:%M')
    return dt.replace(tzinfo=_FLEET_TZ).timestamp()


def _fetch_tide_series(begin_dt, end_dt):
    data = _fetch_json({
        'begin_date': begin_dt.strftime('%Y%m%d'), 'end_date': end_dt.strftime('%Y%m%d'),
        'station': config.TIDE_STATION_ID, 'product': 'predictions', 'datum': 'MLLW',
        'time_zone': 'lst_ldt', 'interval': 'h', 'units': 'english', 'format': 'json',
    })
    return [
        {'ts': _parse_noaa_time(p['t']), 'height_ft': float(p['v'])}
        for p in data.get('predictions', [])
    ]


def _fetch_tide_hilo(begin_dt, end_dt):
    data = _fetch_json({
        'begin_date': begin_dt.strftime('%Y%m%d'), 'end_date': end_dt.strftime('%Y%m%d'),
        'station': config.TIDE_STATION_ID, 'product': 'predictions', 'datum': 'MLLW',
        'time_zone': 'lst_ldt', 'interval': 'hilo', 'units': 'english', 'format': 'json',
    })
    return [
        {'ts': _parse_noaa_time(p['t']), 'height_ft': float(p['v']), 'type': p['type']}
        for p in data.get('predictions', [])
    ]


def _fetch_current_events(begin_dt, end_dt):
    data = _fetch_json({
        'begin_date': begin_dt.strftime('%Y%m%d'), 'end_date': end_dt.strftime('%Y%m%d'),
        'station': config.CURRENT_STATION_ID, 'product': 'currents_predictions',
        'time_zone': 'lst_ldt', 'interval': 'MAX_SLACK', 'units': 'english', 'format': 'json',
    })
    events = data.get('current_predictions', {}).get('cp', [])
    return [
        {
            'ts': _parse_noaa_time(e['Time']), 'speed_kt': float(e['Velocity_Major']),
            'type': e.get('Type'),
            'flood_dir': e.get('meanFloodDir'), 'ebb_dir': e.get('meanEbbDir'),
        }
        for e in events
    ]


def _refresh():
    global _tide_series, _tide_hilo, _current_events, _last_fetch_ts, _last_fetch_ok
    if not getattr(config, 'TIDE_ENABLED', True):
        return
    now = datetime.now(_FLEET_TZ)
    begin = now - timedelta(hours=getattr(config, 'SPECIAL_HISTORY_HOURS', 24) + 6)
    end = now + timedelta(hours=getattr(config, 'TIDE_FORECAST_HOURS', 36))
    try:
        tide = _fetch_tide_series(begin, end)
        hilo = _fetch_tide_hilo(begin, end)
        current = _fetch_current_events(begin, end)
    except Exception as e:
        logger.error(f'[TIDES] Refresh failed: {e}')
        with _lock:
            _last_fetch_ts = time.time()
            _last_fetch_ok = False
        return
    with _lock:
        _tide_series = tide
        _tide_hilo = hilo
        _current_events = current
        _last_fetch_ts = time.time()
        _last_fetch_ok = True
    logger.info(
        f'[TIDES] Refreshed: {len(tide)} tide points, {len(hilo)} hi/lo events,'
        f' {len(current)} current events'
    )


def _refresh_loop():
    while True:
        try:
            _refresh()
        except Exception as e:
            logger.error(f'[TIDES] Refresh loop error: {e}')
        time.sleep(max(300, getattr(config, 'TIDE_REFRESH_INTERVAL_S', 21600)))


def start_tide_refresh_thread():
    """Start the periodic NOAA refresh. Call once at app startup (see
    main.py init_background_services)."""
    if not getattr(config, 'TIDE_ENABLED', True):
        logger.info('[TIDES] Disabled via config — not starting refresh thread')
        return None
    thread = threading.Thread(target=_refresh_loop, daemon=True, name='tide-refresh')
    thread.start()
    return thread


def _interpolate(series, ts):
    """Linear interpolation of {'ts', 'height_ft'} points at arbitrary ts.
    None if ts falls outside the series' covered range (series is sorted,
    chronological, as NOAA returns it)."""
    if not series or ts <= series[0]['ts'] or ts >= series[-1]['ts']:
        return None
    for i in range(1, len(series)):
        if series[i]['ts'] >= ts:
            t0, t1 = series[i - 1]['ts'], series[i]['ts']
            v0, v1 = series[i - 1]['height_ft'], series[i]['height_ft']
            frac = (ts - t0) / (t1 - t0) if t1 > t0 else 0.0
            return v0 + (v1 - v0) * frac
    return None


def _interpolate_current(events, ts):
    """Raised-cosine interpolation of signed current speed between
    consecutive known slack/max events — see module docstring."""
    if not events or ts <= events[0]['ts'] or ts >= events[-1]['ts']:
        return None
    for i in range(1, len(events)):
        if events[i]['ts'] >= ts:
            t0, t1 = events[i - 1]['ts'], events[i]['ts']
            v0, v1 = events[i - 1]['speed_kt'], events[i]['speed_kt']
            frac = (ts - t0) / (t1 - t0) if t1 > t0 else 0.0
            eased = (1 - math.cos(math.pi * frac)) / 2.0
            return v0 + (v1 - v0) * eased
    return None


def _current_state_label(speed_kt):
    if abs(speed_kt) < _SLACK_THRESHOLD_KT:
        return 'slack'
    return 'flood' if speed_kt > 0 else 'ebb'


def get_state_at(ts):
    """Tide/current snapshot at an arbitrary timestamp (past, present, or
    within the cached forecast) — {'tide_height_ft', 'current_speed_kt',
    'current_state'} with only the keys we have data for, or None if tides
    are disabled / never successfully fetched / ts is outside the cached
    window. Used both for the click-to-highlight chart feature and to
    attach context to a movement alert at the moment it fired."""
    with _lock:
        tide_series, current_events, ok = list(_tide_series), list(_current_events), _last_fetch_ok
    if not ok:
        return None
    result = {}
    height = _interpolate(tide_series, ts)
    if height is not None:
        result['tide_height_ft'] = round(height, 2)
    speed = _interpolate_current(current_events, ts)
    if speed is not None:
        result['current_speed_kt'] = round(abs(speed), 2)
        result['current_state'] = _current_state_label(speed)
    return result or None


def get_current_snapshot():
    """'Right now' summary for a live panel: tide height+trend+next hi/lo,
    current speed/state+next slack-or-max. Always returns the full key set
    (None where unavailable) so callers don't need defensive .get() chains."""
    now = time.time()
    result = {
        'available': False,
        'tide_height_ft': None, 'tide_trend': None,
        'next_tide_ts': None, 'next_tide_type': None, 'next_tide_height_ft': None,
        'current_speed_kt': None, 'current_state': None,
        'next_current_ts': None, 'next_current_type': None,
    }
    with _lock:
        tide_series, hilo = list(_tide_series), list(_tide_hilo)
        current_events, ok = list(_current_events), _last_fetch_ok
    result['available'] = ok
    if not ok:
        return result

    height = _interpolate(tide_series, now)
    if height is not None:
        result['tide_height_ft'] = round(height, 2)
        prev = _interpolate(tide_series, now - 1800)
        if prev is not None:
            result['tide_trend'] = 'rising' if height > prev else ('falling' if height < prev else 'steady')

    upcoming_hilo = [p for p in hilo if p['ts'] >= now]
    if upcoming_hilo:
        nxt = min(upcoming_hilo, key=lambda p: p['ts'])
        result['next_tide_ts'] = nxt['ts']
        result['next_tide_type'] = 'high' if nxt['type'] == 'H' else 'low'
        result['next_tide_height_ft'] = round(nxt['height_ft'], 2)

    speed = _interpolate_current(current_events, now)
    if speed is not None:
        result['current_speed_kt'] = round(abs(speed), 2)
        result['current_state'] = _current_state_label(speed)

    upcoming_current = [e for e in current_events if e['ts'] >= now]
    if upcoming_current:
        nxt = min(upcoming_current, key=lambda e: e['ts'])
        result['next_current_ts'] = nxt['ts']
        result['next_current_type'] = nxt['type']

    return result


def get_history_series():
    """Full cached tide-height + current-event series for charting, spanning
    [now - SPECIAL_HISTORY_HOURS, now + TIDE_FORECAST_HOURS] — the same
    historical window as the position trails, so both can be read side by
    side on one timeline."""
    with _lock:
        return {
            'available': _last_fetch_ok,
            'last_fetch_ts': _last_fetch_ts,
            'tide_points': list(_tide_series),
            'tide_hilo': list(_tide_hilo),
            'current_events': list(_current_events),
            'tide_station_id': config.TIDE_STATION_ID,
            'current_station_id': config.CURRENT_STATION_ID,
        }
