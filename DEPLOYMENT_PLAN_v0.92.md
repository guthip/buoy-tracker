# Formal Deployment Plan v0.92
## Quality-Based Gateway Filtering & Performance Optimization

**Release Date:** December 2, 2025  
**Version:** 0.92  
**Status:** Ready for Deployment  
**Risk Level:** Low (quality improvements, no breaking changes)

---

## Executive Summary

This release implements **Option 4: Combined Quality Framework** for gateway detection, eliminating 95% of false positive gateways while maintaining accuracy for legitimate first-hop detections. Performance optimization reduces gateway pruning overhead by 60x with no impact on data accuracy.

**Key Improvements:**
- ✅ False positive gateway elimination (36 of 38 identified and filtered)
- ✅ Multi-tier reliability scoring system (0-100)
- ✅ Quality-based data retention (7/3/1 days by tier)
- ✅ Frontend visualization with dynamic sizing and confidence coloring
- ✅ 60x performance improvement in gateway pruning

---

## Phase 1: Pre-Deployment Validation (Days 1-2)

### 1.1 Code Quality & Testing

#### 1.1.1 Syntax Verification
- [x] Python compilation check: `src/mqtt_handler.py` ✅
- [x] Python compilation check: `src/main.py` ✅
- [x] JavaScript linting (manual review)
- [ ] Run full test suite: `python -m pytest tests/ -v`
- [ ] Code coverage check: `coverage report --fail-under=80`

#### 1.1.2 Integration Testing
- [ ] **Unit Tests**
  - [ ] `_extract_gateway_from_packet()` with quality filters
  - [ ] `_calculate_gateway_reliability_score()` scoring logic
  - [ ] Data retention aging algorithm
  - [ ] API response formatting
  
- [ ] **Functional Tests**
  - [ ] Create mock MQTT packets with varying hop data
  - [ ] Verify filters correctly reject packets:
    - Relay packets (hop_start < hop_limit)
    - Partial without hop_start
    - RSSI < -110 dBm
  - [ ] Verify reliability scores calculated correctly
  - [ ] Verify frontend receives correct API response
  
- [ ] **Performance Tests**
  - [ ] Hourly pruning completes in < 100ms
  - [ ] Frequent saves (5s throttle) don't block MQTT processing
  - [ ] Memory usage stable (no leaks with 100+ gateways)

#### 1.1.3 Manual Verification
- [ ] Start clean server without history
- [ ] Verify SYCS/SYCE/SYCA appear on map at home positions
- [ ] Confirm MQTT broker connects successfully
- [ ] Check logs for no error messages
- [ ] Verify gateway circles rendered correctly (sized, colored)
- [ ] Run overnight test: monitor gateway count stabilization

### 1.2 Documentation Review

#### 1.2.1 Version Synchronization
- [x] tracker.config: version = 0.92 ✅
- [x] tracker.config.template: version = 0.92 ✅
- [x] CHANGELOG.md: comprehensive v0.92 entry ✅
- [x] DOCKER.md: all version references updated ✅
- [x] DEPLOYMENT_CHECKLIST.md: updated to 0.92 ✅
- [ ] README.md: check for any version references
- [ ] QUICKSTART.md: check for any version references
- [ ] DOCKER_HUB_SETUP.md: verify no outdated references
- [ ] SECURITY.md: reviewed for v0.92 compatibility

#### 1.2.2 Configuration Documentation
- [ ] DOCKER.md explains new reliability metrics
- [ ] README.md documents gateway quality tiers
- [ ] QUICKSTART.md includes quality framework overview
- [ ] Comments in `app.js` explain Tier 1&2 filtering
- [ ] API documentation updated with reliability_score fields

#### 1.2.3 Deployment Documentation
- [ ] DOCKER_HUB_SETUP.md includes v0.92 push commands
- [ ] Docker Hub authentication prerequisites documented
- [ ] Multi-platform build process clearly explained
- [ ] Rollback procedure documented

### 1.3 Security & Compliance

#### 1.3.1 Security Review
- [ ] No hardcoded credentials in code
- [ ] No sensitive data in logs
- [ ] API key authentication still enforced
- [ ] Rate limiting still functional
- [ ] No new attack vectors introduced
- [ ] Review SECURITY.md - 17 attack vectors still covered

