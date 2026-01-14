# 明報加拿大港聞 (HK-GA) Wayback Machine 存檔工具

> 將明報加拿大網站的港聞文章存檔至 Internet Archive Wayback Machine，保存香港歷史新聞記錄

## 🤝 Help Us Archive - Volunteer Guide

We need volunteers to help archive 157,000+ historical articles (2013-2026). Here's how you can help:

### Step 1: Claim a Date Range

1. Check [existing claims](https://github.com/yellowcandle/mingpao-backup/issues?q=label%3Aarchive-claim)
2. [Create a new issue](https://github.com/yellowcandle/mingpao-backup/issues/new?template=archive-claim.yml) to claim your quarter
3. Wait for confirmation before starting

### Step 2: Run the Archiver

```bash
# Clone and build
git clone https://github.com/yellowcandle/mingpao-backup.git
cd mingpao-backup
docker build -t mingpao-archiver .

# Create directories
mkdir -p data logs

# Archive your claimed quarter (example: 2015 Q1)
docker run -v $(pwd)/data:/data -v $(pwd)/logs:/logs \
  mingpao-archiver --start 2015-01-01 --end 2015-03-31
```

### Step 3: Report Results

Update your GitHub issue with:
- Articles archived (check with `docker-compose run stats`)
- Any errors encountered

**Estimated time**: ~6-8 hours per quarter (runs unattended)

---

## 📊 Live Dashboard

Track overall progress: https://yellowcandle--mingpao-archiver-dashboard.modal.run

| Endpoint | URL |
|----------|-----|
| **Dashboard** | https://yellowcandle--mingpao-archiver-dashboard.modal.run |
| **Stats API** | https://yellowcandle--mingpao-archiver-get-stats.modal.run |

## 🐳 Docker Commands

```bash
# Archive single date
docker run -v $(pwd)/data:/data mingpao-archiver --date 2015-06-15

# Archive date range
docker run -v $(pwd)/data:/data mingpao-archiver --start 2015-01-01 --end 2015-03-31

# Check your progress
docker-compose run stats

# View logs
tail -f logs/hkga_archiver.log
```

## 📋 Features

- 🐳 **Docker Support**: Easy local running for volunteers
- 🌐 **Cloud Dashboard**: Real-time progress at Modal
- 📅 **Date Range**: Archive any period from 2013-2026
- 💾 **Resume Support**: Safe to stop and restart
- ⏱️ **Rate Limiting**: Respectful to Wayback Machine

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| 403 errors | Wait 1 hour, then retry |
| Connection reset | Automatic retry, just wait |
| Slow progress | Normal - ~40 articles/day per date |

## 📄 License

MIT License - Educational/research use only

## 🙏 Acknowledgments

- Internet Archive Wayback Machine
- All volunteers helping preserve Hong Kong news history
- 明報加拿大 (Ming Pao Canada)

---

**Questions?** Open an issue or check [CONTRIBUTING.md](CONTRIBUTING.md) for detailed instructions.
