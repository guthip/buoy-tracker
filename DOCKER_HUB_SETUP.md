# Docker Hub Publishing Setup

This project uses GitHub Actions to automatically build and push Docker images to Docker Hub.

## Setup Instructions

### 1. Create Docker Hub Credentials

1. Go to https://hub.docker.com/settings/security
2. Create a new Personal Access Token (PAT)
3. Copy the token value

### 2. Add GitHub Secrets

1. Go to your GitHub repository: https://github.com/guthip/buoy-tracker
2. Settings → Secrets and variables → Actions → New repository secret
3. Add two secrets:
   - **DOCKER_USERNAME**: Your Docker Hub username
   - **DOCKER_PASSWORD**: Your Personal Access Token (from step 1)

### 3. Automatic Publishing

Once secrets are configured:

- **On Tag Push**: `git tag v0.72 && git push origin v0.72`
  - Builds and pushes: `guthip/buoy-tracker:v0.72` and `guthip/buoy-tracker:latest`

- **On Main Branch Push**: Any push to main branch
  - Builds and pushes: `guthip/buoy-tracker:latest`

### 4. Monitor Builds

View build status:
1. Go to repository → Actions tab
2. Click "Build and Push Docker Image" workflow
3. Click the latest run to see build logs

## Supported Platforms

Images are built for multiple architectures:
- `linux/amd64` (Intel/AMD 64-bit)
- `linux/arm64` (ARM 64-bit, Raspberry Pi 4+, Apple Silicon)

## Usage

Pull and run the latest image:

```bash
docker pull guthip/buoy-tracker:latest
docker run -p 5102:5102 \
  -v $(pwd)/secret.config:/app/secret.config:ro \
  -v tracker_data:/app/data \
  guthip/buoy-tracker:latest
```

Or use a specific version:

```bash
docker pull guthip/buoy-tracker:v0.72
```
