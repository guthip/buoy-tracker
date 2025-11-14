# GitHub Release Guide - Buoy Tracker v0.2

## Prerequisites
- GitHub account
- Git installed locally
- GitHub CLI (`gh`) installed (optional but recommended)

## Step 1: Initialize Git Repository (if not already done)

```bash
cd /Users/hans/VSC/buoy_tracker

# Initialize git if needed
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit - Buoy Tracker v0.2 with Docker deployment"
```

## Step 2: Create GitHub Repository

### Option A: Using GitHub CLI (Recommended)
```bash
# Install GitHub CLI if needed
brew install gh

# Login to GitHub
gh auth login

# Create repository (choose public or private)
gh repo create buoy-tracker --public --source=. --remote=origin --push

# Or for private repository
gh repo create buoy-tracker --private --source=. --remote=origin --push
```

### Option B: Using GitHub Web Interface
1. Go to https://github.com/new
2. Repository name: `buoy-tracker`
3. Description: "Real-time Meshtastic mesh network node tracker with web interface"
4. Choose Public or Private
5. Do NOT initialize with README (we already have one)
6. Click "Create repository"

Then connect your local repository:
```bash
# Replace 'yourusername' with your GitHub username
git remote add origin https://github.com/yourusername/buoy-tracker.git
git branch -M main
git push -u origin main
```

## Step 3: Create Git Tag for v0.2

```bash
# Create annotated tag
git tag -a v0.2 -m "Release v0.2 - Docker deployment with retention data

Features:
- Real-time node tracking via MQTT
- Interactive Leaflet map with color-coded status
- Special node tracking with 7-day history retention
- Docker deployment with pre-populated retention data
- Docker Compose support
- Complete documentation and Quick Reference Card"

# Push tag to GitHub
git push origin v0.2
```

## Step 4: Create GitHub Release

### Option A: Using GitHub CLI (Recommended)
```bash
# Create release with distribution files
gh release create v0.2 \
  --title "Buoy Tracker v0.2 - Docker Deployment" \
  --notes-file - <<'EOF'
# Buoy Tracker v0.2

Real-time Meshtastic mesh network node tracker with Docker deployment.

## What's New
- 🐳 Docker deployment with pre-populated retention data (313 KB)
- 📦 Docker Compose support for easy orchestration
- 📊 7-day automatic data retention policy
- 🗺️ Interactive map with node status indicators
- 📝 Comprehensive documentation with Quick Reference Card

## Docker Deployment

### Quick Start
```bash
# Import the container
docker load < buoy-tracker-0.2.tar.gz

# Verify checksum
sha256sum -c buoy-tracker-0.2.tar.gz.sha256

# Run with default configuration
docker run -d -p 5102:5102 --name buoy-tracker buoy-tracker:0.2

# Access at http://localhost:5102
```

### Using Docker Compose
```bash
# Extract docker-compose.yml from container
docker run --rm buoy-tracker:0.2 cat /app/docker-compose.yml > docker-compose.yml

# Start services
docker-compose up -d

# View logs
docker-compose logs -f
```

## Distribution Files
- **buoy-tracker-0.2.tar.gz** (192 MB) - Complete Docker image
- **buoy-tracker-0.2.tar.gz.sha256** - Checksum for verification

## Documentation
Complete documentation is included in the container:
- `/app/README.md` - Project overview and quick start
- `/app/DOCKER.md` - Comprehensive Docker deployment guide
- `/app/QUICKSTART.md` - Quick configuration guide
- `/app/CONFIG.md` - Configuration reference

## Requirements
- Docker 20.10+
- Docker Compose 2.0+ (optional)
- 192 MB disk space for container

## Support
See DOCKER.md in the container for complete deployment instructions and troubleshooting.
EOF
  buoy-tracker-0.2.tar.gz \
  buoy-tracker-0.2.tar.gz.sha256
```

### Option B: Using GitHub Web Interface
1. Go to your repository on GitHub
2. Click "Releases" in the right sidebar
3. Click "Draft a new release"
4. Click "Choose a tag" → Select "v0.2"
5. Release title: `Buoy Tracker v0.2 - Docker Deployment`
6. Description: Copy the release notes from above
7. Upload files:
   - Drag `buoy-tracker-0.2.tar.gz` (192 MB)
   - Drag `buoy-tracker-0.2.tar.gz.sha256` (90 bytes)
8. Click "Publish release"

## Step 5: Verify Release

```bash
# View release details
gh release view v0.2

# Or visit:
# https://github.com/yourusername/buoy-tracker/releases/tag/v0.2
```

## Distribution Instructions for Recipients

Once the release is published, recipients can download and deploy:

```bash
# Download release files
wget https://github.com/yourusername/buoy-tracker/releases/download/v0.2/buoy-tracker-0.2.tar.gz
wget https://github.com/yourusername/buoy-tracker/releases/download/v0.2/buoy-tracker-0.2.tar.gz.sha256

# Verify checksum
sha256sum -c buoy-tracker-0.2.tar.gz.sha256

# Import and run
docker load < buoy-tracker-0.2.tar.gz
docker run -d -p 5102:5102 --name buoy-tracker buoy-tracker:0.2
```

## Additional Notes

### Repository Topics (Optional)
Add these topics to your GitHub repository for better discoverability:
- meshtastic
- mqtt
- docker
- flask
- leaflet
- mesh-network
- tracker
- real-time
- web-interface

### GitHub Actions (Future Enhancement)
Consider setting up automated Docker builds with GitHub Actions in future releases.

## Troubleshooting

### Large File Upload Issues
If the 192 MB file fails to upload via web interface:
1. Use GitHub CLI instead: `gh release upload v0.2 buoy-tracker-0.2.tar.gz`
2. Or use Git LFS for files >100 MB (though release assets support up to 2 GB)

### Permission Issues
If push fails:
```bash
# Ensure you have write access to the repository
gh auth refresh -s write:packages,repo

# Or regenerate your GitHub token with proper permissions
```
