#!/bin/bash
# Test script to trigger rate limiter by making rapid requests

PORT=5102
ENDPOINT="http://localhost:$PORT/api/status"
REQUEST_COUNT=0
RATE_LIMITED=0

echo "🔥 Rate Limiter Test Script"
echo "============================"
echo "Rate limit: 1620 requests/hour = 0.45 req/sec"
echo "Testing by making 50 rapid requests..."
echo ""

for i in {1..50}; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$ENDPOINT")
  REQUEST_COUNT=$((REQUEST_COUNT + 1))
  
  if [ "$HTTP_CODE" = "429" ]; then
    RATE_LIMITED=$((RATE_LIMITED + 1))
    echo "❌ Request $i: HTTP $HTTP_CODE (RATE LIMITED)"
  elif [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Request $i: HTTP $HTTP_CODE"
  else
    echo "⚠ Request $i: HTTP $HTTP_CODE"
  fi
  
  # Small delay to avoid overwhelming network
  sleep 0.05
done

echo ""
echo "📊 Results:"
echo "==========="
echo "Total requests: $REQUEST_COUNT"
echo "Rate limited (429): $RATE_LIMITED"
echo "Successful (200): $((REQUEST_COUNT - RATE_LIMITED))"

if [ $RATE_LIMITED -gt 0 ]; then
  echo ""
  echo "✅ Rate limiter IS working!"
else
  echo ""
  echo "⚠️  No rate limit responses received"
  echo "   This could mean:"
  echo "   1. Rate limit is very generous (try more requests)"
  echo "   2. Rate limiter configuration not taking effect"
  echo "   3. Flask-Limiter not properly initialized"
fi
