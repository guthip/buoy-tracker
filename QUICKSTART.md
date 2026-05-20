# Buoy Tracker - Quick Start Guide

Get up and running in 2 minutes.

## Docker (Recommended)

Works on any system with Docker:

```bash
# 1. Clone the repository
git clone https://github.com/guthip/buoy-tracker.git
cd buoy-tracker


# 2. Copy the template to create your local config
cp tracker.config.template tracker.config


# 3. Create logs directory
mkdir -p logs

# 4. Start the application (runs from repo with docker-compose.yml and Dockerfile)
docker compose up -d

# 5. Access at http://localhost:5103
```

**That's it!** The app is pre-configured with defaults and runs immediately.

For advanced configuration, troubleshooting, and full documentation, see [README.md](README.md).

## Local Installation

Requires Python 3.13+ and pip:

```bash
# Install dependencies
pip install -r requirements.txt

nano tracker.config
nano secret.config

# (Optional) Customize settings - app works with defaults
cp tracker.config.template tracker.config
nano tracker.config
cp secret.config.example secret.config
nano secret.config

# Run the application
python3 run.py
```

Access at `http://localhost:5103`

## Next Steps

- See [README.md](README.md) for configuration options, features, and API documentation.
