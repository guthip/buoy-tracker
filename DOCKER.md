# Buoy Tracker — Docker Deployment Guide

Complete instructions for deploying Buoy Tracker v0.96 with Docker.

## Platform Support

✅ **Multi-Platform Image** - Automatically works on:
- **Intel/AMD (x86_64)** - Standard desktop/server processors
- **Apple Silicon (ARM64)** - M1/M2/M3 Macs
- **Raspberry Pi (ARM64)** - Pi 4 and newer

Docker automatically selects the correct architecture for your platform.

## Quick Start

### Deploy from Docker Hub (Recommended)

No build required—use the pre-built image from Docker Hub:

**1. Create deployment directory:**
```bash
mkdir buoy-tracker && cd buoy-tracker
mkdir -p config data logs
```

**2. Create `docker-compose.yml` file and copy this content:**
```yaml
services:
  buoy-tracker:
    image: dokwerker8891/buoy-tracker:latest
    container_name: buoy-tracker
    restart: unless-stopped
    ports:
      - 5103:5103
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
    environment:
      MQTT_USERNAME: ${MQTT_USERNAME:-}
      MQTT_PASSWORD: ${MQTT_PASSWORD:-}
      MQTT_KEY: ${MQTT_KEY:-}
      ALERT_SMTP_USERNAME: ${ALERT_SMTP_USERNAME:-}
      ALERT_SMTP_PASSWORD: ${ALERT_SMTP_PASSWORD:-}
    healthcheck:
      test: [CMD, curl, -f, http://localhost:5103/health]
      interval: 30s
      timeout: 5s
      retries: 3
```

**3. Start the container:**
```bash
docker compose up -d
```
On first run, the container auto-initializes config files in `./config/`

**4. Customize configuration:**
```bash
nano config/tracker.config  # MQTT broker, special nodes, etc.
nano config/secret.config   # Credentials (if needed)
```

**5. (Optional) Use environment variables instead of config files:**

For security, sensitive credentials can be passed via environment variables instead of config files. Create a `.env` file (example below is configured for San Francisco Bay Area):

```bash
# Create .env with your credentials (optional)
cat > .env << 'EOF'
# MQTT Credentials (San Francisco Bay Area Meshtastic Network)
MQTT_USERNAME=meshdev
MQTT_PASSWORD=large4cats
MQTT_KEY=AQ==

# Email Alert Credentials (if using SMTP alerts)
ALERT_SMTP_USERNAME=your_smtp_username
ALERT_SMTP_PASSWORD=your_smtp_password
EOF
```

Then edit with your actual values:
```bash
nano .env
```

This file will be automatically loaded by docker-compose. Supported variables:
- `MQTT_USERNAME` - MQTT broker username
- `MQTT_PASSWORD` - MQTT broker password
- `MQTT_KEY` - MQTT encryption key
- `ALERT_SMTP_USERNAME` - SMTP username for email alerts
- `ALERT_SMTP_PASSWORD` - SMTP password for email alerts

**Note:** Environment variables override values in `config/tracker.config` and `config/secret.config`. If you don't create a `.env` file, the container will use values from the config files instead (recommended for most deployments).

**6. Restart the container to apply configuration changes:**
```bash
docker compose restart
```

Access the web interface at **http://localhost:5103**

---

## Management Commands

Use these commands to manage the running container:

```bash
# View logs
docker compose logs -f

# Check status
docker compose ps

# Restart (apply config changes)
docker compose restart

# Stop
docker compose down

# Access shell inside container
docker compose exec buoy-tracker /bin/bash
```

## Configuration

Configuration files are stored in `./config/` on the host and are editable without rebuilding:

```bash
# Edit MQTT configuration
nano config/tracker.config

# Edit secrets (optional - only if using email alerts)
nano config/secret.config

# Restart to apply changes
docker compose restart
```

**On first run**, the container automatically initializes:
- `./config/tracker.config` (copied from template in image)
- `./config/secret.config` (copied from template in image)

**Volume Structure:**
- `./config/tracker.config` → Auto-created on first run (edit here for MQTT broker, special nodes, etc.)
- `./config/secret.config` → Auto-created on first run (edit here for credentials)
- `./data/` → Application data persistence (special_nodes.json, etc.)
- `./logs/` → Application logs

## Ports

- `5103` - Web interface and API

## Health Check

The container includes a health check:

```bash
# Check container health
docker compose ps
```

## Upgrading

```bash
# Pull latest image and restart
docker compose pull
docker compose up -d
```

Data in `./data/` is automatically preserved.

## Fresh Deployment

Simply start the container with your configuration files, and the application will:
1. Connect to your MQTT broker
2. Begin receiving packets from mesh nodes
3. Automatically create required data files (logs, etc.)
4. Build position history and gateway connections from live MQTT traffic

## Data Persistence

The following persists across container restarts:
- `./config/tracker.config` - MQTT and application settings
- `./config/secret.config` - Credentials (if configured)
- `./logs/` - Application logs
- `./data/` - Persistent application data (special nodes, node metadata, etc.)

On restart, the tracker rebuilds live data (node positions, connections) from incoming MQTT packets.

**Controlling persistence:**

You can enable or disable persistence in `tracker.config`:

```ini
[app_features]
enable_persistence = true   # Enable disk persistence (recommended for development)
enable_persistence = false  # Disable (recommended for production/stateless operation)
```

When disabled (default for production), all special node history is cleared on restart. When enabled, it persists across restarts.

## Troubleshooting

### Container won't start
```bash
# Check logs for errors
docker logs buoy-tracker

# Check if port is already in use
lsof -i :5103
```

### MQTT connection issues
```bash
# Verify network access from container
docker exec buoy-tracker ping mqtt.bayme.sh

# Check config
docker exec buoy-tracker cat /app/tracker.config
```

### Data not persisting
```bash
# Verify volume mount
docker inspect buoy-tracker | grep -A 10 Mounts
```

## Production Recommendations

1. **Use environment variables for secrets** (MQTT password, SMTP credentials) - keeps sensitive data out of config files and enables secrets to be managed by your container orchestration platform (Docker secrets, Kubernetes secrets, etc.)
2. **Set up reverse proxy** (nginx) with SSL for secure HTTPS access
3. **Monitor health endpoint** (`/api/status`) for alerts
4. **Use Docker restart policies**: `--restart unless-stopped`

## Email Distribution Template

```
Subject: Buoy Tracker v0.96 - Docker Container

Buoy Tracker v0.96 Docker image for real-time Meshtastic node tracking.

Quick Start:
1. mkdir buoy-tracker && cd buoy-tracker
2. Create docker-compose.yml (see DOCKER.md Quick Start section)
3. touch tracker.config && mkdir -p data logs
4. docker compose up -d
5. Open: http://localhost:5103

The container runs with sensible defaults. To customize:
- Get tracker.config.template and copy to tracker.config, then edit
- Restart: docker compose restart

See DOCKER.md for complete instructions.
```

## Security & Authorization

**Access Model:**
- All users can **view the map and data** without authentication
- **Control Menu (settings and configuration changes) requires password** via API key
- Rate limiting is always active on all endpoints
- `/health` endpoint always public (used by Docker healthcheck)

**Password Protection:**
1. Set API key in `secret.config` under `[webapp] api_key = your_secure_password`
2. Control Menu actions automatically send Authorization header with password
3. In development mode, localhost is automatically exempted from auth requirement

**Behavior:**
- If API key is configured: Control Menu actions require correct password (401 if missing/invalid)
- If no API key configured: No authentication required (development mode)
- Unauthorized requests receive 401 response
