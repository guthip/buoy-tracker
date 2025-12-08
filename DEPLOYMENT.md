# Deployment Guide v0.93

**Release Date:** December 7, 2025  
**Version:** 0.93  
**Status:** Ready for Deployment  
**Risk Level:** Low (security & bug fixes, no breaking changes)

---

## Executive Summary

Version 0.93 includes security improvements to the authorization modal system and fixes to MQTT reconnection logic. The release includes comprehensive quality assurance infrastructure (pre-commit hooks, build validation, GitHub Actions CI).

**Key Improvements:**
- ✅ Authorization modal security fixes (modal only appears on Control Menu access)
- ✅ MQTT handler undefined function bug fixed
- ✅ Docker permission issues resolved
- ✅ Quality assurance infrastructure operational
- ✅ Multi-platform Docker images (amd64, arm64)

---

## Pre-Deployment Checklist

Use this checklist to verify everything is working before deployment.

### Code Quality

- [ ] **Python Syntax** - `python3 -m py_compile src/*.py tests/*.py` passes
- [ ] **No Dead Code** - Review for unused imports and debug statements
- [ ] **Tests Pass** - `python3 -m pytest tests/ -v` succeeds (12+ tests)
- [ ] **Documentation Complete** - tracker.config.template, README.md, SECURITY.md all current

### Comprehensive Code Review

**STEP 1: Data Flow Tracing** - Trace end-to-end for authorization logic:
- [ ] **Config layer** (config.py) - apiKeyRequired setting defined
- [ ] **Backend** (main.py) - @require_api_key decorator checks auth
- [ ] **Template** (templates/simple.html) - Data attributes set correctly
- [ ] **Frontend** (static/app.js) - Modal gating logic correct (lines 4-35)
- [ ] **Security** (SECURITY.md) - Attack vector documentation current

**STEP 2: Cross-Layer Verification**
- [ ] Config → Backend: API key required properly enforced
- [ ] Backend → Template: Auth status passed to frontend
- [ ] Template → Frontend: JS receives correct data attributes
- [ ] Frontend Logic: Auth modal only shows on Control Menu access (not page load)

**STEP 3: Testing**
- [ ] **Local Testing**
  - [ ] Map loads without auth prompt
  - [ ] Clicking Control Menu shows password modal
  - [ ] Entering wrong password shows error
  - [ ] Clicking "Clear" requires password re-entry
  - [ ] After entering correct password, Control Menu accessible
  
- [ ] **Error Cases**
  - [ ] 401 errors trigger auth modal
  - [ ] Network failures don't leave UI broken
  - [ ] Modal can be dismissed and retried
  - [ ] No console errors in browser

### Docker & Deployment

- [ ] **Dockerfile Valid** - `docker build -t test:latest .` succeeds
- [ ] **Multi-Platform Build** - Both amd64 and arm64 images build successfully
- [ ] **docker-compose Works** - `docker compose up -d` starts cleanly
- [ ] **Web Interface Accessible** - http://localhost:5103 responds (port 5103 - upgraded from 5102)
- [ ] **MQTT Connection Verified** - Logs show "Connected to MQTT broker"
- [ ] **Permissions OK** - Container starts without "Permission denied" errors

### Version Synchronization

- [ ] **tracker.config** - version = 0.93
- [ ] **tracker.config.template** - version = 0.93
- [ ] **CHANGELOG.md** - v0.93 entry present with changes
- [ ] **DOCKER.md** - Port references updated to 5103
- [ ] **SECURITY.md** - v0.93 compatibility verified
- [ ] **README.md** - No outdated version references
- [ ] **QUICKSTART.md** - Port and version current

### Security & Configuration

- [ ] **No Hardcoded Credentials** - grep -r "password\|api_key\|secret" src/ shows only references, not values
- [ ] **API Key Protection** - @require_api_key decorator on protected endpoints
- [ ] **SSL/HTTPS** - Documented for production deployments (if applicable)
- [ ] **.gitignore Correct** - tracker.config, secret.config not tracked
- [ ] **Configuration Files** - tracker.config and secret.config NOT in Docker image
- [ ] **Sensitive Data** - No API keys, passwords, or credentials in logs

### Quality Assurance Infrastructure

- [ ] **Pre-Commit Hook** - `.git/hooks/pre-commit` validates Python syntax before commits
- [ ] **Build Script** - `validate_and_build.sh` (local only, not in GitHub/Docker):
  - [ ] Python syntax validation works
  - [ ] Undefined function detection works
  - [ ] Unit tests run successfully
  - [ ] Docker multi-platform build succeeds
- [ ] **GitHub Actions CI** - `.github/workflows/quality-check.yml` configured to run on push/PR
- [ ] **Pre-commit Excluded** - `validate_and_build.sh` added to .gitignore
- [ ] **Docker Excluded** - `validate_and_build.sh` added to .dockerignore