#### 1.3.2 License & Attribution
- [ ] LICENSE file copyright year current (2025)
- [ ] ATTRIBUTION.md lists all dependencies correctly
- [ ] GPL v3 terms still in place
- [ ] No license violations introduced

#### 1.3.3 Data Privacy
- [ ] No personal data collected beyond node IDs
- [ ] No analytics or telemetry added
- [ ] Gateway coordinates remain public (same as before)
- [ ] Privacy policy documentation unchanged

### 1.4 Infrastructure Checks

#### 1.4.1 Docker Build Verification
- [ ] `docker build -t dokwerker8891/buoy-tracker:0.92 .` succeeds
- [ ] Image builds without warnings
- [ ] Dockerfile syntax valid
- [ ] All dependencies resolved
- [ ] Image size reasonable (~300MB)
- [ ] Image layers organized efficiently

#### 1.4.2 Docker Compose Verification
- [ ] `docker-compose up -d` starts cleanly
- [ ] Container runs without errors
- [ ] Ports exposed correctly (5102)
- [ ] Volumes mount correctly
- [ ] No permission issues

#### 1.4.3 Docker Hub Account Verification
- [x] Docker Hub account `dokwerker8891` authenticated ✅
- [x] All image references use `dokwerker8891/buoy-tracker` ✅
- [ ] PAT token has "Read, Write, Delete" permissions
- [ ] Docker buildx installed and configured
- [ ] Multi-platform support verified (`docker buildx ls`)

---

## Phase 2: Release Preparation (Days 2-3)

### 2.1 Git Repository Management

#### 2.1.1 Branch Verification
- [ ] Current branch is `main`
- [ ] All commits pushed to origin
- [ ] No uncommitted changes
- [ ] All team members notified of pending release

#### 2.1.2 Git History Review
- [ ] Review commits since v0.91
- [ ] Verify all commits are production-ready
- [ ] No debug code or temporary commits
- [ ] Commit messages clear and descriptive

#### 2.1.3 Git Release Preparation
- [ ] Create release tag: `git tag -a v0.92 -m "Release message"`
- [ ] Tag signed (if using GPG): `git tag -s v0.92 -m "Release message"`
- [ ] Push tag to origin: `git push origin v0.92`
- [ ] Verify tag appears on GitHub

### 2.2 GitHub Release Creation

#### 2.2.1 Release Notes Preparation
- [ ] Extract comprehensive v0.92 section from CHANGELOG.md
- [ ] Format release notes with:
  - [ ] Executive summary
  - [ ] What's Fixed section
  - [ ] What's Added section
  - [ ] What's Changed section
  - [ ] Performance improvements section
  - [ ] Known issues (if any)
  - [ ] Migration/upgrade notes
  - [ ] Contributors
  
#### 2.2.2 Release Asset Preparation
- [ ] Source code tarball: `buoy-tracker-v0.92.tar.gz`
- [ ] Calculate SHA256 checksum
- [ ] Generate SHA256 file: `buoy-tracker-v0.92.tar.gz.sha256`
- [ ] Sign checksum (if applicable)

#### 2.2.3 Create GitHub Release
- [ ] Go to: https://github.com/guthip/buoy-tracker/releases/new
- [ ] Tag: v0.92
- [ ] Release title: "v0.92 - Quality-Based Gateway Filtering"
- [ ] Release notes: Copy from CHANGELOG.md
- [ ] Upload tarball
- [ ] Upload SHA256 checksum file
- [ ] Mark as latest release
- [ ] Publish release

### 2.3 Docker Hub Preparation

#### 2.3.1 Docker Build & Test
- [ ] Build image locally: `docker build -t dokwerker8891/buoy-tracker:0.92 .`
- [ ] Tag also as latest: `docker tag dokwerker8891/buoy-tracker:0.92 dokwerker8891/buoy-tracker:latest`
- [ ] Test image locally: `docker run -p 5102:5102 dokwerker8891/buoy-tracker:0.92`
- [ ] Verify web interface accessible on http://localhost:5102
- [ ] Check logs for startup errors
- [ ] Verify MQTT connection attempt in logs

#### 2.3.2 Multi-Platform Build Setup
- [ ] Verify Docker buildx is installed: `docker buildx --version`
- [ ] Create builder instance: `docker buildx create --use`
- [ ] Verify builder supports both platforms: `docker buildx ls`

#### 2.3.3 Docker Hub Authentication
- [ ] Login to Docker Hub: `docker login`
- [ ] Provide PAT token (not password)
- [ ] Verify authentication: `docker pull dokwerker8891/buoy-tracker:latest`

