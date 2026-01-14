# 明報加拿大港聞 (HK-GA) Wayback Machine 存檔工具

> 將明報加拿大網站的港聞文章存檔至 Internet Archive Wayback Machine，保存香港歷史新聞記錄

## 🌐 Cloud Deployment (Modal)

The archiver is now deployed as a serverless application on **Modal** for reliable, continuous operation.

### Live Endpoints

- **Archive API**: `https://yellowcandle--mingpao-archiver-archive-articles.modal.run`
- **Statistics API**: `https://yellowcandle--mingpao-archiver-get-stats.modal.run`
- **Dashboard**: https://modal.com/apps/yellowcandle/main/deployed/mingpao-archiver

### Quick Usage

```bash
# Archive recent articles
curl -X POST https://yellowcandle--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{"mode": "backdays", "backdays": 7}'

# Check statistics
curl https://yellowcandle--mingpao-archiver-get-stats.modal.run | jq '.'
```

### Deployment Commands

```bash
# Install dependencies
uv sync

# Deploy to Modal
uv run modal deploy modal_app.py

# Run batch job in cloud (continues even if you close terminal)
uv run modal run modal_app.py --start-date 2013-01-01 --end-date 2013-03-31

# Daily auto-archive (runs at 6 AM UTC)
# Already scheduled via modal.Cron() in the app
```

## 📋 功能特色

- 🌐 **雲端部署**：Modal 無伺服器部署，自動擴展
- 🎯 **專注港聞**：專門針對 HK-GA (港聞) 類別文章
- 📅 **批次處理**：支援日期範圍批次存檔（2013-2026）
- 💾 **進度追蹤**：SQLite 數據庫自動記錄所有操作
- 🔄 **IA 優先**：使用 internetarchive 庫作為主要存檔方法
- ⏱️ **速率控制**：內建 rate limiting 保護 Wayback Machine
- 🔁 **錯誤重試**：自動重試機制處理臨時錯誤
- 📊 **統計報告**：詳細的執行統計和報告生成功能
- ⚡ **斷點續傳**：中斷後可從上次進度繼續
- 🤖 **自動排程**：每日 6 AM UTC 自動執行，無需手動干預

## 📁 文件結構

```
mingpao-backup/
├── mingpao_hkga_archiver.py    # 主程序
├── newspaper_extractor.py      # newspaper3k 文章提取模組
├── config.json                 # 配置文件
├── run_archiver.py             # 快速開始執行腳本
├── hkga_archive.db             # SQLite 數據庫 (自動生成)
├── logs/
│   └── hkga_archiver.log       # 執行日誌
└── output/
    └── archive_report.txt      # 存檔報告
```

## 🚀 快速開始

### 方式一：雲端部署（推薦）

直接使用已部署的 Modal 服務，無需本地設置：

```bash
# 檢查統計
curl https://yellowcandle--mingpao-archiver-get-stats.modal.run | jq '.'

# 存檔最近文章
curl -X POST https://yellowcandle--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{"mode": "backdays", "backdays": 7}'
```

### 方式二：本地執行

#### 前置需求

```bash
# Python 3.12+ (使用 uv 管理)
uv --version

# 或傳統方式
python3 --version

# pip 套件
pip install requests newspaper3k internetarchive
```

### 方法一：快速開始 (推薦新手)

直接執行快速開始腳本，會存檔最近 7 天的港聞文章：

```bash
python3 run_archiver.py
```

### 方法二：命令行參數 (推薦進階用戶)

#### 1. 存檔單一日期

```bash
python3 mingpao_hkga_archiver.py --date 2025-01-12
```

#### 2. 存檔日期範圍

```bash
# 存檔整個 2025 年 1 月
python3 mingpao_hkga_archiver.py --start 2025-01-01 --end 2025-01-31
```

#### 3. 回溯 N 天

```bash
# 存檔最近 30 天
python3 mingpao_hkga_archiver.py --backdays 30
```

#### 4. 自定義配置文件

```bash
python3 mingpao_hkga_archiver.py --config my_config.json
```

#### 5. 僅生成報告

```bash
# 不執行存檔，只生成統計報告
python3 mingpao_hkga_archiver.py --report
```

#### 6. 使用 newspaper3k 發現文章 URL

```bash
# 使用 newspaper3k 自動發現文章（實驗性功能）
python3 mingpao_hkga_archiver.py --newspaper

# 或在配置文件中設置
# "use_newspaper": true
```

