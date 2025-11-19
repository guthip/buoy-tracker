# Buoy Tracker - Quick Start Guide

Get up and running in 2 minutes.

## Docker (Recommended)

Works on any system with Docker:

```bash
# 1. Clone the repository
git clone https://github.com/guthip/buoy-tracker.git
cd buoy-tracker

# 2. Create minimal tracker.config (uses built-in defaults)
touch tracker.config

# 3. Create data and logs directories
mkdir -p data logs

# 4. Start the application (runs from repo with docker-compose.yml and Dockerfile)
docker compose up -d

# 5. Access at http://localhost:5102
```

**That's it!** The app is pre-configured with defaults and runs immediately.

**Optional - Customize Configuration:**
If you want to customize MQTT broker, special nodes, or other settings, get the full config template:
```bash
curl -o tracker.config https://raw.githubusercontent.com/guthip/buoy-tracker/main/tracker.config.template
nano tracker.config  # Edit as needed
docker compose restart  # Restart for changes to take effect
```

## Local Installation

Requires Python 3.13+ and pip:

```bash

## Local Installation

Requires Python 3.13+ and pip:

```bash
# Install dependencies
pip install -r requirements.txt

# (Optional) Customize settings - app works with defaults
cp tracker.config.template tracker.config
nano tracker.config

# Run the application
python3 run.py
```

Access at `http://localhost:5102`

## Access the Web Interface

Open your browser to: **http://localhost:5102**

The server will automatically connect to the MQTT broker and start tracking nodes.

## First Steps

1. **Wait a few seconds** - Nodes will appear as MQTT messages arrive
2. **Click a node card** in the sidebar to zoom to its location on the map
3. **Click a map marker** for detailed information and link to public map
4. **Open the ☰ menu** (top-right) to:
   - Toggle "Show only special nodes" (enabled by default)
   - Toggle position trails
   - (Sorting is automatic: special nodes are always shown at the top, sorted alphabetically; all other nodes are sorted by most recently seen)

## What You're Seeing

**Node Colors:**
- 🔵 Blue: Recently seen (< 1 hour)
- 🟠 Orange: Stale (1-12 hours)  
- 🔴 Red: Very old (> 12 hours)
- 🟡 Gold: Special node (active)
- ⚫ Dark Gray: Special node (stale)

**Time Indicators on Each Card:**
- **LPU**: Last Position Update (time since last GPS packet)
- **SoL**: Sign of Life (time since any packet received)

**For Special Nodes:**
- 🟢 Green dashed ring = Movement threshold boundary (50m)
- 🔴 Red solid ring = Node moved beyond threshold
- Red card background = Outside expected range
- Packet history automatically saved (last 50 packets per node)

## Configuration

Edit `tracker.config` to:
- Change MQTT broker/credentials
- Add special nodes to track with movement alerts
- Configure email alerts
- Adjust display settings

See [README.md](README.md) for complete configuration options and API documentation.

## Troubleshooting

**No nodes appearing?**
- The app uses default MQTT settings (mqtt.bayme.sh:1883). To connect to a different broker, copy `tracker.config.template` to `tracker.config` and edit the `[mqtt]` section
- Check MQTT connection: `curl http://localhost:5102/api/status`
- Verify network connectivity to your MQTT broker
- Check logs in `logs/` directory

**Port 5102 already in use?**
- Edit `tracker.config` and change the `port` setting
- Or: `lsof -ti:5102 | xargs kill` to free the port

## Next Steps

- **Customize Config**: Copy `tracker.config.template` to `tracker.config` and edit MQTT broker, special nodes, etc.
- **Add Special Nodes**: Edit `[special_nodes]` section to track specific nodes with movement detection
- **Email Alerts**: Configure SMTP in `[alerts]` section to receive notifications when nodes move ([README.md](README.md#email-alerts))
- **API Reference**: See [README.md](README.md) for complete API documentation

---

For complete documentation, configuration options, and API reference, see [README.md](README.md).
