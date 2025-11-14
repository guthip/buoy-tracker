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
- **Special Node Tracking**: Track specific nodes with home positions and movement alerts
  - Green dashed rings show movement threshold (50m default)
  - Red solid rings when nodes move beyond threshold
  - Light red card background alerts when nodes move outside expected range
  - Gray markers at home position until first GPS fix
  - Packet activity display with timestamps
  - **Persistent Data**: Node info (battery, telemetry, channel, position) survives restarts
  - **Packet History**: Last 50 packets per special node persisted to disk
  - **Dynamic Config Updates**: Origin coordinates recalculated on config reload/restart
- **Debug Tools**: View recent raw MQTT messages
- **Configurable**: All settings in `tracker.config`

## Quick Start

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# (Optional) Customize configuration
cp tracker.config.example tracker.config
nano tracker.config

# Run the application (uses tracker.config or falls back to example)
python3 run.py
```

The web interface will be available at `http://localhost:5102`

The application runs out-of-the-box with default settings. To customize MQTT broker, special nodes, or other settings, copy `tracker.config.example` to `tracker.config` and edit as needed.

### Docker Deployment

**Option 1: Pull from Docker Hub (Easiest)**
```bash
# Pull and run the latest version (works on Intel, Apple Silicon, and Raspberry Pi)
docker run -d --name buoy-tracker -p 5102:5102 dokwerker8891/buoy-tracker:0.2

# Access the application
open http://localhost:5102
```

> **Multi-Platform Support**: Image automatically works on Intel/AMD (x86_64), Apple Silicon (ARM64), and Raspberry Pi (ARM64) - Docker selects the correct architecture for your platform.

**Option 2: Load from tarball**
```bash
# Load the distributed container
docker load < buoy-tracker-0.2.tar.gz

# Run the container (includes 7-day retention data)
docker run -d --name buoy-tracker -p 5102:5102 buoy-tracker:0.2

# Access the application
open http://localhost:5102
```

**Option 3: Using docker-compose**
```bash
# Load the image first (if using distributed container)
docker load < buoy-tracker-0.2.tar.gz

# Start with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

**Optional**: Add volume mounts for persistence or custom config:
```bash
docker run -d --name buoy-tracker \
  -p 5102:5102 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  buoy-tracker:0.2
```

For complete Docker instructions, see [DOCKER.md](DOCKER.md).

## Using the Interface

- **Node Sidebar**: Click any node to zoom map to its location
- **Map Markers**: Click markers for detailed popups with node information
  - Includes link to view node on [Meshtastic Map](https://meshtastic.liamcottle.net) (liamcottle's public map viewer)
- **Display Filters**: 
  - Toggle "Show only special nodes" to filter the map and sidebar
  - Toggle channels in the menu to show/hide nodes by channel
- **Debug Menu**: Click ☰ menu for recent MQTT messages
- **Movement Alerts**: 
  - Green dashed circles show 50m threshold around special node home positions
  - Red solid circles appear when nodes exceed threshold
  - Card backgrounds turn light red when nodes move outside expected range
  - Browser alert on first threshold breach
- **Color Coding**:
  - 🔵 Blue: Recent (< 5min)
  - 🟠 Orange: Stale (5-30min)
  - 🔴 Red: Very old (> 30min)
  - 🟡 Gold: Special node active
  - ⚫ Dark Gray: Special node stale
  - ⚪ Light Gray: Awaiting GPS (at home position)
  - 🔴 Light Red Card: Special node outside expected range

## Configuration

The application works out-of-the-box with default settings. To customize, copy the example config and edit:

```bash
cp tracker.config.example tracker.config
nano tracker.config
```

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
default_lat = 37.7749
default_lon = -122.4194
default_zoom = 10
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

Send email notifications when special nodes move outside their home fence:

### Configuration

Add to `tracker.config`:

```ini
[alerts]
enabled = true
alert_cooldown = 3600

# SMTP Configuration (example for Gmail)
smtp_host = smtp.gmail.com
smtp_port = 587
smtp_ssl = starttls
smtp_username = your-email@gmail.com
smtp_password = your-app-password

# Email Settings
email_from = your-email@gmail.com
email_to = recipient1@example.com, recipient2@example.com

# Optional: URL for links in emails
tracker_url = http://10.10.3.221:5102
```

### Gmail Setup

1. Enable 2-factor authentication in your Google account
2. Generate an app password: https://myaccount.google.com/apppasswords
3. Use the 16-character app password in `smtp_password`

### Alternative SMTP Providers

**SendGrid:**
```ini
smtp_host = smtp.sendgrid.net
smtp_port = 587
smtp_ssl = starttls
smtp_username = apikey
smtp_password = your-sendgrid-api-key
```

**AWS SES:**
```ini
smtp_host = email-smtp.us-west-2.amazonaws.com
smtp_port = 587
smtp_ssl = starttls
smtp_username = your-ses-smtp-username
smtp_password = your-ses-smtp-password
```

### Security: Environment Variables

For production, use environment variables instead of storing credentials in config:

```bash
export ALERT_SMTP_USERNAME="your-email@gmail.com"
export ALERT_SMTP_PASSWORD="your-app-password"
```

Then omit `smtp_username` and `smtp_password` from `tracker.config`.

### Testing

Test your email configuration:

```bash
curl -X POST http://localhost:5102/api/test-alert
```

### Email Features

- **Movement Detection**: Alerts trigger when nodes exceed `movement_threshold` distance from home
- **Cooldown**: Prevents spam - only one alert per node per cooldown period (default 3600s = 1 hour)
- **Google Maps Links**: Emails include links to view node locations
- **Node Details**: Battery level, distance from home, timestamp included in alert
- `special_history.json` - Position history for movement tracking
- Data survives server restarts and is automatically updated as packets arrive

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

## API Reference

```
buoy_tracker/
├── src/
│   ├── main.py              # Flask app and routes
│   ├── mqtt_handler.py      # MQTT client and message handlers
│   ├── config.py            # Configuration loader
│   └── __init__.py
├── templates/
│   └── simple.html          # Web UI (Leaflet map)
├── examples/
│   └── my_working_mesh_mqtt.py  # Original example
├── tests/                   # Test suite
├── tracker.config           # Configuration file
├── run.py                   # Application runner
└── requirements.txt         # Python dependencies
```

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

## Development

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

## License

[Add license information here]

## Support

For issues and questions, please open an issue on the repository.
