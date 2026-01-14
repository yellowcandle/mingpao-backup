#!/bin/bash
# Quick test script for Modal deployment

# Colors
GREEN='\033[0.32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=================================="
echo "Ming Pao Archiver - Modal Test"
echo "=================================="
echo ""

# Load environment variables from .env file
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
    echo ""
else
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo ""
fi

# Check if endpoint URL is set
if [ -z "$MODAL_ENDPOINT" ]; then
    echo -e "${RED}Error: MODAL_ENDPOINT environment variable not set${NC}"
    echo ""
    echo "Create a .env file with:"
    echo "  MODAL_ENDPOINT='https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run'"
    echo "  MODAL_STATS_ENDPOINT='https://YOUR_USERNAME--mingpao-archiver-get-stats.modal.run'"
    echo ""
    exit 1
fi

# Check if stats URL is set
if [ -z "$MODAL_STATS_ENDPOINT" ]; then
    echo -e "${YELLOW}Warning: MODAL_STATS_ENDPOINT not set, using default${NC}"
    MODAL_STATS_ENDPOINT="${MODAL_ENDPOINT/archive-articles/get-stats}"
fi

echo -e "${GREEN}Testing Modal endpoints...${NC}"
echo ""

# Test 1: Get initial stats
echo "1. Getting initial statistics..."
echo "   Endpoint: $MODAL_STATS_ENDPOINT"
curl -s "$MODAL_STATS_ENDPOINT" | jq '.' || echo "Failed to get stats"
echo ""

# Test 2: Archive single date
echo "2. Archiving single date (2026-01-13)..."
echo "   Endpoint: $MODAL_ENDPOINT"
echo "   This may take a few minutes..."
response=$(curl -s -X POST "$MODAL_ENDPOINT" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "date",
    "date": "2026-01-13"
  }')

echo "$response" | jq '.' || echo "Failed to archive"

status=$(echo "$response" | jq -r '.status')
if [ "$status" = "success" ]; then
    echo -e "${GREEN}✅ Archiving successful${NC}"
    successful=$(echo "$response" | jq -r '.stats.successful')
    total=$(echo "$response" | jq -r '.stats.total_attempted')
    echo "   Articles archived: $successful / $total"
else
    echo -e "${RED}❌ Archiving failed${NC}"
    error=$(echo "$response" | jq -r '.error')
    echo "   Error: $error"
fi
echo ""

# Test 3: Get updated stats
echo "3. Getting updated statistics..."
curl -s "$MODAL_STATS_ENDPOINT" | jq '.' || echo "Failed to get stats"
echo ""

echo "=================================="
echo "Test complete!"
echo "=================================="
