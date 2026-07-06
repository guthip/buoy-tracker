"""Buoy Tracker Application - Flask web interface for Meshtastic node tracking"""

from flask import Flask, jsonify, render_template, request, Response
from functools import wraps
import logging
import threading
import sys
from pathlib import Path
import hmac
from typing import Callable, Dict, Any, Tuple, Optional
# Add parent dir to path so relative imports work when run as script
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import src.mqtt_handler as mqtt_handler
    import src.config as config
    import src.alerts as alerts
    import src.storage as storage
else:
    from . import mqtt_handler, config, alerts, storage
import time
from collections import defaultdict

# Configure logging with rotating file handler
log_level = getattr(logging, config.LOG_LEVEL)

# Console handler (stdout)
console_handler = logging.StreamHandler()
console_handler.setLevel(log_level)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# File handler - create fresh log file on each startup
# Use /app/logs in Docker, otherwise use local logs directory
if Path('/app').exists() and Path('/app').is_dir():
    log_dir = Path('/app/logs')
else:
    log_dir = Path(__file__).parent.parent / 'logs'
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / 'buoy_tracker.log'

# If log file exists from previous run, archive it with timestamp
if log_file.exists():
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    archived_log = log_dir / f'buoy_tracker-{timestamp}.log'
    log_file.rename(archived_log)

# Create fresh log file for this run
file_handler = logging.FileHandler(str(log_file), mode='w')
file_handler.setLevel(log_level)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(log_level)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)
logger.info(f'=== BUOY TRACKER STARTED at {time.strftime("%Y-%m-%d %H:%M:%S")} (log_level={config.LOG_LEVEL}) ===')

# Open the SQLite durable store (settings + time series; survives restarts)
storage.init()
# Rebuild in-memory position trails from the durable store
mqtt_handler.rebuild_history_from_db()

# ----------------------------------------------------------------------------
# Runtime-tunable settings (review decision Q9): the config file supplies each
# default at startup; a DB override row — created when an admin changes the
# value in the UI — wins from then on, including across restarts and later
# config-file edits. "Reset to config defaults" deletes the override rows.
# ----------------------------------------------------------------------------
_CONFIG_FILE_DEFAULTS = {
    'movement_threshold_m': config.SPECIAL_MOVEMENT_THRESHOLD_METERS,
    'low_battery_threshold': config.LOW_BATTERY_THRESHOLD,
    'show_gateways': config.SHOW_GATEWAYS,
    'alerts_enabled': config.ALERT_ENABLED,
}

_TRUTHY = (True, 'True', 'true', '1', 1)


def _apply_setting(key: str, value) -> None:
    """Apply one runtime setting value to the live config module."""
    if key == 'movement_threshold_m':
        config.SPECIAL_MOVEMENT_THRESHOLD_METERS = float(value)
    elif key == 'low_battery_threshold':
        config.LOW_BATTERY_THRESHOLD = int(float(value))
    elif key == 'show_gateways':
        config.SHOW_GATEWAYS = value in _TRUTHY
    elif key == 'alerts_enabled':
        config.ALERT_ENABLED = value in _TRUTHY


for _key, _value in storage.all_settings().items():
    if _key in _CONFIG_FILE_DEFAULTS:
        _apply_setting(_key, _value)
        logger.info(f'[SETTINGS] DB override applied: {_key} = {_value}')

if getattr(config, 'DEBUG_SIMULATION_ENABLED', False):
    logger.warning('=' * 64)
    logger.warning('⚠️  SIMULATION MODE ENABLED — /api/debug/* endpoints are active')
    logger.warning(f'    Alert emails: {"REAL" if config.DEBUG_SEND_REAL_EMAILS else "DRY-RUN (logged, not sent)"}')
    logger.warning(f'    Alert window: {config.DEBUG_ALERT_WINDOW_S or 60.0:.0f}s | cooldown: {config.ALERT_COOLDOWN}s')
    logger.warning('    Do not enable on production deployments.')
    logger.warning('=' * 64)

# Suppress verbose Flask/Werkzeug HTTP request logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Configure socket reuse for faster restarts
app.config['ENV_SOCKET_REUSE'] = True