> **注意**: newspaper3k 可能不適用於所有新聞網站，部分網站可能有反爬蟲措施或特殊結構導致無法正確識別文章 URL。預設使用暴力模式生成 URL，適用於明報的 URL 結構。

### 方法三：修改配置文件

編輯 `config.json` 設置日期範圍，然後執行：

```json
{
  "date_range": {
    "start": "2020-01-01",
    "end": "2025-12-31"
  },
  "daily_limit": 2000,
  "archiving": {
    "rate_limit_delay": 3
  }
}
```

然後執行：

```bash
python3 mingpao_hkga_archiver.py
```

## ⚙️ 配置文件說明

### config.json

```json
{
  "database": {
    "path": "hkga_archive.db"           // SQLite 數據庫路徑
  },
  "logging": {
    "level": "INFO",                     // 日誌級別: DEBUG, INFO, WARNING, ERROR
    "file": "logs/hkga_archiver.log"    // 日誌文件路徑
  },
  "archiving": {
    "rate_limit_delay": 3,              // 每篇文章間隔秒數（建議 ≥3）
    "verify_first": true,               // 是否先檢查 URL 是否存在
    "timeout": 30,                      // 請求超時時間（秒）
    "max_retries": 3,                   // 失敗重試次數
    "retry_delay": 10                   // 重試間隔（秒）
  },
  "daily_limit": 2000,                  // 每天最多存檔文章數
  "date_range": {
    "start": "2025-01-01",              // 存檔開始日期
    "end": "2025-01-31"                 // 存檔結束日期
  }
}
```

## 📊 數據庫結構

### archive_records 表

記錄所有存檔嘗試的詳細信息：

| 欄位 | 類型 | 說明 |
|------|------|------|
| article_url | TEXT | 原始文章 URL |
| wayback_url | TEXT | Wayback Machine 存檔 URL |
| archive_date | TEXT | 文章日期 (YYYYMMDD) |
| status | TEXT | 狀態: success, failed, exists, timeout |
| http_status | INTEGER | HTTP 狀態碼 |
| error_message | TEXT | 錯誤信息 |
| created_at | TIMESTAMP | 創建時間 |
| updated_at | TIMESTAMP | 更新時間 |

### daily_progress 表

記錄每日處理進度：

| 欄位 | 類型 | 說明 |
|------|------|------|
| date | TEXT | 日期 (YYYYMMDD) |
| articles_found | INTEGER | 找到的文章數 |
| articles_archived | INTEGER | 成功存檔數 |
| articles_failed | INTEGER | 失敗數 |
| articles_not_found | INTEGER | 不存在的 URL 數 |
| execution_time | REAL | 執行時間（秒） |
| completed_at | TIMESTAMP | 完成時間 |

## 📈 執行統計

執行完成後會顯示類似以下的統計信息：

```
============================================================
完成: 20250112 (2025-01-12 Sunday)
============================================================
  找到: 23 | 成功: 21 | 失敗: 1 | 不存在: 183
  時間: 85.3 秒
============================================================
```

以及最終統計：

```
============================================================
最終統計
============================================================
文章嘗試: 4832
成功存檔: 4621
已存在: 89
失敗: 122
============================================================
```

## 🔍 日誌文件

所有操作詳細記錄在 `logs/hkga_archiver.log`：

```
2025-01-13 10:30:15 - INFO - 開始處理: 20250112 (2025-01-12 Sunday)
2025-01-13 10:30:18 - INFO - ✅ 存檔成功: http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa1_r.htm
2025-01-13 10:30:18 - INFO -    Wayback: https://web.archive.org/web/20250113103018/http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa1_r.htm
2025-01-13 10:30:21 - INFO - ✅ 存檔成功: http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa2_r.htm
...
```

## ⚠️ 注意事項

### 1. Rate Limiting & Connection Issues
- **Wayback Machine 限制**: 每分鐘最多 15-20 個請求
- **建議設置**: `rate_limit_delay` ≥ 3 秒
- **IA 庫優勢**: 自動處理重試和速率限制
- **HTTP 520 錯誤**: 常見的 Wayback 服務中斷，IA 庫會自動處理
- **每日限制**: 建議 1000-2000 篇/天（視網站響應而定）

### 2. 錯誤重試
- 自動重試 3 次處理超時錯誤
- 指數退避避免持續失敗
- HTTP 4xx 錯誤不會重試（客戶端錯誤）

### 3. 完整性
- 無法保證 100% 存檔（網站可能有訪問限制）
- 建議多次執行補充缺失文章
- 定期增量存檔新文章

