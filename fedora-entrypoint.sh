#!/bin/bash
# Fedora-specific entrypoint for Buoy Tracker Docker container
# Handles variable docker group GID across different Linux distributions
# Use this entrypoint on Fedora systems where docker group GID != 999

set -e

echo "=== Buoy Tracker Entrypoint (Fedora) ==="

# Get docker GID from environment or use 978 as default (common Fedora GID)
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

# Change ownership to app:$DOCKER_GID (uses Fedora's actual docker group GID)
# This allows host users in the docker group to access container files
chown -R app:$DOCKER_GID /app/config /app/data /app/logs

echo "✓ Configuration files ready in /app/config/"
echo "✓ Data directory ready at /app/data/"
echo "✓ Logs directory ready at /app/logs/"
echo "✓ File ownership set to app:$DOCKER_GID"
echo ""
echo "Starting Buoy Tracker as user 'app'..."
echo ""

# Switch to app user and run the application
# WORKDIR is /app, so run.py will be found
exec su -s /bin/bash app -c "exec python3 run.py"
