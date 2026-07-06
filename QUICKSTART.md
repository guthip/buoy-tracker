# Buoy Tracker - Quick Start Guide

Get up and running in 2 minutes.

## Docker (Recommended)

Works on any system with Docker:

```bash
# 1. Clone the repository
git clone https://github.com/guthip/buoy-tracker.git
cd buoy-tracker

# 2. Create the config layers from the examples (all optional — the app
#    runs on built-in defaults with none of these present)
mkdir -p config data logs
cp site.config.example config/site.config               # your fleet: buoys, homes, alert policy
cp environment.config.example config/environment.config # your infra: broker, smtp, ports
cp secret.config.template config/secret.config           # only if using auth/alerts

# 3. Start the application (runs from repo with docker-compose.yml and Dockerfile)
docker compose up -d

# 4. Access at http://localhost:5103
```

**That's it!** The app is pre-configured with defaults and runs immediately.

For advanced configuration, troubleshooting, and full documentation, see [README.md](README.md).

## Local Installation

Requires Python 3.13+ and pip:

```bash
# Install dependencies
pip install -r requirements.txt

# Create config files from the examples
mkdir -p config
cp site.config.example config/site.config
cp environment.config.example config/environment.config
cp secret.config.template config/secret.config

# (Optional) Customize settings - app works with defaults
nano config/site.config
nano config/environment.config
nano config/secret.config

# Run the application
python3 run.py
```

Access at `http://localhost:5103`

## Next Steps

- See [README.md](README.md) for configuration options, features, and API documentation.
