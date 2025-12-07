# Dockerfile for Buoy Tracker v0.6
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN apt-get update \
    # TODO: Pin package versions for security, e.g. gcc=VERSION build-essential=VERSION curl=VERSION ca-certificates=VERSION \
    && apt-get install -y --no-install-recommends gcc build-essential curl ca-certificates \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get remove -y gcc build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . /app

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create non-root user
RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app

# Create config/data/logs directories and set them world-writable
# Entrypoint runs as root and needs to write to these
RUN mkdir -p /app/config /app/data /app/logs

# Set ownership of application source files to app user (but NOT the config/data/logs dirs)
# This is done AFTER creating config/data/logs so they remain writable
RUN find /app -maxdepth 1 -type f -exec chown app:app {} \; && \
    find /app -maxdepth 1 -type d -not -name config -not -name data -not -name logs -exec chown app:app {} \;

VOLUME ["/app/config", "/app/data", "/app/logs"]
EXPOSE 5103

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5103/health || exit 1

# Run entrypoint as root (it will switch to app user before running the app)
ENTRYPOINT ["/entrypoint.sh"]