---

## Deployment Checklist

### Pre-Release Preparation

#### 1. Final Code Review
- [ ] Review all commits since v0.92
- [ ] All commits production-ready (no debug code)
- [ ] Commit messages clear and descriptive
- [ ] No FIXME/TODO comments remaining
- [ ] No console.log() or print() for debugging
- [ ] All imports used (no dead imports)

#### 2. Git & GitHub
- [ ] Current branch is `main`
- [ ] All changes committed and pushed
- [ ] Create release tag: `git tag -a v0.93 -m "Release: v0.93 - Security & QA improvements"`
- [ ] Push tag: `git push origin v0.93`
- [ ] Verify tag appears on GitHub

#### 3. Docker Build Verification
```bash
# Local build
docker build -t dokwerker8891/buoy-tracker:0.93 .

# Multi-platform build (requires buildx)
docker buildx build --platform linux/amd64,linux/arm64 \
  -t dokwerker8891/buoy-tracker:0.93 \
  -t dokwerker8891/buoy-tracker:latest \
  --push .
```

- [ ] Local build succeeds without errors or warnings
- [ ] Image builds in < 10 minutes
- [ ] Image size reasonable (~300-400MB)
- [ ] Multi-platform push succeeds
- [ ] Both amd64 and arm64 manifests created

#### 4. Docker Hub Verification
- [ ] Wait 2-3 minutes for image processing
- [ ] Visit: https://hub.docker.com/r/dokwerker8891/buoy-tracker
- [ ] Verify v0.93 tag visible
- [ ] Verify latest tag updated to v0.93
- [ ] Click tag to verify both architectures present
- [ ] Test pull: `docker pull dokwerker8891/buoy-tracker:0.93`
- [ ] Test run: `docker run -p 5103:5103 dokwerker8891/buoy-tracker:0.93`

#### 5. GitHub Release Creation
- [ ] Extract v0.93 section from CHANGELOG.md
- [ ] Go to: https://github.com/guthip/buoy-tracker/releases/new
- [ ] Tag: v0.93
- [ ] Release title: "v0.93 - Security & QA improvements"
- [ ] Release notes include:
  - [ ] Executive summary
  - [ ] What's Fixed section
  - [ ] What's Added section
  - [ ] Known issues (if any)
  - [ ] Contributors
- [ ] Mark as latest release
- [ ] Publish release

---

## Deployment to Production

### Pre-Deployment Environment Check

- [ ] System has Docker & Docker Compose installed
- [ ] Sufficient disk space: `df -h` (minimum 5GB available)
- [ ] Sufficient RAM (minimum 2GB recommended)
- [ ] Network connectivity to MQTT broker (mqtt.bayme.sh:1883)
- [ ] Port 5103 available (not in use)
- [ ] System time synchronized (important for MQTT timestamps)

### Backup Current Deployment

```bash
# Backup current configuration (IMPORTANT - contains MQTT credentials)
cp tracker.config tracker.config.backup.$(date +%Y%m%d_%H%M%S)
cp secret.config secret.config.backup.$(date +%Y%m%d_%H%M%S)

# Stop current version
docker compose down
```

### Deploy v0.93

```bash
# Pull latest image
docker pull dokwerker8891/buoy-tracker:0.93

# Update docker-compose.yml if needed
# Ensure image: dokwerker8891/buoy-tracker:0.93

# Start service
docker compose up -d

# Wait for startup (5-10 seconds)
sleep 10

# Verify service
docker ps | grep buoy-tracker
docker compose logs | head -50
```

### Initial Verification (First 30 minutes)

