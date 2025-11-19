"""Buoy Tracker Application - Flask web interface for Meshtastic node tracking"""

from flask import Flask, jsonify, render_template, url_for, request
import logging
import threading
import sys
import os
from pathlib import Path
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

# Add cache control for static files (JS, CSS, etc)
@app.after_request
def set_cache_headers(response):
    """Set cache headers to prevent stale content."""
    # Force no-cache on all responses to prevent stale data
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

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
                          special_highlight_color=config.SPECIAL_NODE_HIGHLIGHT_COLOR,
                          special_history_hours=getattr(config, 'SPECIAL_HISTORY_HOURS', 24),
                          show_offline_specials=getattr(config, 'SPECIAL_SHOW_OFFLINE', True),
                          stale_special_symbol=getattr(config, 'STALE_SPECIAL_SYMBOL', '☆'),
                          mqtt_channels=','.join(config.MQTT_CHANNELS),
                          special_move_threshold=getattr(config, 'SPECIAL_MOVEMENT_THRESHOLD_METERS', 50.0),
                          build_id=int(time.time())))
    # Disable caching for HTML to always get fresh page
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'})


@app.route('/api/mqtt/connect', methods=['POST'])
def mqtt_connect():
    global mqtt_thread
    try:
        if mqtt_thread is None or not mqtt_thread.is_alive():
            mqtt_thread = threading.Thread(target=run_mqtt_in_background, daemon=True)
            mqtt_thread.start()
            logger.info('MQTT connect requested - thread started')
        return jsonify({'status': 'connecting'}), 200
    except Exception as e:
        logger.exception('Failed to start MQTT thread')
        return jsonify({'error': str(e)}), 500


@app.route('/api/mqtt/disconnect', methods=['POST'])
def mqtt_disconnect():
    mqtt_handler.disconnect_mqtt()
    logger.info('MQTT disconnect requested')
    return jsonify({'status': 'disconnected'}), 200



@app.route('/api/mqtt/status', methods=['GET'])
def mqtt_status():
    status = mqtt_handler.is_connected()
    return jsonify({'status': status})


@app.route('/api/status', methods=['GET'])
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
            'status_orange_threshold': config.STATUS_ORANGE_THRESHOLD
        }
    })


@app.route('/api/recent_messages', methods=['GET'])
def recent_messages():
    try:
        msgs = mqtt_handler.get_recent(limit=100)
        return jsonify({'recent': msgs, 'count': len(msgs)})
    except Exception as e:
        logger.exception('Failed to return recent messages')
        return jsonify({'error': str(e)}), 500


@app.route('/api/nodes', methods=['GET'])
def get_nodes():
    """Return all tracked nodes with their current status."""
    nodes = mqtt_handler.get_nodes()
    return jsonify({'nodes': nodes, 'count': len(nodes)})


@app.route('/api/special/history', methods=['GET'])
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

@app.route('/api/special/all_history', methods=['GET'])
def all_special_history():
    from flask import request
    try:
        hours = request.args.get('hours', type=int) or getattr(config, 'SPECIAL_HISTORY_HOURS', 24)
        data = mqtt_handler.get_all_special_history(hours)
        return jsonify({'hours': hours, 'histories': data})
    except Exception as e:
        logger.exception('Failed to get all special histories')
        return jsonify({'error': str(e)}), 500


@app.route('/api/special/packets', methods=['GET'])
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


@app.route('/api/special/packets/<int:node_id>', methods=['GET'])
def special_packets_single(node_id):
    """Get recent packets for a specific special node."""
    from flask import request
    try:
        limit = request.args.get('limit', type=int, default=50)
        data = mqtt_handler.get_special_node_packets(node_id=node_id, limit=limit)
        return jsonify({'node_id': node_id, 'packets': data, 'count': len(data)})
    except Exception as e:
        logger.exception('Failed to get special node packets')
        return jsonify({'error': str(e)}), 500


@app.route('/api/special/voltage_history/<int:node_id>', methods=['GET'])
def voltage_history(node_id):
    """Get voltage history for a specific node from past week of telemetry packets."""
    from flask import request
    try:
        # Get time range (default 1 week)
        days = request.args.get('days', type=int, default=7)
        cutoff_time = time.time() - (days * 24 * 3600)
        
        # Get packets and extract voltage data
        packets = mqtt_handler.get_special_node_packets(node_id=node_id, limit=None)
        voltage_data = []
        
        for pkt in packets:
            if pkt.get('packet_type') == 'TELEMETRY_APP':
                timestamp = pkt.get('timestamp')
                voltage = pkt.get('voltage')
                battery_level = pkt.get('battery_level')
                
                # Filter by time range and valid voltage
                if timestamp and timestamp >= cutoff_time and voltage is not None:
                    voltage_data.append({
                        'timestamp': timestamp,
                        'voltage': voltage,
                        'battery_level': battery_level
                    })
        
        # Sort by timestamp (oldest first)
        voltage_data.sort(key=lambda x: x['timestamp'])
        
        return jsonify({
            'node_id': node_id,
            'days': days,
            'count': len(voltage_data),
            'data': voltage_data
        })
    except Exception as e:
        logger.exception('Failed to get voltage history')
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/reload', methods=['POST'])
def reload_config():
    """Reload configuration from tracker.config without restarting the server."""
    try:
        import importlib
        importlib.reload(config)
        
        # Update special nodes in mqtt_handler
        mqtt_handler.update_special_nodes()
        
        logger.info('Configuration reloaded successfully')
        return jsonify({
            'status': 'success', 
            'message': 'Configuration reloaded',
            'special_nodes': len(getattr(config, 'SPECIAL_NODE_IDS', []))
        }), 200
    except Exception as e:
        logger.error(f'Failed to reload config: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/restart', methods=['POST'])
