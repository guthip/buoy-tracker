"""Buoy Tracker Application - Flask web interface for Meshtastic node tracking"""

from flask import Flask, jsonify, render_template, request
from functools import wraps
import logging
import threading
import sys
from pathlib import Path
import hmac
# Add parent dir to path so relative imports work when run as script
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import src.mqtt_handler as mqtt_handler
    import src.config as config
else:
    from . import mqtt_handler, config
import time
from collections import defaultdict

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL),
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Configure socket reuse for faster restarts
app.config['ENV_SOCKET_REUSE'] = True

# Initialize simple custom rate limiter - use X-Forwarded-For for reverse proxy clients
def get_client_ip():
    """Extract client IP from X-Forwarded-For header (reverse proxy) or remote_addr."""

    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

# Custom rate limiter - tracks requests per IP per hour
class SimpleRateLimiter:
    def __init__(self, requests_per_hour):
        self.requests_per_hour = requests_per_hour

        self.request_history = defaultdict(list)  # IP -> list of timestamps

        self.lock = threading.Lock()
    
    def is_allowed(self, client_ip):
        """Check if request is allowed for this IP."""
        now = time.time()
        hour_ago = now - 3600
        
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
    
    def get_remaining(self, client_ip):
        """Get remaining requests for this IP this hour."""
        now = time.time()
        hour_ago = now - 3600
        
        with self.lock:
            recent = [ts for ts in self.request_history[client_ip] if ts > hour_ago]
            return max(0, self.requests_per_hour - len(recent))

# Calculate rate limit from config
# Formula: (3600 / polling_seconds) * (3_base_endpoints + N_special_nodes) * 2.0_safety_multiplier
# Base endpoints: api/status, api/nodes, api/special/packets (3 requests)
# Per special node: api/special/history request when trails enabled (N requests)
# Rate limit is computed from actual special nodes configured in tracker.config
_polling_seconds = config.API_POLLING_INTERVAL_MS // 1000
_num_special_nodes = len(config.SPECIAL_NODE_IDS)
_requests_per_poll = 3 + _num_special_nodes  # 3 base endpoints + N special node history requests
rate_limiter = SimpleRateLimiter(int(config.API_RATE_LIMIT.split('/')[0]))
logger.info(f'Rate limiter initialized: {config.API_RATE_LIMIT} (polling: {_polling_seconds}s, {_requests_per_poll} requests/interval, {_num_special_nodes} special nodes)')

def check_rate_limit(f):
    """Decorator to check rate limit before executing endpoint."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Exempt localhost from rate limiting
        is_localhost = request.remote_addr in ['127.0.0.1', 'localhost', '::1']
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
if API_KEY:
    logger.info('API key authentication enabled')
else:
    logger.warning('API key not configured in secret.config - API endpoints will not be protected')

def require_api_key(f):
    """Decorator to require API key in Authorization header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Exempt localhost from API key authentication
        is_localhost = request.remote_addr in ['127.0.0.1', 'localhost', '::1']
        if is_localhost:
            return f(*args, **kwargs)
        auth_header = request.headers.get('Authorization', '')
        # If no API key configured, skip auth (development mode)
        if not API_KEY:
            return f(*args, **kwargs)
        # If API key IS configured, require it for non-localhost
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        provided_key = auth_header[7:]
        if not hmac.compare_digest(provided_key, API_KEY):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# Add cache control for static files (JS, CSS, etc)
@app.after_request
def set_cache_headers(response):
    """Set cache headers to prevent stale content and add CORS headers."""
    # Force no-cache on all responses to prevent stale data
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    # Add server timestamp so client can detect cached responses

    response.headers['X-Server-Time'] = str(int(time.time() * 1000))  # milliseconds
    # Add CORS headers to allow requests from same origin
    response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

# Flag to track if MQTT is running
mqtt_thread = None
mqtt_connected = False