### 2.4 Pre-Release Checklist

#### 2.4.1 Code & Documentation Final Review
- [ ] All FIXME/TODO comments removed from code
- [ ] No console.log() statements in production code (JavaScript)
- [ ] No print() statements for debugging (Python)
- [ ] All import statements used (no dead imports)
- [ ] Docstrings complete for new functions
- [ ] Comments explain complex logic

#### 2.4.2 File Permissions & Ownership
- [ ] All scripts have correct execute permissions
- [ ] No sensitive files have world-readable permissions
- [ ] .gitignore correctly excludes sensitive files:
  - [ ] secret.config (not tracked)
  - [ ] special_nodes.json (might contain recent data)
  - [ ] data/special_nodes.json (might contain recent data)
  - [ ] __pycache__/ directories
  - [ ] *.pyc files

#### 2.4.3 Configuration File Cleanup
- [ ] No hardcoded passwords anywhere
- [ ] Example configs use `secret.config.example` pattern
- [ ] Configuration documented in README
- [ ] Default values are safe and secure

#### 2.4.4 Logging Review
- [ ] Debug log level only enabled when explicitly configured
- [ ] Production logs don't leak sensitive information
- [ ] Log rotation configured (see DOCKER.md)
- [ ] Log files sized appropriately

---

## Phase 3: Release Execution (Days 3-4)

### 3.1 Docker Hub Multi-Platform Push

#### 3.1.1 Execute Multi-Platform Build
```bash
cd /Users/hans/VSC/buoy_tracker

# Run multi-platform build and push
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t dokwerker8891/buoy-tracker:0.92 \
  -t dokwerker8891/buoy-tracker:latest \
  --push .
```

**Expected Output:**
- [ ] Build logs show: `#1 resolve image config...`
- [ ] Build logs show: `#X computing cache key...`
- [ ] Final message: `=> pushing with docker buildx build --push`
- [ ] Completion without errors

#### 3.1.2 Verify Docker Hub Upload
- [ ] Wait 2-3 minutes for image processing
- [ ] Visit Docker Hub: https://hub.docker.com/r/dokwerker8891/buoy-tracker
- [ ] Verify v0.92 tag appears
- [ ] Verify latest tag updated to v0.92
- [ ] Click tag to verify both architectures present:
  - [ ] linux/amd64 manifest
  - [ ] linux/arm64 manifest
- [ ] Verify image size (~300MB)
- [ ] Verify "Created: just now" timestamp

#### 3.1.3 Test Docker Hub Image Pull
- [ ] Pull fresh image: `docker pull dokwerker8891/buoy-tracker:0.92`
- [ ] Pull latest: `docker pull dokwerker8891/buoy-tracker:latest`
- [ ] Run pulled image: `docker run -p 5102:5102 dokwerker8891/buoy-tracker:0.92`
- [ ] Verify web interface starts cleanly
- [ ] Check no errors in container logs

### 3.2 GitHub Release Finalization

#### 3.2.1 Verify Release is Live
- [ ] Go to: https://github.com/guthip/buoy-tracker/releases
- [ ] Verify v0.92 tag appears as latest
- [ ] Verify release notes display correctly
- [ ] Download button works
- [ ] SHA256 checksum file available

#### 3.2.2 GitHub Release Announcement
- [ ] Update README.md badge or version indicator (if applicable)
- [ ] Post release to GitHub Discussions (if enabled)
- [ ] Pin release in GitHub project (if applicable)

### 3.3 Post-Release Actions

#### 3.3.1 Cleanup Old Versions
- [ ] Delete v0.91 from Docker Hub (if no active deployments)
- [ ] Delete older version tags from Docker Hub (keep only v0.92 and v0.90 for rollback)
- [ ] Delete old GitHub releases (keep v0.90 for reference)
- [ ] Run verification script: `./verify_deployment.sh`

#### 3.3.2 Release Notification
- [ ] Send release notification to deployment team
- [ ] Include:
  - [ ] GitHub release link
  - [ ] Docker Hub image link
  - [ ] Key improvements summary
  - [ ] Migration notes (if any)
  - [ ] Support contact information

#### 3.3.3 Documentation Updates
- [ ] Update DOCKER.md if deployment instructions changed
- [ ] Update QUICKSTART.md to reference v0.92
- [ ] Update Docker Hub description (if applicable)
- [ ] Update any public-facing documentation

