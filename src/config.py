"""Configuration loader for Buoy Tracker"""
import configparser
import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Find config files (look in project root)
# Public config: tracker.config (user copy) or tracker.config.template (template)
# Secrets config: secret.config (user copy, optional)
CONFIG_FILE = Path(__file__).parent.parent / 'tracker.config'
CONFIG_TEMPLATE_FILE = Path(__file__).parent.parent / 'tracker.config.template'
CONFIG_SECRETS_FILE = Path(__file__).parent.parent / 'secret.config'

# Use tracker.config if exists, otherwise fall back to tracker.config.template
if not CONFIG_FILE.exists():
    CONFIG_FILE = CONFIG_TEMPLATE_FILE

def parse_coordinate(coord_str: str) -> float:
    """
    Parse coordinate in either decimal or degrees-minutes format.
    
    Supports:
    - Decimal: 37.5637125, -122.2189855
    - Degrees-minutes: N37° 33.81', W122° 13.13'
    
    Returns float coordinate value.
    Raises ValueError if format is invalid.
    """
    coord_str = coord_str.strip()
    
    # Try decimal format first
    try:
        return float(coord_str)
    except ValueError:
        pass
    
    # Try degrees-minutes format: N37° 33.81' or W122° 13.13'
    # Pattern: (N|S|E|W)(\d+)°\s*(\d+\.?\d*)'?
    pattern = r'([NSEW])(\d+)°\s*(\d+\.?\d*)'
    match = re.match(pattern, coord_str, re.IGNORECASE)
    
    if match:
        direction = match.group(1).upper()
        degrees = float(match.group(2))
        minutes = float(match.group(3))
        
        # Validate ranges
        if degrees < 0 or degrees > 180:
            raise ValueError(f"Degrees out of range (0-180): {degrees}")
        if minutes < 0 or minutes >= 60:
            raise ValueError(f"Minutes out of range (0-60): {minutes}")
        
        # Convert to decimal degrees
        decimal = degrees + (minutes / 60.0)
        
        # Apply sign based on direction
        if direction in ['S', 'W']:
            decimal = -decimal
        
        return decimal
    
    # If neither format works, raise error with helpful message
    raise ValueError(f"Invalid coordinate format: '{coord_str}'\nExpected: decimal (37.5637125) or degrees-minutes (N37° 33.81')")

# Load configuration
config = configparser.ConfigParser()
if CONFIG_FILE.exists():
    config.read(CONFIG_FILE)
else:
    raise FileNotFoundError(f"Configuration file not found: {CONFIG_FILE}")

# Load secrets configuration if it exists (overrides public config)
secrets_config = configparser.ConfigParser()
if CONFIG_SECRETS_FILE.exists():
    secrets_config.read(CONFIG_SECRETS_FILE)
    # Merge secrets into main config (secrets take precedence)
    for section in secrets_config.sections():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in secrets_config.items(section):
            config.set(section, key, value)

# App Metadata
APP_TITLE = config.get('app', 'title', fallback='Buoy Tracker')
APP_VERSION = config.get('app', 'version', fallback='0.1')

# MQTT Configuration
MQTT_BROKER = config.get('mqtt', 'broker', fallback='mqtt.bayme.sh')
MQTT_PORT = config.getint('mqtt', 'port', fallback=1883)
MQTT_ROOT_TOPIC = config.get('mqtt', 'root_topic', fallback='msh/US/bayarea/2/e/')
# SECURITY: Try environment variables first, fallback to config file
# This allows production deployments to keep secrets out of version control
MQTT_USERNAME = os.getenv('MQTT_USERNAME') or config.get('mqtt', 'username', fallback='meshdev')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD') or config.get('mqtt', 'password', fallback='large4cats')
MQTT_KEY = os.getenv('MQTT_KEY') or config.get('mqtt', 'encryption_key', fallback='AQ==')

# Note: We do not map channel numbers to modem presets because
# the numeric channel in packets (e.g., 31) is not a reliable indicator
# of the configured LoRa modem preset. We will extract preset names
# from packet payloads if/when present.

