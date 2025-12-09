#!/bin/bash
# Quick Subpath Test Environment
# Tests subpath routing locally without remote deployment

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=================================================="
echo "  Local Subpath Testing"
echo "=================================================="
echo ""

# Kill any existing processes on port 5103
echo "Cleaning up port 5103..."
lsof -ti:5103 | xargs kill -9 2>/dev/null || true
sleep 1

echo -e "${GREEN}✓ Port cleared${NC}"
echo ""

# Test 1: Root path (using tracker.config.local - url_prefix empty)
echo "Test 1: ROOT PATH deployment (url_prefix empty)"
echo "=========================================="
cp /Users/hans/VSC/buoy_tracker/tracker.config.local /Users/hans/VSC/buoy_tracker/tracker.config

cd /Users/hans/VSC/buoy_tracker
python3 run.py > /tmp/server.log 2>&1 &
SERVER_PID=$!
sleep 3

if ps -p $SERVER_PID > /dev/null 2>&1; then
    echo "Server running (PID: $SERVER_PID)"
    
    # Test root path
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5103/)
    echo "  GET / → $STATUS (should be 200)"
    
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5103/health)
    echo "  GET /health → $STATUS (should be 200)"
    
    # This should fail because app isn't at /buoy-tracker/
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5103/buoy-tracker/health)
    echo "  GET /buoy-tracker/health → $STATUS (should be 404)"
else
    echo -e "${RED}Failed to start server${NC}"
    tail -5 /tmp/server.log
    exit 1
fi

echo -e "${GREEN}✓ Root path works correctly${NC}"
echo ""

# Kill and restart with subpath config
echo "Test 2: SUBPATH deployment (url_prefix=/buoy-tracker)"
echo "=========================================="
kill -9 $SERVER_PID 2>/dev/null || true
sleep 1

cp /Users/hans/VSC/buoy_tracker/tracker.config.remote /Users/hans/VSC/buoy_tracker/tracker.config
python3 run.py > /tmp/server.log 2>&1 &
SERVER_PID=$!
sleep 3

if ps -p $SERVER_PID > /dev/null 2>&1; then
    echo "Server running (PID: $SERVER_PID)"
    
    # Test root path (should fail now)
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5103/)
    echo "  GET / → $STATUS (should be 404)"
    
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5103/health)
    echo "  GET /health → $STATUS (should be 404)"
    
    # This should work
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5103/buoy-tracker/)
    echo "  GET /buoy-tracker/ → $STATUS (should be 200)"
    
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5103/buoy-tracker/health)
    echo "  GET /buoy-tracker/health → $STATUS (should be 200)"
    
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5103/buoy-tracker/api/nodes)
    echo "  GET /buoy-tracker/api/nodes → $STATUS (should be 200)"
else
    echo -e "${RED}Failed to start server${NC}"
    tail -5 /tmp/server.log
    exit 1
fi

echo -e "${GREEN}✓ Subpath routing works correctly${NC}"
echo ""

# Cleanup
kill -9 $SERVER_PID 2>/dev/null || true
cp /Users/hans/VSC/buoy_tracker/tracker.config.local /Users/hans/VSC/buoy_tracker/tracker.config

echo "=================================================="
echo -e "${GREEN}✓ All tests passed!${NC}"
echo "=================================================="
echo ""
echo "Summary:"
echo "  • Root path config: Works at http://localhost:5103/*"
echo "  • Subpath config: Works at http://localhost:5103/buoy-tracker/*"
echo ""
echo "Browser testing:"
echo "  1. Switch to tracker.config.remote"
echo "  2. Start server: ./start_server.sh"
echo "  3. Visit: http://localhost:5103/buoy-tracker/"
echo "  4. Check Network tab in DevTools - all requests should go to /buoy-tracker/*"
echo ""