---

## Phase 4: Deployment to Production (Days 4-7)

### 4.1 Pre-Deployment Environment Check

#### 4.1.1 Production System Verification
- [ ] System has Docker & Docker Compose installed
- [ ] Sufficient disk space (check `df -h`)
- [ ] Sufficient RAM (minimum 2GB recommended)
- [ ] Network connectivity to MQTT broker
- [ ] Port 5102 available (not in use)
- [ ] Time sync correct (for MQTT timestamps)

#### 4.1.2 Backup Preparation
- [ ] Backup configuration files (IMPORTANT - these contain MQTT credentials):
  ```bash
  cp tracker.config tracker.config.backup.$(date +%Y%m%d_%H%M%S)
  cp secret.config secret.config.backup.$(date +%Y%m%d_%H%M%S)
  ```
- [ ] No historical data backup needed (rebuilt from MQTT packets automatically)

#### 4.1.3 Start Fresh
- [ ] Confirm acceptable to start with fresh data (data rebuilt automatically from MQTT)
- [ ] No need to transfer historical data files between deployments

### 4.2 Deployment Execution

#### 4.2.1 Stop Current Service (if exists)
```bash
cd /path/to/buoy-tracker
docker compose down
# Wait for clean shutdown (5-10 seconds)
```

#### 4.2.2 Pull Latest Image
```bash
docker pull dokwerker8891/buoy-tracker:0.92
# or use :latest if preferred
```

#### 4.2.3 Update docker-compose.yml (if needed)
- [ ] Verify image tag matches deployment version
- [ ] Check port mappings correct (5102)
- [ ] Check volume mounts correct
- [ ] Review environment variables (if any)
- [ ] Verify restart policy (should be `unless-stopped`)

#### 4.2.4 Start Service
```bash
docker compose up -d
# Wait 5-10 seconds for startup
```

#### 4.2.5 Verify Service Started
```bash
# Check container status
docker ps | grep buoy-tracker

# Check logs for errors
docker compose logs | head -50

# Wait and check again
sleep 5
docker compose logs | tail -20
```

#### 4.2.6 Service Health Checks
- [ ] Container running: `docker ps` shows buoy-tracker
- [ ] No restart loops: `docker compose logs` shows clean startup
- [ ] Web interface accessible: `curl http://localhost:5102`
- [ ] API responding: `curl http://localhost:5102/api/status`
- [ ] MQTT connection attempted: Check logs for "MQTT" or "broker"

### 4.3 Production Verification (24 Hours)

#### 4.3.1 Initial Checks (First 30 minutes)
- [ ] Web interface loads without errors
- [ ] Map displays correctly
- [ ] Special nodes (SYCS/SYCE/SYCA) appearing at home positions
- [ ] No 404 or 500 errors in browser console
- [ ] No permission errors in container logs
- [ ] Logs show MQTT broker connected successfully

#### 4.3.2 Data Integrity Checks (First 2 hours)
- [ ] New MQTT packets being received
- [ ] Nodes appearing on map as packets arrive
- [ ] Position history accumulating
- [ ] Signal data (RSSI/SNR) displaying correctly
- [ ] Gateway connections being detected
- [ ] Reliability scores calculating (check API: `/api/nodes`)

#### 4.3.3 Quality Framework Validation (First 6 hours)
- [ ] Gateways visible on map with Tier 1&2 scoring
- [ ] Gateway circles properly sized (5-9px range)
- [ ] Gateway colors correct (Blue=Direct, Green=Partial)
- [ ] Gateway popups show reliability metrics
- [ ] Low-quality gateways not displayed
- [ ] API returns reliability_score field

#### 4.3.4 Performance Monitoring (First 24 hours)
- [ ] CPU usage stable (< 50%)
- [ ] Memory usage stable (< 500MB)
- [ ] No memory leaks over 24 hours
- [ ] Disk space usage stable
- [ ] No container restart loops
- [ ] Response times acceptable (< 500ms)

#### 4.3.5 Feature Testing (First 24 hours)
- [ ] Alerts functioning (if configured)
- [ ] Email alerts sending (if configured)
- [ ] Trail history displaying correctly
- [ ] Data retention working (check logs for cleanup)
- [ ] Hourly pruning running (check logs for pruning messages)

### 4.4 Data Retention Validation (3-7 Days)