# Special Nodes movement alert threshold (meters)
# Support both keys: movement_threshold and movement_threshold_meters
try:
    SPECIAL_MOVEMENT_THRESHOLD_METERS = config.getfloat('special_nodes', 'movement_threshold')
except Exception as e:
    try:
        SPECIAL_MOVEMENT_THRESHOLD_METERS = config.getfloat('special_nodes', 'movement_threshold_meters', fallback=50.0)
    except Exception:
        logger.warning(f"Invalid movement_threshold in [special_nodes] section: {e}")
        logger.warning("Using fallback value: 50.0 meters")
        SPECIAL_MOVEMENT_THRESHOLD_METERS = 50.0

# Web App Configuration
WEBAPP_HOST = config.get('webapp', 'host', fallback='127.0.0.1')
WEBAPP_PORT = config.getint('webapp', 'port', fallback=5102)

# Parse default center point (supports both decimal and degrees-minutes formats)
_default_center = config.get('webapp', 'default_center', fallback='37.7749,-122.4194')
_center_parts = [p.strip() for p in _default_center.split(',')]
if len(_center_parts) >= 2:
    try:
        DEFAULT_LAT = parse_coordinate(_center_parts[0])
        DEFAULT_LON = parse_coordinate(_center_parts[1])
    except (ValueError, IndexError) as e:
        logger.error(f"Invalid default_center format in [webapp] section: {e}")
        logger.error(f"  Value provided: {_default_center}")
        logger.error("Expected format: decimal (37.5528,-122.1947) or degrees-minutes (N37° 33.16', W122° 11.70')")
        raise
else:
    logger.error("default_center must contain exactly 2 coordinates (latitude,longitude)")
    logger.error(f"  Value provided: {_default_center}")
    raise ValueError("Invalid default_center format")

DEFAULT_ZOOM = config.getint('webapp', 'default_zoom', fallback=10)
# Status thresholds: configured in hours, converted to seconds for internal use
_status_blue_threshold_hours = config.getint('webapp', 'status_blue_threshold', fallback=1)
STATUS_BLUE_THRESHOLD = _status_blue_threshold_hours * 3600
_status_orange_threshold_hours = config.getint('webapp', 'status_orange_threshold', fallback=12)
STATUS_ORANGE_THRESHOLD = _status_orange_threshold_hours * 3600
# API Polling Interval - single unified interval for all endpoints
# Read from config (defaults to 60 seconds if not specified)
_api_polling_interval_seconds = config.getint('webapp', 'api_polling_interval', fallback=60)

# Validate polling interval is reasonable
if _api_polling_interval_seconds < 1:
    logger.warning(f"api_polling_interval is too low: {_api_polling_interval_seconds}s (minimum: 5s), using 5s")
    _api_polling_interval_seconds = 5
elif _api_polling_interval_seconds > 60:
    logger.warning(f"api_polling_interval is inefficient: {_api_polling_interval_seconds}s (recommended: 5-60s), using 60s")
    _api_polling_interval_seconds = 60

# Convert polling interval (seconds) to milliseconds for client
API_POLLING_INTERVAL_MS = _api_polling_interval_seconds * 1000

# API rate limit will be calculated after SPECIAL_NODES are loaded
API_RATE_LIMIT = None

# API Authentication - key must be in secret.config (never in public tracker.config)
# If not set, API endpoints will not require authentication (development mode)
# Generate a key: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Format in secret.config: [webapp]
#                         api_key = your-secret-key-here
API_KEY = config.get('webapp', 'api_key', fallback=None)

# Debug Configuration
LOG_LEVEL = config.get('debug', 'log_level', fallback='INFO')
RECENT_MESSAGE_BUFFER_SIZE = config.getint('debug', 'recent_message_buffer_size', fallback=200)

# Battery Configuration
LOW_BATTERY_THRESHOLD = config.getint('battery', 'low_battery_threshold', fallback=50)

