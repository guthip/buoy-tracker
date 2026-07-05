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

# v2.1 layered configs: legacy single-file tracker.config is no longer read.
if [ -f /app/config/tracker.config ] && [ ! -f /app/config/site.config ]; then
    echo "✗ ERROR: legacy tracker.config found but v2.1 uses layered configs."
    echo "  Migrate once (on the host):"
    echo "    python3 tools/split_config.py config/tracker.config"
    echo "  or inside the container:"
    echo "    docker exec buoy-tracker python3 /app/tools/split_config.py /app/config/tracker.config"
    echo "  then restart. The legacy file is ignored afterwards."
    exit 1
fi

# First-run initialization: drop commented example files for the two layers
for name in site.config environment.config; do
    if [ ! -f "/app/config/$name" ] && [ ! -f "/app/config/$name.example" ]; then
        cp "/app/$name.example" "/app/config/$name.example" 2>/dev/null || true
        echo "ⓘ  No $name yet — example placed at config/$name.example (app runs on defaults until you create $name)"
    fi
done

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
# Use || true so SMB-mounted AppleDouble (._*) files that can't be chowned don't abort startup
chown -R app:docker /app/config /app/data /app/logs 2>/dev/null || true

echo "✓ Configuration files ready in /app/config/"
echo "✓ Data directory ready at /app/data/"
echo "✓ Logs directory ready at /app/logs/"
echo ""
echo "Starting Buoy Tracker as user 'app'..."
echo ""

# Switch to app user and run the application
# WORKDIR is /app, so run.py will be found
exec su -s /bin/bash app -c "exec python3 run.py"
