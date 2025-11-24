# How to Observe Rate Limiter in Action

## Current Configuration
- **Rate Limit**: 1620 requests/hour per IP
- **Polling Interval**: 10 seconds  
- **4 Browser Windows**: ~72 requests/minute total (way over limit)

## How to Check if Rate Limiter is Working

### Method 1: Browser DevTools (Best for seeing it live)

1. Open **one of your 4 browser windows**
2. Press **F12** to open Developer Tools
3. Go to the **Console** tab
4. Watch for `[RATELIMIT]` messages in the console
5. Switch to the **Network** tab
6. Look for requests with status code **429** (Too Many Requests)

### Method 2: Check Server Logs

```bash
# In a terminal, watch the server logs in real-time
tail -f /Users/hans/VSC/buoy_tracker/server.log | grep -i "rate\|429"
```

If you see:
- `WARNING - Rate limit exceeded for IP 127.0.0.1: ...`
- HTTP 429 responses in the Network tab
- `[RATELIMIT]` in the console

Then the rate limiter **IS working**.

### Method 3: Forced Test (Rapid Sequential Requests)

To force trigger the rate limiter quickly:

```bash
# Make 50 rapid requests in succession
for i in {1..50}; do
  curl -s -o /dev/null -w "Request %i: %{http_code}\n" http://localhost:5102/api/status
done
```

Watch for HTTP 429 responses (should appear after ~1-2 requests given the 1620/hour limit).

## Why It Might Not Be Visible

1. **Browser Caching**: Firefox/Chrome might cache 200 responses so subsequent requests don't even hit the server
2. **Polling Interval**: With 10-second intervals from 4 windows, you get ~1.2 requests/sec total, which is still within limit if requests are spread slightly
3. **Clock Skew**: The rate limit window resets hourly, so you might be near the beginning of a new window

## Expected Behavior When Rate Limited

- Progress bar turns **RED** (#f44336)
- Status shows **"🛑 RATE LIMIT EXCEEDED - Polling Paused 60s"** banner
- Console shows `[RATELIMIT] 429 Too Many Requests - pausing polling`
- Polling pauses for 60 seconds before retrying

## To Truly Test It

The easiest way is to temporarily **reduce** `api_polling_interval` in tracker.config:

```ini
[webapp]
api_polling_interval = 1  # Change from 10 to 1 second for rapid testing
```

Then restart the server and watch the 4 windows. You should hit the rate limit within seconds.

**Remember to change it back to 10 after testing!**
