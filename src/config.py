"""Configuration loader for Buoy Tracker"""
import configparser
import os
import re
from pathlib import Path

# Find config file (look in project root)
# Try tracker.config first, fall back to tracker.config.example
CONFIG_FILE = Path(__file__).parent.parent / 'tracker.config'
if not CONFIG_FILE.exists():
    CONFIG_FILE = Path(__file__).parent.parent / 'tracker.config.example'

def parse_coordinate(coord_str):
    """
    Parse coordinate in either decimal or degrees-minutes format.
    
    Supports:
    - Decimal: 37.5637125, -122.2189855
    - Degrees-minutes: N37° 33.81', W122° 13.13'
    
    Returns float coordinate value.
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
        
        # Convert to decimal degrees
        decimal = degrees + (minutes / 60.0)
        
        # Apply sign based on direction
        if direction in ['S', 'W']:
            decimal = -decimal
        
        return decimal
    
    # If neither format works, raise error
    raise ValueError(f"Invalid coordinate format: {coord_str}")

# Load configuration
config = configparser.ConfigParser()
if CONFIG_FILE.exists():
    config.read(CONFIG_FILE)
else:
    raise FileNotFoundError(f"Configuration file not found: {CONFIG_FILE}")

# App Metadata
APP_TITLE = config.get('app', 'title', fallback='Buoy Tracker')
APP_VERSION = config.get('app', 'version', fallback='0.1')

# MQTT Configuration
MQTT_BROKER = config.get('mqtt', 'broker', fallback='mqtt.bayme.sh')
MQTT_PORT = config.getint('mqtt', 'port', fallback=1883)
MQTT_ROOT_TOPIC = config.get('mqtt', 'root_topic', fallback='msh/US/bayarea/2/e/')
# Parse MQTT channels (comma-separated list of LoRa modem presets)
MQTT_CHANNELS = [c.strip() for c in config.get('mqtt', 'mqtt_channels', fallback='MediumFast').split(',') if c.strip()]
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
except Exception:
    SPECIAL_MOVEMENT_THRESHOLD_METERS = config.getfloat('special_nodes', 'movement_threshold_meters', fallback=50.0)

# Web App Configuration
WEBAPP_HOST = config.get('webapp', 'host', fallback='127.0.0.1')
WEBAPP_PORT = config.getint('webapp', 'port', fallback=5101)
DEFAULT_LAT = config.getfloat('webapp', 'default_lat', fallback=37.7749)
DEFAULT_LON = config.getfloat('webapp', 'default_lon', fallback=-122.4194)
DEFAULT_ZOOM = config.getint('webapp', 'default_zoom', fallback=10)
STATUS_BLUE_THRESHOLD = config.getint('webapp', 'status_blue_threshold', fallback=3600)
STATUS_ORANGE_THRESHOLD = config.getint('webapp', 'status_orange_threshold', fallback=43200)
NODE_REFRESH_INTERVAL = config.getint('webapp', 'node_refresh_interval', fallback=2000)
STATUS_REFRESH_INTERVAL = config.getint('webapp', 'status_refresh_interval', fallback=5000)

# Debug Configuration
LOG_LEVEL = config.get('debug', 'log_level', fallback='INFO')
RECENT_MESSAGE_BUFFER_SIZE = config.getint('debug', 'recent_message_buffer_size', fallback=200)

# Battery Configuration
LOW_BATTERY_THRESHOLD = config.getint('battery', 'low_battery_threshold', fallback=50)

# Special Nodes Configuration (parse format: node_id = label,home_lat,home_lon)
SPECIAL_NODES = {}
SPECIAL_NODE_SYMBOL = '⭐'  # Default symbol for all special nodes
SPECIAL_NODE_HIGHLIGHT_COLOR = '#FFD700'  # Gold color for highlighting

if config.has_section('special_nodes'):
    for node_id_str, value in config.items('special_nodes'):
        # Skip comments
        if node_id_str.startswith('#'):
            continue
        try:
            node_id = int(node_id_str.strip())
            parts = [p.strip() for p in value.split(',')]
            
            # Format: label,home_lat,home_lon
            # Coordinates can be in decimal (37.5637125,-122.2189855) 
            # or degrees-minutes format (N37° 33.81', W122° 13.13')
            label = parts[0] if len(parts) > 0 else 'Special Node'
            
            # Optional: home position (lat, lon)
            home_lat = None
            home_lon = None
            if len(parts) >= 3:
                try:
                    home_lat = parse_coordinate(parts[1])
                    home_lon = parse_coordinate(parts[2])
                except (ValueError, IndexError) as e:
                    print(f"Warning: Invalid coordinates for node {node_id}: {e}")
                    pass  # Invalid coordinates, will use first position as origin
            
            SPECIAL_NODES[node_id] = {
                'symbol': SPECIAL_NODE_SYMBOL,  # Use default symbol for all
                'label': label,
                'home_lat': home_lat,
                'home_lon': home_lon
            }
        except (ValueError, IndexError):
            # Skip invalid entries
            pass

# List of special node IDs for easy checking
SPECIAL_NODE_IDS = list(SPECIAL_NODES.keys())

# Special nodes advanced settings
SPECIAL_SHOW_OFFLINE = config.getboolean('special_nodes', 'show_offline', fallback=True)
SPECIAL_HISTORY_HOURS = config.getint('special_nodes', 'history_hours', fallback=24)
# Default persist path under project data/
_default_history_path = str((Path(__file__).parent.parent / 'data' / 'special_history.json').resolve())
SPECIAL_HISTORY_PERSIST_PATH = config.get('special_nodes', 'persist_path', fallback=_default_history_path)
# Consider nodes stale when time since last seen exceeds the orange threshold
STALE_AFTER_SECONDS = config.getint('special_nodes', 'stale_after_seconds', fallback=STATUS_ORANGE_THRESHOLD)
STALE_SPECIAL_SYMBOL = config.get('special_nodes', 'stale_symbol', fallback='☆')

# Alert Configuration
ALERT_ENABLED = config.getboolean('alerts', 'enabled', fallback=False)
ALERT_COOLDOWN = config.getint('alerts', 'alert_cooldown', fallback=3600)
ALERT_TRACKER_URL = config.get('alerts', 'tracker_url', fallback='http://localhost:5101')

# SMTP settings - try environment variables first for security
ALERT_SMTP_HOST = config.get('alerts', 'smtp_host', fallback='smtp.gmail.com')
ALERT_SMTP_PORT = config.getint('alerts', 'smtp_port', fallback=587)
ALERT_SMTP_SSL = config.getboolean('alerts', 'smtp_ssl', fallback=False)
ALERT_SMTP_USERNAME = os.getenv('ALERT_SMTP_USERNAME') or config.get('alerts', 'smtp_username', fallback='')
ALERT_SMTP_PASSWORD = os.getenv('ALERT_SMTP_PASSWORD') or config.get('alerts', 'smtp_password', fallback='')

# Email addresses
ALERT_EMAIL_FROM = config.get('alerts', 'email_from', fallback='buoy-tracker@example.com')
ALERT_EMAIL_TO = config.get('alerts', 'email_to', fallback='admin@example.com')
