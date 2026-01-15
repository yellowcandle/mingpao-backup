# 明報加拿大港聞 (HK-GA) Wayback Machine 存檔工具

> 將明報加拿大網站的港聞文章存檔至 Internet Archive Wayback Machine，保存香港歷史新聞記錄

## 🚀 Quick Start with Docker

The easiest way to run the archiver is using Docker.

### 1. Setup
```bash
# Clone the repository
git clone https://github.com/yellowcandle/mingpao-backup.git
cd mingpao-backup

# Build the image
docker build -t mingpao-archiver .

# Create data and logs directories
mkdir -p data logs
```

### 2. Basic Usage
```bash
# Archive a single date
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --date 2025-06-15

# Archive a date range
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --start 2025-01-01 --end 2025-01-31

# Archive multiple non-consecutive dates
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --dates "2025-01-15,2025-01-20,2025-01-25"

# Archive with keywords (Traditional Chinese)
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --enable-keywords --keyword "香港" --keyword "政治" --backdays 7
```

### 3. Check Progress
```bash
# View archive statistics from the database
docker-compose run stats

# Monitor logs
tail -f logs/hkga_archiver.log
```

## 🤝 Volunteer Guide - Help Us Archive

We need volunteers to help archive 157,000+ historical articles (2013-2026).

### Step 1: Claim a Date Range
1. Check [existing claims](https://github.com/yellowcandle/mingpao-backup/issues?q=label%3Aarchive-claim)
2. [Create a new issue](https://github.com/yellowcandle/mingpao-backup/issues/new?template=archive-claim.yml) to claim your quarter (e.g., 2015 Q1)
3. Wait for confirmation before starting

### Step 2: Run the Archiver
Follow the [Quick Start](#-quick-start-with-docker) instructions to setup, then run your claimed range:
```bash
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --start 2015-01-01 --end 2015-03-31
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

You can pass these flags to the docker command:

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Archive a single date |
| `--dates "D1,D2,D3"` | Archive multiple non-consecutive dates (comma-separated) |
| `--start YYYY-MM-DD` | Start date for range |
| `--end YYYY-MM-DD` | End date for range |
| `--backdays N` | Archive last N days from today |
| `--enable-keywords` | Filter articles by keywords |
| `--keyword "TERM"` | Add a keyword (repeat for multiple) |
| `--search-content` | Search full article body (slower) |
| `--daily-limit N` | Limit number of articles per run |

## 📋 Features

- 🐳 **Docker Native**: Primary way to run, ensuring environment consistency.
- 🔍 **Keyword Filtering**: Support for Traditional Chinese keyword matching (Title or Body).
- 📅 **Flexible Ranges**: Archive specific dates, ranges, non-consecutive dates, or rolling windows (backdays).
- 💾 **State Persistence**: SQLite database tracks progress to avoid duplicate work.
- ⏱️ **Respectful Archiving**: Built-in rate limiting for Wayback Machine.
- 🌐 **Cloud Dashboard**: Syncs results to a [live dashboard](https://yellowcandle--mingpao-archiver-dashboard.modal.run).

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| 403 errors | Wait 1 hour, then retry |
| Connection reset | Automatic retry, just wait |
| Slow progress | Normal - ~40 articles/day per date |

## 🐍 Native Installation (Advanced)

If you prefer to run the archiver natively without Docker, we recommend using [uv](https://github.com/astral-sh/uv):

```bash
# Install dependencies
uv sync

# Run the archiver
uv run python mingpao_hkga_archiver.py --backdays 7

# Archive multiple non-consecutive dates
uv run python mingpao_hkga_archiver.py --dates "2025-01-15,2025-01-20,2025-01-25"

# Archive with keywords and daily limit
uv run python mingpao_hkga_archiver.py --dates "2025-01-15,2025-01-20" --enable-keywords --keyword "香港" --daily-limit 10
```

## 📄 License

MIT License - Educational/research use only

## 🙏 Acknowledgments

- Internet Archive Wayback Machine
- All volunteers helping preserve Hong Kong news history
- 明報加拿大 (Ming Pao Canada)

---

**Questions?** Open an issue or check [CONTRIBUTING.md](CONTRIBUTING.md) for detailed instructions.