### 4. 存檔驗證
- 存檔後可在 Wayback Machine 查閱：https://web.archive.org/web/*/http://www.mingpaocanada.com/tor/htm/News/YYYYMMDD/HK-*.htm
- 建議抽查驗證存檔質量

### 5. 法律與道德
- 僅用於教育研究目的
- 遵守網站 robots.txt
- 不進行商業利用
- 尊重版權，僅作為歷史檔案保存

## 🐛 故障排除

### 問題 1: `requests.exceptions.Timeout`

**原因**: 網絡連接慢或 Wayback Machine 繁忙

**解決**: 
- 增加 `timeout` 到 60 秒
- 增加 `rate_limit_delay` 到 5 秒
- 減少 `daily_limit`

### 問題 2: Rate Limited (403)

**原因**: 請求過於頻繁

**解決**:
- 增加 `rate_limit_delay` 到 5 或更高
- 等待幾小時後繼續

### 問題 3: 找不到 URL (大量 not_found)

**原因**: 可能日期太舊或格式錯誤

**解決**:
- 檢查日期格式是否正確
- 確認網站是否仍存在該日期文章
- 手動訪問幾個 URL 驗證

### 問題 4: 數據庫鎖定 (database is locked)

**原因**: 同時有多個進程訪問

**解決**:
- 確保只運行一個實例
- 刪除 `hkga_archive.db-journal` 臨時文件
- 重試執行

## 📚 進階使用

### 自定義前綴列表

如需存檔其他類別，可修改 `HK_GA_PREFIXES` 列表：

```python
# 在 mingpao_hkga_archiver.py 中
HK_GA_PREFIXES = [
    # 港聞
    'gaa', 'gab', 'gac', 'gad', 'gae', 'gaf',
    'gba', 'gbb', 'gbc', 'gbd', 'gbe', 'gbf',
    
    # 可以加其他類別的前綴
    'taa', 'tab', 'tac',  # 要聞
    'tda', 'tdb', 'tdc',  # 加國新聞
]
```

### 增量存檔

定期執行以存檔新文章：

```bash
# 添加到 crontab（每天凌晨 3 點執行）
0 3 * * * cd /path/to/mingpao-backup && python3 run_archiver.py --backdays 1
```

### 使用 newspaper3k 提取文章內容

如需提取文章完整內容（標題、作者、正文、圖片等），可使用 `newspaper_extractor.py`：

```bash
# 測試提取功能
python newspaper_extractor.py

# API 使用
from newspaper_extractor import MingPaoExtractor
extractor = MingPaoExtractor()
articles = extractor.extract_full_article("http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa1_r.htm")
print(articles['title'], articles['text'][:100])
```

## 🔍 繁體中文關鍵詞過濾

### 功能特色

- **繁體中文關鍵詞匹配**: 支援傳統中文（繁體字）關鍵詞搜索
- ** Wayback 優先策略**: 先檢查 Wayback Machine 是否已有存檔，避免重複請求
- **標題搜索（快速模式）**: 並行處理，5x 加速
- **內容搜索（完整模式）**: 標題 + 正文搜索，更全面但較慢
- **Unicode 正規化**: 正確處理 CJKV 字符

### 配置方法

在 `config.json` 中設置關鍵詞：

```json
{
  "keywords": {
    "enabled": true,
    "terms": ["香港", "政治", "中國", "台灣", "國安法", "選舉", "示威"],
    "case_sensitive": false,
    "language": "zh-TW",
    "search_content": false,
    "parallel_workers": 2,
    "wayback_first": true
  }
}
```

### CLI 使用方法

```bash
# 啟用關鍵詞過濾（標題搜索，快速）
python mingpao_hkga_archiver.py --enable-keywords --keyword "香港" --keyword "政治" --backdays 7

# 使用逗號分隔的關鍵詞
python mingpao_hkga_archiver.py --keywords "香港,政治,中國" --backdays 3

# 啟用完整內容搜索（標題 + 正文）
python mingpao_hkga_archiver.py --enable-keywords --search-content --keywords "香港,示威" --backdays 1

# 區分大小寫
python mingpao_hkga_archiver.py --enable-keywords --case-sensitive --keywords "HK,Hong Kong" --backdays 1

# 禁用關鍵詞過濾
python mingpao_hkga_archiver.py --disable-keywords --backdays 1
```