# App Features Configuration
# Controls which features are visible and configurable by end users
SHOW_ALL_NODES = config.getboolean('app_features', 'show_all_nodes', fallback=False)
SHOW_GATEWAYS = config.getboolean('app_features', 'show_gateways', fallback=True)
SHOW_POSITION_TRAILS = config.getboolean('app_features', 'show_position_trails', fallback=True)
SHOW_GATEWAY_CONNECTIONS = config.getboolean('app_features', 'show_gateway_connections', fallback=True)
SHOW_NAUTICAL_MARKERS = config.getboolean('app_features', 'show_nautical_markers', fallback=True)
# SHOW_CONTROLS_MENU: Admin-controlled setting to show/hide the Configuration panel
#   - true: Users see both "Legend" and "Controls" tabs in the settings menu (default)
#   - false: Users only see "Legend" tab; "Controls" tab is hidden (locks configuration)
# This is a read-only setting controlled by the administrator via tracker.config.
# End users cannot override this setting. When false, prevents user modification of:
#   - Node display filters (all nodes, gateways, etc.)
#   - Position trail settings
#   - Battery/movement thresholds
#   - API polling interval
# Use this to enforce consistent configuration across all users in public deployments.
SHOW_CONTROLS_MENU = config.getboolean('app_features', 'show_controls_menu', fallback=True)
TRAIL_HISTORY_HOURS = config.getint('app_features', 'trail_history_hours', fallback=24)

# Special Nodes Configuration (parse format: node_id = label,home_lat,home_lon)
SPECIAL_NODES = {}
SPECIAL_NODE_SYMBOL = config.get('special_nodes_settings', 'special_symbol', fallback='⭐')  # Symbol for special nodes

if config.has_section('special_nodes'):
    seen_node_ids = {}  # Track node IDs to detect duplicates
    for key, value in config.items('special_nodes'):
        # Skip non-numeric keys (like movement_threshold)
        if not key.isdigit():
            continue
        try:
            # Parse three flexible formats:
            # (1) node_id (value is empty)
            # (2) node_id = label (value is label)
            # (3) node_id = label,home_lat,home_lon (value is comma-separated)

            node_id = int(key)
            label = None
            home_lat = None
            home_lon = None

            if value and value.strip():
                # Has value - could be format 2 or 3
                # Remove any inline comments
                value_clean = value.split('#')[0].strip()

                if value_clean:
                    parts = [p.strip() for p in value_clean.split(',')]
                    # First part is always the label
                    label = parts[0] if parts[0] else None

                    # Optional home position (lat, lon) in parts 2 and 3
                    if len(parts) >= 3:
                        try:
                            home_lat = parse_coordinate(parts[1])
                            home_lon = parse_coordinate(parts[2])
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Invalid coordinates for node {node_id} ({label}): {e}. Will use first position as origin.")

            # Check for duplicate node IDs
            if node_id in seen_node_ids:
                logger.error(f"DUPLICATE special node ID {node_id} found in '{key}' and '{seen_node_ids[node_id]}' - second entry will be ignored!")
                continue
            seen_node_ids[node_id] = key

            SPECIAL_NODES[node_id] = {
                'symbol': SPECIAL_NODE_SYMBOL,  # Use default symbol for all
                'label': label,
                'home_lat': home_lat,
                'home_lon': home_lon
            }
        except (ValueError, IndexError) as e:
            logger.warning(f"Skipping invalid special_nodes entry '{key} = {value}': {e}. Expected formats: (1) node_id, (2) node_id = label, (3) node_id = label,latitude,longitude")

# List of special node IDs for easy checking
SPECIAL_NODE_IDS = list(SPECIAL_NODES.keys())

