# Buoy Tracker — Docker Deployment Guide

Complete instructions for deploying Buoy Tracker v0.92 with Docker.

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
      - 5102:5102
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
      test: [CMD, curl, -f, http://localhost:5102/api/status]
      interval: 30s
      timeout: 5s
      retries: 3
```

**3. (Optional) Create `.env` file for environment variables:**

For security, sensitive credentials can be passed via environment variables instead of config files:

```bash
# Copy the template
cp .env.template .env

# Edit with your values (optional - MQTT and SMTP credentials)
nano .env
```

This file will be automatically loaded by docker-compose. Supported variables:
- `MQTT_USERNAME` - MQTT broker username
- `MQTT_PASSWORD` - MQTT broker password
- `MQTT_KEY` - MQTT encryption key
- `ALERT_SMTP_USERNAME` - SMTP username for email alerts
- `ALERT_SMTP_PASSWORD` - SMTP password for email alerts

**Note:** If you don't create a `.env` file, the container will use values from `config/tracker.config` and `config/secret.config` instead (recommended for most deployments).

**4. Start the container:
```bash
docker compose up -d
```
On first run, the container auto-initializes config files in `./config/`

**5. Customize configuration:**
```bash
nano config/tracker.config  # MQTT broker, special nodes, etc.
nano config/secret.config   # Credentials (if needed)
```

**6. Restart the container to apply configuration changes:**
```bash
docker compose restart
```

Access the web interface at **http://localhost:5102**

---

## Running Options

### Docker Compose (Recommended)

All configuration lives in `./config/` on the host and is easily editable:

```bash
# View logs
docker compose logs -f

# Check status
docker compose ps

# Restart (apply config changes)
docker compose restart

# Stop
docker compose down
```

**Volume Structure:**
- `./config/tracker.config` → Auto-created from template on first run (edit here)
- `./config/secret.config` → Auto-created from template on first run (edit here)
- `./config/tracker.config.template` → Included in image (reference)
- `./config/secret.config.template` → Included in image (reference)
- `./data/` → Application data persistence (special_nodes.json, etc.)
- `./logs/` → Application logs

## Configuration

Configuration files are stored in `./config/` on the host and are editable without rebuilding or restarting the container:

```bash
# Edit MQTT configuration
nano config/tracker.config

# Edit secrets (optional - only if using email alerts)
nano config/secret.config

# Reload without restart
curl -X POST http://localhost:5102/api/config/reload
```

**On first run**, the container automatically initializes:
- `./config/tracker.config` (copied from template in image)
- `./config/secret.config` (copied from template in image)
- `./config/tracker.config.template` (reference template from image)
- `./config/secret.config.template` (reference template from image)

## Ports

- `5102` - Web interface and API

## Health Check

The container includes a health check on `/health` endpoint:

```bash
# Check if container is healthy
docker inspect --format='{{.State.Health.Status}}' buoy-tracker
```

## Management Commands

```bash
# View logs
docker logs -f buoy-tracker

# Stop container
docker stop buoy-tracker

# Start container
docker start buoy-tracker

# Remove container
docker rm -f buoy-tracker

# Access shell inside container
docker exec -it buoy-tracker /bin/bash
```

## Upgrading

**Using docker-compose:**
```bash
# Pull latest image and restart
docker compose pull
docker compose up -d
```
Data in `./data/` is automatically preserved.

**Using docker run:**
```bash
# Stop and remove old container
docker stop buoy-tracker
docker rm buoy-tracker

# Rebuild from latest source
cd buoy-tracker
git pull origin main
docker build -t buoy-tracker:latest .

# Start with same volumes
docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  --restart unless-stopped \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  -v $(pwd)/logs:/app/logs \
  buoy-tracker:latest
```

Data in `./data/` is automatically preserved across upgrades.

## Historical Data

**Important**: Real-time tracking data (current node positions, active connections) is stored in memory. Configuration and node metadata are persisted in `./data/` directory.

### Data Persistence

The following data persists across restarts:
- `logs/` - Application logs directory
- Configuration files (`tracker.config`, `secret.config`)

The application automatically rebuilds tracking data from MQTT packets on each startup. No historical data files need to be transferred between deployments.

## Fresh Deployment

Simply start the container with your configuration files, and the application will:
1. Connect to your MQTT broker
2. Begin receiving packets from mesh nodes
3. Automatically create required data files (logs, etc.)
4. Start rebuilding position history and gateway connections from live MQTT traffic

## Troubleshooting

### Container won't start
```bash
# Check logs for errors
docker logs buoy-tracker

# Check if port is already in use
lsof -i :5102
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

1. **Use environment variables** for secrets (not config file)
2. **Set up reverse proxy** (nginx) with SSL
3. **Configure log rotation** for `logs/` directory
4. **Backup `data/`** directory regularly
5. **Monitor health endpoint** for alerts
6. **Use Docker restart policies**: `--restart unless-stopped`

## Email Distribution Template

```
Subject: Buoy Tracker v0.92 - Docker Container

Buoy Tracker v0.92 Docker image for real-time Meshtastic node tracking.

Quick Start:
1. mkdir buoy-tracker && cd buoy-tracker
2. Create docker-compose.yml (see DOCKER.md Quick Start section)
3. touch tracker.config && mkdir -p data logs
4. docker compose up -d
5. Open: http://localhost:5102

The container runs with sensible defaults. To customize:
- Get tracker.config.template and copy to tracker.config, then edit
- Restart: docker compose restart

See DOCKER.md for complete instructions.
```

---

## Quick Reference

**Getting Started:**
```bash
mkdir buoy-tracker && cd buoy-tracker
touch tracker.config
mkdir -p data logs
docker compose up -d
```

**Access:** http://localhost:5102

**Management:**
```bash
docker compose logs -f       # View logs
docker compose ps            # Check status  
docker compose restart       # Restart
docker compose down          # Stop
```

## Security & Authorization

All API endpoints require authorization using an API key (if configured). The API key must be set in `secret.config` and provided by clients in the `Authorization: Bearer <API_KEY>` header for all requests.

- The API key is securely stored in `secret.config` (not tracked by git).
- If `API_KEY` is not configured, authorization is not required.
- Unauthorized requests to protected endpoints will receive a 401 response.
- Localhost (127.0.0.1) automatically receives the API key if configured.
- For more details, see the security section in `CHANGELOG.md`.