# Create a Blueprint for all API and app routes
# Note: url_prefix is NOT set here when behind a reverse proxy that strips the prefix
# The URL_PREFIX config is only used for JavaScript in the browser
from flask import Blueprint
api_bp = Blueprint('buoy_tracker', __name__, url_prefix=None)

# ============================================================================
# Constants
# ============================================================================
SECONDS_PER_HOUR = 3600
MILLISECONDS_PER_SECOND = 1000
SPECIAL_HIGHLIGHT_COLOR = '#FFD700'  # Gold for special nodes on map
LOCALHOST_ADDRESSES = ['127.0.0.1', 'localhost', '::1']

# Initialize simple custom rate limiter - use X-Forwarded-For for reverse proxy clients
def get_client_ip() -> str:
    """Extract client IP, trusting only configured reverse proxies."""
    # Only parse X-Forwarded-For if request comes from trusted proxy
    try:
        if config.TRUSTED_PROXIES and request.remote_addr in config.TRUSTED_PROXIES:
            xff = request.headers.get('X-Forwarded-For', '')
            if xff:
                # Parse the leftmost IP (original client)
                first_ip = xff.split(',')[0].strip()
                if first_ip:  # Validate non-empty
                    return first_ip
    except Exception as e:
        logger.warning(f'Error parsing X-Forwarded-For header: {e}')
    return request.remote_addr

# Custom rate limiter - tracks requests per IP per hour
class SimpleRateLimiter:
    def __init__(self, requests_per_hour: int) -> None:
        self.requests_per_hour = requests_per_hour

        self.request_history = defaultdict(list)  # IP -> list of timestamps

        self.lock = threading.Lock()
    
    def is_allowed(self, client_ip: str) -> bool:
        """Check if request is allowed for this IP."""
        now = time.time()
        hour_ago = now - SECONDS_PER_HOUR
        
        with self.lock:
            # Clean old requests (older than 1 hour)
            self.request_history[client_ip] = [
                ts for ts in self.request_history[client_ip] 
                if ts > hour_ago
            ]
            
            # Check if under limit
            if len(self.request_history[client_ip]) < self.requests_per_hour:
                self.request_history[client_ip].append(now)
                return True
            else:
                return False
    
    def get_remaining(self, client_ip: str) -> int:
        """Get remaining requests for this IP this hour."""
        now = time.time()
        hour_ago = now - SECONDS_PER_HOUR
        
        with self.lock:
            recent = [ts for ts in self.request_history[client_ip] if ts > hour_ago]
            return max(0, self.requests_per_hour - len(recent))

# Calculate rate limit from config
# Formula: (3600 / polling_seconds) * (3_base_endpoints + N_special_nodes) * 2.0_safety_multiplier
# Base endpoints: health, api/nodes, api/special/history (3 requests)
# Per special node: api/special/history request when trails enabled (N requests)
# Rate limit is computed from actual special nodes configured in tracker.config
_polling_seconds = config.API_POLLING_INTERVAL_MS // 1000
_num_special_nodes = len(config.SPECIAL_NODE_IDS)
_requests_per_poll = 3 + _num_special_nodes  # 3 base endpoints + N special node history requests
rate_limiter = SimpleRateLimiter(int(config.API_RATE_LIMIT.split('/')[0]))
logger.info(f'Rate limiter initialized: {config.API_RATE_LIMIT} (polling: {_polling_seconds}s, {_requests_per_poll} requests/interval, {_num_special_nodes} special nodes)')

