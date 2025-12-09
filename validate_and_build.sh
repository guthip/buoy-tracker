#!/bin/bash
# Validation and build script for Buoy Tracker
# Ensures code quality and version consistency before building and pushing Docker images

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  Buoy Tracker Build Validation"
echo "=========================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Extract version from tracker.config.template (source of truth)
VERSION=$(grep "^version = " tracker.config.template | head -1 | cut -d= -f2 | xargs)
echo "ℹ️  Detected version: $VERSION"
echo ""

# Step 1: Version Consistency Check
echo "📋 Step 1: Version Consistency Check"
echo "   Verifying all version references match..."

CONFIG_VERSION=$(grep "^version = " tracker.config.template | head -1 | cut -d= -f2 | xargs)
LOCAL_VERSION=$(grep "^version = " tracker.config.local | head -1 | cut -d= -f2 | xargs)
REMOTE_VERSION=$(grep "^version = " tracker.config.remote | head -1 | cut -d= -f2 | xargs)
DOCKERFILE_VERSION=$(grep "^ARG APP_VERSION=" Dockerfile | cut -d= -f2 | xargs)

echo "     tracker.config.template: v${CONFIG_VERSION}"
echo "     tracker.config.local:     v${LOCAL_VERSION}"
echo "     tracker.config.remote:    v${REMOTE_VERSION}"
echo "     Dockerfile:               v${DOCKERFILE_VERSION}"

if [ "$CONFIG_VERSION" != "$LOCAL_VERSION" ] || \
   [ "$CONFIG_VERSION" != "$REMOTE_VERSION" ] || \
   [ "$CONFIG_VERSION" != "$DOCKERFILE_VERSION" ]; then
    echo -e "${RED}   ❌ VERSION MISMATCH${NC}"
    echo ""
    echo "All version references must match. Update these files to v${CONFIG_VERSION}:"
    [ "$LOCAL_VERSION" != "$CONFIG_VERSION" ] && echo "     - tracker.config.local"
    [ "$REMOTE_VERSION" != "$CONFIG_VERSION" ] && echo "     - tracker.config.remote"
    [ "$DOCKERFILE_VERSION" != "$CONFIG_VERSION" ] && echo "     - Dockerfile (ARG APP_VERSION)"
    exit 1
else
    echo -e "${GREEN}   ✓ All versions match: v${CONFIG_VERSION}${NC}"
fi
echo ""

# Step 2: Syntax validation
echo "📋 Step 2: Python Syntax Validation"
echo "   Checking all Python files..."
if python3 -m py_compile src/*.py tests/*.py 2>&1 | grep -q "SyntaxError"; then
    echo -e "${RED}   ❌ Syntax errors found!${NC}"
    python3 -m py_compile src/*.py tests/*.py
    exit 1
else
    echo -e "${GREEN}   ✓ All Python files valid${NC}"
fi
echo ""

# Step 3: Check for undefined functions
echo "📋 Step 3: Undefined Function Detection"
echo "   Scanning for common undefined patterns..."

# List of functions to check
UNDEFINED_CHECKS=(
    "reconnect_mqtt"
    "undefined_function"
)

ISSUES_FOUND=0
for check in "${UNDEFINED_CHECKS[@]}"; do
    if grep -r "$check" src/*.py 2>/dev/null | grep -v "^Binary"; then
        echo -e "${YELLOW}   ⚠ Found: $check${NC}"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
    fi
done

if [ $ISSUES_FOUND -gt 0 ]; then
    echo -e "${RED}   ❌ $ISSUES_FOUND undefined function(s) found!${NC}"
    exit 1
else
    echo -e "${GREEN}   ✓ No undefined function calls detected${NC}"
fi
echo ""

# Step 4: Run unit tests
echo "📋 Step 4: Unit Tests"
echo "   Running pytest..."
if [ -d "tests" ] && [ "$(ls -A tests/*.py 2>/dev/null)" ]; then
    if python3 -m pytest tests/ -v --tb=short 2>&1 | tee /tmp/pytest.log | grep -q "passed\|PASSED"; then
        PASS_COUNT=$(grep -c "PASSED\|passed" /tmp/pytest.log || echo "0")
        echo -e "${GREEN}   ✓ Tests passed ($PASS_COUNT)${NC}"
    else
        echo -e "${RED}   ❌ Some tests failed!${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}   ⚠ No tests found (skipping)${NC}"
fi
echo ""

# Step 5: Build Docker image
echo "📋 Step 5: Docker Build & Push"
echo "   Building for platforms: amd64, arm64"
echo "   Tags: $VERSION, latest"
echo ""
echo -e "${YELLOW}   ⚠  This will push to Docker Hub${NC}"
echo "   Continue? (Press Enter to continue, Ctrl+C to cancel)"
read -r

if docker buildx build --platform linux/amd64,linux/arm64 \
    -t dokwerker8891/buoy-tracker:${VERSION} \
    -t dokwerker8891/buoy-tracker:latest \
    --push .; then
    echo -e "${GREEN}   ✓ Docker build and push successful${NC}"
else
    echo -e "${RED}   ❌ Docker build failed!${NC}"
    exit 1
fi
echo ""

# Step 6: Create GitHub release
echo "📋 Step 6: Creating GitHub Release"
if command -v gh &> /dev/null; then
    echo "   Creating release v${VERSION}..."
    
    # Extract changelog entry for this version
    CHANGELOG_ENTRY=$(sed -n "/## \[.*\] - v${VERSION}/,/## \[.*\] - v[0-9]/p" CHANGELOG.md | head -n -1)
    
    if gh release create "v${VERSION}" \
        --title "v${VERSION}: Release" \
        --notes "${CHANGELOG_ENTRY}" 2>/dev/null; then
        echo -e "${GREEN}   ✓ GitHub release created${NC}"
    else
        echo -e "${YELLOW}   ⚠  Release may already exist or GitHub CLI not configured${NC}"
    fi
else
    echo -e "${YELLOW}   ⚠  GitHub CLI (gh) not found - skipping release creation${NC}"
    echo "     Install with: brew install gh"
    echo "     Or manually create release at: https://github.com/guthip/buoy-tracker/releases/new?tag=v${VERSION}"
fi
echo ""

echo "=========================================="
echo -e "${GREEN}✓ All validation checks passed!${NC}"
echo "=========================================="
echo ""
echo "Release complete:"
echo "  - GitHub: https://github.com/guthip/buoy-tracker/releases/tag/v${VERSION}"
echo "  - Docker Hub: dokwerker8891/buoy-tracker:${VERSION}"
echo "  - Docker latest: dokwerker8891/buoy-tracker:latest"
echo "  - Platforms: linux/amd64, linux/arm64"