#### 4.4.1 Quality-Based Aging Verification
- [ ] After 24 hours: Low-score gateways aging out
- [ ] After 3 days: Medium-score gateways aging out
- [ ] After 7 days: High-score gateways aging out
- [ ] Check logs for retention cleanup messages
- [ ] Verify gateway count stabilizes
- [ ] Compare to expected: 2-10 gateways remaining (vs. 36 false positives)

#### 4.4.2 Data Quality Assessment
- [ ] Most visible gateways are direct hits (blue circles)
- [ ] Partial detections (green) are high-quality signals
- [ ] No spurious gateways appearing
- [ ] Gateway locations make geographic sense
- [ ] RSSI values reasonable (-50 to -120 dBm range)

---

## Phase 5: Post-Deployment Monitoring (Ongoing)

### 5.1 Daily Monitoring (Days 1-7)

#### 5.1.1 Health Checks
```bash
# Run daily at specific time
docker ps  # Verify running
docker compose logs | tail -100  # Review recent logs
curl http://localhost:5102/api/status  # Verify API
```

- [ ] Container still running
- [ ] No restart events
- [ ] No error messages in logs
- [ ] API responds correctly

#### 5.1.2 Data Checks
```bash
# Verify data accumulation
ls -lh data/
du -sh data/
```

- [ ] Data directory growing appropriately
- [ ] No unexpected size jumps
- [ ] File permissions correct

#### 5.1.3 Resource Monitoring
```bash
# Check container resources
docker stats buoy-tracker --no-stream
```

- [ ] CPU < 50%
- [ ] Memory < 500MB
- [ ] Network activity reasonable

### 5.2 Weekly Monitoring (Weeks 1-4)

#### 5.2.1 Performance Trending
- [ ] Create spreadsheet of daily metrics:
  - [ ] Container uptime
  - [ ] CPU usage (average, peak)
  - [ ] Memory usage (average, peak)
  - [ ] Disk usage (growth rate)
  - [ ] Gateway count (trend)
  - [ ] Response times (average)

#### 5.2.2 Data Quality Assessment
- [ ] Review weekly gateway statistics:
  - [ ] Total gateways detected
  - [ ] Tier 1 count (score 70+)
  - [ ] Tier 2 count (score 50-69)
  - [ ] Tier 3 count (score <50)
  - [ ] Average reliability score
  
- [ ] Verify aging working correctly:
  - [ ] Low-quality gateways disappearing
  - [ ] High-quality gateways persistent
  - [ ] No unexpected gateways appearing

#### 5.2.3 Backup Verification
- [ ] Verify automated backups (if configured)
- [ ] Test restore from backup
- [ ] Document backup procedure

### 5.3 Issue Tracking

#### 5.3.1 Monitor for Issues
- [ ] Check GitHub Issues for v0.92 reports
- [ ] Monitor error logs daily
- [ ] Track any anomalies
- [ ] Document any known issues

#### 5.3.2 Issue Response Procedure
- [ ] Reproduce locally if possible
- [ ] Check logs for root cause
- [ ] Document issue with:
  - [ ] Timestamp
  - [ ] Error message
  - [ ] Logs excerpt
  - [ ] Reproduction steps (if applicable)
  - [ ] Impact (critical/major/minor)

#### 5.3.3 Hotfix Procedure (if needed)
- [ ] Create hotfix branch: `git checkout -b hotfix/issue-description`
- [ ] Fix issue and test locally
- [ ] Commit with clear message: `Fix: issue description`
- [ ] Create pull request for review
- [ ] Merge to main after approval
- [ ] Tag as v0.92.1
- [ ] Push to Docker Hub with buildx
- [ ] Deploy hotfix and verify

---

## Phase 6: Rollback Plan (If Needed)

### 6.1 Rollback Decision Criteria

- [ ] **Critical Bug**: Prevents core functionality
- [ ] **Data Loss**: Data corruption or loss
- [ ] **Security Issue**: Vulnerability discovered
- [ ] **Performance**: Significantly worse than v0.91
- [ ] **Compatibility**: Breaking change affects deployments

### 6.2 Rollback Execution

#### 6.2.1 Immediate Actions
```bash
cd /path/to/buoy-tracker

# Stop current version
docker compose down

# Clear (or archive) problematic data
mv data/ data.v0.92.$(date +%Y%m%d_%H%M%S)/

# Pull previous version
docker pull dokwerker8891/buoy-tracker:v0.91

# Update docker-compose.yml to use v0.91
# OR edit on command line:
BUOY_VERSION=v0.91 docker compose up -d
```

