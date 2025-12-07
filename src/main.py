"""Buoy Tracker Application - Flask web interface for Meshtastic node tracking"""

from flask import Flask, jsonify, render_template, request, Response
from functools import wraps
import logging
from logging.handlers import RotatingFileHandler
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
else:
    from . import mqtt_handler, config
import time
from collections import defaultdict

# Configure logging with rotating file handler
log_level = getattr(logging, config.LOG_LEVEL)

# Console handler (stdout)
console_handler = logging.StreamHandler()
console_handler.setLevel(log_level)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# File handler with rotation (5MB per file, keep 5 backups = 25MB total)
# Use /app/logs in Docker, otherwise use local logs directory
if Path('/app').exists() and Path('/app').is_dir():
    log_dir = Path('/app/logs')
else:
    log_dir = Path(__file__).parent.parent / 'logs'
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / 'buoy_tracker.log'
file_handler = RotatingFileHandler(
    str(log_file),
    maxBytes=5 * 1024 * 1024,  # 5MB per file
    backupCount=5  # Keep 5 backups
)
file_handler.setLevel(log_level)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(log_level)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)
logger.info(f'=== BUOY TRACKER STARTING (log_level={config.LOG_LEVEL}) ===')

# Suppress verbose Flask/Werkzeug HTTP request logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Configure socket reuse for faster restarts
app.config['ENV_SOCKET_REUSE'] = True

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
# If no API key configured, endpoints will not require authentication (development mode)
API_KEY = config.API_KEY
if config.REQUIRE_API_KEY:
    if API_KEY:
        logger.info('API key authentication enabled (required by config)')
    else:
        logger.warning('API key requirement enabled but no key configured in secret.config')
else:
    logger.info('API key authentication disabled (config: require_api_key=false)')

def require_api_key(f: Callable) -> Callable:
    """Decorator to require API key in Authorization header (if enabled in config)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # If API key requirement is disabled in config, allow all requests
        if not config.REQUIRE_API_KEY:
            return f(*args, **kwargs)
        
        # For development: Allow localhost exemption
        # For production: Always require API key
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
@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/api/<path:path>', methods=['OPTIONS'])
@app.route('/health', methods=['OPTIONS'])
def handle_options(path: str = '') -> Tuple[str, int]:
    """Handle CORS preflight OPTIONS requests."""
    return '', 204


@app.route('/', methods=['GET'])
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
                          api_key_required=config.REQUIRE_API_KEY,  # Tell client if auth is needed
                          api_key=client_api_key,  # Send actual key only for localhost
                          is_localhost=is_localhost,
                          # show_controls_menu: Admin-controlled flag to show/hide Configuration tab
                          # When false, prevents end users from modifying UI settings (locked configuration)
                          show_controls_menu=getattr(config, 'SHOW_CONTROLS_MENU', True),
                          build_id=int(time.time())))
    # Disable caching for HTML to always get fresh page
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/health', methods=['GET'])
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
        'nodes_tracked': len(nodes),
        'nodes_with_position': len(nodes),
        'config': {
            'status_blue_threshold': config.STATUS_BLUE_THRESHOLD,
            'status_orange_threshold': config.STATUS_ORANGE_THRESHOLD,
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


@app.route('/api/recent/messages', methods=['GET'])
@check_rate_limit
def recent_messages() -> Response:
    try:
        msgs = mqtt_handler.get_recent(limit=100)
        return jsonify({'recent': msgs, 'count': len(msgs)})
    except Exception as e:
        logger.exception('Failed to return recent messages')
        return jsonify({'error': str(e)}), 500


@app.route('/api/nodes', methods=['GET'])
@check_rate_limit
def get_nodes() -> Response:
    """Return all tracked nodes with their current status."""
    try:
        nodes = mqtt_handler.get_nodes()
        return jsonify({'nodes': nodes, 'count': len(nodes)})
    except Exception as e:
        logger.exception('Failed to get nodes')
        return jsonify({'error': str(e)}), 500


@app.route('/api/special/history', methods=['GET'])
@check_rate_limit
def get_special_history() -> Response:
    from flask import request
    try:
        node_id = int(request.args.get('node_id'))
    except (TypeError, ValueError):
        logger.warning('special_history: Missing or invalid node_id parameter')
        return jsonify({'error': 'node_id is required'}), 400
    try:
        hours = request.args.get('hours', type=int) or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
        data = mqtt_handler.get_special_history(node_id, hours)
        return jsonify({'node_id': node_id, 'hours': hours, 'points': data, 'count': len(data)})
    except Exception as e:
        logger.exception('Failed to get special history')
        return jsonify({'error': str(e)}), 500



@app.route('/api/signal/history', methods=['GET'])
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

@app.route('/api/config/movement-threshold', methods=['POST'])
@require_api_key
@check_rate_limit
def update_movement_threshold() -> Response:
    """Update the special nodes movement threshold in memory."""
    try:
        data = request.get_json()
        threshold = float(data.get('threshold', 80))
        if threshold <= 0:
            return jsonify({'error': 'threshold must be positive'}), 400
        # Update in memory
        config.SPECIAL_MOVEMENT_THRESHOLD_METERS = threshold
        logger.info(f'Movement threshold updated to {threshold} meters')
        return jsonify({'success': True, 'threshold': threshold})
    except Exception as e:
        logger.exception('Failed to update movement threshold')
        return jsonify({'error': str(e)}), 500


@app.route('/docs/<filename>', methods=['GET'])
def serve_docs(filename: str) -> Tuple[str, int, Dict[str, str]]:
    """Serve documentation files (LICENSE, ATTRIBUTION.md)."""
    # Whitelist allowed files for security
    allowed_files = {'LICENSE', 'ATTRIBUTION.md', 'license', 'attribution.md'}
    if filename.lower() not in allowed_files:
        return jsonify({'error': 'Not found'}), 404

    try:
        # Get the project root directory
        project_root = Path(__file__).parent.parent

        # Try exact filename first, then lowercase
        doc_path = project_root / filename
        if not doc_path.exists():
            doc_path = project_root / filename.lower()

        if doc_path.exists() and doc_path.is_file():
            with open(doc_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Return as HTML with pre-formatted text
            html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{filename}</title>
    <style>
        body {{ font-family: monospace; white-space: pre-wrap; word-wrap: break-word; margin: 20px; background: #f5f5f5; }}
        pre {{ background: white; padding: 20px; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    </style>
</head>
<body>
<pre>{content}</pre>
</body>
</html>'''
            return html, 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        logger.warning(f'Failed to serve doc file {filename}: {e}')
        return jsonify({'error': 'Failed to read file'}), 500

    return jsonify({'error': 'File not found'}), 404


if __name__ == '__main__':
    logger.info(f'Starting Buoy Tracker on http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}')
    start_mqtt_on_startup()
    app.run(debug=False, host=config.WEBAPP_HOST, port=config.WEBAPP_PORT, threaded=True)
