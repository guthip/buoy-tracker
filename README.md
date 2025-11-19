# Buoy Tracker

A real-time web interface for tracking Meshtastic mesh network nodes on a live map.

## Features

- **Real-time Node Tracking**: Live MQTT feed of mesh node positions
- **Interactive Map**: Leaflet-based map with color-coded status markers
- **Node Details**: Battery levels, hardware info, last-seen times, and channel information
- **Status Color-Coding**: Blue (recent), Orange (stale), Red (very old)
- **Time Indicators**: Each node card shows:
  - **LPU** (Last Position Update): Time since last GPS position packet
  - **SoL** (Sign of Life): Time since any packet received
  - **Position History**: Deduplicated by packet timestamp to show only unique positions (retransmitted packets are automatically filtered)
- **Special Node Tracking**: Track specific nodes with home positions and movement alerts
  - Green dashed rings show movement threshold (50m default)
  - Red solid rings when nodes move beyond threshold
  - Light red card background alerts when nodes move outside expected range
  - Gray markers at home position until first GPS fix
  - Packet activity display with timestamps
  - **Persistent Data**: Node info (battery, telemetry, channel, position) survives restarts
  - **Packet History**: All packets per special node persisted to disk (7-day retention)
  - **Position Trails**: Visual polylines showing movement history on the map
  - **Position Deduplication**: Retransmitted packets automatically filtered to show only unique positions
  - **Dynamic Config Updates**: Origin coordinates recalculated on config reload/restart
- **Debug Tools**: View recent raw MQTT messages
- **Data Retention**: Automatic 7-day retention policy
  - Position history and packet data older than 7 days automatically cleaned up
  - Prevents unlimited storage growth while preserving recent activity
  - Cleanup runs on every save operation
- **Efficient Persistence**: Event-driven data saves
  - Saves to disk only when data changes (5-second minimum throttle to batch updates)
  - Dramatically reduces unnecessary disk I/O compared to fixed-interval saves
  - Responsive data persistence for mission-critical tracking
- **Configurable**: All settings in `tracker.config`

## Quick Start

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# (Optional) Customize configuration
cp tracker.config.template tracker.config
nano tracker.config

# Run the application (uses tracker.config or falls back to template)
python3 run.py
```

The web interface will be available at `http://localhost:5102`

The application runs out-of-the-box with default settings. To customize MQTT broker, special nodes, or other settings, copy `tracker.config.template` to `tracker.config` and edit as needed.

### Docker Deployment (Recommended)

**Using docker-compose (Easiest) - Follow these steps:**

1. Clone the repository:
```bash
git clone https://github.com/guthip/buoy-tracker.git
cd buoy-tracker
```

2. Create required directories:
```bash
mkdir -p data logs
```

3. Create minimal tracker.config (uses built-in defaults):
```bash
touch tracker.config
```

4. (Optional) Customize configuration - copy and edit the template:
```bash
cp tracker.config.template tracker.config
nano tracker.config
```

5. Start the service (must run from repo directory with docker-compose.yml):
```bash
docker compose up -d
```

6. View logs:
```bash
docker compose logs -f
```

Access the web interface at **http://localhost:5102**

**Building from Source**

```bash
# Clone the repository
git clone https://github.com/guthip/buoy-tracker.git
cd buoy-tracker

# Build the Docker image
docker build -t buoy-tracker:latest .

# Run with docker-compose
docker compose up -d
```

**What's Included:**
- ✅ Real-time Meshtastic mesh network node tracking
- ✅ 7-day retention data (position history and telemetry)
- ✅ Persistent volumes for config, data, and logs
- ✅ Multi-platform: Works on Intel/AMD (x86_64), Apple Silicon (ARM64), Raspberry Pi (ARM64)

**Volumes Created:**
- `./tracker.config` → Container's config (read-only)
- `./data/` → Node data, history, packets
- `./logs/` → Application logs
- `./docs/` → Documentation (optional)


## Using the Interface