def run_mqtt_in_background():
    """Run MQTT connection in background thread."""
    global mqtt_connected
    print('[DEBUG] [MAIN] Entered run_mqtt_in_background thread.')
    try:
        logger.info('[MQTT] run_mqtt_in_background() called')
        logger.info('[MQTT] Starting MQTT client in background thread')
        print('[DEBUG] [MAIN] About to call mqtt_handler.connect_mqtt()')
        result = mqtt_handler.connect_mqtt()
        print(f'[DEBUG] [MAIN] mqtt_handler.connect_mqtt() returned: {result}')
        if result:
            logger.info('[MQTT] connect_mqtt() returned True, client should be running')
        else:
            logger.error('[MQTT] connect_mqtt() returned False, client failed to start')
        mqtt_connected = True
        # Keep thread alive - process any callbacks that need to run
        while True:
            time.sleep(1)
            # Check if client is still alive
            if mqtt_handler.client is None:
                logger.warning('[MQTT] MQTT client disconnected unexpectedly')
                break
    except Exception as e:
        logger.error(f'[MQTT] MQTT connection error: {e}')
        mqtt_connected = False


# Auto-start MQTT on app init
def start_mqtt_on_startup():
    """Start MQTT when Flask app initializes."""
    global mqtt_thread
    logger.info('[MQTT] start_mqtt_on_startup() called')
    if mqtt_thread is None or not mqtt_thread.is_alive():
        logger.info('[MQTT] Starting MQTT background thread')
        mqtt_thread = threading.Thread(target=run_mqtt_in_background, daemon=True)
        mqtt_thread.start()
        logger.info('[MQTT] MQTT auto-started on app init')


def init_background_services():
    """Explicit initializer for background services (MQTT)."""
    start_mqtt_on_startup()


@app.before_request
def _():
    """Ensure MQTT is started on first request."""
    global mqtt_thread
    if mqtt_thread is None or not mqtt_thread.is_alive():
        start_mqtt_on_startup()


# Handle CORS preflight requests for API endpoints only
@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/api/<path:path>', methods=['OPTIONS'])
@app.route('/health', methods=['OPTIONS'])
def handle_options(path=''):
    """Handle CORS preflight OPTIONS requests."""
    return '', 204


@app.route('/', methods=['GET'])
def index():
    """Serve the main map page."""
    from flask import make_response
    # Determine if this is localhost access
    is_localhost = request.remote_addr in ['127.0.0.1', 'localhost', '::1']
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
                          special_highlight_color='#FFD700',  # Gold color - hardcoded as not configurable

                          special_history_hours=getattr(config, 'SPECIAL_HISTORY_HOURS', 24),
                          special_move_threshold=getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0),
                          api_key_required=bool(API_KEY),  # Tell client if auth is needed
                          api_key=client_api_key,  # Send actual key only for localhost
                          is_localhost=is_localhost,
                          build_id=int(time.time())))
    # Disable caching for HTML to always get fresh page
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})


# /api/mqtt/connect removed - MQTT managed by background thread
# /api/mqtt/disconnect and /api/mqtt/status removed


@app.route('/api/status', methods=['GET'])
@require_api_key
@check_rate_limit
def api_status():
    """Compatibility status endpoint used by the simple.html UI."""
    nodes = mqtt_handler.get_nodes()
    mqtt_connected = mqtt_handler.is_connected()
    mqtt_status = mqtt_handler.get_mqtt_status() if hasattr(mqtt_handler, 'get_mqtt_status') else ('connected_to_server' if mqtt_connected else 'disconnected')
    return jsonify({
        'mqtt_connected': mqtt_connected,
        'mqtt_status': mqtt_status,
        'nodes_tracked': len(nodes),
        'nodes_with_position': len(nodes),
        'config': {
            'status_blue_threshold': config.STATUS_BLUE_THRESHOLD,
            'status_orange_threshold': config.STATUS_ORANGE_THRESHOLD,
            'special_movement_threshold': getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50)
        },
        'features': {
            'show_all_nodes': getattr(config, 'SHOW_ALL_NODES', False),
            'show_gateways': getattr(config, 'SHOW_GATEWAYS', True),
            'show_position_trails': getattr(config, 'SHOW_POSITION_TRAILS', True),
            'show_nautical_markers': getattr(config, 'SHOW_NAUTICAL_MARKERS', True),
            'trail_history_hours': getattr(config, 'TRAIL_HISTORY_HOURS', 24)
        }
    })


