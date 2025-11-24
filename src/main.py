"""Buoy Tracker Application - Flask web interface for Meshtastic node tracking"""

from flask import Flask, jsonify, render_template, url_for, request, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
import logging
import threading
import sys
import os
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
import socket

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL), 
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Configure socket reuse for faster restarts
app.config['ENV_SOCKET_REUSE'] = True

# Initialize rate limiter - use X-Forwarded-For for reverse proxy clients
def get_client_ip():
    """Extract client IP from X-Forwarded-For header (reverse proxy) or remote_addr."""
    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

limiter = Limiter(
    app=app,
    key_func=get_client_ip,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

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
        if not API_KEY:
            # If no API key configured, allow access (development mode)
            return f(*args, **kwargs)
        
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        
        provided_key = auth_header[7:]  # Strip "Bearer " prefix
        # Use constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(provided_key, API_KEY):
            return jsonify({'error': 'Unauthorized'}), 401
        
        return f(*args, **kwargs)
    return decorated

# Add cache control for static files (JS, CSS, etc)
@app.after_request
def set_cache_headers(response):
    """Set cache headers to prevent stale content."""
    # Force no-cache on all responses to prevent stale data
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.before_request
def enforce_https():
    """Enforce HTTPS when behind reverse proxy (X-Forwarded-Proto header)."""
    # Check X-Forwarded-Proto header set by reverse proxy
    if request.headers.get('X-Forwarded-Proto', 'http') == 'http':
        # Only redirect if we're actually behind a reverse proxy
        # Check for reverse proxy indicators (X-Forwarded-For, X-Forwarded-Host)
        if request.headers.get('X-Forwarded-For') or request.headers.get('X-Forwarded-Host'):
            url = request.url.replace('http://', 'https://', 1)
            return redirect(url, code=301)

# Flag to track if MQTT is running
mqtt_thread = None
mqtt_connected = False


def run_mqtt_in_background():
    """Run MQTT connection in background thread."""
    global mqtt_connected
    try:
        logger.info('Starting MQTT client in background thread')
        mqtt_handler.connect_mqtt()
        mqtt_connected = True
        # Keep thread alive - process any callbacks that need to run
        while True:
            time.sleep(1)
            # Check if client is still alive
            if mqtt_handler.client is None:
                logger.warning('MQTT client disconnected unexpectedly')
                break
    except Exception as e:
        logger.error(f'MQTT connection error: {e}')
        mqtt_connected = False


# Auto-start MQTT on app init
def start_mqtt_on_startup():
    """Start MQTT when Flask app initializes."""
    global mqtt_thread
    if mqtt_thread is None or not mqtt_thread.is_alive():
        mqtt_thread = threading.Thread(target=run_mqtt_in_background, daemon=True)
        mqtt_thread.start()
        logger.info('MQTT auto-started on app init')


@app.before_request
def _():
    """Ensure MQTT is started on first request."""
    global mqtt_thread
    if mqtt_thread is None or not mqtt_thread.is_alive():
        start_mqtt_on_startup()


@app.route('/', methods=['GET'])
def index():
    """Serve the main map page."""
    from flask import make_response
    response = make_response(render_template('simple.html',
                          app_title=config.APP_TITLE,
                          app_version=config.APP_VERSION,
                          default_lat=config.DEFAULT_LAT,
                          default_lon=config.DEFAULT_LON,
                          default_zoom=config.DEFAULT_ZOOM,
                          node_refresh=config.NODE_REFRESH_INTERVAL,
                          status_refresh=config.STATUS_REFRESH_INTERVAL,
                          special_symbol=config.SPECIAL_NODE_SYMBOL,
                          special_highlight_color='#FFD700',
                          special_history_hours=getattr(config, 'SPECIAL_HISTORY_HOURS', 24),
                          special_move_threshold=getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0),
                          api_key_required=(API_KEY is not None),
                          api_key=API_KEY or '',
                          build_id=int(time.time())))
    # Disable caching for HTML to always get fresh page
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})





@app.route('/api/status', methods=['GET'])
@require_api_key
@limiter.limit("100/hour")
def api_status():
    """Compatibility status endpoint used by the simple.html UI."""
    nodes = mqtt_handler.get_nodes()
    mqtt_status = mqtt_handler.is_connected()
    return jsonify({
        'mqtt_connected': (mqtt_status in ('connected_to_server', 'receiving_packets')),
        'mqtt_status': mqtt_status,
        'nodes_tracked': len(nodes),
        'nodes_with_position': len(nodes),
        'config': {
            'status_blue_threshold': config.STATUS_BLUE_THRESHOLD,
            'status_orange_threshold': config.STATUS_ORANGE_THRESHOLD,
            'special_movement_threshold': getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50)
        }
    })





@app.route('/api/nodes', methods=['GET'])
@require_api_key
@limiter.limit("100/hour")
def get_nodes():
    """Return all tracked nodes with their current status."""
    nodes = mqtt_handler.get_nodes()
    return jsonify({'nodes': nodes, 'count': len(nodes)})


@app.route('/api/special/history', methods=['GET'])
@require_api_key
@limiter.limit("200/hour")
def special_history():
    from flask import request
    try:
        node_id = int(request.args.get('node_id'))
    except Exception:
        return jsonify({'error': 'Invalid request'}), 400
    try:
        hours = request.args.get('hours', type=int) or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
        # Validate bounds to prevent DoS via excessive data requests
        if hours < 1 or hours > 168:  # Max 7 days
            return jsonify({'error': 'Invalid request'}), 400
        data = mqtt_handler.get_special_history(node_id, hours)
        return jsonify({'node_id': node_id, 'hours': hours, 'points': data, 'count': len(data)})
    except Exception as e:
        logger.exception('Failed to get special history')
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/special/packets', methods=['GET'])
@require_api_key
@limiter.limit("200/hour")
def special_packets_all():
    """Get recent packets for all special nodes."""
    from flask import request
    try:
        limit = request.args.get('limit', type=int, default=50)
        # Validate bounds to prevent DoS via excessive data requests
        if limit < 1 or limit > 1000:
            return jsonify({'error': 'Invalid request'}), 400
        data = mqtt_handler.get_special_node_packets(node_id=None, limit=limit)
        return jsonify({'packets': data, 'count': sum(len(v) for v in data.values())})
    except Exception as e:
        logger.exception('Failed to get special node packets')
        return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    logger.info(f'Starting Buoy Tracker on http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}')
    app.run(debug=False, host=config.WEBAPP_HOST, port=config.WEBAPP_PORT, threaded=True)


@app.after_request
def add_no_cache_headers(response):
    """Disable caching so template/script updates are seen immediately."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response
