# Modal Deployment Guide

Quick reference for deploying the Ming Pao archiver to Modal.

## Prerequisites

- Python 3.12+
- Modal account (sign up at https://modal.com)

## One-Time Setup

```bash
# 1. Install Modal
pip install modal

# 2. Authenticate
modal setup
# Follow the prompts to link your account
```

## Deploy

```bash
# Deploy the app to Modal cloud
modal deploy modal_app.py
```

You'll get two endpoint URLs:
- `archive_articles`: POST endpoint for triggering archiving
- `get_stats`: GET endpoint for viewing statistics

## Usage Examples

### Archive Single Date

```bash
curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{"mode": "date", "date": "2026-01-13"}'
```

### Archive Date Range

```bash
curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "range",
    "start": "2026-01-01",
    "end": "2026-01-31"
  }'
```

### Archive Last 7 Days

```bash
curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "backdays",
    "backdays": 7
  }'
```

### With Keywords

```bash
curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "backdays",
    "backdays": 3,
    "keywords": ["香港", "政治", "中國"]
  }'
```

### View Statistics

```bash
curl https://YOUR_USERNAME--mingpao-archiver-get-stats.modal.run
```

## Monitoring

### View Logs

```bash
# View recent logs
modal logs mingpao-archiver

# Follow logs in real-time
modal logs mingpao-archiver --follow
```

### Check Volume

```bash
# List files in persistent volume
modal volume ls mingpao-db

# Download database backup
modal volume get mingpao-db /data/hkga_archive.db ./backup.db
```

## Testing Locally

Before deploying, test the app locally:

```bash
modal run modal_app.py
```

This runs the test in `@app.local_entrypoint()` which archives 2026-01-13.

## Common Tasks

### Daily Automated Archiving

Add to your crontab:

```bash
# Archive yesterday's articles daily at 3am
0 3 * * * curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{"mode": "backdays", "backdays": 1}' \
  >> /var/log/mingpao-archiver.log 2>&1
```

### Backfill Historical Data

Archive multiple date ranges:

```bash
# January 2026
curl -X POST <ENDPOINT> \
  -d '{"mode": "range", "start": "2026-01-01", "end": "2026-01-31"}'

# December 2025
curl -X POST <ENDPOINT> \
  -d '{"mode": "range", "start": "2025-12-01", "end": "2025-12-31"}'
```

### Download Database

```bash
# Get latest database snapshot
modal volume get mingpao-db /data/hkga_archive.db ./local_backup.db

# Query locally
sqlite3 local_backup.db "SELECT COUNT(*) FROM archive_records WHERE status='success'"
```

## Troubleshooting

### "Connection reset by peer" errors

The rate limiting is configured at 3s per request. If you still see errors:
1. Check Modal logs: `modal logs mingpao-archiver --follow`
2. Increase `rate_limit_delay` in config.json
3. Redeploy: `modal deploy modal_app.py`

### Timeout errors

For large date ranges (>30 days), split into smaller ranges:
- Modal has 24-hour timeout per function call
- Recommended: archive in monthly chunks

### Database not persisting

Make sure volume is being committed:
- Check `modal_app.py` line 155: `volume.commit()`
- Verify volume exists: `modal volume ls mingpao-db`

## Cost Management

Monitor usage:
```bash
modal profile
```

Free tier limits:
- 30 GPU hours/month (CPU is free during free tier)
- After free tier: ~$0.23/hour for CPU

Estimated costs:
- 40 articles/day × 3s/article = 2 minutes/day
- Monthly: ~1 hour/month (well within free tier!)
- Storage: <$0.10/month

## Security

Modal endpoints are public by default. To add authentication:

1. Add authentication decorator (future enhancement)
2. Use Modal secrets for sensitive config
3. Restrict access via API gateway/proxy

## Updating

When you modify code:

```bash
# Redeploy
modal deploy modal_app.py

# Changes take effect immediately
# No downtime
```

## Uninstalling

Remove the deployment:

```bash
# Delete app
modal app delete mingpao-archiver

# Delete volume (WARNING: deletes database!)
modal volume delete mingpao-db
```

## Support

- Modal docs: https://modal.com/docs
- Modal Discord: https://discord.gg/modal
- Check logs first: `modal logs mingpao-archiver --follow`
