# AGENTS.md - Development Guide for Ming Pao Backup

This file provides guidance for AI agents and developers working on this project.

please use uv to manage dependencies and run the archiver.

## Project Overview

A Wayback Machine archiving tool for Ming Pao Canada (明報加拿大) Hong Kong news articles. The tool:
- Generates article URLs from date-based patterns
- Archives articles to web.archive.org
- Supports Traditional Chinese (繁體中文) keyword filtering
- Tracks progress in SQLite database

## Quick Start

```bash
# Install dependencies
uv sync

# Run basic archiving
uv run python mingpao_hkga_archiver.py --backdays 7

# Run with keywords
uv run python mingpao_hkga_archiver.py --enable-keywords --keyword "香港" --keyword "政治" --backdays 3
```

## Project Structure

```
mingpao-backup/
├── mingpao_hkga_archiver.py    # Main archiver class (MingPaoHKGAArchiver)
├── newspaper_extractor.py      # Optional newspaper3k integration
├── config.json                 # Configuration file
├── run_archiver.py             # Convenience runner
├── hkga_archive.db             # SQLite database (auto-generated)
├── requirements.txt            # Python dependencies
├── AGENTS.md                   # This file
└── README.md                   # User documentation
```

## Key Classes

### MingPaoHKGAArchiver (mingpao_hkga_archiver.py)

Main class for archiving operations.

**Key Methods:**
- `archive_date(target_date)` - Archive a single date
- `archive_date_range(start_date, end_date)` - Archive date range
- `generate_article_urls(target_date)` - Generate URL list for date
- `archive_to_wayback(url)` - Archive single URL
- `filter_urls_by_keywords(urls)` - Filter by keywords (title only)
- `filter_urls_by_keywords_parallel(urls)` - Parallel keyword filtering
- `check_wayback_exists(url)` - Check if URL archived
- `check_cjkv_keywords(text, terms)` - Match Traditional Chinese keywords
- `normalize_cjkv_text(text)` - Unicode normalization for CJKV

**Key Attributes:**
- `config` - Configuration dict
- `logger` - Python logger
- `conn` - SQLite connection
- `cursor` - SQLite cursor
- `stats` - Statistics dict

## Configuration (config.json)

### Keywords Section

```json
{
  "keywords": {
    "enabled": false,           // Enable keyword filtering
    "terms": ["香港", "政治"],   // Traditional Chinese keywords
    "case_sensitive": false,    // Case sensitivity
    "language": "zh-TW",        // Language code
    "script": "traditional",    // Character script
    "normalization": "NFC",     // Unicode normalization
    "logic": "or",              // Keyword matching logic
    "search_content": false,    // Search article body (slower)
    "parallel_workers": 2,      // Parallel workers for filtering
    "wayback_first": true       // Check Wayback before fetching
  }
}
```

### Parallel Section

```json
{
  "parallel": {
    "enabled": true,           // Enable parallel processing
    "max_workers": 5,          // Max concurrent workers
    "rate_limit_delay": 2.0    // Delay between batches
  }
}
```

## Database Schema

### archive_records Table

```sql
CREATE TABLE archive_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_url TEXT UNIQUE,          -- Original article URL
    wayback_url TEXT,                 -- Wayback archive URL
    archive_date TEXT,                -- Date (YYYYMMDD)
    status TEXT,                      -- success, failed, exists
    http_status INTEGER,              -- HTTP status code
    error_message TEXT,               -- Error if failed
    created_at TIMESTAMP,             -- Creation time
    updated_at TIMESTAMP,             -- Last update
    matched_keywords TEXT,            -- Comma-separated matched keywords
    checked_wayback INTEGER,          -- 1 if Wayback was checked
    title_search_only INTEGER,        -- 1 if title-only search
    article_title TEXT                -- Extracted article title
);
```

### daily_progress Table

```sql
CREATE TABLE daily_progress (
    date TEXT PRIMARY KEY,            -- Date (YYYYMMDD)
    articles_found INTEGER,           -- Found articles
    articles_archived INTEGER,        -- Successfully archived
    articles_failed INTEGER,          -- Failed
    articles_not_found INTEGER,       -- Not found
    execution_time REAL,              -- Execution time (seconds)
    completed_at TIMESTAMP,           -- Completion timestamp
    keywords_filtered INTEGER         -- URLs filtered by keywords
);
```

## CLI Arguments

### Basic Options

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Archive single date |
| `--start YYYY-MM-DD` | Start date for range |
| `--end YYYY-MM-DD` | End date for range |
| `--backdays N` | Archive last N days |
| `--config FILE` | Custom config path |
| `--report` | Generate report only |
| `--daily-limit N` | Override daily limit |

### Keyword Options

| Flag | Description |
|------|-------------|
| `--enable-keywords` | Enable keyword filtering |
| `--disable-keywords` | Disable keyword filtering |
| `--keyword TERM` | Add keyword (can repeat) |
| `--keywords "A,B,C"` | Comma-separated keywords |
| `--search-content` | Search article body |
| `--case-sensitive` | Case-sensitive matching |

### Other Options

| Flag | Description |
|------|-------------|
| `--newspaper` | Use newspaper3k URL discovery |
| `--help` | Show help |

## Common Development Tasks

