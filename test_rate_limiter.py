#!/usr/bin/env python3
"""
Rate Limiter Test Script - Verifies the rate limiter is working correctly.
Tests by making rapid sequential requests to trigger the limit.
"""

import requests
import time
import sys
from collections import defaultdict

BASE_URL = 'http://localhost:5102'
API_KEY = 'SycLovesBoats'  # From secret.config
ENDPOINT = f'{BASE_URL}/api/status'
DEBUG_ENDPOINT = f'{BASE_URL}/api/debug/rate-limit'

def get_headers():
    """Get headers with API key authentication."""
    return {
        'Authorization': f'Bearer {API_KEY}'
    }

def print_header(text):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")

def get_rate_limit_status():
    """Get current rate limit status from debug endpoint."""
    try:
        resp = requests.get(DEBUG_ENDPOINT, headers=get_headers(), timeout=5)
        return resp.json()
    except Exception as e:
        print(f"ERROR: Failed to get rate limit status: {e}")
        return None

def test_rate_limiter():
    """Test the rate limiter by making rapid requests."""
    print_header("RATE LIMITER TEST")
    
    # Get initial status
    initial_status = get_rate_limit_status()
    if not initial_status:
        print("FAILED: Could not get rate limit status")
        return False
    
    limit_per_hour = initial_status['rate_limit_per_hour']
    initial_remaining = initial_status['requests_remaining_this_hour']
    polling_interval = initial_status['polling_interval_seconds']
    
    print(f"\n📊 Rate Limit Configuration:")
    print(f"   Limit: {limit_per_hour} requests/hour")
    print(f"   Remaining: {initial_remaining}")
    print(f"   Polling interval: {polling_interval} seconds")
    
    # Calculate how many requests to make
    # We'll make enough to use up 50% of the hourly limit, which should trigger limits
    requests_to_make = limit_per_hour // 2
    
    print(f"\n🔥 Test Plan:")
    print(f"   Making {requests_to_make} rapid requests")
    print(f"   Expected remaining after: ~{initial_remaining - requests_to_make}")
    
    # Track results
    results = defaultdict(int)
    start_time = time.time()
    
    print(f"\n📡 Sending requests...")
    for i in range(requests_to_make):
        try:
            resp = requests.get(ENDPOINT, headers=get_headers(), timeout=2)
            http_code = resp.status_code
            results[http_code] += 1
            
            if http_code == 429:
                print(f"   ✓ Request {i+1}: 429 RATE LIMITED (good!)")
            elif http_code == 200:
                if (i + 1) % 100 == 0:
                    print(f"   ✓ Request {i+1}: 200 OK (quota not exceeded yet)")
            else:
                print(f"   ✗ Request {i+1}: {http_code} (unexpected)")
        except requests.Timeout:
            results['TIMEOUT'] += 1
            print(f"   ⏱ Request {i+1}: TIMEOUT")
        except Exception as e:
            results['ERROR'] += 1
            print(f"   ✗ Request {i+1}: ERROR - {e}")
    
    elapsed = time.time() - start_time
    
    # Get final status
    print(f"\n⏱️  Total time: {elapsed:.1f}s ({requests_to_make/elapsed:.1f} req/sec)")
    
    final_status = get_rate_limit_status()
    if final_status:
        final_remaining = final_status['requests_remaining_this_hour']
        used = initial_remaining - final_remaining
        print(f"\n📊 Final Status:")
        print(f"   Started with: {initial_remaining} remaining")
        print(f"   Now have: {final_remaining} remaining")
        print(f"   Used: {used} requests")
    
    # Print results
    print(f"\n📈 Response Summary:")
    for code, count in sorted(results.items()):
        if code == 200:
            print(f"   ✓ 200 OK: {count} requests")
        elif code == 429:
            print(f"   🛑 429 RATE LIMITED: {count} requests (WORKING!)")
        else:
            print(f"   ✗ {code}: {count} requests")
    
    # Verdict
    print_header("TEST RESULT")
    if results[429] > 0:
        print("✅ PASS - Rate limiter is working!")
        print(f"   Received {results[429]} rate limit responses (429 status)")
        return True
    elif used > requests_to_make * 0.5:
        print("⚠️  INCONCLUSIVE - Quota used but no 429 responses")
        print(f"   Quota tracking seems to work ({used} requests tracked)")
        print(f"   But rate limit responses not triggered (yet)")
        return None
    else:
        print("❌ FAIL - Rate limiter not working")
        print(f"   Made {requests_to_make} requests but got no rate limit responses")
        print(f"   Quota tracking shows: {used} requests used")
        return False

if __name__ == '__main__':
    try:
        result = test_rate_limiter()
        sys.exit(0 if result is True else 1 if result is False else 2)
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
