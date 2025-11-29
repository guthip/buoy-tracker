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

# Create non-root user
RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app \
    && chown -R app:app /app

USER app

VOLUME ["/app/data", "/app/logs"]
EXPOSE 5102

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5102/api/status || exit 1

CMD ["python3", "run.py"]