@app.route('/api/recent_messages', methods=['GET'])
@require_api_key
@check_rate_limit
def recent_messages():
    try:
        msgs = mqtt_handler.get_recent(limit=100)
        return jsonify({'recent': msgs, 'count': len(msgs)})
    except Exception as e:
        logger.exception('Failed to return recent messages')
        return jsonify({'error': str(e)}), 500


@app.route('/api/nodes', methods=['GET'])
@require_api_key
@check_rate_limit
def get_nodes():
    """Return all tracked nodes with their current status."""
    nodes = mqtt_handler.get_nodes()
    return jsonify({'nodes': nodes, 'count': len(nodes)})


@app.route('/api/special/history', methods=['GET'])
@require_api_key
@check_rate_limit
def special_history():
    from flask import request
    try:
        node_id = int(request.args.get('node_id'))
    except Exception:
        return jsonify({'error': 'node_id is required'}), 400
    try:
        hours = request.args.get('hours', type=int) or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
        data = mqtt_handler.get_special_history(node_id, hours)
        return jsonify({'node_id': node_id, 'hours': hours, 'points': data, 'count': len(data)})
    except Exception as e:
        logger.exception('Failed to get special history')
        return jsonify({'error': str(e)}), 500

# /api/special/all_history removed - unused endpoint


@app.route('/api/special/packets', methods=['GET'])
@require_api_key
@check_rate_limit
def special_packets_all():
    """Get recent packets for all special nodes."""
    from flask import request
    try:
        limit = request.args.get('limit', type=int, default=50)
        data = mqtt_handler.get_special_node_packets(node_id=None, limit=limit)
        return jsonify({'packets': data, 'count': sum(len(v) for v in data.values())})
    except Exception as e:
        logger.exception('Failed to get special node packets')
        return jsonify({'error': str(e)}), 500


@app.route('/api/signal/history', methods=['GET'])
@require_api_key
@check_rate_limit
def signal_history():
    """Get signal history (battery, RSSI, SNR) for a specific node."""
    from flask import request
    try:
        node_id = int(request.args.get('node_id'))
    except Exception:
        return jsonify({'error': 'node_id is required'}), 400
    try:
        data = mqtt_handler.get_signal_history(node_id)
        return jsonify({'node_id': node_id, 'points': data, 'count': len(data)})
    except Exception as e:
        logger.exception('Failed to get signal history')
        return jsonify({'error': str(e)}), 500
# /api/special/packets/<node_id> removed - use /api/special/packets?limit= instead
# /api/special/voltage_history/<node_id> removed - redundant with /api/special/packets

# /api/config/reload removed - security risk
# /api/restart removed - security risk (remote DoS)
# Alert test endpoints removed - debug only


@app.route('/api/debug/rate-limit', methods=['GET'])
@check_rate_limit
def debug_rate_limit():
    """Debug endpoint to check rate limiter status - rate-limited but not auth-protected for testing."""
    client_ip = get_client_ip()
    remaining = rate_limiter.get_remaining(client_ip)
    limit = rate_limiter.requests_per_hour
    return jsonify({
        'client_ip': client_ip,
        'rate_limit_per_hour': limit,
        'requests_remaining_this_hour': remaining,
        'polling_interval_seconds': config.API_POLLING_INTERVAL_MS // 1000,
        'note': 'This endpoint is rate-limited and used for testing'
    })


@app.route('/docs/<filename>', methods=['GET'])
def serve_docs(filename):
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


# /api/inject-telemetry removed - security risk (test endpoint)

if __name__ == '__main__':
    logger.info(f'Starting Buoy Tracker on http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}')
    start_mqtt_on_startup()
    app.run(debug=False, host=config.WEBAPP_HOST, port=config.WEBAPP_PORT, threaded=True)