### 關鍵詞配置說明

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `enabled` | 啟用關鍵詞過濾 | `false` |
| `terms` | 關鍵詞列表（繁體中文） | `["香港", "政治", "中國", ...]` |
| `case_sensitive` | 區分大小寫 | `false` |
| `language` | 語言設置 | `zh-TW` |
| `search_content` | 搜索正文（較慢） | `false` |
| `parallel_workers` | 並行 worker 數量 | `2` |
| `wayback_first` | 先檢查 Wayback | `true` |

### 數據庫記錄

關鍵詞匹配結果會記錄到數據庫：

```sql
-- 查看關鍵詞匹配的文章
SELECT article_url, matched_keywords, article_title 
FROM archive_records 
WHERE matched_keywords IS NOT NULL;

-- 查看關鍵詞過濾統計
SELECT date, articles_found, keywords_filtered 
FROM daily_progress;
```

### 效能表現

- **標題搜索模式**: ~248 個 URL / 分鐘（2 workers）
- **內容搜索模式**: ~20 個 URL / 分鐘（遵從 rate limiting）
- **Wayback 優先**: 減少對原站點的請求

> **注意**: 關鍵詞匹配使用子字符串匹配。如需更精確的詞語匹配，可考慮未來添加 jieba 分詞支援。

### 匯出 CSV

從數據庫匯出已存檔文章列表：

```bash
sqlite3 hkga_archive.db -csv "SELECT * FROM archive_records WHERE status='success'" > archived_articles.csv
```

## 🆘 聯繫支持

如有問題：

1. 檢查日誌文件 `logs/hkga_archiver.log`
2. 檢查數據庫 `hkga_archive.db`
3. 手動測試 URL是否正常訪問
4. 訪問 Wayback Machine 狀態頁面

## 📰 newspaper3k 文章提取模組（可選）

> 注意：專案現在使用 internetarchive 庫作為主要存檔方法，更穩定可靠。

### 安裝

```bash
pip install newspaper3k
python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords')"
```

### 使用方法

```python
from newspaper_extractor import MingPaoExtractor

# 初始化提取器
extractor = MingPaoExtractor(language="zh")

# 提取文章 URL
articles = extractor.extract_article_urls("http://www.mingpaocanada.com/tor")
for a in articles:
    print(a['url'])

# 提取單篇文章完整內容
article = extractor.extract_full_article("http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa1_r.htm")
print(article['title'], article['text'][:200])

# 批量提取
articles = extractor.batch_extract("http://www.mingpaocanada.com/tor", max_articles=10)
```

### WaybackArchiverWithNewspaper

結合 newspaper3k 和 Wayback Machine 存檔：

```python
from newspaper_extractor import MingPaoExtractor, WaybackArchiverWithNewspaper

extractor = MingPaoExtractor()
archiver = WaybackArchiverWithNewspaper(extractor)
results = archiver.archive_articles("http://www.mingpao.com")
print(f"成功: {len(results['archived'])}, 失敗: {len(results['failed'])}")
```

> **注意**: newspaper3k 可能不適用於所有新聞網站。預設使用暴力模式生成 URL，適用於明報的 URL 結構。

## 📄 授權

MIT License - 僅限教育研究用途使用

## 🙏 致謝

- Internet Archive Wayback Machine
- Modal (serverless platform)
- internetarchive Python library
- 明報加拿大 (Ming Pao Canada)
- 香港新聞工作者

## 📊 當前狀態

- **部署狀態**: ✅ 已部署至 Modal
- **主要方法**: 🔄 internetarchive 庫優先
- **統計 API**: 🔍 即時可查
- **自動排程**: ⏰ 每日 6 AM UTC
- **總文章數**: 157,000+ (2013-2026)
- **已處理**: 431+ 篇
- **成功率**: 41% (持續提升中)

**查看最新進度**: `curl https://yellowcandle--mingpao-archiver-get-stats.modal.run | jq '.'`

## ☁️ Cloud Deployment (Modal)

Deploy the archiver to Modal for serverless execution with HTTP API endpoints.

### Quick Setup

1. **Install Modal**:
   ```bash
   pip install modal
   ```

2. **Authenticate** (first time only):
   ```bash
   modal setup
   ```

3. **Deploy to Modal**:
   ```bash
   modal deploy modal_app.py
   ```

4. **Test locally** (optional):
   ```bash
   modal run modal_app.py
   ```

### Usage

Modal provides two HTTP endpoints after deployment:

#### 1. Archive Articles (POST)

