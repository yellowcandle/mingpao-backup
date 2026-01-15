# 明報加拿大港聞 (HK-GA) Wayback Machine 存檔工具

> 將明報加拿大網站的港聞文章存檔至 Internet Archive Wayback Machine，保存香港歷史新聞記錄

## 🚀 Quick Start with Docker

The easiest way to run the archiver is using Docker.

### 1. Initial Setup
```bash
# Clone the repository
git clone https://github.com/yellowcandle/mingpao-backup.git
cd mingpao-backup

# Build the Docker image (requires BuildKit for cache optimization)
DOCKER_BUILDKIT=1 docker build -t mingpao-archiver .

# Create necessary directories for persistent data
mkdir -p data logs output

# Set proper permissions (important for some systems)
chmod 755 data logs output
```

### 2. Docker Usage Examples

#### Single Date Archiving
```bash
# Archive a specific date
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --date 2025-06-15

# Archive with custom configuration
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs -v $(pwd)/config.json:/app/config.json \
  mingpao-archiver --date 2025-06-15 --daily-limit 50
```

#### Date Range Archiving
```bash
# Archive a continuous date range
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --start 2025-01-01 --end 2025-01-31

# Archive recent days with keyword filtering
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --backdays 7 --enable-keywords --keyword "香港" --keyword "政治"
```

#### Multiple Non-Consecutive Dates
```bash
# Archive specific dates (new feature!)
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --dates "2025-01-15,2025-01-20,2025-01-25"

# Multiple dates with advanced options
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --dates "2025-01-15,2025-01-20" \
  --enable-keywords --keyword "香港" --daily-limit 20 --search-content
```

#### CSV Generation for Crowdsourcing
```bash
# Generate CSV file for manual archiving (no actual archiving)
docker run -v $(pwd)/data:/data -v $(pwd)/output:/app/output \
  mingpao-archiver --dates "2025-01-15,2025-01-20" --generate-csv \
  --csv-no-verify --csv-no-wayback-check
```

### 3. Docker Compose (Recommended for Production)

Create a `docker-compose.yml` file:
```yaml
version: '3.8'
services:
  archiver:
    build: .
    volumes:
      - ./data:/data
      - ./logs:/logs
      - ./output:/app/output
      - ./config.json:/app/config.json:ro
    environment:
      - TZ=Asia/Hong_Kong
    command: --backdays 3

  stats:
    build: .
    volumes:
      - ./data:/data
    command: --report
```

Usage:
```bash
# Run archiver with compose
docker-compose run archiver --start 2025-01-01 --end 2025-01-31

# View statistics
docker-compose run stats

# Run in detached mode with custom dates
docker-compose run -d archiver --dates "2025-01-15,2025-01-20"
```

### 4. Monitoring and Logs

#### Real-time Monitoring
```bash
# Follow archiver logs in real-time
docker run -v $(pwd)/logs:/logs --rm alpine tail -f logs/hkga_archiver.log

# View recent activity
docker run -v $(pwd)/data:/data --rm alpine sqlite3 data/hkga_archive.db \
  "SELECT archive_date, status, COUNT(*) FROM archive_records GROUP BY archive_date, status ORDER BY archive_date DESC LIMIT 10;"
```

#### Progress Tracking
```bash
# Generate quick report
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --report

# Check database statistics interactively
docker run -v $(pwd)/data:/data -it --rm alpine sh -c '
  apk add --no-cache sqlite3
  sqlite3 data/hkga_archive.db "SELECT * FROM daily_progress ORDER BY date DESC LIMIT 5;"
'
```

## 🤝 Volunteer Guide - Help Us Archive

We need volunteers to help archive 157,000+ historical articles (2013-2026).