def restart_server():
    """Restart the server by spawning a new process and exiting."""
    def do_restart():
        """Execute restart in background thread."""
        try:
            logger.info('Server restart requested - waiting 2 seconds to send response')
            time.sleep(2)  # Give time for HTTP response to be sent
            
            logger.info('Disconnecting MQTT')
            mqtt_handler.disconnect_mqtt()
            
            logger.info('Starting new server process...')
            # Get the path to the current Python interpreter
            python = sys.executable
            
            # Use run.py in the current directory
            import subprocess
            import os
            script_dir = os.path.dirname(os.path.abspath(__file__))
            run_script = os.path.join(os.path.dirname(script_dir), 'run.py')
            
            # Start new process with output redirected to same log file
            subprocess.Popen(
                [python, run_script],
                stdout=open('/tmp/buoy.log', 'a'),
                stderr=subprocess.STDOUT,
                start_new_session=True  # Detach from parent
            )
            
            logger.info('New process started, exiting old process')
            # Exit current process forcefully
            os._exit(0)
        except Exception as e:
            logger.error(f'Failed to restart server: {e}')
    
    # Start restart in background thread to allow response to be sent
    threading.Thread(target=do_restart, daemon=True).start()
    logger.info('Server restart initiated')
    return jsonify({'status': 'restarting', 'message': 'Server will restart in 2 seconds'}), 200


@app.route('/api/test-alert', methods=['POST'])
def test_alert():
    """Test the email alert system configuration."""
    from . import alerts
    
    if not getattr(config, 'ALERT_ENABLED', False):
        return jsonify({'status': 'error', 'message': 'Alerts are disabled in configuration'}), 400
    
    try:
        # Test email configuration
        alerts.test_email_config()
        return jsonify({'status': 'success', 'message': 'Test email sent successfully'}), 200
    except Exception as e:
        logger.error(f'Alert test failed: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/test-alert-movement', methods=['POST'])
def test_alert_movement():
    """Test movement alert with sample data."""
    from . import alerts
    
    if not getattr(config, 'ALERT_ENABLED', False):
        return jsonify({'status': 'error', 'message': 'Alerts are disabled in configuration'}), 400
    
    try:
        # Get first special node as test case
        if not config.SPECIAL_NODE_IDS:
            return jsonify({'status': 'error', 'message': 'No special nodes configured'}), 400
        
        test_node_id = config.SPECIAL_NODE_IDS[0]
        test_node_data = {
            'long_name': 'Test Node',
            'short_name': 'TEST',
            'latitude': 37.5800,
            'longitude': -122.2200,
            'origin_lat': 37.5637,
            'origin_lon': -122.2190,
            'battery_level': 75
        }
        
        # Send movement alert (300m from origin)
        alerts.send_movement_alert(test_node_id, test_node_data, 300.0)
        return jsonify({'status': 'success', 'message': 'Movement alert test sent successfully'}), 200
    except Exception as e:
        logger.error(f'Movement alert test failed: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/test-alert-battery', methods=['POST'])
def test_alert_battery():
    """Test battery alert with sample data."""
    from . import alerts
    
    if not getattr(config, 'ALERT_ENABLED', False):
        return jsonify({'status': 'error', 'message': 'Alerts are disabled in configuration'}), 400
    
    try:
        # Get first special node as test case
        if not config.SPECIAL_NODE_IDS:
            return jsonify({'status': 'error', 'message': 'No special nodes configured'}), 400
        
        test_node_id = config.SPECIAL_NODE_IDS[0]
        test_node_data = {
            'long_name': 'Test Node',
            'short_name': 'TEST',
            'latitude': 37.5800,
            'longitude': -122.2200,
        }
        
        # Send battery alert (15% battery, below threshold)
        alerts.send_battery_alert(test_node_id, test_node_data, 15)
        return jsonify({'status': 'success', 'message': 'Battery alert test sent successfully'}), 200
    except Exception as e:
        logger.error(f'Battery alert test failed: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


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


@app.route('/api/inject-telemetry', methods=['POST'])
def inject_telemetry():
    """Inject fake MQTT telemetry data for testing.
    
    POST data:
    {
        "node_id": 2512106321,        # Node ID (SYCA)
        "battery_level": 40,           # Battery percentage
        "channel_name": "MediumFast",  # Optional, default "TEST"
        "from_name": "Test Node"       # Optional, default "Test Node"
    }
    """
    try:
        data = request.get_json()
        node_id = data.get('node_id')
        battery_level = data.get('battery_level')
        channel_name = data.get('channel_name', 'TEST')
        from_name = data.get('from_name', 'Test Node')
        
        if not node_id or battery_level is None:
            return jsonify({'status': 'error', 'message': 'Missing node_id or battery_level'}), 400
        
        # Inject the telemetry data
        success = mqtt_handler.inject_telemetry_data(node_id, battery_level, channel_name, from_name)
        
        if success:
            return jsonify({
                'status': 'success',
                'message': f'Injected telemetry for node {node_id}',
                'node_id': node_id,
                'battery_level': battery_level
            }), 200
        else:
            return jsonify({'status': 'error', 'message': 'Failed to inject telemetry'}), 500
            
    except Exception as e:
        logger.error(f'Telemetry injection failed: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500
