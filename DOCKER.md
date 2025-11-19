# Buoy Tracker — Docker Deployment Guide

Complete instructions for deploying Buoy Tracker v0.68 with Docker.

## Platform Support

✅ **Multi-Platform Image** - Automatically works on:
- **Intel/AMD (x86_64)** - Standard desktop/server processors
- **Apple Silicon (ARM64)** - M1/M2/M3 Macs
- **Raspberry Pi (ARM64)** - Pi 4 and newer

Docker automatically selects the correct architecture for your platform.

## Quick Start

**Buoy Tracker v0.68** - Real-time Meshtastic mesh network node tracking with data persistence

### Using docker-compose (Recommended)

```bash
# 1. Get the docker-compose.yml file
wget https://raw.githubusercontent.com/guthip/buoy-tracker/main/docker-compose.yml

# 2. Create required directories
mkdir -p data logs

# 3. (Optional) Copy and customize config
cp tracker.config.template tracker.config
nano tracker.config  # Edit if needed

# 4. Start the service
docker compose up -d

# 5. Check status
docker compose ps
docker compose logs -f

# 6. Access the application
# http://localhost:5102
```

**What's created in your directory:**
```
./tracker.config       # Configuration file (mounted read-only to container)
./data/                # Node data, history, packets (persisted)
./logs/                # Application logs (persisted)
./docs/                # Documentation files (mounted read-only)
```

**To update to a new version:**
```bash
docker compose pull
docker compose up -d
```

The existing `./data` directory is preserved across updates.

## Running Options

### Recommended: Docker Compose

Uses the included `docker-compose.yml` with pre-configured volumes:

```bash
# Start services
docker compose up -d

# View logs
docker compose logs -f

# Stop services
docker compose down
```

**Automatic volume setup:**
- `./tracker.config` → Configuration
- `./data/` → Persistent data
- `./logs/` → Application logs
- `./docs/` → Documentation

### Manual: docker run with Volumes

For systems without docker-compose, build from source and run:

```bash
# Clone the repository and build
git clone https://github.com/guthip/buoy-tracker.git
cd buoy-tracker
docker build -t buoy-tracker:latest .

# Run with volumes for persistence
docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  --restart unless-stopped \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  buoy-tracker:latest
```

### Quick Start (No Persistence)

For testing - runs with defaults, no volume mounts (requires build first):

```bash
git clone https://github.com/guthip/buoy-tracker.git && cd buoy-tracker
docker build -t buoy-tracker:latest .

docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  buoy-tracker:latest
```

⚠️ **Note**: Data will be lost when container restarts. Use volumes for production.

## Configuration Priority

The app loads config in this order:
1. Environment variables (highest priority)
2. Mounted `tracker.config` file
3. Built-in `tracker.config.example` (default fallback)

## Volume Mounts Strategy

Separate volumes for different concerns makes deployment and upgrades seamless:

### Configuration Volume (Recommended for Production)
```bash
-v $(pwd)/tracker.config:/app/tracker.config:ro
```
- **Benefits**: Update config without rebuilding image, works at any installation path
- **Persistence**: Survives container restarts and image upgrades
- **Security**: Read-only mount prevents accidental changes in container
- **Multi-environment**: Use same image with different configs (dev/prod/staging)

### Data Volume (Persistent Storage)
```bash
-v $(pwd)/data:/app/data
-v $(pwd)/logs:/app/logs
```
- **data volume**: Node positions, special node history, packet cache
- **logs volume**: Application logs for troubleshooting
- **Atomic writes**: Prevents data corruption on ungraceful shutdowns
- **7-day retention**: Auto-cleanup of old packets and position history

### Documentation Volume (Optional)
```bash
-v $(pwd)/docs:/app/docs:ro
```
- Serve project documentation from host without rebuilding
- Keep docs in sync with deployed version

### Complete Volume Setup
```bash
git clone https://github.com/guthip/buoy-tracker.git && cd buoy-tracker
docker build -t buoy-tracker:latest .

docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  --restart unless-stopped \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  buoy-tracker:latest
```

**Why This Approach?**
1. ✅ Config changes don't require image rebuild or container restart
2. ✅ Same image works across dev/staging/production with different configs
3. ✅ Data persists across container upgrades
4. ✅ Logs accessible from host for monitoring
5. ✅ Easy to backup configuration separately from data

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
Subject: Buoy Tracker v0.68 - Docker Container

Buoy Tracker v0.68 Docker image for real-time Meshtastic node tracking.

Quick Start:
1. mkdir buoy-tracker && cd buoy-tracker
2. Create docker-compose.yml (see DOCKER.md Quick Start section)
3. touch tracker.config && mkdir -p data logs
4. docker compose up -d
5. Open: http://localhost:5102

The container runs with sensible defaults. To customize:
- Get tracker.config.template and edit it
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