def check_rate_limit(f: Callable) -> Callable:
    """Decorator to check rate limit before executing endpoint."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # For development: Allow localhost exemption
        # For production: Always enforce rate limiting
        if config.ENV == 'development':
            is_localhost = request.remote_addr in LOCALHOST_ADDRESSES
            if is_localhost:
                return f(*args, **kwargs)

        client_ip = get_client_ip()
        if not rate_limiter.is_allowed(client_ip):
            rate_limiter.get_remaining(client_ip)
            logger.warning(f'Rate limit exceeded for IP {client_ip}')
            return jsonify({
                'error': 'Rate limit exceeded',
                'retry_after': 3600
            }), 429
        return f(*args, **kwargs)
    return decorated

# API Key authentication - stored server-side in secret.config (never in code or env)
# Control Menu access requires password. Read-only endpoints are public.
API_KEY = config.API_KEY
logger.info('API key authentication enabled (required for Control Menu access)')

def require_api_key(f: Callable) -> Callable:
    """Decorator to require API key in Authorization header for protected endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # For development: Allow localhost exemption
        if config.ENV == 'development':
            is_localhost = request.remote_addr in LOCALHOST_ADDRESSES
            if is_localhost:
                return f(*args, **kwargs)
        
        auth_header = request.headers.get('Authorization', '')
        # If no API key configured, skip auth (development mode)
        if not API_KEY:
            return f(*args, **kwargs)
        # If API key IS configured, require it
        if not auth_header.startswith('Bearer '):
            logger.warning(f'API request without authorization from {request.remote_addr}')
            return jsonify({'error': 'Unauthorized'}), 401
        provided_key = auth_header[7:]
        if not hmac.compare_digest(provided_key, API_KEY):
            logger.warning(f'API request with invalid key from {request.remote_addr}')
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# Add cache control for static files (JS, CSS, etc)
@app.after_request
def set_cache_headers(response: Response) -> Response:
    """Set cache headers, security headers, and validated CORS headers."""
    # Force no-cache on all responses to prevent stale data
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    # Add server timestamp so client can detect cached responses
    response.headers['X-Server-Time'] = str(int(time.time() * MILLISECONDS_PER_SECOND))  # milliseconds
    
    # CORS: Only allow configured origins
    origin = request.headers.get('Origin', '')
    if origin:
        if '*' in config.ALLOWED_ORIGINS:
            # Wildcard: allow all origins
            response.headers['Access-Control-Allow-Origin'] = origin
        elif origin in config.ALLOWED_ORIGINS:
            # Explicit whitelist: only allow configured origins
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    
    # Security headers: Prevent clickjacking, MIME sniffing, XSS
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Content Security Policy: Restrict script sources
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "font-src 'self' cdn.jsdelivr.net; "
        "frame-ancestors 'none';"
    )
    
    # HTTPS enforcement (if using HTTPS reverse proxy)
    if request.scheme == 'https':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    return response

# Flag to track if MQTT is running
mqtt_thread = None


def run_mqtt_in_background() -> None:
    """Run MQTT connection in background thread."""
    logger.debug('[MAIN] Entered run_mqtt_in_background thread.')
    try:
        logger.info('[MQTT] run_mqtt_in_background() called')
        logger.info('[MQTT] Starting MQTT client in background thread')
        logger.debug('[MAIN] About to call mqtt_handler.connect_mqtt()')
        result = mqtt_handler.connect_mqtt()
        logger.debug(f'[MAIN] mqtt_handler.connect_mqtt() returned: {result}')
        if result:
            logger.info('[MQTT] connect_mqtt() returned True, client should be running')
        else:
            logger.error('[MQTT] connect_mqtt() returned False, client failed to start')
        # Keep thread alive - process any callbacks that need to run
        while True:
            time.sleep(1)
            # Check if client is still alive
            if mqtt_handler.client is None:
                logger.warning('[MQTT] MQTT client disconnected unexpectedly')
                break
    except Exception as e:
        logger.error(f'[MQTT] MQTT connection error: {e}')


# Auto-start MQTT on app init
def start_mqtt_on_startup() -> None:
    """Start MQTT when Flask app initializes."""
    global mqtt_thread
    logger.info('[MQTT] start_mqtt_on_startup() called')
    # Reset dead threads so we can restart them
    if mqtt_thread is not None and not mqtt_thread.is_alive():
        logger.warning('[MQTT] Previous MQTT thread is dead, restarting...')
        mqtt_thread = None
    
    if mqtt_thread is None:
        logger.info('[MQTT] Starting MQTT background thread')
        mqtt_thread = threading.Thread(target=run_mqtt_in_background, daemon=True)
        mqtt_thread.start()
        logger.info('[MQTT] MQTT auto-started on app init')


def init_background_services() -> None:
    """Explicit initializer for background services (MQTT)."""
    start_mqtt_on_startup()


@app.before_request
def _() -> None:
    """Ensure MQTT is started on first request."""
    global mqtt_thread
    if mqtt_thread is None or not mqtt_thread.is_alive():
        start_mqtt_on_startup()


# Handle CORS preflight requests for API endpoints only
@api_bp.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@api_bp.route('/api/<path:path>', methods=['OPTIONS'])
@api_bp.route('/health', methods=['OPTIONS'])
def handle_options(path: str = '') -> Tuple[str, int]:
    """Handle CORS preflight OPTIONS requests."""
    return '', 204


