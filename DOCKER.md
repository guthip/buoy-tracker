# Buoy Tracker — Docker Deployment Guide

Complete instructions for deploying Buoy Tracker v0.69 with Docker.

## Platform Support

✅ **Multi-Platform Image** - Automatically works on:
- **Intel/AMD (x86_64)** - Standard desktop/server processors
- **Apple Silicon (ARM64)** - M1/M2/M3 Macs
- **Raspberry Pi (ARM64)** - Pi 4 and newer

Docker automatically selects the correct architecture for your platform.

## Quick Start

**Buoy Tracker v0.69** - Real-time Meshtastic mesh network node tracking with data persistence

**Using docker-compose (Recommended)**

Clone the repository and use docker-compose:

```bash
# 1. Clone the repository
git clone https://github.com/guthip/buoy-tracker.git
cd buoy-tracker


# 2. Create logs directory
mkdir -p logs

# 3. Copy and customize configuration files
cp tracker.config.template tracker.config
cp secret.config.example secret.config
nano tracker.config  # Edit your local config

# 5. Start the service (must run from repo directory)
docker compose up -d

# 6. Check status
docker compose ps
docker compose logs -f

# Access at http://localhost:5102
```

**What's created in your directory:**
```
./tracker.config       # Local configuration file (mounted read-only to container, not tracked)
./tracker.config.template # Template config (distributed, tracked)
./secret.config        # Local secrets file (optional, not tracked)
./secret.config.example # Example secrets file (distributed, tracked)
./logs/                # Application logs
```

**To update to a new version:**
```bash
docker compose pull
docker compose up -d
```

All history is cleared on server restart; no data directory is used.

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
- `./tracker.config` → Local configuration file (must be a file, not a folder; place next to secret.config, not tracked)
- `./tracker.config.template` → Template config (distributed, tracked)
- `./secret.config.example` → Example secrets file (should be copied to secret.config for deployment)
- `./secret.config` → Local secrets file (optional, not tracked)
- `./logs/` → Application logs

### Manual: docker run with Volumes

For systems without docker-compose, build from source and run:

```bash
# Clone the repository and build
git clone https://github.com/guthip/buoy-tracker.git
cd buoy-tracker
docker build -t buoy-tracker:latest .


# Create logs directory and local config
mkdir -p logs
cp tracker.config.template tracker.config

# Run with volumes for persistence
docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  --restart unless-stopped \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  -v $(pwd)/logs:/app/logs \
  buoy-tracker:latest
```

**Note:** Only mount `tracker.config` (required). Don't mount `secret.config` unless you have one—the app works fine without it. If you do have a `secret.config` file, add: `-v $(pwd)/secret.config:/app/secret.config:ro` to the docker run command.

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
2. Mounted `secret.config` file (overrides tracker.config for sensitive fields)
3. Mounted `tracker.config` file (local, not tracked)
4. Built-in `tracker.config.template` (default fallback, distributed)

## Volume Mounts Strategy

Separate volumes for different concerns makes deployment and upgrades seamless:

### Configuration Volume (Recommended for Production)
```bash
-v $(pwd)/tracker.config:/app/tracker.config:ro
-v $(pwd)/secret.config:/app/secret.config:ro
```
- **Benefits**: Update config without rebuilding image, works at any installation path
- **Persistence**: Survives container restarts and image upgrades
- **Security**: Read-only mount prevents accidental changes in container
- **Multi-environment**: Use same image with different configs (dev/prod/staging)
- **tracker.config**: Local configuration (not tracked)
- **tracker.config.template**: Distributed template (tracked)
- **secret.config**: Sensitive credentials (email passwords, SMTP credentials) - optional, only if using email alerts

### Complete Volume Setup
```bash
git clone https://github.com/guthip/buoy-tracker.git && cd buoy-tracker
docker build -t buoy-tracker:latest .

# Create required files and directories
mkdir -p data logs
touch tracker.config

docker run -d \
  --name buoy-tracker \
  -p 5102:5102 \
  --restart unless-stopped \
  -v $(pwd)/tracker.config:/app/tracker.config:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  buoy-tracker:latest
```

**Optional:** If you have a `secret.config` file with credentials, add this volume to the docker run command:
```bash
-v $(pwd)/secret.config:/app/secret.config:ro \
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

## Historical Data

**Important**: All runtime data (node positions, packet history) is stored in memory and cleared on server restart.

### Transferring Data Between Deployments

If you're migrating to a new deployment:

**Note**: The server starts fresh on each restart. All history is rebuilt from incoming MQTT packets; no data is persisted. The server rebuilds real-time tracking data from incoming MQTT packets.

To migrate to a new deployment:

1. **From source deployment**, get the data files (if you want to preserve recent packet data):
   ```bash
   - data/special_nodes.json (optional - recent packets)
   ```

2. **To new deployment**, place them in the data directory:
   ```bash
   # Copy files to new deployment's data/ directory (optional)
   cp special_nodes.json ./data/
   
   # Restart the service
   docker compose restart
   ```

3. **On startup**, the application will:
   - Start with empty historical data (fresh history begins from packet arrival time)
   - Restore any packet data from `special_nodes.json` if present
   - Begin tracking nodes as MQTT messages arrive

If you don't have existing data files, the application will create them automatically when the first MQTT packets arrive.

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
Subject: Buoy Tracker v0.69 - Docker Container

Buoy Tracker v0.69 Docker image for real-time Meshtastic node tracking.

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

All API endpoints require authorization using an API key. The API key must be set in `secret.config` and provided by clients in the `Authorization: Bearer <API_KEY>` header for all requests.

- The API key is securely stored in `secret.config` (not tracked by git).
- Unauthorized requests will receive a 401 response.
- For more details, see the security section in `CHANGELOG.md`.
