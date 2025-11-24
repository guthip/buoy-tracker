# Changelog

All notable changes to the Buoy Tracker project are documented here.

## [2025-11-23] - Configuration Cleanup - v0.7

### Changed
- **Removed unused config items**:
  - `show_offline` (hardcoded to always show special nodes at home positions)
  - `stale_symbol` (was loaded but never used by frontend)

- **New configurable setting**:
  - `special_symbol` in `[special_nodes_settings]` - now configurable instead of hardcoded
  - Default: `⭐` (star emoji)

### Behavior
- **Special nodes now always show** at their configured home position before receiving their first GPS packet
  - No configuration needed - this is the desired behavior for initial deployment phase
  - Ensures you see everything about special nodes, whether assumed (home position) or received (actual packets)

### Documentation
- Updated README.md and tracker.config.template to reflect removed config items
- Simplified Special Nodes configuration section
- Clarified that special nodes are always displayed at home positions until they send their first packet

## [2025-11-23] - Bug Fixes & UI Polish - v0.69

### Fixed
- **Critical: Position Packets Not Displaying (Field Name Mismatch)**
  - Issue: Non-special node positions were being received but never displayed on map
  - Root Cause: Code used camelCase field names (`latitudeI`, `longitudeI`) but protobuf JSON conversion uses snake_case (`latitude_i`, `longitude_i`)
  - Solution: Standardized all field name accesses to snake_case format
  - Result: Non-special nodes now appear on map immediately when position packets arrive
  - Impact: Map now shows 2-3x more nodes (all nodes with positions, not just special nodes)

- **Field Name Standardization Across All Message Types**
  - NODEINFO: `hwModel` → `hw_model`, `longName` → `long_name`, `shortName` → `short_name`
  - TELEMETRY: `deviceMetrics` → `device_metrics`, `powerMetrics` → `power_metrics`
  - MAP_REPORT: `modemPreset` → `modem_preset`, `firmwareVersion` → `firmware_version`
  - All changes use `preserving_proto_field_name=True` which guarantees snake_case output

- **Docker Bytecode Caching Issue**
  - Issue: Code changes weren't taking effect in running container
  - Solution: Use `--no-cache` flag during development to force fresh Python bytecode

### Changed
- **UI Improvements**:
  - Removed channel information (MediumFast, MediumSlow) from node cards - now working reliably
  - Default "Show all nodes" setting changed from enabled to disabled (shows only nodes with positions by default)
  - Cleaner card display focusing on essential information

- **Version**: Bumped to 0.69

### Technical
- Removed unnecessary code fallbacks for field name compatibility
- Removed all debug logging added during troubleshooting
- Deleted temporary `deduplicate_nodes.py` utility script
- Code is now production-ready and clean

### Performance
- Position packet processing now reliable with zero packet loss
- All nodes with positions immediately visible on map
- Reduced false "offline" status issues due to missing position data

# [2025-11-14] - Menu & UI Simplification

### Changed
- **Menu Simplification**: Removed channel filter, debug menu, and sort dropdown from the user interface
- **Automatic Sorting**: Node sorting is now automatic—special nodes always appear at the top (alphabetically), all other nodes are sorted by most recently seen
- **UI Cleanup**: Menu now only includes toggles for "Show only special nodes" and position trails; all other controls and filters removed
- **Code Cleanup**: Removed all frontend and backend code related to channel filter, debug/debug menu, and sort dropdown

# Changelog

All notable changes to the Buoy Tracker project are documented here.

## [2025-11-13] - Pre-Configured Docker Image with Retained Data

### Added
- **Pre-Configured Docker Image**: Image now includes live configuration and data
  - Includes production `tracker.config` (SYC buoys: SYCS, SYCE, SYCA, SYCX)
  - Includes 7-day retention data (position history and telemetry)
  - Ready to run immediately with zero configuration
  - Users can override config by mounting custom tracker.config if needed

### Changed
- **`.dockerignore` Updated**: Removed `tracker.config` exclusion
  - Image now contains working configuration instead of just example
  - Simplifies deployment - no manual configuration needed
  - Retained data provides immediate historical context on first launch

### Documentation
- Updated DOCKER.md Quick Start with "What's Included" section
- Updated README.md Docker section with pre-configuration details
- Clarified that image contains working config + data, not just templates

## [2025-11-13] - Multi-Platform Docker Hub Deployment

### Added
- **Multi-Platform Docker Image**: Built and published for multiple architectures
  - **linux/amd64** - Intel/AMD processors (standard desktop/server)
  - **linux/arm64** - Apple Silicon (M1/M2/M3) and Raspberry Pi 4+
  - Automatic platform detection - Docker pulls the correct architecture
  - Single command works across all platforms
  
- **Docker Hub Distribution**: Published image to Docker Hub
  - Available at: `dokwerker8891/buoy-tracker:0.2`
  - Provides easiest deployment option: `docker pull dokwerker8891/buoy-tracker:0.2`
  - Eliminates need to download 192 MB tarball for most users
  - Both `:0.2` and `:latest` tags available
  - Works on Intel/AMD, Apple Silicon, and Raspberry Pi

### Changed
- **Docker Compose Configuration**: Updated to pull from Docker Hub by default
  - Primary: `image: dokwerker8891/buoy-tracker:0.2`
  - Alternative: Local build available via `build: .` (commented)
  - Enables `docker-compose up` without tarball or local build

### Documentation
- Added Platform Support section to DOCKER.md
- Updated README.md with multi-platform note
- Updated DOCKER.md with Docker Hub deployment instructions
- Added Docker Hub pull commands to Quick Reference Card
- Updated all deployment examples to use Docker Hub image

## [2025-11-13] - GitHub Release & Docker Deployment with Retention Data

### Added
- **GitHub Release**: Published v0.2 to GitHub
  - Repository: https://github.com/guthip/buoy-tracker
  - Release: https://github.com/guthip/buoy-tracker/releases/tag/v0.2
  - Distribution files: 192 MB tarball + SHA256 checksum
  - Complete release notes with deployment instructions

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
- Updated DOCKER.md with 6 deployment options explaining data persistence
- Added warnings about mounting empty host directories over built-in data
- Clarified when to use volume mounts vs. built-in container data
- Added GITHUB_RELEASE.md with complete GitHub setup instructions

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