Trigger archiving jobs on-demand:

```bash
# Archive single date
curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "date",
    "date": "2026-01-13"
  }'

# Archive date range with keywords
curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "range",
    "start": "2026-01-01",
    "end": "2026-01-31",
    "keywords": ["香港", "政治"],
    "daily_limit": 500
  }'

# Archive last N days
curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "backdays",
    "backdays": 7
  }'
```

#### 2. Get Statistics (GET)

View archiving statistics:

```bash
curl https://YOUR_USERNAME--mingpao-archiver-get-stats.modal.run
```

**Response example**:
```json
{
  "status": "success",
  "total_articles": 425,
  "successful": 398,
  "failed": 27,
  "success_rate": "93.6%",
  "days_processed": 12,
  "recent_archives": [...]
}
```

### Monitoring

**View logs**:
```bash
modal logs mingpao-archiver
```

**Follow logs in real-time**:
```bash
modal logs mingpao-archiver --follow
```

**Check volume contents**:
```bash
modal volume ls mingpao-db
```

**Download database backup**:
```bash
modal volume get mingpao-db /data/hkga_archive.db ./backup.db
```

### Request Parameters

All archiving requests accept these optional parameters:

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `mode` | string | Archiving mode: `date`, `range`, `backdays` | `"date"` |
| `date` | string | Single date (for `mode=date`) | `"2026-01-13"` |
| `start` | string | Start date (for `mode=range`) | `"2026-01-01"` |
| `end` | string | End date (for `mode=range`) | `"2026-01-31"` |
| `backdays` | integer | Days to look back (for `mode=backdays`) | `7` |
| `keywords` | array | Traditional Chinese keywords (optional) | `["香港", "政治"]` |
| `daily_limit` | integer | Max articles per day (optional) | `500` |

### Cost Estimation

Modal pricing (as of 2026):
- **Free tier**: 30 GPU hours/month (CPU usage free during free tier)
- **Compute**: $0.000231/second for CPU
- **Storage**: $0.10/GB-month

**Current performance**:
- **Success rate**: ~41% with IA-first approach
- **Articles processed**: 431+ (historical 2013-2026)
- **Running batch jobs**: Multiple quarterly ranges in parallel

**Estimated costs**:
- Historical batch (157,000 articles): ~471 hours (~$109)
- Daily incremental (40 articles/day): ~80 minutes/month (~$1.1)
- Storage: <1GB for database (<$0.10)
- **Total**: ~$110 for complete archive, then $1-2/month for maintenance

### Advantages

✅ **No server management** - Serverless, auto-scaling
✅ **Persistent storage** - SQLite database persists across runs
✅ **Built-in logging** - View logs in Modal dashboard
✅ **HTTP API** - Easy integration with other tools
✅ **Pay-per-use** - Only charged when running
✅ **Long-running jobs** - 24-hour timeout for large date ranges
✅ **Python-native** - No Docker/Kubernetes knowledge needed
✅ **IA-first approach** - More reliable than direct Wayback HTTP
✅ **Automatic scheduling** - Daily cron job at 6 AM UTC
✅ **Resilient fallbacks** - Handles Wayback outages gracefully
✅ **Progress tracking** - Real-time statistics via API

### Limitations

⚠️ **24-hour timeout** - Very large jobs may need splitting
⚠️ **Cold starts** - First request may be slower (~5-10s)
⚠️ **No direct SQL access** - Use stats endpoint or download database

### Integration Examples

**Scheduled archiving** (using cron + curl):
```bash
# Add to crontab - archive yesterday's articles daily at 3am
0 3 * * * curl -X POST https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run \
  -H "Content-Type: application/json" \
  -d '{"mode": "backdays", "backdays": 1}'
```

**Python integration**:
```python
import requests

response = requests.post(
    "https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run",
    json={
        "mode": "date",
        "date": "2026-01-13",
        "keywords": ["香港", "政治"]
    }
)

result = response.json()
print(f"Status: {result['status']}")
print(f"Articles archived: {result['stats']['successful']}")
```

**JavaScript/Node.js integration**:
```javascript
const response = await fetch(
  'https://YOUR_USERNAME--mingpao-archiver-archive-articles.modal.run',
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      mode: 'date',
      date: '2026-01-13'
    })
  }
);

const result = await response.json();
console.log('Archived:', result.stats.successful, 'articles');
```

---

**重要聲明**: 此工具僅用於保存歷史新聞資料，請遵守相關法律法規和網站使用條款。
