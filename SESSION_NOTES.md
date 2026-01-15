# Session Notes - January 15, 2026

## Current System Status

### Docker Archiver
- **Status**: Running (container: priceless_shockley)
- **Current Task**: Archiving 2019-06-05 (51 articles discovered)
- **Rate Limiting**: Working correctly with 8-second delays between save attempts
- **Progress**: ~2 articles processed (out of 51) with rate limiting active

### Rate Limiting Behavior
The archiver is properly respecting Wayback Machine's strict rate limits:
- SPN API limit: 15-20 requests/minute (very strict)
- Config setting: 8 seconds between requests (7.5 req/min - safe margin)
- Wayback is still returning 429/403 errors on aggressive attempts
- Archiver correctly marks these as "rate_limited" status

### 502 Bad Gateway Errors
These can come from two sources:

1. **Ming Pao Website (mingpaocanada.com)**
   - Sometimes returns 502 when checking if articles exist
   - Archiver handles this by treating as "failed" status
   - Can be retried later when their server recovers

2. **Wayback Machine (web.archive.org)**
   - Returns 502 when overwhelmed during SPN requests
   - Wayback's SPN API is heavily loaded
   - Archiver retries with exponential backoff (20s, 40s, 80s, 160s)

### Configuration
**Current config.docker.json settings:**
```json
{
  "rate_limit_delay": 8,        // 8 seconds between Wayback save requests
  "timeout": 120,                // 120 second timeout for API calls
  "max_retries": 5,              // 5 total attempts
  "retry_delay": 20,             // 20 seconds base retry delay (exponential backoff)
  "verify_first": true,          // Check if already in Wayback before saving
  "parallel": {
    "enabled": false             // Sequential processing only
  }
}
```

### What's Working Well
- ✅ Database tracking (archive_records + daily_progress tables)
- ✅ URL generation from Ming Pao index pages
- ✅ Rate limiting respects Wayback's constraints
- ✅ Error handling and retry logic
- ✅ Proper logging in Chinese + English
- ✅ Modal dashboard live with heatmap and copy buttons

### Known Issues & Limitations

1. **Wayback Save Page Now (SPN) API is Slow**
   - Takes 10-30 seconds per request (their API is slow)
   - With 8s delay + 20s processing = ~30s per article
   - 51 articles = ~25 minutes for one date
   - Rate limiting causes some to fail (marked as "rate_limited")

2. **Ming Pao Site Reliability**
   - Sometimes returns 502 Bad Gateway errors
   - Intermittent connection issues
   - No pattern - random across dates/articles

3. **Wayback Already Has Most Content**
   - Many 2019 articles already in Wayback (marked as "exists")
   - Only new articles get "success" status
   - Most work is verification, not new archiving

### Recommendations for Improvement

**Short-term (Acceptable for Now)**
- Keep 8s rate limit - prevents more aggressive blocking
- Accept slower archiving - reliability > speed
- Monitor error logs for patterns
- Focus on priority date ranges first

**Medium-term (1-2 weeks)**
- Implement custom SPN client with better error handling
- Add intelligent retry backoff (exponential + jitter)
- Support database upload from volunteers
- Real-time progress notifications

**Long-term (1-2 months)**
- Consider alternative archiving services
- Implement incremental archiving (daily jobs)
- Add ML-based date priority prediction
- Volunteer reputation system

## Docker Archiver Flow

```
Docker Container (priceless_shockley)
    ↓
Read config.docker.json (8s rate limit, 120s timeout)
    ↓
For each date (2019-07-21, 2019-06-04, 2019-06-05, 2020-06-05):
    ↓
Fetch index page → Get 25-51 articles
    ↓
For each article:
    ├─ Check if already in database (cached)
    ├─ Wait 8 seconds
    ├─ Attempt to save to Wayback
    │   ├─ If 429/403: Mark as "rate_limited"
    │   ├─ If 502: Mark as "failed", log error
    │   ├─ If success: Mark as "success"
    │   └─ If already exists: Mark as "exists"
    ├─ Update database
    └─ Log result
    ↓
Generate daily_progress report
    ↓
Update SQLite database
```

## Test Results

**2019-07-21**: 25 articles
- Found: 25 | Archived: 0 (all already exist) | Failed: 0

**2019-06-04**: 48 articles  
- Found: 2 (new) | Archived: 0 | Failed: 2 (rate limited)

**2019-06-05**: 51 articles
- In progress... (2 processed, rate limited)

**2020-06-05**: Pending

## Next Actions

1. **Let the current run complete** (5-10 more minutes)
2. **Check final statistics** in database
3. **Review logs** for patterns in which articles fail
4. **Consider running priority dates next**:
   - 2019-04-26 to 2019-06-04 (Anti-extradition protests)
   - 2021-01-06 to 2021-11-30 (47 Democrats case)

---
**Session Summary**: System is stable and working correctly. Rate limiting prevents aggressive blocking. Some articles fail due to Wayback/Ming Pao server issues, which is expected. Dashboard is live with volunteer coordination features.