### Step 1: Claim a Date Range
1. Check [existing claims](https://github.com/yellowcandle/mingpao-backup/issues?q=label%3Aarchive-claim)
2. [Create a new issue](https://github.com/yellowcandle/mingpao-backup/issues/new?template=archive-claim.yml) to claim your quarter (e.g., 2015 Q1)
3. Wait for confirmation before starting

### Step 2: Run the Archiver
Follow the [Quick Start](#-quick-start-with-docker) instructions to setup, then run your claimed range:

**For continuous date ranges:**
```bash
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --start 2015-01-01 --end 2015-03-31
```

**For specific dates within your range:**
```bash
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --dates "2015-01-05,2015-01-12,2015-01-19,2015-01-26,2015-02-02,2015-02-09,2015-02-16,2015-02-23"
```

**With keyword filtering to focus on important topics:**
```bash
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --start 2015-01-01 --end 2015-03-31 \
  --enable-keywords --keyword "香港" --keyword "政治" --keyword "社會"
```

### Step 3: Report Results
Update your GitHub issue with the summary from `docker-compose run stats`.

---

## 📊 Live Dashboard

Track overall progress: https://yellowcandle--mingpao-archiver-dashboard.modal.run

| Endpoint | URL |
|----------|-----|
| **Dashboard** | https://yellowcandle--mingpao-archiver-dashboard.modal.run |
| **Stats API** | https://yellowcandle--mingpao-archiver-get-stats.modal.run |

## 🛠️ CLI Options

You can pass these flags to the docker command or native installation:

### Date Selection Options
| Flag | Description | Example |
|------|-------------|---------|
| `--date YYYY-MM-DD` | Archive a single date | `--date 2025-06-15` |
| `--dates "D1,D2,D3"` | Archive multiple non-consecutive dates (comma-separated) | `--dates "2025-01-15,2025-01-20,2025-01-25"` |
| `--start YYYY-MM-DD` | Start date for range | `--start 2025-01-01` |
| `--end YYYY-MM-DD` | End date for range | `--end 2025-01-31` |
| `--backdays N` | Archive last N days from today | `--backdays 7` |

### Keyword Filtering Options
| Flag | Description | Example |
|------|-------------|---------|
| `--enable-keywords` | Enable keyword filtering (required) | `--enable-keywords` |
| `--keyword "TERM"` | Add a keyword (repeat for multiple) | `--keyword "香港" --keyword "政治"` |
| `--keywords "A,B,C"` | Comma-separated keywords | `--keywords "香港,政治,社會"` |
| `--search-content` | Search full article body (slower) | `--search-content` |
| `--case-sensitive` | Case-sensitive matching | `--case-sensitive` |

### Performance and Limits
| Flag | Description | Example |
|------|-------------|---------|
| `--daily-limit N` | Limit number of articles per day | `--daily-limit 50` |
| `--config FILE` | Custom configuration file | `--config custom.json` |

### Reporting and CSV Generation
| Flag | Description | Example |
|------|-------------|---------|
| `--report` | Generate report only (no archiving) | `--report` |
| `--generate-csv` | Generate CSV for crowdsourcing | `--generate-csv` |
| `--csv-output FILE` | Custom CSV output path | `--csv-output articles.csv` |
| `--csv-no-verify` | Skip URL verification (faster) | `--csv-no-verify` |
| `--csv-no-wayback-check` | Skip Wayback status check (faster) | `--csv-no-wayback-check` |

### Advanced Options
| Flag | Description | Example |
|------|-------------|---------|
| `--newspaper` | Use newspaper3k for URL discovery | `--newspaper` |
| `--disable-keywords` | Disable keyword filtering | `--disable-keywords` |

## 📋 Features

- 🐳 **Docker Native**: Primary way to run, ensuring environment consistency.
- 🔍 **Keyword Filtering**: Support for Traditional Chinese keyword matching (Title or Body).
- 📅 **Flexible Ranges**: Archive specific dates, ranges, non-consecutive dates, or rolling windows (backdays).
- 💾 **State Persistence**: SQLite database tracks progress to avoid duplicate work.
- ⏱️ **Respectful Archiving**: Built-in rate limiting for Wayback Machine.
- 🌐 **Cloud Dashboard**: Syncs results to a [live dashboard](https://yellowcandle--mingpao-archiver-dashboard.modal.run).

## 🐛 Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| 403 errors from Wayback | Wait 1 hour, then retry (rate limiting) |
| Connection reset by peer | Automatic retry, just wait for recovery |
| Slow progress | Normal - ~40 articles/day per date |
| Docker permission errors | Use `sudo` or add user to docker group |
| Database locked | Ensure only one archiver instance is running |

### Docker-Specific Issues

```bash
# Fix permission issues
sudo chown -R $USER:$USER data logs output

# Clean up failed containers
docker system prune -f

# Check container logs
docker logs $(docker ps -a -q --filter ancestor=mingpao-archiver)

# Run with different user if needed
docker run --user $(id -u):$(id -g) -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --date 2025-06-15
```

### Performance Optimization

```bash
# Increase daily limit for faster processing
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --date 2025-06-15 --daily-limit 100

# Skip keyword filtering for faster full archiving
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --dates "2025-01-15,2025-01-20" --disable-keywords

# Use CSV generation for distributed archiving
docker run -v $(pwd)/data:/data -v $(pwd)/output:/app/output \
  mingpao-archiver --start 2025-01-01 --end 2025-01-31 --generate-csv \
  --csv-no-verify --csv-no-wayback-check
```

## 🐍 Native Installation (Advanced)

If you prefer to run the archiver natively without Docker, we recommend using [uv](https://github.com/astral-sh/uv):

### Setup
```bash
# Clone the repository
git clone https://github.com/yellowcandle/mingpao-backup.git
cd mingpao-backup

# Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Create necessary directories
mkdir -p data logs output
```

### Native Usage Examples
```bash
# Basic archiving
uv run python mingpao_hkga_archiver.py --backdays 7

# Archive multiple non-consecutive dates
uv run python mingpao_hkga_archiver.py --dates "2025-01-15,2025-01-20,2025-01-25"

# Advanced filtering and limits
uv run python mingpao_hkga_archiver.py --dates "2025-01-15,2025-01-20" \
  --enable-keywords --keyword "香港" --daily-limit 10 --search-content

# Generate CSV for crowdsourcing
uv run python mingpao_hkga_archiver.py --start 2025-01-01 --end 2025-01-31 \
  --generate-csv --csv-no-verify
```

### Environment Variables (Optional)
```bash
# Set custom timezone
export TZ=Asia/Hong_Kong

# Custom database location
export HKGA_DB_PATH=/path/to/custom/db.sqlite

# Custom log level
export LOG_LEVEL=DEBUG

# Run with environment variables
uv run python mingpao_hkga_archiver.py --backdays 7
```

### Development Mode
```bash
# Install development dependencies
uv sync --dev

# Run tests
uv run pytest tests/

# Run with debug logging
uv run python -m logging --level=DEBUG mingpao_hkga_archiver.py --date 2025-06-15
```

## ❓ Frequently Asked Questions

### Docker Questions

**Q: Should I use Docker or native installation?**
A: **Use Docker for production/volunteering** - ensures consistency and easier setup. Use native for development or debugging.

**Q: How do I update the archiver?**
```bash
# Pull latest changes
git pull origin main

# Rebuild Docker image (BuildKit required for cache optimization)
DOCKER_BUILDKIT=1 docker build -t mingpao-archiver .

# Or with Docker Compose
DOCKER_BUILDKIT=1 docker-compose build
```

**Q: Can I run multiple instances simultaneously?**
A: Not recommended - database locking may occur. Use `--dates` to process multiple dates sequentially instead.

### Archiving Questions

**Q: How long does it take to archive one date?**
A: Typically 1-3 hours, depending on network and keyword filtering. With keyword filtering: ~30-60 minutes.

**Q: What's the difference between `--search-content` and default?**
A: Default only searches article titles (fast). `--search-content` searches full article body (slow but more comprehensive).

**Q: How do I resume after interruption?**
A: The archiver automatically tracks progress in the database. Simply re-run the same command to continue.

**Q: Can I archive without keyword filtering?**
A: Yes! Use `--disable-keywords` or just don't specify any keywords for full archiving.

### CSV Generation Questions

**Q: When should I use CSV generation?**
A: For distributed archiving with volunteers, or when Wayback Machine is rate-limiting.

**Q: What do the CSV flags do?**
- `--csv-no-verify`: Skip URL verification (faster, but may include invalid URLs)
- `--csv-no-wayback-check`: Skip checking if already archived (faster)

## 📄 License

MIT License - Educational/research use only

## 🙏 Acknowledgments

- Internet Archive Wayback Machine
- All volunteers helping preserve Hong Kong news history
- 明報加拿大 (Ming Pao Canada)
- The open-source community for tools and libraries

---

**Questions?** Open an issue or check [CONTRIBUTING.md](CONTRIBUTING.md) for detailed instructions.

**Found a bug?** Please report with: OS, Docker/native install, command used, and error logs.
