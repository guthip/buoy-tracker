# Dockerfile for Buoy Tracker
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN apt-get update \
    # TODO: Pin package versions for security, e.g. gcc=VERSION build-essential=VERSION curl=VERSION ca-certificates=VERSION \
    && apt-get install -y --no-install-recommends gcc build-essential curl ca-certificates sqlite3 tzdata \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get remove -y gcc build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . /app

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
# 755 explicitly: files copied from SMB contexts can arrive 600, and
# rootless podman must be able to exec this as a non-root user
RUN chmod 755 /entrypoint.sh

# Non-root app user (1000:1000 baseline; the entrypoint re-numbers it to
# PUID/PGID at runtime — linuxserver.io convention, v2.1)
RUN groupadd -g 1000 app && \
    useradd -u 1000 -g app --create-home --home-dir /home/app app

# Create config/data/logs directories and set them world-writable
# Entrypoint runs as root and needs to write to these
RUN mkdir -p /app/config /app/data /app/logs

# Set ownership of application source files to app user (but NOT the config/data/logs dirs)
# Chown recursively for src/static/templates, and top-level files directly in /app.
# chmod ensures files copied from SMB (which may arrive mode 600) are readable by the app user.
RUN chown -R app:app /app/src /app/static /app/templates && \
    find /app -maxdepth 1 -type f -exec chown app:app {} \; && \
    chmod -R a+rX /app   # world-readable: rootless podman may run as any UID

VOLUME ["/app/config", "/app/data", "/app/logs"]
EXPOSE 5103

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5103/health || exit 1

# Run entrypoint as root (it will switch to app user before running the app)
ENTRYPOINT ["/entrypoint.sh"]
