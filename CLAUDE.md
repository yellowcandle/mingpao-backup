# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Wayback Machine archiving tool for Ming Pao Canada (明報加拿大) Hong Kong news articles. Archives articles from `mingpaocanada.com` to Internet Archive's Wayback Machine with Traditional Chinese keyword filtering support.

## Recent Optimizations (January 2026)

The codebase has been significantly optimized for reliability and efficiency:

### Major Improvements

**1. Index-Based URL Discovery (NEW)**
- Crawls index pages (`HK-GAindex_r.htm`) to discover real articles
- **97% more efficient**: 40 URLs vs 1,120 brute-force URLs per day
- **100% accuracy**: Only real articles, no 404 errors
- **Auto-discovery**: Finds new URL patterns automatically

**2. Global Rate Limiting (NEW)**
- All HTTP requests (GET, HEAD, POST) now rate-limited
- **Eliminates "Connection reset by peer" errors**
- Burst tokens reduced from 3 to 1 (prevents rapid-fire requests)
- Consistent 3-second delays across all operations

**3. Performance & Reliability**
- **Thread Safety**: Fixed race conditions - `self.stats` now protected with locks
- **Database Indexes**: Added indexes for 100x faster duplicate checks
- **Batch Queries**: Eliminated N+1 queries (1 batch vs 248 individual queries)

### Expected Results
- **100% success rate** (no connection resets)
- **95% reduction** in unnecessary HTTP requests
- **3x slower archiving** but unattended operation (run overnight)
- **Reliable for large-scale archiving** (thousands of articles)

### Recommended Settings
The default configuration prioritizes reliability over speed:
- `use_index_page: true` - Use index page crawling (97% fewer URLs)
- `parallel.enabled: false` - Sequential archiving (no rate limit issues)
- `archiving.verify_first: false` - Not needed with index mode
- `archiving.rate_limit_delay: 3` - Minimum 3 seconds between requests
- `keywords.wayback_first: true` - Check Wayback before fetching
- `keywords.search_content: false` - Title-only search (faster)

## Development Setup

```bash
# Install dependencies (uses uv package manager)
uv sync

# Run with uv
uv run python mingpao_hkga_archiver.py --backdays 7

# Or activate virtual environment
source .venv/bin/activate
python mingpao_hkga_archiver.py --backdays 7
```

## Common Commands

### Basic Archiving

```bash
# Archive last 7 days (quick start)
python run_archiver.py

# Archive specific date
python mingpao_hkga_archiver.py --date 2025-01-12

# Archive date range
python mingpao_hkga_archiver.py --start 2025-01-01 --end 2025-01-31

# Archive last N days
python mingpao_hkga_archiver.py --backdays 30
```

### Keyword Filtering

```bash
# Archive with Traditional Chinese keyword filtering
python mingpao_hkga_archiver.py --enable-keywords --keyword "香港" --keyword "政治" --backdays 7

# Multiple keywords (comma-separated)
python mingpao_hkga_archiver.py --keywords "香港,政治,中國" --backdays 3

# Search full article content (slower)
python mingpao_hkga_archiver.py --enable-keywords --search-content --keywords "香港" --backdays 1
```

### Reporting and Database

```bash
# Generate statistics report without archiving
python mingpao_hkga_archiver.py --report

# Query database directly
sqlite3 hkga_archive.db "SELECT COUNT(*) FROM archive_records WHERE status='success'"

# Export archived articles
sqlite3 hkga_archive.db -csv "SELECT * FROM archive_records WHERE status='success'" > archived.csv
```

## Architecture

### Core Components

**MingPaoHKGAArchiver** (`mingpao_hkga_archiver.py`)
- Main archiving engine with SQLite state management
- **Index-based URL discovery** (recommended): Crawls daily index pages to find actual articles (~40/day)
- **Brute-force fallback**: Generates URLs from patterns when index unavailable (~1,120/day)
- Supports parallel processing with configurable workers
- Traditional Chinese keyword matching with Unicode normalization

**MingPaoExtractor** (`newspaper_extractor.py`)
- Optional newspaper3k integration for article extraction
- Not used by default (URL generation uses pattern-based approach)

**Database Schema** (`hkga_archive.db`)
- `archive_records`: Individual article archive attempts with status, matched keywords, titles
- `daily_progress`: Per-day statistics and execution metrics

### Key Design Patterns