def _request_url_prefix() -> str:
    """Subpath prefix for THIS request, from X-Forwarded-Prefix.

    Traefik's stripprefix middleware sets the header automatically; for
    Apache/nginx add one line (RequestHeader set X-Forwarded-Prefix ... /
    proxy_set_header X-Forwarded-Prefix ...). Only used to build the URLs
    returned to the same requester — no security decisions read it.
    """
    prefix = request.headers.get('X-Forwarded-Prefix', '').strip()
    if prefix and not prefix.startswith('/'):
        prefix = '/' + prefix
    return prefix.rstrip('/')


@api_bp.route('/', methods=['GET'])
def index() -> Response:
    """Serve the main map page."""
    from flask import make_response
    # Determine if this is localhost access
    is_localhost = request.remote_addr in LOCALHOST_ADDRESSES
    # API key is only sent to client if on localhost (remote users enter it in modal)
    client_api_key = config.API_KEY if is_localhost else ''
    
    response = make_response(render_template('simple.html',
                          app_title=config.APP_TITLE,
                          app_version=config.APP_VERSION,
                          default_lat=config.DEFAULT_LAT,
                          default_lon=config.DEFAULT_LON,
                          default_zoom=config.DEFAULT_ZOOM,
                          node_refresh=config.API_POLLING_INTERVAL_MS,
                          status_refresh=config.API_POLLING_INTERVAL_MS,
                          special_symbol=config.SPECIAL_NODE_SYMBOL,
                          special_highlight_color=SPECIAL_HIGHLIGHT_COLOR,

                          special_history_hours=getattr(config, 'SPECIAL_HISTORY_HOURS', 24),
                          special_move_threshold=getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0),
                          api_key_required=True,  # API key always required for Control Menu
                          api_key=client_api_key,  # Send actual key only for localhost
                          is_localhost=is_localhost,
                          url_prefix=_request_url_prefix(),  # from X-Forwarded-Prefix (v2.1)
                          build_id=int(time.time())))
    # Disable caching for HTML to always get fresh page
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@api_bp.route('/health', methods=['GET'])
@check_rate_limit
def health_check() -> Response:
    """Health check endpoint with status and configuration."""
    nodes = mqtt_handler.get_nodes()
    mqtt_status = mqtt_handler.is_connected()  # Returns: 'receiving_packets', 'stale_data', 'connected_to_server', 'connecting', or 'disconnected'
    mqtt_connected = mqtt_status in ('receiving_packets', 'connected_to_server')  # True if we have any connection
    return jsonify({
        'status': 'ok',
        'mqtt_connected': mqtt_connected,
        'mqtt_status': mqtt_status,
        'config_sources': getattr(config, 'CONFIG_SOURCES', []),
        'nodes_tracked': len(nodes),
        'nodes_with_position': len(nodes),
        'config': {
            'status_blue_threshold': config.STATUS_BLUE_THRESHOLD,
            'status_orange_threshold': config.STATUS_ORANGE_THRESHOLD,
            'lpu_blue_threshold': config.LPU_BLUE_THRESHOLD,
            'lpu_orange_threshold': config.LPU_ORANGE_THRESHOLD,
            'sol_blue_threshold': config.SOL_BLUE_THRESHOLD,
            'sol_orange_threshold': config.SOL_ORANGE_THRESHOLD,
            'special_movement_threshold': getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50),
            'low_battery_threshold': getattr(config, 'LOW_BATTERY_THRESHOLD', 50),
            'api_polling_interval': getattr(config, 'API_POLLING_INTERVAL_MS', 10000) // 1000  # Convert ms to seconds
        },
        'features': {
            'show_all_nodes': getattr(config, 'SHOW_ALL_NODES', False),
            'show_gateways': getattr(config, 'SHOW_GATEWAYS', True),
            'show_position_trails': getattr(config, 'SHOW_POSITION_TRAILS', True),
            'show_nautical_markers': getattr(config, 'SHOW_NAUTICAL_MARKERS', True),
            'trail_history_hours': getattr(config, 'TRAIL_HISTORY_HOURS', 24)
        }
    })


# /api/mqtt/connect removed - MQTT managed by background thread


