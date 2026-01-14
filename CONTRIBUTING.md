# Contributing to Ming Pao Archive

Thank you for helping preserve Hong Kong news history! This guide explains how to contribute by archiving articles using Docker.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed on your machine
- Git for cloning the repository
- Stable internet connection

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/yellowcandle/mingpao-backup.git
cd mingpao-backup
```

### 2. Build the Docker Image

```bash
docker build -t mingpao-archiver .
```

### 3. Create Data Directories

```bash
mkdir -p data logs
```

### 4. Claim a Date Range

Before starting, **create a GitHub issue** to claim your date range:

1. Go to [Issues](https://github.com/yellowcandle/mingpao-backup/issues/new/choose)
2. Select "Claim Archive Date Range"
3. Fill in the year and quarter you want to archive
4. Submit the issue

This prevents duplicate work!

### 5. Run the Archiver

```bash
# Archive a specific quarter (example: 2015 Q1)
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --start 2015-01-01 --end 2015-03-31

# Or use docker-compose
docker-compose run archiver --start 2015-01-01 --end 2015-03-31
```

### 6. Check Progress

```bash
# View statistics
docker-compose run stats

# Or check logs
tail -f logs/hkga_archiver.log
```

### 7. Report Results

Update your GitHub issue with:
- Number of articles archived
- Any errors encountered
- The database file size

## Date Range Guidelines

| Range Type | Command Example |
|------------|-----------------|
| Single day | `--date 2015-01-15` |
| Quarter | `--start 2015-01-01 --end 2015-03-31` |
| Month | `--start 2015-06-01 --end 2015-06-30` |

**Recommended chunk size**: One quarter (3 months) per claim

## Expected Performance

- ~40 articles per day (using index page crawling)
- ~3 seconds between requests (rate limiting)
- One quarter takes approximately 6-8 hours

## Troubleshooting

### Rate Limiting (403 errors)

If you see many 403 errors, increase the delay:
```bash
# Edit config.docker.json before building
# Change "rate_limit_delay": 3 to "rate_limit_delay": 5
docker build -t mingpao-archiver .
```

### Connection Errors

The archiver will retry automatically. If persistent:
- Check your internet connection
- Wait a few minutes and retry
- The progress is saved, so you can resume

### Database Issues

The SQLite database is in `./data/hkga_archive.db`. You can:
```bash
# Check contents
sqlite3 data/hkga_archive.db "SELECT status, COUNT(*) FROM archive_records GROUP BY status"

# Export to CSV
sqlite3 data/hkga_archive.db -csv "SELECT * FROM archive_records" > export.csv
```

## Submitting Your Results

After completing your claimed range:

1. Update your GitHub issue with final statistics
2. (Optional) Share your database file if you want it merged into the main archive
3. Close the issue

## Code Contributions

For code improvements:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Questions?

- Open an issue for questions
- Check existing issues for common problems
