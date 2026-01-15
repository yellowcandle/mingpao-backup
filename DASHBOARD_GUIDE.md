# Dashboard Coordination Hub Guide

## Overview

The Ming Pao Archive Dashboard has been transformed into a **volunteer coordination hub** designed to help volunteers identify which date ranges need archiving and provide easy-to-use tools to contribute.

## Features

### 1. Priority Date Configuration

The dashboard highlights historically significant date ranges that should be prioritized for archiving. These are defined in `PRIORITY_RANGES` in `modal_app.py`:

```python
PRIORITY_RANGES = [
    {
        "start": "2019-04-01",
        "end": "2019-12-31",
        "label": "2019 Apr-Dec (Hong Kong Unrest)",
    },
    # ... more ranges
]
```

**Current Priority Dates:**
- **2019 Apr-Dec**: Hong Kong Unrest period
- **Apr 26 - Jun 4**: Recurring annually
- **Jul 21-22**: Recurring annually from 2019 onward
- **Aug 31**: Recurring annually from 2019 onward
- **Jan 6, 2021 - Nov 2024**: 47人案 (47 Democrats Case) period
- **Jun 24, 2021**: 蘋果日報 (Apple Daily) final issue date

### 2. Month-by-Year Heatmap

The dashboard displays a comprehensive heatmap showing coverage for every month from 2013-2026:

- **🟢 Green (>95%)**: Month is fully archived
- **🟡 Yellow (50-94%)**: Partial coverage, some articles missing
- **🟠 Orange (1-49%)**: Low coverage, significant gaps
- **⚫ Grey (0%)**: No data found yet
- **🔴 Red Border**: Priority date range

Click any month cell to see details and get Docker commands.

### 3. Hourly Wayback Sync

A scheduled function runs **every hour** to sync with the Wayback Machine:

- Checks the last 30 days for archives
- Updates database with coverage status
- Keeps the heatmap accurate without requiring new runs

**Function**: `hourly_sync_wayback()` - runs via `modal.Cron("0 * * * *")`

### 4. One-Click Docker Commands

The dashboard will eventually include buttons to copy Docker commands for any missing month:

```bash
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --start 2015-04-01 --end 2015-04-30
```

## How to Use

### As a Volunteer

1. **Visit the Dashboard**: https://yellowcandle--mingpao-archiver-dashboard.modal.run
2. **Find Missing Data**: Look for months with 🟠 Orange or ⚫ Grey
3. **Prioritize**: Focus on months with 🔴 Red borders
4. **Get the Command**: (Coming soon) Copy the Docker command for that month
5. **Run Locally**: Use Docker to archive the date range
6. **Verify**: The hourly sync will pick up your work within the next hour

### Modifying Priority Ranges

To add or change priority dates:

1. Edit `PRIORITY_RANGES` in `modal_app.py`
2. Commit and push changes
3. Run `modal deploy modal_app.py` to update

**Example - Add a new priority range:**

```python
{
    "start": "2025-01-01",
    "end": "2025-01-31",
    "label": "Recent Crisis (2025)",
}
```

## Technical Details

### Date Matching Logic

The `is_priority_date()` function supports three types of matching:

1. **Static Range**: `"start"` and `"end"` dates define a fixed period
2. **Recurring Yearly**: `"recurring_yearly": True` repeats the same month/day every year from start year onward
3. **Recurring Monthly**: `"recurring_monthly": True` repeats the month-day range every year

Example:

```python
# Jul 21-22 every year from 2019 onward
{
    "start": "2019-07-21",
    "end": "2019-07-22",
    "recurring_yearly": True,
    "label": "Jul 21-22 (Annual Recurring from 2019)",
}
```

### Coverage Calculation

Coverage is determined by:
1. Checking `archive_records` table for successful archives (`status` in 'success', 'exists')
2. Calculating percentage of articles found vs. total expected
3. Marking priority gaps separately for dashboard highlighting

### Hourly Sync Details

The `hourly_sync_wayback()` function:
- Runs automatically every hour via Modal Cron scheduler
- Checks the last 30 days for new/updated archives
- Uses Wayback API with 0.2s rate limiting
- Inserts records with `status='exists'` for found archives
- Commits changes to the Modal volume

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/dashboard` | GET | View the coordination heatmap |
| `/get-stats` | GET | Get raw statistics JSON |
| `/archive-articles` | POST | Trigger archiving (manual mode) |

## Database Schema

The dashboard uses two key tables:

**archive_records**: Tracks individual article archiving
- `article_url`: Original article URL
- `wayback_url`: Wayback Machine archive URL
- `status`: 'success', 'exists', 'failed', 'error', etc.
- `archive_date`: Date the article was published (YYYYMMDD)

**daily_progress**: Tracks daily archiving runs
- `date`: Day processed (YYYY-MM-DD)
- `articles_found`: Total articles discovered
- `articles_archived`: Successfully archived
- `articles_failed`: Failed attempts
- `execution_time`: Time taken in seconds

## Future Enhancements

Planned features:

1. **Interactive Month Details**: Click a month to see:
   - Exact counts (342/360 articles)
   - Expected vs. actual coverage
   - Recent activity in that month

2. **GitHub Integration**: Auto-create issue claims
3. **Upload Support**: Allow volunteers to upload local DBs
4. **Admin Panel**: Real-time priority configuration
5. **Contributor Stats**: Leaderboards for volunteers

## Troubleshooting

**Dashboard shows no data?**
- Database may be empty, run an archiving job first
- Wait for next hourly sync if you just uploaded data

**Heatmap not updating?**
- Hourly sync runs at :00 of every hour UTC
- Manual runs of `sync_from_wayback` can be triggered via Modal CLI

**Want to test locally?**
```bash
modal run modal_app.py  # Test with live reload
modal deploy modal_app.py  # Deploy to production
```

## Support

For questions or issues:
1. Check the dashboard help at: https://yellowcandle--mingpao-archiver-dashboard.modal.run
2. Open an issue on GitHub: https://github.com/yellowcandle/mingpao-backup/issues
3. Review AGENTS.md for development guide