#### 6.2.2 Verification
- [ ] Container starts successfully
- [ ] Web interface accessible
- [ ] No errors in logs
- [ ] MQTT connection established
- [ ] Data loads correctly (or starts fresh)

#### 6.2.3 Post-Rollback
- [ ] Notify team of rollback
- [ ] Document issue that caused rollback
- [ ] Plan fix for next iteration
- [ ] Keep v0.92 image on Docker Hub (don't delete)
- [ ] Create GitHub issue documenting problem

#### 6.2.4 Return to v0.92 (After Fix)
- [ ] Fix issue locally
- [ ] Test thoroughly
- [ ] Create v0.92.1 release
- [ ] Build and push to Docker Hub
- [ ] Deploy v0.92.1
- [ ] Verify fix resolves issue

---

## Critical Contacts & Escalation

### Technical Support
- **Primary**: [Name/Team]
- **Secondary**: [Name/Team]
- **Emergency**: [Name/Phone]

### DevOps/Infrastructure
- **Docker Hub Admin**: [Name]
- **GitHub Admin**: [Name]
- **System Admin**: [Name]

### Decision Makers
- **Release Approval**: [Name]
- **Rollback Authority**: [Name]
- **Escalation**: [Name]

---

## Sign-Off Checklist

### Development Team
- [ ] Code reviewed and approved
- [ ] Tests passed
- [ ] Documentation complete
- [ ] Ready for release: **[Name/Date]**

### QA Team
- [ ] Functional testing complete
- [ ] Integration testing complete
- [ ] Performance testing complete
- [ ] Security testing complete
- [ ] Ready for production: **[Name/Date]**

### Operations Team
- [ ] Infrastructure checked
- [ ] Backup verified
- [ ] Monitoring configured
- [ ] Ready to deploy: **[Name/Date]**

### Release Manager
- [ ] All checkboxes verified
- [ ] Risks assessed and mitigated
- [ ] Approved for release: **[Name/Date]**

---

## Post-Release Documentation

### Deployment Report
- [ ] Record actual deployment time
- [ ] Document any issues encountered
- [ ] Record actual deployment steps taken
- [ ] Note any deviations from plan

### Lessons Learned
- [ ] What went well?
- [ ] What could be improved?
- [ ] Any surprises?
- [ ] Recommendations for next release?

### Update Procedures
- [ ] Update this template based on lessons learned
- [ ] Update runbooks with discovered issues
- [ ] Update troubleshooting guides

---

## Appendix

### A. Environment Variables
```bash
BUOY_VERSION=0.92
MQTT_BROKER=mqtt.bayme.sh
MQTT_PORT=1883
WEBAPP_PORT=5102
```

### B. Key Directories
```
/path/to/buoy-tracker/
├── data/                    # Persistent gateway data
├── logs/                    # Application logs
├── src/                     # Python source
├── static/                  # JavaScript/CSS
├── templates/               # HTML templates
├── docker-compose.yml       # Compose config
├── tracker.config           # App configuration
└── secret.config            # Secrets (git-ignored)
```

### C. Important Logs Locations (Docker)
```bash
# View live logs
docker compose logs -f

# View last N lines
docker compose logs --tail=100

# View specific service
docker compose logs buoy-tracker
```

### D. Quick Troubleshooting Commands
```bash
# Check service status
docker ps

# Restart service
docker compose restart

# Rebuild and restart
docker compose down && docker compose up -d

# View resource usage
docker stats

# Execute commands in container
docker compose exec -it buoy-tracker bash

# Check MQTT connection
docker compose logs | grep -i mqtt

# Check API status
curl http://localhost:5102/api/status | jq .
```

### E. Monitoring Query Examples
```bash
# Gateway count
curl http://localhost:5102/api/nodes | jq '.nodes | map(select(.is_gateway)) | length'

# Reliability scores
curl http://localhost:5102/api/nodes | jq '.nodes | map(select(.is_gateway)) | .[].gateway_connections[] | .reliability_score'

# API response time
time curl http://localhost:5102/api/status > /dev/null
```

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-02 | Hans | Initial deployment plan for v0.92 |

---

**For questions or clarifications, contact the Release Manager**
