#!/bin/bash
# Entrypoint script for Buoy Tracker Docker container
# Handles first-run initialization of configuration files

set -e

echo "=== Buoy Tracker Entrypoint ==="

# Ensure config directory exists
mkdir -p /app/config
mkdir -p /app/data
mkdir -p /app/logs

# First-run initialization: copy templates if config files don't exist
if [ ! -f /app/config/tracker.config ]; then
    echo "First run detected: copying tracker.config template..."
    if [ -f /app/tracker.config.template ]; then
        cp /app/tracker.config.template /app/config/tracker.config
        echo "Created /app/config/tracker.config from template"
    else
        echo "ERROR: tracker.config.template not found in image!"
        exit 1
    fi
fi

if [ ! -f /app/config/secret.config ]; then
    echo "First run detected: copying secret.config template..."
    if [ -f /app/secret.config.template ]; then
        cp /app/secret.config.template /app/config/secret.config
        echo "Created /app/config/secret.config from template"
    else
        echo "WARNING: secret.config.template not found, skipping (optional)"
    fi
fi

# Ensure proper permissions
chown -R app:app /app/config /app/data /app/logs 2>/dev/null || true
chmod 755 /app/config /app/data /app/logs

echo "Configuration files ready in /app/config/"
echo "Starting Buoy Tracker..."

# Run the application
exec "$@"
