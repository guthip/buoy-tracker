# Fedora Linux Deployment Guide for Buoy Tracker

**Date**: December 16, 2025
**Container Version**: v0.97d or later
**Target OS**: Fedora Linux (tested on Fedora 39+)

---

## Important Fedora-Specific Differences

### Docker Group GID Mismatch

**The Issue:**
- **Debian/Ubuntu**: Docker group typically uses GID 999
- **Fedora**: Docker group uses a variable GID (often 978, 988, or similar)
- **Fedora GID 999**: Reserved for the "input" group (hardware input devices)

**Impact on Buoy Tracker:**
The container creates a docker group with GID 999 inside the container, but on Fedora hosts:
- Files will be owned by `999:999` on the host filesystem
- The host's GID 999 belongs to the "input" group, not docker
- Users in the host's docker group (e.g., GID 978) won't have access to files with GID 999

---

## Pre-Deployment: Check Your System

### 1. Check Docker Group GID on Your Fedora System

```bash
# Find your docker group GID
getent group docker

# Example output:
# docker:x:978:hans
#        ^^^ This is your docker group GID
```

### 2. Check What Group Owns GID 999

```bash
# Find what group has GID 999
getent group 999

# Expected output on Fedora:
# input:x:999
```

---

## Deployment Options for Fedora

You have three options, listed from simplest to most robust:

### Option 1: Add Your User to the Input Group (Quick Fix)

**Best for**: Single-user Fedora systems, development environments

```bash
# Add your user to the input group (GID 999)
sudo usermod -aG input $USER

# Logout and login for changes to take effect
# Or run: newgrp input

# Verify membership
groups $USER | grep input
```

**Pros:**
- Quick and easy
- No container changes needed
- Works immediately

**Cons:**
- Gives your user access to input devices (minor security consideration)
- Need to do this for every user who needs access
- Not ideal for multi-user systems

---

### Option 2: Use Host's Docker Group GID (Recommended)

**Best for**: Production Fedora deployments, shared servers

This option modifies the container to use your Fedora system's actual docker group GID.

#### Step 1: Find Your Docker Group GID

```bash
# Get docker group GID
DOCKER_GID=$(getent group docker | cut -d: -f3)
echo "Docker group GID: $DOCKER_GID"
```

#### Step 2: Override Container Group at Runtime

Add environment variable to your `docker-compose.yml`:

```yaml
services:
  buoy-tracker:
    image: dokwerker8891/buoy-tracker:0.97d
    environment:
      - DOCKER_GID=${DOCKER_GID:-978}  # Use your actual GID
    volumes:
      - ./buoy-tracker/config:/app/config
      - ./buoy-tracker/data:/app/data
      - ./buoy-tracker/logs:/app/logs
    ports:
      - "5103:5103"
    restart: unless-stopped
```

#### Step 3: Modify Entrypoint to Use DOCKER_GID

**Create a custom entrypoint** (fedora-entrypoint.sh):

```bash
#!/bin/bash
# Fedora-specific entrypoint for Buoy Tracker
# Handles variable docker group GID

set -e

echo "=== Buoy Tracker Entrypoint (Fedora) ==="

# Get docker GID from environment or use 978 as default
DOCKER_GID=${DOCKER_GID:-978}
echo "Using docker group GID: $DOCKER_GID"

# Ensure config/data/logs directories exist with proper permissions
mkdir -p /app/config /app/data /app/logs

# Make sure directories are writable by docker group (host user access)
chmod 775 /app/config /app/data /app/logs

# First-run initialization: copy templates if config files don't exist
if [ ! -f /app/config/tracker.config ]; then
    echo "First run detected: copying tracker.config template..."
    if [ -f /app/tracker.config.template ]; then
        cp /app/tracker.config.template /app/config/tracker.config
        chmod 664 /app/config/tracker.config
        echo "✓ Created /app/config/tracker.config from template"
    else
        echo "✗ ERROR: tracker.config.template not found in image!"
        exit 1
    fi
fi

if [ ! -f /app/config/secret.config ]; then
    echo "First run detected: copying secret.config template..."
    if [ -f /app/secret.config.template ]; then
        cp /app/secret.config.template /app/config/secret.config
        chmod 664 /app/config/secret.config
        echo "✓ Created /app/config/secret.config from template"
    else
        echo "⚠ WARNING: secret.config.template not found, skipping (optional)"
    fi
fi

# Change ownership to app:$DOCKER_GID (Fedora's docker group GID)
chown -R app:$DOCKER_GID /app/config /app/data /app/logs

echo "✓ Configuration files ready in /app/config/"
echo "✓ Data directory ready at /app/data/"
echo "✓ Logs directory ready at /app/logs/"
echo ""
echo "Starting Buoy Tracker as user 'app'..."
echo ""

# Switch to app user and run the application
exec su -s /bin/bash app -c "exec python3 run.py"
```