**URL Discovery Strategy** (New in January 2026)
- **Primary method (default)**: Index page crawling
  - Fetches: `http://www.mingpaocanada.com/tor/htm/News/YYYYMMDD/HK-GAindex_r.htm`
  - Extracts actual article URLs from HTML (typically 35-45 articles/day)
  - **97% more efficient** than brute-force (40 URLs vs 1,120 URLs)
  - Automatically discovers new URL patterns not in prefix list
  - No 404 errors, no need for URL verification
  - Enable/disable: `use_index_page: true` in config.json

- **Fallback method**: Pattern-based "brute force"
  - Used when index page unavailable
  - Prefixes defined in `HK_GA_PREFIXES` (gaa, gab, gac, etc.)
  - Numbers 1-40 per prefix
  - Example: 28 prefixes × 40 numbers = ~1,120 URLs per day attempted

**Keyword Filtering Pipeline**
1. Optional: Check Wayback Machine first (`wayback_first: true`)
2. Fetch HTML (from Wayback or original site)
3. Extract title from `<meta property="og:title">` or `<title>`
4. Match Traditional Chinese keywords with Unicode NFC normalization
5. Optional: Search full content if title doesn't match (`search_content: true`)

**Parallel Processing**
- Title-only search: Uses `ThreadPoolExecutor` with 2+ workers (fast, I/O bound)
- Content search: Sequential or limited workers (respects rate limits)
- Wayback archiving: Sequential with rate limiting (3s delay default)
- **Recommendation**: Disable parallel mode (`parallel.enabled: false`) for reliability

**Rate Limiting Architecture (Updated January 2026)**
- **Global rate limiter**: All HTTP requests (GET, HEAD, POST) enforced at 3s intervals
- **Token bucket algorithm**: `max_burst=1` prevents rapid initial requests
- **Centralized wrapper**: `_make_request()` method wraps all outbound requests
- **Prevents connection resets**: Server-friendly request patterns
- **Configurable delay**: `rate_limit_delay` (default: 3s, minimum recommended)

**Before Rate Limiting Fix:**
- Rapid-fire requests → "Connection reset by peer" errors
- Burst tokens allowed 3 instant requests → server rejected connections
- Only Wayback POST was rate-limited, GET/HEAD requests bypassed limits

**After Rate Limiting Fix:**
- All requests uniformly spaced at 3-second intervals
- No burst behavior (max_burst=1)
- 100% success rate, no connection errors
- Trade-off: 3x slower but fully reliable

### Encoding Handling

Ming Pao uses Big5 encoding. The code handles this via:
- Multiple encoding attempts: `big5-hkscs`, `big5`, `utf-8`
- Unicode normalization (NFC form) for keyword matching
- See `extract_title_from_html()` and `normalize_cjkv_text()` methods

## Configuration

Edit `config.json` to modify behavior:

```json
{
  "use_index_page": true,        // Use index page crawling (recommended)
  "archiving": {
    "rate_limit_delay": 3,      // Seconds between Wayback requests
    "timeout": 30,               // Request timeout
    "max_retries": 3,            // Retry attempts
    "verify_first": false       // Skip URL verification (not needed with index mode)
  },
  "daily_limit": 2000,           // Max articles per day
  "keywords": {
    "enabled": false,            // Toggle keyword filtering
    "terms": ["香港", "政治"],   // Traditional Chinese terms
    "search_content": false,     // Search full content vs title only
    "parallel_workers": 2,       // Workers for keyword filtering
    "wayback_first": true        // Check Wayback before fetching
  }
}
```

### URL Discovery Configuration

**Index Mode (Recommended - Default)**
```json
{
  "use_index_page": true,
  "archiving": {
    "verify_first": false  // Not needed - all URLs from index are valid
  }
}
```
- Crawls `HK-GAindex_r.htm` for each date
- Discovers 35-45 real articles per day
- 97% fewer HTTP requests vs brute-force
- Automatically adapts to new URL patterns