# /api/status merged into /health endpoint - see health_check() above


@api_bp.route('/api/nodes', methods=['GET'])
@check_rate_limit
def get_nodes() -> Response:
    """Return all tracked nodes with their current status."""
    try:
        nodes = mqtt_handler.get_nodes()
        return jsonify({'nodes': nodes, 'count': len(nodes)})
    except Exception as e:
        logger.exception('Failed to get nodes')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/alerts/toggle', methods=['POST'])
@check_rate_limit
@require_api_key
def toggle_alerts() -> Response:
    """
    Toggle email alerts on/off without restarting the server.
    
    This allows users to temporarily disable movement and battery alerts
    to prevent alert spam during network issues or testing.
    
    Returns:
        {
            'status': 'ok',
            'alerts_enabled': boolean,
            'message': 'Alerts enabled/disabled'
        }
    """
    try:
        # Get current alert status
        current_status = getattr(config, 'ALERT_ENABLED', False)
        
        # Toggle the status
        new_status = not current_status
        config.ALERT_ENABLED = new_status
        storage.set_setting('alerts_enabled', new_status)

        logger.info(f"Alerts toggled: {'ENABLED' if new_status else 'DISABLED'} by {request.remote_addr}")
        
        return jsonify({
            'status': 'ok',
            'alerts_enabled': new_status,
            'message': f'Alerts {("enabled" if new_status else "disabled")}'
        })
    except Exception as e:
        logger.exception('Failed to toggle alerts')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/alerts/status', methods=['GET'])
@check_rate_limit
@require_api_key
def get_alerts_status() -> Response:
    """
    Get current alert status (enabled/disabled).
    
    Returns:
        {
            'alerts_enabled': boolean,
            'alert_cooldown': int (seconds),
            'low_battery_threshold': int (%)
        }
    """
    try:
        return jsonify({
            'alerts_enabled': getattr(config, 'ALERT_ENABLED', False),
            'alert_cooldown': getattr(config, 'ALERT_COOLDOWN', 3600),
            'low_battery_threshold': getattr(config, 'LOW_BATTERY_THRESHOLD', 50)
        })
    except Exception as e:
        logger.exception('Failed to get alert status')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/alerts/mutes', methods=['GET'])
@check_rate_limit
def get_alert_mutes() -> Response:
    """
    Get per-node movement-alert mute states (public read).

    Returns:
        {'mutes': {node_id_str: {'muted_at': int, 'note': str}}}
    """
    try:
        return jsonify({'mutes': storage.get_all_mutes()})
    except Exception as e:
        logger.exception('Failed to get alert mutes')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/alerts/mute', methods=['POST'])
@check_rate_limit
@require_api_key
def set_alert_mute() -> Response:
    """
    Mute or unmute movement-alert emails for one special node.

    Body: {'node_id': int, 'muted': bool}
    Muting affects movement emails only — battery alerts and the UI
    out-of-position indication stay active. Auto-unmutes when the node
    reports consecutive in-home positions (homecoming).
    """
    try:
        data = request.get_json(silent=True) or {}
        try:
            node_id = int(data.get('node_id'))
        except (TypeError, ValueError):
            return jsonify({'error': 'node_id (int) is required'}), 400
        if node_id not in config.SPECIAL_NODE_IDS:
            return jsonify({'error': f'node {node_id} is not a special node'}), 400
        muted = data.get('muted')
        if not isinstance(muted, bool):
            return jsonify({'error': 'muted (true/false) is required'}), 400

        storage.set_movement_muted(node_id, muted, note=f'via API from {get_client_ip()}')
        return jsonify({'success': True, 'node_id': node_id, 'muted': muted})
    except Exception as e:
        logger.exception('Failed to set alert mute')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/server/restart', methods=['POST'])
