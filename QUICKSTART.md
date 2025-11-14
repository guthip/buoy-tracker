# Buoy Tracker - Quick Start Guide

Get up and running in 3 minutes.

## Installation

```bash
# Clone or download the repository
cd buoy_tracker

# Install dependencies
pip install -r requirements.txt

# (Optional) Customize settings - app works with defaults
cp tracker.config.example tracker.config
nano tracker.config

# Run the application
python3 run.py
```

The application runs immediately with built-in defaults (connects to mqtt.bayme.sh). Customize by editing `tracker.config` if needed.

## Access the Web Interface

Open your browser to: **http://localhost:5102**

The server will automatically connect to the MQTT broker and start tracking nodes.

## First Steps

1. **Wait a few seconds** - Nodes will appear as MQTT messages arrive
2. **Click a node card** in the sidebar to zoom to its location on the map
3. **Click a map marker** for detailed information and link to public map
4. **Open the ☰ menu** (top-right) to:
   - Filter by special nodes only (enabled by default)
   - Toggle position trails
   - Filter by channel
   - View debug messages

## What You're Seeing

**Node Colors:**
- 🔵 Blue: Recently seen (< 5min)
- 🟠 Orange: Stale (5-30min)  
- 🔴 Red: Very old (> 30min)
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
- The app uses default MQTT settings (mqtt.bayme.sh:1883). To connect to a different broker, copy `tracker.config.example` to `tracker.config` and edit the `[mqtt]` section
- Check MQTT connection: `curl http://localhost:5102/api/status`
- Verify network connectivity to your MQTT broker
- Check logs in `logs/` directory

**Port 5102 already in use?**
- Edit `tracker.config` and change the `port` setting
- Or: `lsof -ti:5102 | xargs kill` to free the port

## Next Steps

- **Customize Config**: Copy `tracker.config.example` to `tracker.config` and edit MQTT broker, special nodes, etc.
- **Add Special Nodes**: Edit `[special_nodes]` section to track specific nodes with movement detection
- **Email Alerts**: Configure SMTP in `[alerts]` section to receive notifications when nodes move ([README.md](README.md#email-alerts))
- **API Reference**: See [README.md](README.md) for complete API documentation

---

For complete documentation, configuration options, and API reference, see [README.md](README.md).
