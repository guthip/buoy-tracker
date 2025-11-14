# Buoy Tracker — Docker Deployment Guide

Complete instructions for deploying Buoy Tracker v0.2 with Docker.

## Quick Start

**Buoy Tracker v0.2** - Real-time Meshtastic mesh network node tracking

### From Docker Hub (Recommended)

```bash
# Pull and run the latest version
docker run -d --name buoy-tracker -p 5102:5102 dokwerker8891/buoy-tracker:0.2

# Access at http://localhost:5102
```

### From Tarball

```bash
# Load the distributed container
docker load < buoy-tracker-0.2.tar.gz

# Run with built-in retention data
docker run -d --name buoy-tracker -p 5102:5102 buoy-tracker:0.2
```

### With Custom Configuration

```bash
# Create and edit your config
cp tracker.config.example tracker.config
nano tracker.config

# Run with custom config
docker run -d --name buoy-tracker \
  -p 5102:5102 \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  dokwerker8891/buoy-tracker:0.2
```

**Data Persistence**: Container includes retention data. Add `-v $(pwd)/data:/app/data` only if you need to persist data across container recreation.

## Building the Image (Optional)

If you want to build from source:

```bash
docker build -t buoy-tracker:0.2 .
```

## Running Options

### Option 1: Pull from Docker Hub (Recommended)

Easiest method - no build or download required:

```bash
docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  dokwerker8891/buoy-tracker:0.2
```

### Option 2: Default Configuration (from local image)

Runs immediately with example config (connects to mqtt.bayme.sh) and built-in retention data:

```bash
docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  buoy-tracker:0.2
```

### Option 3: With Data Persistence

Add volume mount to persist data across container restarts:

```bash
docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  -v $(pwd)/data:/app/data \
  dokwerker8891/buoy-tracker:0.2
```

### Option 4: Custom Configuration (Full Control)

Create your config file first:

```bash
cp tracker.config.example tracker.config
nano tracker.config  # Edit MQTT settings, special nodes, etc.

docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  dokwerker8891/buoy-tracker:0.2
```

**Note**: Data volume mount removed to preserve built-in retention data.

### Option 5: Environment Variables (Production)

Pass secrets via environment variables (uses built-in retention data):

```bash
docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  -e MQTT_USERNAME=your_user \
  -e MQTT_PASSWORD=your_password \
  -e MQTT_KEY=your_encryption_key \
  dokwerker8891/buoy-tracker:0.2
```

**Note**: Add `-v $(pwd)/data:/app/data` if you need to persist data beyond the built-in retention data.

### Option 6: Docker Compose (Best for Development)

Uses the included `docker-compose.yml`:

```bash
# (Optional) Load distributed image first
docker load < buoy-tracker-0.2.tar.gz

# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

**Note**: Edit `docker-compose.yml` or create `.env` file to configure environment variables. Uncomment volume mounts in `docker-compose.yml` for data persistence or custom config.

## Configuration Priority

The app loads config in this order:
1. Environment variables (highest priority)
2. Mounted `tracker.config` file
3. Built-in `tracker.config.example` (default fallback)

## Volume Mounts

**Note**: The container includes pre-populated retention data (7-day history). Volume mounts are optional for persistence.

### Optional (for ongoing persistence)
- `./data:/app/data` - Persists node data, position history, packets across container restarts
- `./logs:/app/logs` - Access logs from host
- `./tracker.config:/app/tracker.config:ro` - Custom configuration

**Important**: If you mount `./data:/app/data` from an empty host directory, it will override the built-in retention data. Either:
- Don't mount data volume to use built-in data
- Mount data volume only after container has been running to preserve accumulated data

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

```bash
# Stop and remove old container
docker stop buoy-tracker
docker rm buoy-tracker

# Pull/build new image
docker build -t buoy-tracker:0.2 .

# Start with same volumes
docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  buoy-tracker:0.2
```

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
Subject: Buoy Tracker v0.2 - Docker Container

Attached is the Buoy Tracker v0.2 Docker image for real-time Meshtastic node tracking.

Quick Start:
1. Load image: docker load < buoy-tracker-0.2.tar
2. Run: docker run -d -p 5102:5102 -v $(pwd)/data:/app/data buoy-tracker:0.2
3. Open: http://localhost:5102

The container runs with sensible defaults. To customize:
- Copy tracker.config.example to tracker.config
- Edit MQTT broker, special nodes, and other settings
- Re-run with: -v $(pwd)/tracker.config:/app/tracker.config:ro

See DOCKER.md for complete instructions.
```

## Exporting Image for Distribution

```bash
# Build image
docker build -t buoy-tracker:0.2 .

# Save to tarball
docker save buoy-tracker:0.2 | gzip > buoy-tracker-0.2.tar.gz

# Recipient loads image
gunzip -c buoy-tracker-0.2.tar.gz | docker load
```

---

## Quick Reference Card

**For recipients of the distributed container:**

**Option 1: Pull from Docker Hub (Easiest)**
```bash
# 1. Pull and run
docker run -d --name buoy-tracker -p 5102:5102 dokwerker8891/buoy-tracker:0.2

# 2. Access the application
open http://localhost:5102
```

**Option 2: Load from tarball**
```bash
# 1. Load the image
docker load < buoy-tracker-0.2.tar.gz

# 2. Run with defaults (includes retention data)
docker run -d --name buoy-tracker -p 5102:5102 buoy-tracker:0.2

# 3. Access the application
open http://localhost:5102
```

**Option 3: Using docker-compose**
```bash
# 1. Download docker-compose.yml (or create from example)
wget https://raw.githubusercontent.com/guthip/buoy-tracker/main/docker-compose.yml

# 2. Start services (automatically pulls image)
docker-compose up -d

# 3. View logs
docker-compose logs -f

# Stop services
docker-compose down
```

**With optional persistence:**
```bash
docker run -d --name buoy-tracker \
  -p 5102:5102 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  dokwerker8891/buoy-tracker:0.2
```

**Management commands:**
```bash
docker logs -f buoy-tracker        # View logs
docker stop buoy-tracker           # Stop container
docker start buoy-tracker          # Start container
docker rm -f buoy-tracker          # Remove container
```