@check_rate_limit
@require_api_key
def restart_server() -> Response:
    """
    Gracefully restart the server process.
    
    This clears all in-memory cache (position trails, deduplication data, etc.)
    while preserving configuration files. Used to recover from network issues
    or reset accumulated stale data.
    
    Returns:
        {
            'status': 'ok',
            'message': 'Server restarting...'
        }
    """
    try:
        import os
        import signal
        
        logger.warning(f"Server restart requested via /api/server/restart by {request.remote_addr}")
        
        # Return success response first (client will see this before shutdown)
        response_data = {
            'status': 'ok',
            'message': 'Server restarting...'
        }
        
        # Schedule restart for 1 second from now to allow response to be sent.
        # Bind the kill function and pid NOW (not at fire time) so the action
        # is fixed at schedule time regardless of later interpreter state.
        kill_fn, pid = os.kill, os.getpid()

        def restart_after_delay():
            import time
            time.sleep(1)
            logger.info("Initiating graceful shutdown for server restart")
            kill_fn(pid, signal.SIGTERM)
        
        import threading
        restart_thread = threading.Thread(target=restart_after_delay, daemon=True)
        restart_thread.start()
        
        return jsonify(response_data), 202  # 202 Accepted (operation in progress)
    
    except Exception as e:
        logger.exception('Failed to restart server')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/special/history/batch', methods=['GET'])
@check_rate_limit
def get_special_history_batch() -> Response:
    """
    Get trail history for ALL special nodes in a single request.
    Eliminates N+1 query problem (1 request instead of N requests).

    Query params:
        hours (int, optional): History window in hours (default from config)

    Returns:
        {
            'hours': int,
            'trails': {
                'node_id': {'points': [...], 'count': int},
                ...
            }
        }
    """
    from flask import request
    try:
        hours = request.args.get('hours', type=int) or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
        trails = {}

        # Get history for all special nodes
        for node_id in config.SPECIAL_NODE_IDS:
            data = mqtt_handler.get_special_history(node_id, hours)
            trails[str(node_id)] = {
                'points': data,
                'count': len(data)
            }

        return jsonify({'hours': hours, 'trails': trails})
    except Exception as e:
        logger.exception('Failed to get batch special history')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/signal/history', methods=['GET'])
@check_rate_limit
def get_signal_history() -> Response:
    """Get signal history (battery, RSSI, SNR) for a specific node."""
    from flask import request
    try:
        node_id = int(request.args.get('node_id'))
    except (TypeError, ValueError):
        logger.warning('signal_history: Missing or invalid node_id parameter')
        return jsonify({'error': 'node_id is required'}), 400
    try:
        data = mqtt_handler.get_signal_history(node_id)
        return jsonify({'node_id': node_id, 'points': data, 'count': len(data)})
    except Exception as e:
        logger.exception('Failed to get signal history')
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/config/movement-threshold', methods=['POST'])
@check_rate_limit
@require_api_key
def update_movement_threshold() -> Response:
    """Update the special nodes movement threshold in memory."""
    try:
        data = request.get_json(silent=True) or {}
        threshold = float(data.get('threshold', 80))
        if threshold <= 0:
            return jsonify({'error': 'threshold must be positive'}), 400
        # Update in memory and persist as a DB override (survives restarts)
        config.SPECIAL_MOVEMENT_THRESHOLD_METERS = threshold
        storage.set_setting('movement_threshold_m', threshold)
        logger.info(f'Movement threshold updated to {threshold} meters')
        return jsonify({'success': True, 'threshold': threshold})
    except Exception as e:
        logger.exception('Failed to update movement threshold')
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/config/battery-threshold', methods=['POST'])
@check_rate_limit
@require_api_key
def update_battery_threshold() -> Response:
    """Update the low battery threshold in memory."""
    try:
        data = request.get_json(silent=True) or {}
        threshold = int(data.get('threshold', 25))
        if threshold <= 0 or threshold > 100:
            return jsonify({'error': 'threshold must be between 1 and 100'}), 400
        # Update in memory and persist as a DB override (survives restarts)
        config.LOW_BATTERY_THRESHOLD = threshold
        storage.set_setting('low_battery_threshold', threshold)
        logger.info(f'Low battery threshold updated to {threshold}%')
        return jsonify({'success': True, 'threshold': threshold})
    except Exception as e:
        logger.exception('Failed to update battery threshold')
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/config/show-gateways', methods=['POST'])
@check_rate_limit
@require_api_key
def update_show_gateways() -> Response:
    """Update the show_gateways setting and reload MQTT subscriptions."""
    try:
        data = request.get_json(silent=True) or {}
        show_gateways = bool(data.get('show_gateways', True))

        # Update in memory and persist as a DB override (survives restarts)
        config.SHOW_GATEWAYS = show_gateways
        storage.set_setting('show_gateways', show_gateways)
        logger.info(f'show_gateways updated to {show_gateways}')

        # Reload MQTT subscriptions with new setting
        reload_success = mqtt_handler.reload_mqtt_subscriptions()

        if reload_success:
            return jsonify({
                'success': True,
                'show_gateways': show_gateways,
                'subscriptions_reloaded': True
            })
        else:
            return jsonify({
                'success': True,
                'show_gateways': show_gateways,
                'subscriptions_reloaded': False,
                'warning': 'Setting updated but MQTT subscriptions could not be reloaded'
            }), 207  # Multi-Status
    except Exception as e:
        logger.exception('Failed to update show_gateways')
        return jsonify({'error': str(e)}), 500