### Adding New URL Patterns

The URL pattern is: `http://www.mingpaocanada.com/tor/htm/News/{YYYYMMDD}/HK-{PREFIX}{NUM}_r.htm`

To add new prefixes, edit `HK_GA_PREFIXES` in `MingPaoHKGAArchiver`:

```python
HK_GA_PREFIXES = [
    "gab", "gaa", "gac",  # Existing prefixes
    "new1", "new2",       # Add new prefixes here
]
```

### Adding Keyword Logic

The current logic is OR (any keyword matches). To change to AND:

1. Find `check_cjkv_keywords` method
2. Modify to require all terms match:

```python
def check_cjkv_keywords(self, text, terms, case_sensitive=False):
    # AND logic: all terms must match
    matched = []
    for term in terms:
        if term_search in text_search:
            matched.append(term)
    return matched if len(matched) == len(terms) else []
```

### Adding Content Search

Currently, keyword search is title-only by default. To enable full content search:

1. Set `"search_content": true` in config.json
2. Or use CLI: `--search-content`

The content search will:
1. Extract title first
2. If title matches, archive immediately
3. If not, search full HTML content

### Adding New Languages

To support Simplified Chinese or other CJKV languages:

1. Update `language` in config: `"zh-CN"` for Simplified
2. Update `terms` with appropriate keywords
3. Consider adding language-specific normalization

## Encoding Notes

### Traditional Chinese Encoding

Ming Pao uses Big5 encoding for Traditional Chinese. The code handles this via:

1. Fetching from Wayback (UTF-8) or original (Big5)
2. Trying multiple encodings: `big5-hkscs`, `big5`, `utf-8`
3. Unicode normalization with NFC form

If encoding issues occur, check:
- `extract_title_from_html()` method
- `normalize_cjkv_text()` method

## Rate Limiting

The Wayback Machine has strict rate limits:
- ~15-20 requests/minute recommended
- `rate_limit_delay: 3` seconds default

For parallel processing:
- Title-only filtering can use more workers
- Content search should use fewer workers
- Wayback save requests should be sequential

## Testing

### Quick Test

```bash
# Test keyword matching
uv run python -c "
from mingpao_hkga_archiver import MingPaoHKGAArchiver
archiver = MingPaoHKGAArchiver()
print(archiver.check_cjkv_keywords('香港政治新聞', ['香港', '政治']))
"

# Test URL generation
uv run python -c "
from mingpao_hkga_archiver import MingPaoHKGAArchiver
from datetime import datetime
archiver = MingPaoHKGAArchiver()
urls = archiver.generate_article_urls(datetime(2024, 1, 15))
print(f'Generated {len(urls)} URLs')
"
```

### Database Queries

```bash
# Check archived articles
sqlite3 hkga_archive.db "SELECT COUNT(*) FROM archive_records WHERE status='success'"

# Check keyword matches
sqlite3 hkga_archive.db "SELECT article_url, matched_keywords FROM archive_records WHERE matched_keywords IS NOT NULL LIMIT 10"

# Check daily progress
sqlite3 hkga_archive.db "SELECT * FROM daily_progress ORDER BY date DESC LIMIT 5"
```

## Common Issues

### 1. Connection Reset by Peer

The Ming Pao site may reset connections. The workaround:
- Use `wayback_first: true` (default) to check Wayback first
- Increase timeout in config
- Use fewer parallel workers

### 2. Encoding Issues

If titles appear as garbled text:
- Check `extract_title_from_html()` encoding attempts
- Ensure `normalize_cjkv_text()` is using correct form
- Try adding more encodings to the fallback list

### 3. Database Locked

If database is locked:
- Ensure only one instance running
- Delete `.db-journal` file if exists
- Check for crashed processes

## Code Style

- Python 3.12+
- Type hints for function signatures
- UTF-8 encoding for all files
- Traditional Chinese comments where appropriate
- Logging at INFO level for main operations
- DEBUG level for detailed tracing

## Dependencies

Key packages:
- `requests` - HTTP requests
- `newspaper3k` - Article extraction (optional)
- `lxml_html_clean` - HTML parsing for newspaper3k
- `internetarchive` - Internet Archive API (optional)

See `requirements.txt` for full list.

## Performance Tuning

For large-scale archiving:

1. **Increase workers**: `"parallel_workers": 5`
2. **Reduce delays**: `"rate_limit_delay": 1`
3. **Disable verification**: `"verify_first": false`
4. **Increase daily limit**: `"daily_limit": 5000`

Warning: Too aggressive settings may trigger rate limiting.

## Future Enhancements

Potential additions:
- jieba tokenization for better Chinese matching
- Progress bar for long operations
- Configuration via environment variables
- Prometheus metrics endpoint
- Docker containerization

## Support

For issues:
1. Check `logs/hkga_archiver.log`
2. Query database for error details
3. Test with single URL first
4. Check Wayback Machine status

## References

- [Wayback Machine Save API](https://archive.org/developers/index.html)
- [Internet Archive Python Library](https://internetarchive.readthedocs.io/)
- [Unicode Normalization](https://unicode.org/reports/tr15/)
- [Big5-HKSCS Encoding](https://en.wikipedia.org/wiki/Big5-HKSCS)