- [ ] Container running: `docker ps` shows buoy-tracker
- [ ] No restart loops: `docker compose logs` shows clean startup
- [ ] Web interface accessible: `curl http://localhost:5103`
- [ ] API responding: `curl http://localhost:5103/api/status`
- [ ] No 404 or 500 errors
- [ ] MQTT connection attempted: Check logs for "MQTT broker"
- [ ] No permission errors in logs
- [ ] Map displaying correctly (check http://localhost:5103 in browser)

### 24-Hour Monitoring

- [ ] New MQTT packets being received
- [ ] Nodes appearing on map as packets arrive
- [ ] Position history accumulating
- [ ] Signal data (RSSI/SNR) displaying correctly
- [ ] CPU usage stable (< 50%)
- [ ] Memory usage stable (< 500MB)
- [ ] No memory leaks over 24 hours
- [ ] Container still running (no restart loops)
- [ ] Disk space usage stable
- [ ] Response times acceptable (< 500ms)

---

## Deployment Type Configuration

**Before deployment, select the deployment type and configure accordingly:**

### Development (Local Machine / Testing)
```
log_level = DEBUG
show_controls_menu = true
enable_persistence = true
```

### Staging (Internal Team / QA)
```
log_level = INFO
show_controls_menu = true
enable_persistence = false
show_all_nodes = true
```

### Production (Live Deployment / Public Access)
```
log_level = WARNING
show_controls_menu = false
enable_persistence = false
show_all_nodes = false
show_gateways = false (optional)
show_position_trails = true
trail_history_hours = 24
```

### Public Display / Monitor (Kiosk)
```
log_level = ERROR
show_controls_menu = false
show_all_nodes = false
show_gateways = false
show_position_trails = true
trail_history_hours = 12
alerts.enabled = false
```

---

## Quality Assurance Infrastructure

### Pre-Commit Validation

**Location:** `.git/hooks/pre-commit`

Automatically validates Python syntax before each commit. Prevents syntax errors from being committed.

```bash
git add src/mqtt_handler.py
git commit -m "Fix MQTT bug"
# Pre-commit hook runs automatically and validates
```

To skip (not recommended):
```bash
git commit --no-verify -m "Skip validation"
```

### Build Validation Script

**Location:** `validate_and_build.sh` (local only, not in GitHub or Docker)

Comprehensive validation pipeline before production deployment.

**Steps:**
1. Python syntax validation
2. Undefined function detection
3. Unit test execution
4. Multi-platform Docker build and push

**Usage:**
```bash
./validate_and_build.sh
```

**When to use:** Before any production deployment

### GitHub Actions Continuous Integration

**Location:** `.github/workflows/quality-check.yml`

Automated quality checks on every push to main and all pull requests.

**What it checks:**
- Python syntax validation
- Undefined function detection
- Unit test execution
- Automated reporting to GitHub

**View results:** GitHub → Repository → Actions → Latest workflow run

---

## Troubleshooting

### Common Issues

**Web interface not accessible**
```bash
# Check container status
docker ps | grep buoy-tracker

# Check logs
docker compose logs

# Check port binding
docker port buoy-tracker

# Restart if needed
docker compose restart
```

**MQTT connection not working**
```bash
# Check logs for MQTT errors
docker compose logs | grep -i mqtt

# Verify broker connectivity
telnet mqtt.bayme.sh 1883
```

**Tests failing**
```bash
# Run with verbose output
python3 -m pytest tests/ -v --tb=long

# Run specific test
python3 -m pytest tests/test_main.py::test_name -v
```

**Docker build fails**
```bash
# Check Dockerfile syntax
docker build --no-cache -t test:latest .

# View build logs
docker buildx build --progress=plain .
```

**Permission denied errors in container**
```bash
# Check file permissions
ls -la src/ templates/ static/

# Verify Dockerfile sets permissions correctly
grep -A2 "COPY\|RUN chmod" Dockerfile
```

---

## Rollback Plan

### When to Rollback

- Critical bug prevents core functionality
- Data loss or corruption
- Security vulnerability discovered
- Significant performance degradation
- Compatibility issues

### Rollback Execution

```bash
# Stop current version
docker compose down

# Archive problematic data
mv data/ data.v0.93.$(date +%Y%m%d_%H%M%S)/

# Pull previous version
docker pull dokwerker8891/buoy-tracker:v0.92

# Update docker-compose.yml to use v0.92
# Start previous version
docker compose up -d

# Verify
docker compose logs | head -50
curl http://localhost:5103/api/status
```

### After Rollback

1. Document issue that caused rollback
2. Create GitHub issue describing problem
3. Plan fix for next iteration
4. Keep v0.93 image on Docker Hub (don't delete)
5. Notify team of rollback

---

## Key Contacts & Resources

- **GitHub Repository**: https://github.com/guthip/buoy-tracker
- **Docker Hub**: https://hub.docker.com/r/dokwerker8891/buoy-tracker
- **MQTT Broker**: mqtt.bayme.sh:1883
- **Quick Start Guide**: QUICKSTART.md
- **Docker Guide**: DOCKER.md
- **Security Documentation**: SECURITY.md
- **Full README**: README.md

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.93 | 2025-12-07 | Security fixes, QA infrastructure, bug fixes |
| 0.92 | 2025-12-02 | Gateway quality filtering, performance optimization |
| 0.91 | Earlier | Previous release |

---

## Quick Commands Reference

```bash
# Check service status
docker ps

# View logs
docker compose logs -f

# Restart service
docker compose restart

# Stop service
docker compose down

# Start service
docker compose up -d

# Resource usage
docker stats buoy-tracker --no-stream

# Execute command in container
docker compose exec -it buoy-tracker bash

# Check API
curl http://localhost:5103/api/status

# Run tests
python3 -m pytest tests/ -v

# Validate syntax
python3 -m py_compile src/*.py tests/*.py

# Full build validation
./validate_and_build.sh
```

---

**Last Updated:** December 7, 2025  
**For questions or issues:** See TROUBLESHOOTING section or GitHub Issues