@api_bp.route('/api/settings/reset', methods=['POST'])
@check_rate_limit
@require_api_key
def reset_runtime_settings() -> Response:
    """
    Delete all runtime-setting DB overrides and restore config-file defaults
    (the Control Menu "reset to config defaults" action).
    """
    try:
        removed = storage.reset_settings()
        for key, value in _CONFIG_FILE_DEFAULTS.items():
            _apply_setting(key, value)
        # show_gateways may have changed back — refresh MQTT subscriptions
        try:
            mqtt_handler.reload_mqtt_subscriptions()
        except Exception as reload_err:
            logger.warning(f'Subscription reload after reset failed: {reload_err}')
        logger.warning(f'[SETTINGS] reset to config defaults by {get_client_ip()} ({removed} override(s) removed)')
        return jsonify({
            'success': True,
            'overrides_removed': removed,
            'defaults': {k: str(v) for k, v in _CONFIG_FILE_DEFAULTS.items()},
        })
    except Exception as e:
        logger.exception('Failed to reset settings')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/test-alert', methods=['POST'])
@check_rate_limit
@require_api_key
def test_alert() -> Response:
    """Send a test alert email to verify email configuration."""
    try:
        # Check if alerts are enabled
        if not hasattr(config, 'ALERT_ENABLED') or not config.ALERT_ENABLED:
            return jsonify({'error': 'Email alerts are disabled in tracker.config'}), 400

        # Get alert type from request (default to movement)
        # Use force=True to parse JSON even without Content-Type header
        data = request.get_json(force=True, silent=True) or {}
        alert_type = data.get('type', 'movement')

        test_node_id = 999999999
        test_node_data = {
            'long_name': 'Test Node',
            'voltage': 3.45,
            'battery_pct': 45,
        }

        if alert_type == 'battery':
            alerts.send_battery_alert(test_node_id, test_node_data)
            return jsonify({'success': True, 'message': 'Test battery alert sent'})
        else:
            alerts.send_movement_alert(test_node_id, test_node_data, distance_m=250)
            return jsonify({'success': True, 'message': 'Test movement alert sent'})

    except Exception as e:
        logger.exception('Failed to send test alert')
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Debug / Simulation API
# Double-gated: 404 unless [debug] enable_simulation = true, AND Bearer auth.
# The simulation gate runs before auth so a disabled deployment reveals
# nothing (404, not 401) when the endpoints are probed.
# ============================================================================