#### Step 4: Mount Custom Entrypoint

Add to your `docker-compose.yml`:

```yaml
services:
  buoy-tracker:
    image: dokwerker8891/buoy-tracker:0.97d
    environment:
      - DOCKER_GID=978  # Replace with your actual docker group GID
    volumes:
      - ./buoy-tracker/config:/app/config
      - ./buoy-tracker/data:/app/data
      - ./buoy-tracker/logs:/app/logs
      - ./buoy-tracker/fedora-entrypoint.sh:/entrypoint.sh  # Custom entrypoint
    ports:
      - "5103:5103"
    restart: unless-stopped
```

**Pros:**
- Uses proper docker group permissions
- Works for all users in docker group
- No security compromises
- Matches Fedora best practices

**Cons:**
- Requires custom entrypoint script
- Slightly more complex setup

---

### Option 3: Use Numeric UID/GID Mapping (Most Portable)

**Best for**: Multi-distribution environments, containers running on different Linux flavors

This approach uses PUID/PGID environment variables (like LinuxServer.io containers).

**Status**: Not yet implemented in Buoy Tracker
**Future Enhancement**: See FIXOWNERSHIP.md for implementation details

---

## Recommended Deployment Workflow for Fedora

### 1. Prepare Deployment Directory

```bash
# Create directory structure
mkdir -p ~/docker/buoy-tracker/{config,data,logs}
cd ~/docker/buoy-tracker
```

### 2. Get Your Docker Group GID

```bash
# Find docker group GID
DOCKER_GID=$(getent group docker | cut -d: -f3)
echo "Your docker group GID: $DOCKER_GID"
# Example output: Your docker group GID: 978
```

### 3. Create Custom Entrypoint (Option 2 Only)

If using Option 2, create `fedora-entrypoint.sh` with the script shown above:

```bash
# Create the custom entrypoint
nano fedora-entrypoint.sh
# Paste the fedora-entrypoint.sh content from above

# Make it executable
chmod +x fedora-entrypoint.sh
```

### 4. Create docker-compose.yml

**For Option 1 (Input Group):**
```yaml
version: '3.8'

services:
  buoy-tracker:
    image: dokwerker8891/buoy-tracker:0.97d
    container_name: buoy-tracker
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
    ports:
      - "5103:5103"
    restart: unless-stopped
```

**For Option 2 (Custom Entrypoint):**
```yaml
version: '3.8'

services:
  buoy-tracker:
    image: dokwerker8891/buoy-tracker:0.97d
    container_name: buoy-tracker
    environment:
      - DOCKER_GID=978  # Replace with your actual GID
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
      - ./fedora-entrypoint.sh:/entrypoint.sh
    ports:
      - "5103:5103"
    restart: unless-stopped
```

### 5. Deploy Container

```bash
# Start container
docker compose up -d

# Check logs
docker logs buoy-tracker --tail 50

# Verify it started successfully
docker ps | grep buoy-tracker
```

### 6. Verify File Permissions

```bash
# Check ownership of created files
ls -la data/ logs/ config/

# For Option 1 (should show 999:input):
# -rw-r----- 1 999 input ... special_nodes.json

# For Option 2 (should show 999:docker where docker is GID 978):
# -rw-r----- 1 999 978 ... special_nodes.json
```

### 7. Verify Host Access

```bash
# Try to read files as your user (should work)
cat logs/buoy_tracker.log
cat data/special_nodes.json

# If access denied, check your group membership:
groups $USER

# For Option 1: should include 'input'
# For Option 2: should include 'docker'
```

---

## Troubleshooting Fedora Deployments

### Issue: "Permission denied" when accessing files

**Diagnosis:**
```bash
# Check file ownership
ls -l data/special_nodes.json

# Check your group membership
groups $USER
```

**Solution:**
- **Option 1**: Ensure you're in the input group: `sudo usermod -aG input $USER`
- **Option 2**: Verify DOCKER_GID matches your system: `getent group docker`

### Issue: SELinux blocking container access

**Diagnosis:**
```bash
# Check SELinux status
sestatus

# Check for SELinux denials
sudo ausearch -m avc -ts recent | grep buoy
```

**Solution:**
```bash
# Option A: Set SELinux context on volumes
sudo chcon -R -t container_file_t ~/docker/buoy-tracker/{config,data,logs}

# Option B: Add :z or :Z to volume mounts in docker-compose.yml
volumes:
  - ./config:/app/config:z
  - ./data:/app/data:z
  - ./logs:/app/logs:z
```