- **Node Sidebar**: Click any node to zoom map to its location
- **Map Markers**: Click markers for detailed popups with node information
  - Includes link to view node on [Meshtastic Map](https://meshtastic.liamcottle.net)
- **Menu Controls**:
  - Toggle "Show all nodes" to display all nodes (default: show only special nodes)
  - Toggle position trails to visualize movement history on the map
  - (Sorting is automatic: special nodes are always shown at the top, sorted alphabetically; all other nodes are sorted by most recently seen)
- **Movement Alerts**:
  - Green dashed circles show 50m threshold around special node home positions
  - Red solid circles appear when nodes exceed threshold
  - Card backgrounds turn light red when nodes move outside expected range
  - Browser alert on first threshold breach
- **Color Coding**:
  - 🔵 Blue: Recent (< 1 hour, configurable via `status_blue_threshold`)
  - 🟠 Orange: Stale (1-12 hours, configurable via `status_orange_threshold`)
  - 🔴 Red: Very old (> 12 hours)
  - 🟡 Gold: Special node active
  - ⚫ Dark Gray: Special node stale
  - ⚪ Light Gray: Awaiting GPS (at home position)
  - 🔴 Light Red Card: Special node outside expected range

## Configuration

The application works out-of-the-box with default settings. To customize, copy the example config and edit:

```bash
cp tracker.config.template tracker.config
nano tracker.config
```

### Applying Configuration Changes

After editing `tracker.config`, you have two options:

**Option 1: Reload without restart (recommended)**
```bash
# Reload config without stopping the server
curl -X POST http://localhost:5102/api/config/reload
```
This instantly applies changes to special nodes, coordinates, thresholds, and other settings.

**Option 2: Full restart** 
```bash
# Only needed if reload fails or for major updates
docker restart buoy-tracker  # Docker deployment
# or
pkill -f "python3 run.py"   # Direct Python execution
python3 run.py              # Restart locally
```

---

Edit `tracker.config` to customize settings:

### MQTT Connection
```ini
[mqtt]
broker = mqtt.bayme.sh
port = 1883
root_topic = msh/US/bayarea/2/e/
mqtt_channels = MediumSlow,MediumFast,LongFast
username = meshdev
password = large4cats
```

### Web Interface
```ini
[webapp]
host = 127.0.0.1
port = 5102
# Map center point. Supports both decimal and degrees-minutes formats:
# Decimal: default_center = 37.7749,-122.4194
# Degrees-minutes: default_center = N37° 33.81', W122° 13.13'
default_center = 37.7749,-122.4194
default_zoom = 13

# Node status color thresholds (in hours)
# Less than status_blue_threshold = blue (recent)
# Between blue and orange = orange (stale)
# Older than status_orange_threshold = red (very stale)
status_blue_threshold = 1
status_orange_threshold = 12

# Data refresh intervals (in seconds)
node_refresh_interval = 2
status_refresh_interval = 5
```

### Special Nodes

Track specific nodes with extra detail:

```ini
[special_nodes]
show_offline = true
movement_threshold = 50
history_hours = 24
persist_path = data/special_history.json

# Format: node_id = label,home_lat,home_lon
# Coordinates support two formats:
# 1. Decimal degrees: 37.5637125,-122.2189855
# 2. Degrees-minutes: N37° 33.81', W122° 13.13'

# Examples with decimal format
3681533965 = SYCS,37.5637125,-122.2189855
492590216 = SYCE,37.5806826,-122.2175423

# Examples with degrees-minutes format
3681533965 = SYCS, N37° 33.81', W122° 13.13'
2512106321 = SYCA, N37° 31.94', W122° 10.31'
```

**Coordinate Formats**:
- **Decimal Degrees**: Standard latitude/longitude format (e.g., `37.5637125,-122.2189855`)
- **Degrees-Minutes**: Navigation format with hemisphere prefix (e.g., `N37° 33.81', W122° 13.13'`)
  - North/South for latitude (N = positive, S = negative)
  - East/West for longitude (E = positive, W = negative)
  - Format: `[NSEW]degrees° minutes'`
  - **Important**: Separate latitude and longitude with a comma

**Movement Alerts**: Green dashed ring shows threshold boundary. Red solid ring appears when node moves beyond threshold from home position.

**Email Alerts**: Configure email notifications when nodes move outside the fence (see Email Alerts section below).

**Data Persistence**: Special node data automatically persists to the `data/` directory:
- `special_nodes.json` - Unified storage for all special node data
  - Position history for movement tracking (last 10,000 points in memory)
  - Node info (battery, channel, telemetry, position, hardware)
  - Packet history with full details
- `special_channels.json` - Channel information
- Data survives server restarts and is automatically updated as packets arrive
- Packet data includes: timestamps, packet types, channel info, position/telemetry/nodeinfo details

**Data Retention**: Automatic 7-day retention policy keeps data manageable:
- Packets and position history older than 7 days are automatically removed
- Cleanup runs every save operation (60-second intervals)
- Maintains recent data for analysis while preventing unlimited growth
- File size stabilizes around 50KB depending on network activity

## Email Alerts

Send email notifications when special nodes move outside their home fence.

**⚠️ Platform-Specific Setup Required** - Email delivery method depends on your deployment environment.

### How It Works

- **Continuous Monitoring**: Alerts are sent whenever a special node is **outside its safe zone**
- **Smart Cooldown**: Only one email per node per cooldown period (default 1 hour, configurable)
- **No Redundant Alerts**: If a node stays outside the zone, you get one alert per cooldown period, not continuous emails
- **Includes**: Distance from home, battery level, timestamp, and tracker URL

### Platform-Specific Configuration

#### Production Deployment (Linux Servers) - RECOMMENDED

Linux servers have `sendmail` or `postfix` running by default. Use **localhost:25** (no credentials needed):

**In `tracker.config`:**
```ini
[alerts]
enabled = true
alert_cooldown = 1

tracker_url = http://your-server-address:5102
email_from = norepy@sequoiayc.org

# SMTP Configuration for localhost:25 (sendmail/postfix)
smtp_host = localhost
smtp_port = 25
smtp_ssl = false
# No credentials needed for sendmail/postfix
```

**In `secret.config`:**
```ini
[alerts]
# Email recipient address(es)
email_to = admin@sequoiayc.org
```

Verify sendmail is running:
```bash
sudo systemctl status sendmail
# or
sudo systemctl status postfix

# If not installed:
sudo apt install sendmail  # Debian/Ubuntu
# or
sudo yum install sendmail   # RHEL/CentOS
```

#### Development Setup (Mac/Windows) - External SMTP Required

macOS and Windows don't have sendmail/postfix running by default. Use an external SMTP provider:

**In `tracker.config`:**
```ini
[alerts]
enabled = true
alert_cooldown = 1

tracker_url = http://localhost:5102
email_from = norepy@sequoiayc.org

# Override SMTP settings for external provider
smtp_host = smtp.gmail.com
smtp_port = 587
smtp_ssl = false
```

**In `secret.config`:**
```ini
[alerts]
# Email recipient address(es)
email_to = your-email@example.com

# SMTP credentials (required for external providers)
smtp_username = your-email@gmail.com
smtp_password = your-app-password
```

See External SMTP Providers section below for setup instructions.

### External SMTP Providers

For development on Mac/Windows, use an external SMTP provider. All providers work the same way - configure in `tracker.config`:

**Gmail:**
```ini
[alerts]
smtp_host = smtp.gmail.com
smtp_port = 587
smtp_ssl = false
```

**SendGrid:**
```ini
[alerts]
smtp_host = smtp.sendgrid.net
smtp_port = 587
smtp_ssl = false
```

**AWS SES:**
```ini
[alerts]
smtp_host = email-smtp.us-west-2.amazonaws.com
smtp_port = 587
smtp_ssl = false
```

Then add credentials to `secret.config`:
```ini
[alerts]
smtp_username = your-email@gmail.com
smtp_password = your-app-password
email_to = recipient@example.com
```

### Security: Environment Variables

For production, use environment variables instead of storing credentials in config:

```bash
export ALERT_SMTP_USERNAME="your-email@gmail.com"
export ALERT_SMTP_PASSWORD="your-app-password"
```

Then leave `smtp_username` and `smtp_password` blank in `tracker.config`.

### Testing

Test your email configuration with these endpoints:

```bash
# Test configuration
curl -X POST http://localhost:5102/api/test-alert

# Test movement alert  
curl -X POST http://localhost:5102/api/test-alert-movement

# Test battery alert
curl -X POST http://localhost:5102/api/test-alert-battery
```

## API Reference

### Core Endpoints

- **`GET /api/nodes`** - All tracked nodes with position, battery, channel
- **`GET /api/status`** - MQTT connection status and node counts
- **`GET /api/recent_messages?limit=100`** - Recent MQTT messages for debugging
- **`GET /health`** - Health check

### Special Node Endpoints

- **`GET /api/special/history?node_id=<id>&hours=<hours>`** - Position history for a node
- **`GET /api/special/all_history?hours=<hours>`** - History for all special nodes
- **`GET /api/special/packets?limit=<n>`** - Recent packets from special nodes
- **`GET /api/special/packets/<node_id>?limit=<n>`** - Packets from specific node

### MQTT Control

- **`POST /api/mqtt/connect`** - Connect to MQTT broker
- **`POST /api/mqtt/disconnect`** - Disconnect from broker
- **`GET /api/mqtt/status`** - Connection details

## Project Structure

```
buoy_tracker/
├── src/
│   ├── main.py              # Flask app and routes
│   ├── mqtt_handler.py      # MQTT client and message handlers
│   ├── config.py            # Configuration loader
│   └── __init__.py
├── templates/
│   └── simple.html          # Web UI (Leaflet map)
├── static/
│   └── app.js               # Frontend JavaScript
├── data/                    # Persistent data storage
│   ├── special_nodes.json        # Unified: position history, node info, packets
│   └── special_channels.json     # Channel information
├── tests/                   # Test suite
├── tracker.config           # Configuration file
├── run.py                   # Application runner
└── requirements.txt         # Python dependencies
```

## Development

### Running Tests

```bash
pytest tests/
```

### Technology Stack

- Python 3.13+ with Flask 3.x
- Meshtastic MQTT JSON library
- Leaflet.js + OpenStreetMap
- paho-mqtt for MQTT client

## License

[Add license information here]

## Development

The application provides a RESTful API for programmatic access to node data:

### Status Endpoints

- **`GET /api/status`**  
  Returns MQTT connection status and node counts
  ```json
  {
    "mqtt_connected": true,
    "nodes_tracked": 42,
    "nodes_with_position": 38
  }
  ```

- **`GET /health`**  
  Simple health check endpoint
  ```json
  {"status": "ok"}
  ```

### Node Data Endpoints

- **`GET /api/nodes`**  
  Returns all tracked nodes with their current status, position, battery, and channel information
  ```json
  {
    "nodes": [
      {
        "id": 123456789,
        "name": "Node Name",
        "short": "NODE",
        "lat": 37.7749,
        "lon": -122.4194,
        "alt": 10,
        "hw_model": "TBEAM",
        "channel": 0,
        "channel_name": "MediumFast",
        "modem_preset": "MEDIUM_FAST",
        "role": "CLIENT",
        "battery": 85,
        "status": "blue",
        "is_special": false,
        "has_fix": true,
        "age_min": 5
      }
    ],
    "count": 1
  }
  ```

- **`GET /api/recent_messages?limit=100`**  
  Returns recent raw MQTT messages for debugging
  ```json
  {
    "recent": [...],
    "count": 100
  }
  ```

### Special Node Endpoints

Special nodes are configured in `tracker.config` for enhanced tracking:

- **`GET /api/special/history?node_id=<id>&hours=<hours>`**  
  Get position history for a specific special node
  - `node_id` (required): Node ID to query
  - `hours` (optional): Hours of history (default: 24)
  ```json
  {
    "node_id": 123456789,
    "hours": 24,
    "points": [
      {
        "timestamp": 1699999999.123,
        "latitude": 37.7749,
        "longitude": -122.4194,
        "altitude": 10
      }
    ],
    "count": 1
  }
  ```

- **`GET /api/special/all_history?hours=<hours>`**  
  Get position history for all special nodes
  ```json
  {
    "hours": 24,
    "histories": {
      "123456789": [...]
    }
  }
  ```

- **`GET /api/special/packets?limit=<n>`**  
  Get recent packets for all special nodes (default limit: 50)
  ```json
  {
    "packets": {
      "123456789": [
        {
          "timestamp": 1699999999.123,
          "packet_type": "position",
          "latitude": 37.7749,
          "longitude": -122.4194,
          "battery_level": 85,
          "voltage": 4.1,
          "channel_utilization": 5.2,
          "air_util_tx": 1.3
        }
      ]
    },
    "count": 1
  }
  ```

- **`GET /api/special/packets/<node_id>?limit=<n>`**  
  Get recent packets for a specific special node
  ```json
  {
    "node_id": 123456789,
    "packets": [...],
    "count": 1
  }
  ```

### MQTT Control Endpoints

- **`POST /api/mqtt/connect`**  
  Manually connect to MQTT broker

- **`POST /api/mqtt/disconnect`**  
  Disconnect from MQTT broker

- **`GET /api/mqtt/status`**  
  Get MQTT connection details

### Running Tests

```bash
pytest tests/
```

### Code Style

This project follows PEP 8 guidelines. Use `black` for code formatting and `flake8` for linting.

## Contributing

1. Create a feature branch
2. Make your changes
3. Write/update tests
4. Submit a pull request

## Support

For issues and questions, please open an issue on the repository.
