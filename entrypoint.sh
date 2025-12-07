#!/bin/bash
# Entrypoint script for Buoy Tracker Docker container
# Handles first-run initialization of configuration files
# Runs as root initially, then switches to app user to run the application

set -e

echo "=== Buoy Tracker Entrypoint ==="

# Ensure config/data/logs directories exist with proper permissions
mkdir -p /app/config /app/data /app/logs

# First-run initialization: copy templates if config files don't exist
if [ ! -f /app/config/tracker.config ]; then
    echo "First run detected: copying tracker.config template..."
    if [ -f /app/tracker.config.template ]; then
        cp /app/tracker.config.template /app/config/tracker.config
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
        echo "✓ Created /app/config/secret.config from template"
    else
        echo "⚠ WARNING: secret.config.template not found, skipping (optional)"
    fi
fi

# Set proper permissions on all app directories and files
# Directory: 755 (rwxr-xr-x) - app user can read/write/execute
# Files: 644 (rw-r--r--) - app user can read/write
chmod -R 755 /app/config /app/data /app/logs
find /app/config -type f -exec chmod 644 {} \; 2>/dev/null || true
find /app/data -type f -exec chmod 644 {} \; 2>/dev/null || true

# Change ownership to app user so it can read/write files
chown -R app:app /app/config /app/data /app/logs

echo "✓ Configuration files ready in /app/config/"
echo "✓ Data directory ready at /app/data/"
echo "✓ Logs directory ready at /app/logs/"
echo ""
echo "Starting Buoy Tracker as user 'app'..."
echo ""

# Switch to app user and run the application
exec su - app -c "$(printf '%s ' "$@")"
