# Changelog

All notable changes to the Buoy Tracker project are documented here.

## [2025-11-13] - Docker Deployment with Retention Data

### Changed
- **Docker Deployment Strategy**: Modified to include retention data in container
  - Removed `data/` from `.dockerignore` to include 7-day retention data in image
  - Updated DOCKER.md to reflect optional volume mounts (data volume no longer required)
  - Updated docker-compose.yml with commented-out data volume mount
  - Container now ships with pre-populated retention data for immediate deployment
  
- **Volume Mount Strategy**:
  - Data volume now optional (container includes built-in retention data)
  - Logs volume remains optional for host access
  - Config volume optional (falls back to tracker.config.example)

### Documentation
- Updated DOCKER.md with 4 deployment options explaining data persistence
- Added warnings about mounting empty host directories over built-in data
- Clarified when to use volume mounts vs. built-in container data

## [2025-11-13] - Configuration Cleanup & Trail History Enhancement

### Changed
- **Configuration Simplification**: Consolidated duplicate title settings
  - Removed `[webapp] page_title` (was unused in code)
  - Now using single `[app] title` setting
  - Standardized config keys to lowercase: `title` and `version`
  - Updated code to use lowercase config keys

- **Trail History Improvements**:
  - Extended menu range from 72 hours to 168 hours (7 days)
  - Added 100 datapoint limit per node for API responses
  - Implemented comprehensive input validation:
    - Alert dialogs on invalid values with auto-correction
    - Red border visual feedback during input
    - Tooltips explaining limits
    - HTML5 min/max validation

- **.gitignore Updates**: Removed references to old data files
  - Removed: `data/special_history.json`, `data/special_node_data.json`
  - Added: `data/special_nodes.json`, `data/special_channels.json`

### Removed
- Temporary cleanup documentation files
- macOS `.DS_Store` files
- Unused `PAGE_TITLE` configuration variable

### Fixed
- Port references updated from 5101 to 5102 throughout documentation
- Data structure references in README.md and copilot-instructions.md
- Removed references to non-existent deployment documentation

## [2025-11-13] - Data Retention & Persistence

### Added
- **7-Day Retention Policy**: Automatic cleanup of packets and position history older than 7 days
  - Runs on every save operation (60-second throttled or forced on shutdown)
  - Applies to both `packets` and `position_history` arrays
  - Updates in-memory structures during save to maintain consistency
  - Logging shows count of removed entries when cleanup occurs
  - Prevents unlimited data growth while preserving recent history

### Changed
- **Unified Data Storage**: Consolidated three separate JSON files into single `special_nodes.json`
  - Previously: `special_history.json`, `special_node_data.json`, `special_packets.json`
  - Now: Single file with node_id as key, containing all data per node
  - Improved data consistency and reduced file I/O operations
  - Simplified backup and restore procedures
  
- **Data Structure Improvements**:
  - Position history stored in-memory as `deque` with 10,000 point limit
  - Packets stored in-memory as `list` (no limit, retention policy handles cleanup)
  - Added retention cutoff calculation: `current_time - (7 * 24 * 3600)`
  - Enhanced save function with before/after counting for logging

### Technical Details
- Modified `_save_special_nodes_data()` in `mqtt_handler.py` (lines 273-334)
- Retention policy filters data during save operation, not on packet arrival
- In-memory structures updated after filtering to match saved state
- File format: `{node_id: {last_seen, position_history, packets, ...}}`
- Data directory: `/data/special_nodes.json`

### Performance
- File size stabilized at ~50KB (varies with network activity)
- Efficient filtering: list comprehension with timestamp comparison
- No impact on real-time packet processing
- Automatic cleanup prevents gradual performance degradation

## [2025-11-12] - Special Node Packet History

### Added
- **Packet Persistence**: Last 50 packets per special node saved to disk
  - Survives application restarts
  - Stored in `/data/special_packets.json`
  - Includes full packet data (type, timestamp, telemetry, position, etc.)

### Changed
- Special node packets now limited to last 50 per node (FIFO)
- Packet data structure includes all original MQTT message details
- Position updates trigger special node packet save

## [2025-11-11] - Enhanced Special Node Tracking

### Added
- **Voltage History API**: New endpoint `/api/special/voltage_history/<node_id>?days=7`
  - Returns time-series voltage data from telemetry packets
  - Configurable time range (default 7 days)
  - Format: `[{"timestamp": ..., "voltage": ...}, ...]`
  - Used for graphing battery trends over time

- **Movement Detection**: Visual indicators when special nodes move
  - Green dashed circle: Movement threshold (50m default)
  - Red solid circle: Node has exceeded threshold
  - Light red card background: Active alert state
  - Browser alert on first threshold breach

- **Persistent Node Data**: Special node info survives restarts
  - Battery levels and telemetry
  - Channel information
  - Last position
  - Stored in `/data/special_node_data.json`

### Changed
- Special node cards show battery percentage and voltage
- Added Sign of Life (SoL) indicator for any packet activity
- Node colors reflect recency of position updates
- Config file format: `node_id = label,home_lat,home_lon`

## [2025-11-10] - Initial Release

### Added
- Real-time MQTT connection to Meshtastic network
- Interactive Leaflet map with node markers
- Color-coded status indicators (blue/orange/red)
- Node sidebar with filtering capabilities
- Channel-based display filtering
- Debug menu with raw MQTT messages
- LPU (Last Position Update) time display
- Configuration file support (`tracker.config`)
- API endpoints:
  - `/api/nodes` - All tracked nodes
  - `/api/status` - Service status and stats
  - `/api/messages` - Recent debug messages
  - `/api/special/history` - Special node position history
  - `/api/special/packets` - Recent special node packets

### Features
- Flask 3.x web server
- Meshtastic MQTT JSON integration
- OpenStreetMap/Leaflet.js mapping
- Vanilla JavaScript frontend
- Special node tracking with home positions
- Configurable MQTT broker settings
- Configurable map defaults
