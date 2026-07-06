# Buoy Tracker

Real-time tracking for **Meshtastic-equipped racing buoys** — a live map, drift
alerts, and battery monitoring for buoys moored in tidal waters. Built for
yacht clubs; battle-tested on San Francisco Bay.

**When a mooring chain breaks, you get an email before the buoy reaches the
next county.** Everything else is in service of that.

## Quick start

```yaml
# docker-compose.yml
services:
  buoy-tracker:
    image: dokwerker8891/buoy-tracker:latest
    container_name: buoy-tracker
    restart: unless-stopped
    ports: ["5103:5103"]
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
    environment:
      PUID: "1000"   # your host user, for clean volume ownership
      PGID: "1000"
      TZ: America/Los_Angeles
```

```bash
mkdir -p config data logs && docker compose up -d
```

The container runs out of the box on built-in defaults (tracking the SF Bay
mesh). First run drops commented example files into `./config/`; customize:

| file | owns |
|---|---|
| `config/site.config` | **your fleet** — buoy IDs, home coordinates, alert radius |
| `config/environment.config` | **your infrastructure** — MQTT broker, SMTP, ports |
| `config/secret.config` | admin password, SMTP credentials |

Unset keys fall back to application defaults; app upgrades never require
config merging. Upgrading from a pre-2.1 single-file config: run once
`docker exec buoy-tracker python3 /app/tools/split_config.py /app/config/tracker.config`

## Features

- Live Leaflet map with per-buoy status: **On station / Moved / Stale / Muted**
- **Drift alerts** by email, with multi-gateway consensus voting that rejects
  corrupted/mutated position packets (no more 2,000 km false alarms)
- **Battery monitoring**: voltage + charge on every card, history charts,
  low-battery emails; weak buoys sort to the top
- **Per-buoy mute** for planned relocations — auto-unmutes when re-moored
- Mobile-first UI (draggable bottom sheet), automatic dark mode
- SQLite store: positions, telemetry, alert events; state survives restarts
- Runs **rootless** (podman `--userns=keep-id`) or rootful with PUID/PGID
- Reverse-proxy friendly: subdomain or subpath via `X-Forwarded-Prefix`
  (Traefik stripprefix works with zero app config)

## Tags

- `latest` — current stable release
- `2.1`, `2.0` — pinned releases (multi-arch: amd64 + arm64)

## Links

- Source, issues, docs: https://github.com/guthip/buoy-tracker
- Deployment guides (Docker, Traefik, podman, ansible): DOCKER.md in the repo

GPL v3. Built on Meshtastic, Flask, Leaflet, OpenStreetMap.
