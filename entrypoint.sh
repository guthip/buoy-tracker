#!/bin/bash
# Entrypoint script for Buoy Tracker Docker container
# Handles first-run initialization of configuration files
# Should run as root to create and set up config files

set -e

echo "=== Buoy Tracker Entrypoint ==="


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

# Change ownership to app:docker (NOT app:app) so host users in docker group keep access
chown -R app:docker /app/config /app/data /app/logs

echo "✓ Configuration files ready in /app/config/"
echo "✓ Data directory ready at /app/data/"
echo "✓ Logs directory ready at /app/logs/"
echo ""
echo "Starting Buoy Tracker as user 'app'..."
echo ""

# Switch to app user and run the application
# WORKDIR is /app, so run.py will be found
exec su -s /bin/bash app -c "exec python3 run.py"
