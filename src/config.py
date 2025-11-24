"""Configuration loader for Buoy Tracker"""
import configparser
import os
import re
from pathlib import Path

# Find config files (look in project root)
# Public config: tracker.config (user copy) or tracker.config.template (template)
# Secrets config: secret.config (user copy, optional)
CONFIG_FILE = Path(__file__).parent.parent / 'tracker.config'
CONFIG_TEMPLATE_FILE = Path(__file__).parent.parent / 'tracker.config.template'
CONFIG_SECRETS_FILE = Path(__file__).parent.parent / 'secret.config'

# Use tracker.config if exists, otherwise fall back to tracker.config.template
if not CONFIG_FILE.exists():
    CONFIG_FILE = CONFIG_TEMPLATE_FILE

def parse_coordinate(coord_str):
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
    except Exception as inner_e:
        print(f"WARNING: Invalid movement_threshold in [special_nodes] section: {e}")
        print(f"  Using fallback value: 50.0 meters")
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
        print(f"\n*** CONFIGURATION ERROR ***")
        print(f"Invalid default_center format in [webapp] section:")
        print(f"  Value provided: {_default_center}")
        print(f"  Error: {e}")
        print(f"\nExpected format:")
        print(f"  Decimal: default_center = 37.5528,-122.1947")
        print(f"  Degrees-minutes: default_center = N37° 33.16', W122° 11.70'")
        print(f"*** STOPPING - Fix the config file and restart ***\n")
        raise
else:
    print(f"\n*** CONFIGURATION ERROR ***")
    print(f"default_center must contain exactly 2 coordinates (latitude,longitude)")
    print(f"  Value provided: {_default_center}")
    print(f"  Expected format: default_center = latitude,longitude")
    print(f"*** STOPPING - Fix the config file and restart ***\n")
    raise ValueError(f"Invalid default_center format")

DEFAULT_ZOOM = config.getint('webapp', 'default_zoom', fallback=10)
# Status thresholds: configured in hours, converted to seconds for internal use
_status_blue_threshold_hours = config.getint('webapp', 'status_blue_threshold', fallback=1)
STATUS_BLUE_THRESHOLD = _status_blue_threshold_hours * 3600
_status_orange_threshold_hours = config.getint('webapp', 'status_orange_threshold', fallback=12)
STATUS_ORANGE_THRESHOLD = _status_orange_threshold_hours * 3600
# Refresh intervals: configured in seconds, converted to milliseconds for frontend
NODE_REFRESH_INTERVAL = config.getint('webapp', 'node_refresh_interval', fallback=2) * 1000
STATUS_REFRESH_INTERVAL = config.getint('webapp', 'status_refresh_interval', fallback=5) * 1000

# API Polling Interval - single unified interval for all endpoints
# Read from config (defaults to 60 seconds if not specified)
_api_polling_interval_seconds = config.getint('webapp', 'api_polling_interval', fallback=60)

# Validate polling interval is reasonable
if _api_polling_interval_seconds < 1:
    print(f"\n*** CONFIGURATION WARNING ***")
    print(f"api_polling_interval is too low: {_api_polling_interval_seconds}s")
    print(f"Minimum recommended: 5 seconds")
    print(f"Setting to 5 seconds instead\n")
    _api_polling_interval_seconds = 5
elif _api_polling_interval_seconds > 60:
    print(f"\n*** CONFIGURATION WARNING ***")
    print(f"api_polling_interval is inefficient: {_api_polling_interval_seconds}s")
    print(f"Polling intervals > 60 seconds waste the rate limit.")
    print(f"Recommended: 5-60 seconds. Using 60 seconds instead.\n")
    _api_polling_interval_seconds = 60

# Convert polling interval (seconds) to milliseconds for client
API_POLLING_INTERVAL_MS = _api_polling_interval_seconds * 1000

# Auto-calculate API rate limit based on polling interval
# At 3 concurrent endpoints (status, nodes, special/packets) polling every N seconds:
# - 1 hour = 3600 seconds
# - Requests per endpoint = 3600 / N seconds
# - Total requests = (3600 / N) * 3 endpoints * 1.5 (safety margin)
# Round up to nearest 10 for clean numbers
_requests_per_hour = int((3600.0 / _api_polling_interval_seconds) * 3 * 1.5)
_rounded_limit = ((_requests_per_hour + 9) // 10) * 10  # Round up to nearest 10
API_RATE_LIMIT = f'{_rounded_limit}/hour'

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

# Special Nodes Configuration (parse format: node_id = label,home_lat,home_lon)
SPECIAL_NODES = {}
SPECIAL_NODE_SYMBOL = config.get('special_nodes_settings', 'special_symbol', fallback='⭐')  # Symbol for special nodes

if config.has_section('special_nodes'):
    for key, value in config.items('special_nodes'):
        # Skip comments and non-node-id keys (like movement_threshold)
        # Format: "entry1 = node_id,label,home_lat,home_lon", "entry2 = ...", etc.
        if key.startswith('#') or not key.startswith('entry'):
            continue
        try:
            # Value format: "node_id,label,home_lat,home_lon"
            parts = [p.strip() for p in value.split(',')]
            
            if len(parts) < 1:
                raise ValueError(f"Empty node definition")
            
            node_id = int(parts[0])
            label = parts[1] if len(parts) > 1 else 'Special Node'
            
            # Optional: home position (lat, lon)
            home_lat = None
            home_lon = None
            if len(parts) >= 4:
                try:
                    home_lat = parse_coordinate(parts[2])
                    home_lon = parse_coordinate(parts[3])
                except (ValueError, IndexError) as e:
                    print(f"WARNING: Invalid coordinates for node {node_id} ({label}): {e}")
                    print(f"  Format provided: {value}")
                    print(f"  Expected: 'node_id,label,latitude,longitude'")
                    print(f"  Latitude/Longitude can be decimal (37.5637125,-122.2189855)")
                    print(f"  Or degrees-minutes (N37° 33.81',W122° 13.13')")
                    print(f"  Will use first position as origin instead")
                    pass  # Invalid coordinates, will use first position as origin
            
            SPECIAL_NODES[node_id] = {
                'symbol': SPECIAL_NODE_SYMBOL,  # Use default symbol for all
                'label': label,
                'home_lat': home_lat,
                'home_lon': home_lon
            }
        except (ValueError, IndexError) as e:
            # Skip invalid entries
            print(f"WARNING: Skipping invalid special_nodes entry: '{key} = {value}'")
            print(f"  Error: {e}")
            print(f"  Expected format: 'entry# = node_id,label,latitude,longitude'")
            pass

# List of special node IDs for easy checking
SPECIAL_NODE_IDS = list(SPECIAL_NODES.keys())

# Special nodes advanced settings
SPECIAL_HISTORY_HOURS = config.getint('special_nodes_settings', 'history_hours', fallback=24)
# Default persist path under project data/ (use relative path for Docker/portability)
_default_history_path = 'data/special_history.json'
SPECIAL_HISTORY_PERSIST_PATH = config.get('special_nodes_settings', 'persist_path', fallback=_default_history_path)
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
    _host = WEBAPP_HOST if WEBAPP_HOST != '0.0.0.0' else 'localhost'
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