# Now calculate API rate limit based on actual number of special nodes
# Actual requests per polling interval:
#   - Base endpoints: api/status, api/nodes, api/special/packets = 3
#   - Per special node history request (when trails enabled) = N nodes
#   - Total per interval: 3 + N_special_nodes
# Formula: (3600 / polling_seconds) * (3 + N_special_nodes) * 2.0 (safety margin)
# 2.0x multiplier provides safe headroom for traffic spikes
_polling_seconds = _api_polling_interval_seconds
_num_special_nodes = len(SPECIAL_NODE_IDS)
_requests_per_poll = 3 + _num_special_nodes  # 3 base endpoints + N special node history requests
_requests_per_hour = int((3600.0 / _polling_seconds) * _requests_per_poll * 2.0)
_rounded_limit = ((_requests_per_hour + 9) // 10) * 10  # Round up to nearest 10
API_RATE_LIMIT = f'{_rounded_limit}/hour'
logger.info(f'API rate limit: {API_RATE_LIMIT} (polling: {_polling_seconds}s, {_requests_per_poll} requests/interval with {_num_special_nodes} special nodes)')

# Special nodes advanced settings
# Use trail_history_hours for special node history (shared with UI trail display)
SPECIAL_HISTORY_HOURS = TRAIL_HISTORY_HOURS
# Consider nodes stale when time since last seen exceeds this threshold (in hours)
_stale_after_hours = config.getint('special_nodes_settings', 'stale_after_hours', fallback=12)
STALE_AFTER_SECONDS = _stale_after_hours * 3600

# Alert Configuration
ALERT_ENABLED = config.getboolean('alerts', 'enabled', fallback=False)
# Alert cooldown: configured in hours, converted to seconds for internal use
_alert_cooldown_hours = config.getint('alerts', 'alert_cooldown', fallback=1)
ALERT_COOLDOWN = _alert_cooldown_hours * 3600

# Tracker URL for email alerts - REQUIRED for production
# Set this to the public URL where your tracker is accessible (e.g., http://example.com:5102)
# If not set, defaults to localhost (only works for local testing)
_tracker_url = config.get('alerts', 'tracker_url', fallback='')
if _tracker_url:
    ALERT_TRACKER_URL = _tracker_url
else:
    # Fallback: Auto-generate from webapp host and port
    # This only works if WEBAPP_HOST is set to a real hostname/IP (not 0.0.0.0)
    # For production, explicitly set tracker_url in config
    _host = WEBAPP_HOST if WEBAPP_HOST != '127.0.0.1' else 'localhost'  # Consider restricting to specific interfaces in production
    ALERT_TRACKER_URL = f'http://{_host}:{WEBAPP_PORT}'

# SMTP settings - try environment variables first for security
# Default uses localhost:25 (sendmail/postfix) - no auth needed
# Override for external SMTP providers (Gmail, SendGrid, AWS SES, etc.)
ALERT_SMTP_HOST = config.get('alerts', 'smtp_host', fallback='localhost')
ALERT_SMTP_PORT = config.getint('alerts', 'smtp_port', fallback=25)
ALERT_SMTP_SSL = config.getboolean('alerts', 'smtp_ssl', fallback=False)
ALERT_SMTP_USERNAME = os.getenv('ALERT_SMTP_USERNAME') or config.get('alerts', 'smtp_username', fallback='')
ALERT_SMTP_PASSWORD = os.getenv('ALERT_SMTP_PASSWORD') or config.get('alerts', 'smtp_password', fallback='')

# Email addresses
ALERT_EMAIL_FROM = config.get('alerts', 'email_from', fallback='norepy@sequoiayc.org')
ALERT_EMAIL_TO = config.get('alerts', 'email_to', fallback='admin@example.com')

# Special nodes data persistence
SPECIAL_HISTORY_PERSIST_PATH = str(Path(__file__).parent.parent / 'data' / 'special_nodes.json')

# Security Configuration
# Environment: 'development' (localhost allowed) or 'production' (strict security)
ENV = os.getenv('FLASK_ENV', config.get('security', 'environment', fallback='development'))

# Trusted reverse proxy IPs - only these can be trusted for X-Forwarded-For header
# For example: ['10.0.0.50'] for nginx, ['10.0.0.50', '10.0.0.51'] for load balancer
# Empty list = no reverse proxy trusted (direct connection only)
TRUSTED_PROXIES = [ip.strip() for ip in os.getenv('TRUSTED_PROXIES', 
    config.get('security', 'trusted_proxies', fallback='')).split(',') if ip.strip()]

# CORS allowed origins - list of domains allowed to make cross-origin requests
# Example: ['https://tracker.example.com', 'https://app.example.com']
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv('ALLOWED_ORIGINS',
    config.get('security', 'allowed_origins', fallback='*')).split(',') if origin.strip()]