### Issue: Container can't resolve DNS

**Diagnosis:**
```bash
# Test DNS inside container
docker exec buoy-tracker nslookup mqtt.bayme.sh
```

**Solution:**
```bash
# Add DNS servers to docker-compose.yml
services:
  buoy-tracker:
    dns:
      - 8.8.8.8
      - 8.8.4.4
```

### Issue: Firewall blocking port 5103

**Diagnosis:**
```bash
# Check if port is blocked
sudo firewall-cmd --list-ports

# Test from another machine
curl http://<fedora-ip>:5103
```

**Solution:**
```bash
# Open port 5103
sudo firewall-cmd --permanent --add-port=5103/tcp
sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --list-ports | grep 5103
```

---

## Comparison: Fedora vs Debian/Ubuntu Deployment

| Aspect | Debian/Ubuntu | Fedora |
|--------|---------------|--------|
| **Docker Group GID** | 999 (standard) | Variable (978, 988, etc.) |
| **GID 999 Owner** | docker or ping | input (hardware) |
| **Container Works OOTB** | ✅ Yes | ⚠️ Needs adjustment |
| **File Access** | Direct via docker group | Requires Option 1 or 2 |
| **SELinux** | Usually disabled | Enabled by default |
| **Firewall** | ufw (often permissive) | firewalld (restrictive) |

---

## Security Considerations for Fedora

### SELinux
Fedora runs SELinux in enforcing mode by default. This provides additional security but may require:
- Setting proper SELinux contexts on volume mounts
- Using `:z` or `:Z` volume mount options in docker-compose.yml

### Firewalld
Fedora's firewalld is more restrictive than Ubuntu's ufw:
- Port 5103 must be explicitly opened
- Docker networks may need firewall rules

### Input Group Membership
If using Option 1:
- Gives users access to `/dev/input/*` devices
- Generally safe on single-user systems
- Review security implications for multi-user servers

---

## Recommended Approach

**For most Fedora deployments, we recommend Option 2:**
1. Uses proper docker group permissions
2. No security compromises
3. Works across different Fedora versions
4. Easy to maintain

**Quick setup:**
```bash
# 1. Get your docker GID
DOCKER_GID=$(getent group docker | cut -d: -f3)

# 2. Download custom entrypoint
curl -O https://raw.githubusercontent.com/guthip/buoy-tracker/main/fedora-entrypoint.sh
chmod +x fedora-entrypoint.sh

# 3. Update docker-compose.yml with DOCKER_GID environment variable
# 4. Deploy!
docker compose up -d
```

---

## Future Enhancement: Native PUID/PGID Support

A future version of Buoy Tracker will include native PUID/PGID support, making deployment on Fedora (and other distributions) completely seamless:

```yaml
services:
  buoy-tracker:
    image: dokwerker8891/buoy-tracker:future
    environment:
      - PUID=1000    # Your user ID
      - PGID=978     # Your docker group ID
```

This will eliminate the need for custom entrypoints or group membership workarounds.

---

## Testing Your Fedora Deployment

### Basic Functionality Test

```bash
# 1. Container running
docker ps | grep buoy-tracker
# Should show: Up X minutes (healthy)

# 2. Web interface accessible
curl -I http://localhost:5103
# Should return: HTTP/1.1 200 OK

# 3. MQTT connecting
docker logs buoy-tracker | grep -i mqtt
# Should show: ✅ Connected to MQTT broker

# 4. File permissions work
cat data/special_nodes.json
# Should display JSON data (no permission denied)

# 5. Logs accessible
tail -20 logs/buoy_tracker.log
# Should show recent log entries
```

### Full Integration Test

```bash
# Wait 5 minutes for MQTT messages to arrive
sleep 300

# Check if nodes are being tracked
curl http://localhost:5103/api/nodes | jq '.nodes | length'
# Should show number > 0

# Check if data is persisting
ls -lh data/
# Should show special_nodes.json with size > 0
```

---

## Support and Issues

If you encounter issues deploying on Fedora:

1. Check this guide's troubleshooting section
2. Verify your docker group GID: `getent group docker`
3. Check SELinux status: `sestatus`
4. Review container logs: `docker logs buoy-tracker`
5. Open an issue on GitHub with:
   - Fedora version (`cat /etc/fedora-release`)
   - Docker group GID (`getent group docker`)
   - SELinux status (`sestatus`)
   - Container logs

---

**Last Updated**: December 16, 2025
**Tested On**: Fedora 39, Fedora 40
**Container Version**: v0.97d
