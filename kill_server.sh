#!/bin/bash
# Buoy Tracker - Kill Server Script
# Cleanly stops the running server process

CONFIG_FILE="$(dirname "$0")/tracker.config"
VERSION=$(grep "version = " "$CONFIG_FILE" | awk '{print $3}')
# Get port from [webapp] section (line 25 in config)
PORT=$(grep -A 10 "\[webapp\]" "$CONFIG_FILE" | grep "^port = " | awk '{print $3}')

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Buoy Tracker v${VERSION} ===${NC}"
echo -e "${BLUE}Stopping server on port $PORT...${NC}\n"

if ! lsof -i :$PORT > /dev/null 2>&1; then
  echo -e "${GREEN}✓ Server not running${NC}"
  exit 0
fi

echo "Killing process..."
pkill -9 -f "run.py" 2>/dev/null || true
sleep 1

if lsof -i :$PORT > /dev/null 2>&1; then
  echo -e "${RED}✗ Failed to stop server${NC}"
  lsof -i :$PORT | tail -1
  exit 1
else
  echo -e "${GREEN}✓ Server stopped${NC}\n"
fi