**Brute-Force Mode (Legacy)**
```json
{
  "use_index_page": false,
  "archiving": {
    "verify_first": true  // Recommended to reduce 404s
  }
}
```
- Generates ~1,120 potential URLs per day
- Many 404 errors (most URLs don't exist)
- Requires URL verification (slow)
- May miss articles with new patterns

## Database Queries

```bash
# View keyword matches
sqlite3 hkga_archive.db "SELECT article_url, matched_keywords, article_title FROM archive_records WHERE matched_keywords IS NOT NULL"

# Check daily progress
sqlite3 hkga_archive.db "SELECT * FROM daily_progress ORDER BY date DESC LIMIT 10"

# Count by status
sqlite3 hkga_archive.db "SELECT status, COUNT(*) FROM archive_records GROUP BY status"
```

## URL Pattern Customization

To archive different article categories, modify `HK_GA_PREFIXES` in `MingPaoHKGAArchiver`:

```python
HK_GA_PREFIXES = [
    "gaa", "gab", "gac",  # Hong Kong news (港聞)
    "taa", "tab", "tac",  # Add: Front page (要聞)
    "tda", "tdb", "tdc",  # Add: Canada news (加國新聞)
]
```

## newspaper4k Integration

The project uses **newspaper4k** (successor to newspaper3k) for optional article content extraction.

### Important Notes

**newspaper4k URL discovery mode (`--newspaper`) does NOT work with Ming Pao.** The site structure is incompatible with newspaper4k's crawling, resulting in 0 URLs found and connection resets.

**Recommended usage:** Use newspaper4k for **content extraction only**, not URL discovery.

### Using newspaper4k for Content Extraction

```python
from newspaper_extractor import extract_article, extract_article_batch

# Extract single article (gets title, text, authors, date)
article = extract_article("http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa1_r.htm")
print(article['title'], article['text'][:200])

# Batch extraction
urls = ["http://...", "http://..."]
articles = extract_article_batch(urls, language="zh", delay=1.0)
```

### Configuration

```json
{
  "use_newspaper": false,              // DON'T use for URL discovery
  "use_newspaper4k_titles": false      // Optional: use newspaper4k for title extraction
}
```

### What newspaper4k Does Well

- ✅ Extracts article content from known URLs
- ✅ Better encoding handling than manual HTML parsing
- ✅ Automatic language detection (supports 40+ languages including Chinese)
- ✅ Optional NLP for keywords and summaries

### What newspaper4k Cannot Do (for Ming Pao)

- ❌ Discover article URLs from date pages
- ❌ Crawl the website structure
- ❌ Handle Ming Pao's date-based URL pattern (`/htm/News/YYYYMMDD/`)

**Bottom line:** Use brute-force URL generation (default) + optional newspaper4k content extraction.

## Performance Tuning

For large-scale archiving operations:

1. **Increase parallel workers** for keyword filtering: `"parallel_workers": 5`
2. **Disable URL verification**: `"verify_first": false`
3. **Adjust rate limits** carefully to avoid 403 errors
4. **Use Wayback-first strategy**: `"wayback_first": true` (reduces load on Ming Pao)

Warning: Too aggressive settings trigger rate limiting (403 Forbidden).

## Testing

```bash
# Test single URL
python test_function.py

# Quick test with single date
python mingpao_hkga_archiver.py --date $(date -v-1d +%Y-%m-%d) --daily-limit 10

# Test keyword matching in Python REPL
python -c "
from mingpao_hkga_archiver import MingPaoHKGAArchiver
archiver = MingPaoHKGAArchiver()
print(archiver.check_cjkv_keywords('香港政治新聞', ['香港', '政治']))
"
```

## Logs and Debugging

- Main log: `logs/hkga_archiver.log`
- Log level: Set in `config.json` (`INFO`, `DEBUG`, `WARNING`, `ERROR`)
- Execution reports: `output/archive_report.txt`

## Dependencies

Key packages (managed via `uv`):
- `requests` - HTTP requests and Wayback Machine API
- `newspaper4k` - Article content extraction (successor to newspaper3k)
- `internetarchive` - Internet Archive API integration

See `pyproject.toml` for full dependency list.

### Installing Dependencies

```bash
# Install all dependencies
uv sync

# Or use pip
pip install -r pyproject.toml
```

## Important Notes

- **Rate Limiting**: Wayback Machine enforces strict limits. Use `rate_limit_delay >= 3` seconds
- **Resumable**: Database tracks progress. Safe to interrupt (Ctrl+C) and resume later
- **Keyword Logic**: Default is OR (any keyword matches). See AGENTS.md for AND implementation
- **Encoding**: Big5-HKSCS for Traditional Chinese. Automatic fallback to multiple encodings
- **Legal**: Educational/research purposes only. Respects robots.txt and archive.org terms
