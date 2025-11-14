# Buoy Tracker Project Instructions

This is a buoy tracking application that monitors and manages buoy data.

## Project Setup Checklist

- [x] Verify copilot-instructions.md file created
- [x] Clarify project requirements
- [x] Scaffold the project
- [x] Customize the project
- [x] Install required extensions
- [x] Compile the project (Python - no compilation needed)
- [x] Create and run task
- [x] Launch the project
- [x] Ensure documentation is complete

## Project Overview

**Buoy Tracker** is a real-time web interface for tracking Meshtastic mesh network nodes on a live map. It connects to a Meshtastic MQTT broker and displays mesh nodes with their positions, battery levels, and last-seen status on an interactive map.

### Key Features
- **Real-time Node Tracking**: Live MQTT feed of mesh node positions
- **Interactive Map**: Leaflet-based map with color-coded status markers
- **Node Details**: View battery levels, hardware info, and last-seen times
- **Time Indicators**: LPU (Last Position Update) and SoL (Sign of Life) on each node card
- **Status Color-Coding**: Blue (recent), Orange (stale), Red (very old)
- **Special Node Tracking**: Track specific nodes with history and movement detection
- **Data Persistence**: All special node data saved to unified JSON file
- **7-Day Retention Policy**: Automatic cleanup of old packets and position history
- **Debug Tools**: View recent raw MQTT messages for troubleshooting
- **Configurable**: Easy-to-edit configuration file for all settings

### Technology Stack
- Python 3.13+
- Flask 3.x for backend web server
- Meshtastic MQTT JSON library for mesh network integration
- Leaflet.js + OpenStreetMap for map visualization
- Vanilla JavaScript for frontend

### Project Structure
```
buoy_tracker/
├── src/                      # Source code
│   ├── main.py              # Flask app and routes
│   ├── mqtt_handler.py      # MQTT client and message handlers
│   ├── config.py            # Configuration loader
│   └── __init__.py
├── templates/
│   └── simple.html          # Web UI (Leaflet map)
├── static/
│   └── app.js               # Frontend JavaScript
├── tests/                   # Test files
│   └── test_main.py         # API endpoint tests
├── data/                    # Persistent data storage
│   ├── special_nodes.json   # Unified storage: history, node info, packets
│   └── special_channels.json # Channel information
├── examples/                # Example code
├── logs/                    # Application logs
├── tracker.config           # Main configuration file
├── requirements.txt         # Python dependencies
├── run.py                   # Application runner
├── README.md               # Project documentation
├── QUICKSTART.md           # Quick start guide
└── CHANGELOG.md            # Version history and changes
```

### Running the Application
```bash
# Install dependencies
pip install -r requirements.txt

# (Optional) Customize configuration
cp tracker.config.example tracker.config
nano tracker.config

# Run the application
python3 run.py
```

The web interface will be available at `http://localhost:5102`

The application runs with default settings (connects to mqtt.bayme.sh). Customize by editing `tracker.config` if needed.

### Development Status
✅ **COMPLETE** - All core features implemented and tested
- MQTT connection and message handling
- Node tracking with position, telemetry, and status
- Interactive web map with real-time updates
- Special node tracking with history
- LPU/SoL time indicators on node cards
- Unified data storage with 7-day retention policy
- API endpoints for all functionality
- Unit tests passing (6/6 tests)
- Comprehensive documentation