def require_simulation_enabled(f: Callable) -> Callable:
    """Return 404 unless simulation mode is enabled in config."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(config, 'DEBUG_SIMULATION_ENABLED', False):
            return jsonify({'error': 'Not found'}), 404
        return f(*args, **kwargs)
    return decorated


@api_bp.route('/api/debug/inject', methods=['POST'])
@check_rate_limit
@require_simulation_enabled
@require_api_key
def debug_inject() -> Response:
    """
    Inject one synthetic packet through the real handler pipeline.

    Body (raw form):      {'type': 'position', 'packet': {...json_packet...}}
    Body (builder form):  {'type': 'position', 'node_id': int,
                           'lat': float, 'lon': float,   # or 'distance_m' offset from home
                           'gateway': '!hex', 'packet_id': int, 'rssi': int, 'snr': float}
                          {'type': 'telemetry', 'node_id': int, 'voltage': float}
    """
    from . import simulation
    try:
        data = request.get_json(silent=True) or {}
        ptype = data.get('type', 'position')

        if 'packet' in data:
            packet = data['packet']
        else:
            try:
                node_id = int(data.get('node_id'))
            except (TypeError, ValueError):
                return jsonify({'error': 'node_id (int) is required'}), 400
            kwargs = {}
            for key in ('gateway_hex', 'packet_id', 'rssi', 'snr', 'hop_start', 'hop_limit'):
                if key in data:
                    kwargs[key] = data[key]
            if 'gateway' in data:
                kwargs['gateway_hex'] = data['gateway']
            if ptype == 'position':
                if 'lat' in data and 'lon' in data:
                    lat, lon = float(data['lat']), float(data['lon'])
                else:
                    home_lat, home_lon = simulation._home_of(node_id)
                    lat = home_lat + float(data.get('distance_m', 0)) / simulation._M_PER_DEG_LAT
                    lon = home_lon
                if 'precision_bits' in data:
                    kwargs['precision_bits'] = int(data['precision_bits'])
                packet = simulation.build_position_packet(node_id, lat, lon, **kwargs)
            elif ptype == 'telemetry':
                if 'voltage' not in data:
                    return jsonify({'error': 'voltage is required for telemetry'}), 400
                packet = simulation.build_telemetry_packet(node_id, float(data['voltage']), **kwargs)
            else:
                return jsonify({'error': f'builder form supports position/telemetry, not {ptype}'}), 400

        simulation.inject(ptype, packet)
        return jsonify({'success': True, 'type': ptype,
                        'packet_id': packet.get('id'), 'from': packet.get('from')})
    except Exception as e:
        logger.exception('debug inject failed')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/debug/scenario', methods=['POST'])
@check_rate_limit
@require_simulation_enabled
@require_api_key
def debug_scenario() -> Response:
    """
    Run a named scenario generator.

    Body: {'name': 'drift'|'mutation'|'battery_drain'|'gap', 'node_id': int,
           ...scenario-specific params (distance_m, copies, start_v, hours, ...)}
    """
    from . import simulation
    try:
        data = request.get_json(silent=True) or {}
        name = data.get('name')
        if name not in simulation.SCENARIOS:
            return jsonify({'error': f'unknown scenario; available: {sorted(simulation.SCENARIOS)}'}), 400
        try:
            node_id = int(data.get('node_id'))
        except (TypeError, ValueError):
            return jsonify({'error': 'node_id (int) is required'}), 400
        if node_id not in config.SPECIAL_NODE_IDS:
            return jsonify({'error': f'node {node_id} is not a special node'}), 400

        params = {k: v for k, v in data.items() if k not in ('name', 'node_id')}
        result = simulation.SCENARIOS[name](node_id, **params)
        logger.warning(f'[SIM] scenario {name} started for node {node_id} by {get_client_ip()}')
        return jsonify({'success': True, **result})
    except TypeError as e:
        return jsonify({'error': f'bad scenario parameters: {e}'}), 400
    except Exception as e:
        logger.exception('debug scenario failed')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/debug/replay', methods=['POST'])
@check_rate_limit
@require_simulation_enabled
@require_api_key
def debug_replay() -> Response:
    """
    Replay a JSONL fixture from fixtures/ with time compression.

    Body: {'file': 'name.jsonl', 'speed': 60}
    """
    from . import simulation
    try:
        data = request.get_json(silent=True) or {}
        filename = data.get('file')
        if not filename:
            return jsonify({'error': 'file is required'}), 400
        result = simulation.replay_file(filename, speed=float(data.get('speed', 60.0)))
        return jsonify({'success': True, **result})
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.exception('debug replay failed')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/api/debug/state', methods=['GET'])
@check_rate_limit
@require_simulation_enabled
@require_api_key
def debug_state() -> Response:
    """Snapshot of internal alert/mute state for asserting scenario outcomes."""
    from . import simulation
    try:
        return jsonify(simulation.get_state())
    except Exception as e:
        logger.exception('debug state failed')
        return jsonify({'error': str(e)}), 500


# Register blueprint with the Flask app
app.register_blueprint(api_bp)
logger.info('Routes registered at root; subpath prefix (if any) comes from X-Forwarded-Prefix per request')


if __name__ == '__main__':
    logger.info(f'Starting Buoy Tracker on http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}')
    start_mqtt_on_startup()
    app.run(debug=False, host=config.WEBAPP_HOST, port=config.WEBAPP_PORT, threaded=True)
