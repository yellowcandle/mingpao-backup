#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
明報加拿大港聞 (HK-GA) Wayback Machine 存檔工具

功能：
- 從指定日期範圍提取所有 HK-GA 文章
- 存檔至 Wayback Machine (web.archive.org)
- 自動記錄進度與失敗項目
- 遵守 rate limiting 和錯誤重試機制
- 可選使用 newspaper3k 自動發現文章 URL
- 支援繁體中文關鍵詞過濾

使用方法：
    python run_archiver.py
"""

import requests
import time
import json
import sqlite3
import unicodedata
import re
from datetime import datetime, timedelta
from pathlib import Path
import logging
import sys
import argparse
from typing import List, Dict, Tuple, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


class RateLimiter:
    """Pre-request rate limiting with token bucket algorithm"""

    def __init__(self, delay: float, max_burst: int = 3):
        self.delay = delay
        self.tokens = max_burst
        self.max_tokens = max_burst
        self.last_request = time.time()
        self.lock = threading.Lock()

    def acquire(self):
        """Wait if needed before making request"""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request
            self.tokens = min(self.max_tokens, self.tokens + elapsed / self.delay)
            if self.tokens < 1:
                wait_time = (1 - self.tokens) * self.delay
                time.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1
            self.last_request = time.time()


class MingPaoHKGAArchiver:
    """明報港聞存檔主要類別"""

    WAYBACK_SAVE_URL = "https://web.archive.org/save/{url}"
    BASE_URL = "http://www.mingpaocanada.com/tor"

    HK_GA_PREFIXES = [
        "gaa",
        "gab",
        "gac",
        "gad",
        "gae",
        "gaf",
        "gba",
        "gbb",
        "gbc",
        "gbd",
        "gbe",
        "gbf",
        "gca",
        "gcb",
        "gcc",
        "gcd",
        "gce",
        "gcf",
        "gga",
        "ggb",
        "ggc",
        "ggd",
        "gge",
        "ggf",
        "ggh",
        "gha",
        "ghb",
        "ghc",
        "ghd",
        "gma",
        "gmb",
    ]

    def __init__(self, config_path="config.json"):
        """初始化存檔器"""
        self.config = self.load_config(config_path)
        self.setup_logging()
        self.setup_database()
        self.setup_directories()

        self.stats = {
            "total_attempted": 0,
            "successful": 0,
            "failed": 0,
            "already_archived": 0,
            "rate_limited": 0,
            "not_found": 0,
        }
        self.stats_lock = threading.Lock()

        rate_limit_delay = self.config["archiving"]["rate_limit_delay"]
        self.rate_limiter = RateLimiter(delay=rate_limit_delay, max_burst=1)

        self.logger.info("=" * 60)
        self.logger.info("明報加拿大港聞 (HK-GA) Wayback Machine 存檔工具")
        self.logger.info(f"啟動時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 60)

    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Rate-limited HTTP request wrapper

        Ensures all outbound HTTP requests (GET, HEAD, POST) respect the global
        rate limiter to prevent connection resets from the server.

        Args:
            method: HTTP method ('GET', 'POST', 'HEAD')
            url: Target URL
            **kwargs: Additional arguments passed to requests

        Returns:
            requests.Response object

        Raises:
            ValueError: If unsupported HTTP method specified
        """
        self.rate_limiter.acquire()

        method_upper = method.upper()
        if method_upper == "GET":
            return requests.get(url, **kwargs)
        elif method_upper == "POST":
            return requests.post(url, **kwargs)
        elif method_upper == "HEAD":
            return requests.head(url, **kwargs)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

    def load_config(self, config_path):
        """載入配置文件"""
        default_config = {
            "database": {"path": "hkga_archive.db"},
            "logging": {"level": "INFO", "file": "logs/hkga_archiver.log"},
            "archiving": {
                "rate_limit_delay": 3,
                "verify_first": True,
                "timeout": 30,
                "max_retries": 3,
                "retry_delay": 10,
            },
            "daily_limit": 2000,
            "date_range": {"start": "2025-01-01", "end": "2025-01-31"},
            "use_newspaper": False,
            "parallel": {
                "enabled": True,
                "max_workers": 3,
                "rate_limit_delay": 1.0,
            },
            "keywords": {
                "enabled": False,
                "terms": ["香港", "政治", "中國", "台灣", "國安法", "選舉", "示威"],
                "case_sensitive": False,
                "language": "zh-TW",
                "script": "traditional",
                "normalization": "NFC",
                "logic": "or",
                "search_content": False,
                "parallel_workers": 2,
                "wayback_first": True,
            },
        }

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                self.merge_config(default_config, user_config)
                return default_config
        except FileNotFoundError:
            self.logger = logging.getLogger(__name__)
            self.logger.warning(f"配置文件 {config_path} 不存在，使用默認配置")
            return default_config

    def merge_config(self, default, user):
        """合併配置"""
        for key, value in user.items():
            if key in default and isinstance(default[key], dict):
                self.merge_config(default[key], value)
            else:
                default[key] = value

    def setup_logging(self):
        """設置日誌系統"""
        log_config = self.config["logging"]
        log_level = getattr(logging, log_config["level"].upper())

        Path("logs").mkdir(exist_ok=True)

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_config["file"]),
                logging.StreamHandler(sys.stdout),
            ],
        )
        self.logger = logging.getLogger(__name__)

    def setup_database(self):
        """設置 SQLite 數據庫"""
        db_path = self.config["database"]["path"]
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA encoding = 'UTF-8'")
        self.cursor = self.conn.cursor()

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS archive_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_url TEXT UNIQUE,
                wayback_url TEXT,
                archive_date TEXT,
                status TEXT,
                http_status INTEGER,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                matched_keywords TEXT,
                checked_wayback BOOLEAN DEFAULT FALSE,
                title_search_only BOOLEAN DEFAULT FALSE,
                article_title TEXT
            )
        """)

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_progress (
                date TEXT PRIMARY KEY,
                articles_found INTEGER,
                articles_archived INTEGER,
                articles_failed INTEGER,
                articles_not_found INTEGER,
                execution_time REAL,
                completed_at TIMESTAMP,
                keywords_filtered INTEGER DEFAULT 0
            )
        """)

        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_status ON archive_records(status);"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_date ON archive_records(archive_date);"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_keywords ON archive_records(matched_keywords);"
        )
        # Performance optimization: Speed up duplicate URL checks
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_article_url ON archive_records(article_url);"
        )
        # Compound index for common query pattern (checking if URL exists with status)
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_url_status ON archive_records(article_url, status);"
        )

        try:
            self.cursor.execute(
                "ALTER TABLE archive_records ADD COLUMN matched_keywords TEXT"
            )
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute(
                "ALTER TABLE archive_records ADD COLUMN checked_wayback INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute(
                "ALTER TABLE archive_records ADD COLUMN title_search_only INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute(
                "ALTER TABLE archive_records ADD COLUMN article_title TEXT"
            )
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute(
                "ALTER TABLE daily_progress ADD COLUMN keywords_filtered INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass

        self.conn.commit()
        self.logger.info(f"數據庫已初始化: {db_path}")

    def setup_directories(self):
        """創建必要的目錄"""
        Path("output").mkdir(exist_ok=True)
        Path("logs").mkdir(exist_ok=True)

    def generate_article_urls(self, target_date: datetime) -> List[str]:
        """生成指定日期的所有可能 HK-GA 文章 URL"""
        if self.config.get("use_newspaper", False):
            return self.generate_article_urls_newspaper(target_date)

        # Use index-based discovery if enabled (much more efficient)
        if self.config.get("use_index_page", True):
            return self._generate_urls_from_index(target_date)

        return self._generate_urls_bruteforce(target_date)

    def _generate_urls_from_index(self, target_date: datetime) -> List[str]:
        """從索引頁爬取實際存在的文章 URL (推薦方法)

        此方法比暴力生成更高效：
        - 只返回真實存在的文章 (~30-40 篇/天)
        - 無需驗證 URL 是否存在
        - 不會產生 404 錯誤
        - 自動發現新的 URL 模式
        """
        date_str = target_date.strftime("%Y%m%d")
        index_url = f"{self.BASE_URL}/htm/News/{date_str}/HK-GAindex_r.htm"

        try:
            self.logger.debug(f"從索引頁爬取: {index_url}")
            response = requests.get(
                index_url,
                timeout=self.config["archiving"]["timeout"],
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            )

            if response.status_code != 200:
                self.logger.warning(
                    f"索引頁不存在 ({response.status_code})，回退到暴力模式: {date_str}"
                )
                return self._generate_urls_bruteforce(target_date)

            # Parse HTML to extract article URLs
            import re

            article_urls = set()

            # Find all href attributes in listing sections
            # Pattern matches: href="../../../htm/News/YYYYMMDD/HK-xxxN_r.htm"
            pattern = r'href="([^"]*htm/News/\d{8}/HK-[^"]+_r\.htm)"'
            matches = re.findall(pattern, response.text)

            for relative_path in matches:
                # Skip index pages (we only want actual articles)
                if "index" in relative_path.lower():
                    continue

                # Convert relative path to absolute URL
                # ../../../htm/News/20260113/HK-gaa1_r.htm -> http://www.mingpaocanada.com/tor/htm/News/20260113/HK-gaa1_r.htm
                absolute_url = relative_path.replace("../../../", f"{self.BASE_URL}/")
                article_urls.add(absolute_url)

            article_list = sorted(list(article_urls))
            self.logger.info(
                f"從索引頁發現 {len(article_list)} 篇文章 (日期: {date_str})"
            )
            return article_list

        except requests.exceptions.RequestException as e:
            self.logger.warning(f"索引頁爬取失敗: {str(e)}，回退到暴力模式")
            return self._generate_urls_bruteforce(target_date)

    def _generate_urls_bruteforce(self, target_date: datetime) -> List[str]:
        """暴力生成 URL (備用方法)

        注意：此方法會生成大量不存在的 URL (~1,120 個/天)
        建議使用 use_index_page: true 改用索引頁爬取
        """
        date_str = target_date.strftime("%Y%m%d")
        base_path = f"{self.BASE_URL}/htm/News/{date_str}"

        article_urls = []

        for prefix in self.HK_GA_PREFIXES:
            for num in range(1, 9):
                url = f"{base_path}/HK-{prefix}{num}_r.htm"
                article_urls.append(url)

        self.logger.debug(f"暴力生成 {len(article_urls)} 個可能 URL 給日期 {date_str}")
        return article_urls

    def generate_article_urls_newspaper(self, target_date: datetime) -> List[str]:
        """
        使用 newspaper4k 發現文章 URL (已棄用)

        警告: 此方法不適用於明報網站，因為網站結構不符合 newspaper4k 的解析模式。
        建議使用預設的暴力 URL 生成模式。
        """
        self.logger.warning(
            "newspaper4k URL 發現模式不適用於明報網站，將使用暴力模式生成 URL"
        )
        self.logger.warning(
            "建議移除 --newspaper 參數或在配置文件中設置 'use_newspaper': false"
        )
        return self._generate_urls_bruteforce(target_date)

    def discover_articles_full(self, base_url: Optional[str] = None) -> List[Dict]:
        """
        使用 newspaper4k 發現並提取文章完整信息 (已棄用)

        警告: 此方法不適用於明報網站。建議使用暴力 URL 生成 + newspaper4k 內容提取。
        """
        self.logger.warning("discover_articles_full 不適用於明報網站，已棄用")
        return []

    def normalize_cjkv_text(self, text: str) -> str:
        """Normalize CJKV text for consistent matching"""
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        try:
            # Normalize to NFC form
            return unicodedata.normalize("NFC", text)
        except Exception:
            return text

    def check_cjkv_keywords(
        self, text: str, terms: List[str], case_sensitive: bool = False
    ) -> List[str]:
        """Check CJKV keywords in text using OR logic"""
        if not text or not terms:
            return []

        text_normalized = self.normalize_cjkv_text(text)
        text_search = text_normalized if case_sensitive else text_normalized.lower()

        matched = []
        for term in terms:
            term_normalized = self.normalize_cjkv_text(term)
            term_search = term_normalized if case_sensitive else term_normalized.lower()

            if term_search in text_search:
                matched.append(term)

        return matched

    def check_wayback_exists(
        self, url: str, timeout: int = 10
    ) -> Tuple[bool, Optional[str]]:
        """Check if URL exists in Wayback Machine, return (exists, wayback_url)"""
        wayback_url = f"https://web.archive.org/web/2/{url}"
        try:
            response = self._make_request("GET", wayback_url, timeout=timeout)
            if response.status_code == 200:
                return True, wayback_url
        except Exception as e:
            self.logger.debug(f"Wayback check failed: {url[:50]} - {str(e)}")
        return False, None

    def extract_title_from_html(self, html: str) -> str:
        """Extract title from HTML content with proper Traditional Chinese encoding"""
        if not html:
            return ""

        try:
            import re

            # Try og:title first (more reliable)
            og_title_match = re.search(
                r'<meta\s+property="og:title"\s+content="([^"]+)"',
                html,
                re.IGNORECASE,
            )
            if og_title_match:
                title = og_title_match.group(1)
                return self.normalize_cjkv_text(title.strip())

            # Fallback to <title> tag
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1)
                title = re.sub(r"\s+", " ", title).strip()

                # Try different encodings for Traditional Chinese
                encodings_to_try = ["big5-hkscs", "big5", "utf-8"]

                for enc in encodings_to_try:
                    try:
                        # First try to decode as the original encoding was likely mis-detected
                        decoded = title.encode("ISO-8859-1").decode(enc)
                        # Normalize the result
                        normalized = self.normalize_cjkv_text(decoded)
                        if normalized and any(
                            "\u4e00" <= c <= "\u9fff" for c in normalized
                        ):
                            return normalized
                    except (UnicodeDecodeError, LookupError):
                        continue

                # Fallback to UTF-8
                return self.normalize_cjkv_text(title)

        except Exception as e:
            self.logger.debug(f"Title extraction failed: {str(e)}")

        return ""

    def extract_title_with_newspaper4k(self, url: str) -> str:
        """
        Extract title using newspaper4k (more robust for some sites)

        This is an alternative to HTML parsing that may work better
        for sites with complex encodings or structures.
        """
        try:
            from newspaper_extractor import extract_title_only

            title = extract_title_only(url, language="zh", timeout=10)
            if title:
                return self.normalize_cjkv_text(title)
        except ImportError:
            self.logger.debug("newspaper_extractor not available")
        except Exception as e:
            self.logger.debug(f"newspaper4k title extraction failed: {str(e)}")

        return ""

    def fetch_html_content(self, url: str, timeout: int = 15) -> Tuple[str, bool]:
        """Fetch HTML content from URL, return (html, from_wayback)"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }

            wayback_first = self.config.get("keywords", {}).get("wayback_first", True)

            # Check Wayback first with longer timeout
            if wayback_first:
                wayback_url = f"https://web.archive.org/web/2/{url}"
                try:
                    response = self._make_request(
                        "GET", wayback_url, timeout=timeout * 2, headers=headers
                    )
                    if response.status_code == 200 and response.text.strip():
                        return response.text, True
                except Exception as e:
                    self.logger.debug(f"Wayback check failed: {url[:50]} - {str(e)}")

            # Try original site with shorter timeout and retry
            for attempt in range(2):
                try:
                    response = self._make_request(
                        "GET",
                        url,
                        timeout=timeout / 2 if attempt == 0 else timeout,
                        headers=headers,
                    )
                    if response.status_code == 200 and response.text.strip():
                        return response.text, False
                except requests.exceptions.ConnectionError as e:
                    if "Connection reset by peer" in str(e) and attempt == 0:
                        self.logger.debug(
                            f"Connection reset on first attempt for {url[:50]}, retrying..."
                        )
                        time.sleep(1)
                        continue
                    raise e
                except Exception as e:
                    self.logger.debug(f"Fetch failed: {url[:50]} - {str(e)}")
                    raise e

        except Exception as e:
            self.logger.debug(f"Fetch failed: {url[:50]} - {str(e)}")

        return "", False

    def filter_urls_by_keywords(
        self, urls: List[str], parallel: bool = False
    ) -> List[Dict]:
        """Filter URLs by keywords with optional parallel processing"""
        keywords_config = self.config.get("keywords", {})
        if not keywords_config.get("enabled", False):
            return [{"url": url, "should_archive": True} for url in urls]

        terms = keywords_config.get("terms", [])
        search_content = keywords_config.get("search_content", False)
        case_sensitive = keywords_config.get("case_sensitive", False)

        if not terms:
            self.logger.warning("關鍵詞列表為空，跳過過濾")
            return [{"url": url, "should_archive": True} for url in urls]

        if parallel and not search_content:
            return self._filter_keywords_parallel(urls, terms, case_sensitive)
        else:
            return self._filter_keywords_sequential(
                urls, terms, case_sensitive, search_content
            )

    def _filter_keywords_sequential(
        self,
        urls: List[str],
        terms: List[str],
        case_sensitive: bool,
        search_content: bool,
    ) -> List[Dict]:
        """Sequential keyword filtering with optional content search"""
        self.logger.info(
            f"開始關鍵詞過濾: {len(terms)} 個關鍵詞, 搜尋內容: {search_content}"
        )

        matching_articles = []
        total = len(urls)

        for i, url in enumerate(urls):
            try:
                html, from_wayback = self.fetch_html_content(url)
                if not html:
                    continue

                title = self.extract_title_from_html(html)
                title_matches = self.check_cjkv_keywords(title, terms, case_sensitive)

                if title_matches:
                    matching_articles.append(
                        {
                            "url": url,
                            "should_archive": True,
                            "title": title,
                            "matched_keywords": title_matches,
                            "from_wayback": from_wayback,
                            "title_search_only": True,
                        }
                    )
                    if i % 20 == 0:
                        self.logger.info(
                            f"進度: {i}/{total}, 找到: {len(matching_articles)} 篇匹配"
                        )
                    continue

                if search_content:
                    content_matches = self.check_cjkv_keywords(
                        html, terms, case_sensitive
                    )
                    if content_matches:
                        all_matches = list(set(title_matches + content_matches))
                        matching_articles.append(
                            {
                                "url": url,
                                "should_archive": True,
                                "title": title,
                                "matched_keywords": all_matches,
                                "from_wayback": from_wayback,
                                "title_search_only": False,
                            }
                        )

            except Exception as e:
                self.logger.debug(f"關鍵詞過濾失敗: {url[:50]} - {str(e)}")
                continue

        percentage = (len(matching_articles) / total * 100) if total > 0 else 0
        self.logger.info(
            f"關鍵詞過濾完成: {len(matching_articles)}/{total} 篇匹配 ({percentage:.1f}%)"
        )
        return matching_articles

    def _filter_keywords_parallel(
        self, urls: List[str], terms: List[str], case_sensitive: bool
    ) -> List[Dict]:
        """Parallel keyword filtering (title-only)"""
        parallel_workers = self.config.get("keywords", {}).get("parallel_workers", 2)

        self.logger.info(
            f"開始關鍵詞過濾 (並行 {parallel_workers} workers): {len(terms)} 個關鍵詞"
        )

        def process_url(url: str) -> Optional[Dict]:
            try:
                html, from_wayback = self.fetch_html_content(url)
                if not html:
                    return None

                title = self.extract_title_from_html(html)
                title_matches = self.check_cjkv_keywords(title, terms, case_sensitive)

                if title_matches:
                    return {
                        "url": url,
                        "should_archive": True,
                        "title": title,
                        "matched_keywords": title_matches,
                        "from_wayback": from_wayback,
                        "title_search_only": True,
                    }
            except Exception as e:
                self.logger.debug(f"Parallel filter failed: {url[:50]} - {str(e)}")
            return None

        matching_articles = []
        total = len(urls)

        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            futures = {executor.submit(process_url, url): url for url in urls}
            completed = 0

            for future in as_completed(futures):
                completed += 1
                result = future.result()
                if result:
                    matching_articles.append(result)

                if completed % 20 == 0:
                    self.logger.info(
                        f"進度: {completed}/{total}, 找到: {len(matching_articles)} 篇匹配"
                    )

        percentage = (len(matching_articles) / total * 100) if total > 0 else 0
        self.logger.info(
            f"關鍵詞過濾完成: {len(matching_articles)}/{total} 篇匹配 ({percentage:.1f}%)"
        )
        return matching_articles

    def record_keyword_result(
        self, article_data: Dict, archive_date: str, status: str = "success"
    ):
        """Record keyword matching result to database"""
        self.cursor.execute(
            """
            INSERT OR REPLACE INTO archive_records
            (article_url, wayback_url, archive_date, status, http_status, error_message,
             matched_keywords, checked_wayback, title_search_only, article_title, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
            (
                article_data.get("url"),
                article_data.get("wayback_url"),
                archive_date,
                status,
                200 if status == "success" else None,
                None if status == "success" else status,
                ",".join(article_data.get("matched_keywords", [])),
                True,
                article_data.get("title_search_only", False),
                article_data.get("title"),
            ),
        )
        self.conn.commit()

    def check_url_exists(self, url: str) -> bool:
        """檢查 URL 是否存在"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = self._make_request(
                "HEAD", url, timeout=10, allow_redirects=True, headers=headers
            )
            return response.status_code == 200
        except Exception as e:
            self.logger.debug(f"檢查 URL 失敗: {url} - {str(e)}")
            return False

    def check_urls_exist_in_db(self, urls: List[str]) -> Set[str]:
        """
        批量檢查 URL 是否已存在於數據庫中（性能優化）

        Args:
            urls: URL 列表

        Returns:
            已存在於數據庫中的 URL 集合
        """
        if not urls:
            return set()

        # Use batch query with IN clause instead of N individual queries
        placeholders = ",".join("?" * len(urls))
        query = f"SELECT article_url FROM archive_records WHERE article_url IN ({placeholders})"

        self.cursor.execute(query, urls)
        existing_urls = {row[0] for row in self.cursor.fetchall()}

        self.logger.debug(
            f"批量查詢: {len(urls)} 個 URL, {len(existing_urls)} 個已存在"
        )
        return existing_urls

    def archive_to_wayback(self, url: str, retry_count=0) -> Dict:
        """存檔單個 URL 到 Wayback Machine

        Note: Rate limiting is now handled by _make_request() wrapper
        """
        with self.stats_lock:
            self.stats["total_attempted"] += 1

        wayback_target = self.WAYBACK_SAVE_URL.format(url=url)
        config = self.config["archiving"]

        # Set User-Agent header for Wayback requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            response = self._make_request(
                "POST", wayback_target, timeout=config["timeout"], headers=headers
            )

            if response.status_code == 200:
                if "Content-Location" in response.headers:
                    wayback_url = (
                        f"https://web.archive.org{response.headers['Content-Location']}"
                    )
                    self.logger.info(f"✅ 存檔成功: {url}")
                    self.logger.info(f"   Wayback: {wayback_url}")
                    with self.stats_lock:
                        self.stats["successful"] += 1
                    return {
                        "status": "success",
                        "wayback_url": wayback_url,
                        "http_status": response.status_code,
                        "error": None,
                    }
                else:
                    wayback_check = f"https://web.archive.org/web/2/{url}"
                    check_resp = self._make_request(
                        "GET", wayback_check, timeout=config["timeout"], headers=headers
                    )
                    if check_resp.status_code == 200:
                        self.logger.info(f"⚡ 已有存檔: {url}")
                        self.logger.info(f"   Wayback: {wayback_check}")
                        with self.stats_lock:
                            self.stats["already_archived"] += 1
                        return {
                            "status": "exists",
                            "wayback_url": wayback_check,
                            "http_status": response.status_code,
                            "error": None,
                        }
                    else:
                        self.logger.warning(f"⚠️  存檔狀態不明: {url}")
                        with self.stats_lock:
                            self.stats["failed"] += 1
                        return {
                            "status": "unknown",
                            "wayback_url": None,
                            "http_status": response.status_code,
                            "error": "Save returned 200 but no Content-Location",
                        }

            elif response.status_code == 403:
                self.logger.warning(f"⏳ Rate limited: {url}")
                with self.stats_lock:
                    self.stats["rate_limited"] += 1
                return {
                    "status": "rate_limited",
                    "wayback_url": None,
                    "http_status": response.status_code,
                    "error": "Rate limited",
                }

            else:
                self.logger.error(f"❌ 失敗 ({response.status_code}): {url}")
                with self.stats_lock:
                    self.stats["failed"] += 1
                return {
                    "status": "failed",
                    "wayback_url": None,
                    "http_status": response.status_code,
                    "error": f"HTTP {response.status_code}",
                }

        except requests.exceptions.Timeout:
            if retry_count < config["max_retries"]:
                self.logger.warning(
                    f"⏱️  超時，重試 {retry_count + 1}/{config['max_retries']}: {url}"
                )
                time.sleep(config["retry_delay"])
                return self.archive_to_wayback(url, retry_count + 1)
            else:
                self.logger.error(f"⏱️  超時 (重試耗盡): {url}")
                with self.stats_lock:
                    self.stats["failed"] += 1
                return {
                    "status": "timeout",
                    "wayback_url": None,
                    "http_status": None,
                    "error": "Timeout after retries",
                }

        except Exception as e:
            self.logger.error(f"💥 例外錯誤: {url} - {str(e)}")
            with self.stats_lock:
                self.stats["failed"] += 1
            return {
                "status": "error",
                "wayback_url": None,
                "http_status": None,
                "error": str(e),
            }

    def record_attempt(self, article_url: str, result: Dict, archive_date: str):
        """記錄存檔嘗試到數據庫"""
        self.cursor.execute(
            """
            INSERT OR REPLACE INTO archive_records 
            (article_url, wayback_url, archive_date, status, http_status, error_message, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
            (
                article_url,
                result.get("wayback_url"),
                archive_date,
                result["status"],
                result.get("http_status"),
                result.get("error"),
            ),
        )
        self.conn.commit()

    def _archive_url_worker(
        self, url: str, date_str: str, lock: threading.Lock
    ) -> Tuple[str, Dict]:
        """Worker function for parallel archiving"""
        conn = sqlite3.connect(self.config["database"]["path"])
        cursor = conn.cursor()

        result = self.archive_to_wayback(url)

        with lock:
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO archive_records 
                    (article_url, wayback_url, archive_date, status, http_status, error_message, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (
                        url,
                        result.get("wayback_url"),
                        date_str,
                        result["status"],
                        result.get("http_status"),
                        result.get("error"),
                    ),
                )
                conn.commit()
            except Exception as e:
                self.logger.debug(f"DB error: {e}")
            finally:
                conn.close()

        return url, result

    def _log_start_banner(self, target_date: datetime, title_mode: str):
        """Log start banner for archiving operations"""
        date_str = target_date.strftime("%Y%m%d")
        self.logger.info("=" * 60)
        self.logger.info(
            f"開始處理 ({title_mode}): {date_str} ({target_date.strftime('%Y-%m-%d %A')})"
        )
        self.logger.info("=" * 60)

    def _get_urls_to_process(
        self, date_str: str, archive_mode: str = "all"
    ) -> List[Dict]:
        """
        Get URLs to process with filtering applied

        Args:
            date_str: Date string in YYYYMMDD format
            archive_mode: "all" or "keywords"

        Returns:
            List of article dictionaries with at least 'url' key
        """
        from datetime import datetime

        target_date = datetime.strptime(date_str, "%Y%m%d")
        article_urls = self.generate_article_urls(target_date)

        self.logger.info(
            f"生成 {len(article_urls)} 個 URL，開始{'關鍵詞' if archive_mode == 'keywords' else ''}過濾..."
        )

        if not article_urls:
            self.logger.warning("沒有生成任何 URL")
            return []

        existing_urls = self.check_urls_exist_in_db(article_urls)

        if archive_mode == "keywords":
            keywords_config = self.config.get("keywords", {})
            search_content = keywords_config.get("search_content", False)
            parallel_config = self.config.get("parallel", {})
            use_parallel = parallel_config.get("enabled", True) and not search_content

            matching_articles = self.filter_urls_by_keywords(
                article_urls, parallel=use_parallel
            )
            articles_to_process = [
                a for a in matching_articles if a["url"] not in existing_urls
            ]

            if matching_articles:
                filtered_count = len(article_urls) - len(matching_articles)
                self.logger.info(
                    f"待處理: {len(articles_to_process)} 篇匹配文章 ({len(existing_urls)} 個已存在)"
                )
            else:
                self.logger.warning("沒有找到匹配的關鍵詞文章")
                articles_to_process = []
        else:
            articles_to_process = [
                {"url": url} for url in article_urls if url not in existing_urls
            ]
            self.logger.info(
                f"待處理: {len(articles_to_process)} 個新 URL ({len(existing_urls)} 個已存在)"
            )

            if self.config["archiving"]["verify_first"]:
                articles_to_process = [
                    {"url": url}
                    for url in articles_to_process
                    if self.check_url_exists(url["url"])
                ]

        return articles_to_process

    def _record_daily_progress(
        self,
        date_str: str,
        found: int,
        archived: int,
        failed: int,
        not_found: int = 0,
        filtered: int = 0,
        execution_time: float = 0,
    ):
        """Record daily progress to database"""
        keywords_config = self.config.get("keywords", {})
        is_keyword_mode = keywords_config.get("enabled", False)

        if is_keyword_mode:
            self.cursor.execute(
                """
                INSERT OR REPLACE INTO daily_progress
                (date, articles_found, articles_archived, articles_failed, articles_not_found, 
                 execution_time, completed_at, keywords_filtered)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
                (
                    date_str,
                    found,
                    archived,
                    failed,
                    not_found,
                    execution_time,
                    filtered,
                ),
            )
        else:
            self.cursor.execute(
                """
                INSERT OR REPLACE INTO daily_progress 
                (date, articles_found, articles_archived, articles_failed, 
                 articles_not_found, execution_time, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (date_str, found, archived, failed, not_found, execution_time),
            )
        self.conn.commit()

    def _archive_with_strategy(
        self, target_date: datetime, mode: str = "all", parallel: bool = False
    ) -> Dict:
        """Core archiving logic with configurable strategy"""
        date_str = target_date.strftime("%Y%m%d")
        title_mode = f"{'關鍵詞' if mode == 'keywords' else ''}過濾{' (並行)' if parallel else ''}"

        self._log_start_banner(target_date, title_mode)

        if mode == "keywords":
            keywords = self.config.get("keywords", {}).get("terms", [])
            self.logger.info(f"關鍵詞: {', '.join(keywords)}")

        start_time = time.time()
        articles_to_process = self._get_urls_to_process(date_str, archive_mode=mode)

        if not articles_to_process:
            filtered = 100  # Placeholder
            return {
                "date": date_str,
                "found": 0,
                "archived": 0,
                "failed": 0,
                "not_found": 0,
                "filtered": filtered if mode == "keywords" else 0,
                "time": time.time() - start_time,
            }

        found = archived = failed = 0
        not_found = 0 if mode == "all" else 0

        if parallel and mode == "all":
            found, archived, failed = self._archive_parallel(
                articles_to_process, date_str
            )
        else:
            found, archived, failed = self._archive_sequential(
                articles_to_process, date_str, mode
            )

        execution_time = time.time() - start_time
        filtered = (
            len(self.generate_article_urls(target_date)) - len(articles_to_process)
            if mode == "keywords"
            else 0
        )

        self._record_daily_progress(
            date_str, found, archived, failed, not_found, filtered, execution_time
        )

        self.logger.info("=" * 60)
        self.logger.info(f"完成: {date_str}")
        if mode == "keywords":
            self.logger.info(
                f"  找到: {found} | 成功: {archived} | 失敗: {failed} | 過濾: {filtered}"
            )
        else:
            self.logger.info(
                f"  找到: {found} | 成功: {archived} | 失敗: {failed} | 不存在: {not_found}"
            )
        self.logger.info(f"  時間: {execution_time:.1f} 秒")
        self.logger.info("=" * 60)

        return {
            "date": date_str,
            "found": found,
            "archived": archived,
            "failed": failed,
            "not_found": not_found,
            "filtered": filtered if mode == "keywords" else 0,
            "time": execution_time,
        }

    def _archive_sequential(
        self, articles: List[Dict], date_str: str, mode: str
    ) -> Tuple[int, int, int]:
        """Sequential archiving of articles"""
        found = archived = failed = 0
        total = len(articles)

        for i, article in enumerate(articles):
            url = article["url"]
            found += 1

            result = self.archive_to_wayback(url)

            if mode == "keywords":
                article["wayback_url"] = result.get("wayback_url")
                self.record_keyword_result(article, date_str, result["status"])
                if result["status"] in ["success", "exists"]:
                    archived += 1
                    self.logger.info(
                        f"✅ {', '.join(article.get('matched_keywords', []))}: {url[:60]}..."
                    )
                else:
                    failed += 1
            else:
                self.record_attempt(url, result, date_str)
                if result["status"] in ["success", "exists"]:
                    archived += 1
                else:
                    failed += 1

            if found >= self.config["daily_limit"]:
                self.logger.warning(f"達到每日限制: {self.config['daily_limit']}")
                break

            if i % 10 == 0 or i == total - 1:
                self.logger.info(f"進度: {i + 1}/{total} 篇已處理...")

        return found, archived, failed

    def _archive_parallel(
        self, articles: List[Dict], date_str: str
    ) -> Tuple[int, int, int]:
        """Parallel archiving of articles"""
        max_workers = self.config.get("parallel", {}).get("max_workers", 3)
        rate_delay = self.config.get("parallel", {}).get("rate_limit_delay", 1.0)

        found = archived = failed = 0
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._archive_url_worker, article["url"], date_str, lock
                ): article
                for article in articles
            }

            completed = 0
            total = len(futures)

            for future in as_completed(futures):
                completed += 1
                url, result = future.result()

                with self.stats_lock:
                    found += 1
                    if result["status"] in ["success", "exists"]:
                        archived += 1
                    else:
                        failed += 1

                if completed % 10 == 0 or completed == total:
                    progress_pct = (completed / total * 100) if total > 0 else 0
                    self.logger.info(f"進度: {completed}/{total} ({progress_pct:.0f}%)")

                time.sleep(rate_delay / max_workers)

                if found >= self.config["daily_limit"]:
                    self.logger.warning(f"達到每日限制: {self.config['daily_limit']}")
                    for f in list(futures.keys()):
                        f.cancel()
                    break

        return found, archived, failed

    # Old deprecated methods removed - use archive_date() with appropriate config

    def archive_date(self, target_date: datetime):
        """存檔指定日期的所有 HK-GA 文章"""
        keywords_config = self.config.get("keywords", {})
        parallel_config = self.config.get("parallel", {})

        if keywords_config.get("enabled", False):
            search_content = keywords_config.get("search_content", False)
            use_parallel = parallel_config.get("enabled", True) and not search_content
            return self._archive_with_strategy(
                target_date, mode="keywords", parallel=use_parallel
            )

        use_parallel = parallel_config.get("enabled", True)
        return self._archive_with_strategy(
            target_date, mode="all", parallel=use_parallel
        )

    def archive_date_range(self, start_date: datetime, end_date: datetime):
        """存檔指定日期範圍內的所有文章"""
        self.logger.info(f"{'=' * 80}")
        self.logger.info(
            f"批次存檔: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )
        self.logger.info(f"{'=' * 80}")

        total_days = (end_date - start_date).days + 1
        overall = {"days": 0, "found": 0, "archived": 0, "failed": 0}

        for day in range(total_days):
            process_date = start_date + timedelta(days=day)

            self.cursor.execute(
                "SELECT * FROM daily_progress WHERE date = ?",
                (process_date.strftime("%Y%m%d"),),
            )
            if self.cursor.fetchone():
                self.logger.info(f"跳過已完成: {process_date.strftime('%Y-%m-%d')}")
                continue

            try:
                daily_stats = self.archive_date(process_date)
                overall["days"] += 1
                overall["found"] += daily_stats["found"]
                overall["archived"] += daily_stats["archived"]
                overall["failed"] += daily_stats["failed"]

                progress = (day + 1) / total_days * 100
                self.logger.info(
                    f"整體進度: {progress:.1f}% ({day + 1}/{total_days} 天)"
                )

                if day < total_days - 1:
                    self.logger.info("等待 60 秒後繼續...")
                    time.sleep(60)

            except Exception as e:
                self.logger.error(f"處理 {process_date} 時錯誤: {str(e)}")

        return overall

    def calculate_article_priority(
        self, title: str, keywords_matched: List[str]
    ) -> str:
        """Calculate priority based on keywords in title"""
        high_priority_keywords = ["黎智英", "國安處", "國安法", "23條"]
        medium_priority_keywords = ["香港", "政治", "中國", "台灣", "選舉", "示威"]

        if not title:
            return "Low"

        title_lower = title.lower()
        title_kw_lower = (
            [kw.lower() for kw in keywords_matched] if keywords_matched else []
        )
        combined_text = title_lower + " ".join(title_kw_lower)

        for kw in high_priority_keywords:
            if kw.lower() in combined_text:
                return "High"

        count = 0
        for kw in medium_priority_keywords:
            if kw.lower() in combined_text:
                count += 1

        if count >= 2:
            return "High"
        elif count == 1:
            return "Medium"
        else:
            return "Low"

    def check_wayback_status_batch(
        self, urls: List[str], timeout: int = 15
    ) -> List[Tuple[str, str, Optional[str]]]:
        """Check Wayback status for multiple URLs"""
        results = []

        for url in urls:
            self.rate_limiter.acquire()
            exists, wayback_url = self.check_wayback_exists(url, timeout)
            if exists:
                results.append((url, "Already Archived", wayback_url))
            else:
                results.append((url, "Not Archived", None))

        return results

    def generate_article_csv(
        self,
        start_date: datetime,
        end_date: datetime,
        output_file: Optional[str] = None,
        verify_urls: bool = True,
        check_wayback: bool = True,
    ) -> Dict[str, any]:
        """Generate CSV for crowdsourced archiving

        Args:
            start_date: Start date for range
            end_date: End date for range
            output_file: Output CSV path (auto-generated if None)
            verify_urls: Verify URLs exist before including
            check_wayback: Check Wayback status for each URL

        Returns:
            Dict with statistics about generated CSV
        """
        import csv

        if not output_file:
            output_file = f"articles_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"

        self.logger.info("=" * 80)
        self.logger.info(f"Generating CSV for crowdsourced archiving")
        self.logger.info(
            f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )
        self.logger.info(f"Output file: {output_file}")
        self.logger.info(f"Verify URLs: {verify_urls}")
        self.logger.info(f"Check Wayback: {check_wayback}")
        self.logger.info("=" * 80)

        start_time = time.time()

        keywords_config = self.config.get("keywords", {})
        keyword_terms = keywords_config.get("terms", [])

        total_days_processed = 0
        total_articles_found = 0
        total_need_archiving = 0
        total_already_archived = 0
        total_nonexistent = 0

        with open(output_file, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "Date",
                    "Title",
                    "URL",
                    "Wayback Status",
                    "Priority",
                    "Keywords",
                    "Notes",
                ]
            )

            total_days = (end_date - start_date).days + 1

            for day in range(total_days):
                process_date = start_date + timedelta(days=day)
                date_str = process_date.strftime("%Y%m%d")
                date_display = process_date.strftime("%Y-%m-%d")

                self.logger.info(f"Processing date: {date_display}")

                article_urls = self.generate_article_urls(process_date)

                if verify_urls:
                    self.logger.info(f"  Verifying {len(article_urls)} URLs...")
                    existing_urls = []
                    for url in article_urls:
                        if self.check_url_exists(url):
                            existing_urls.append(url)

                    self.logger.info(f"  Found {len(existing_urls)} valid URLs")
                    urls_to_process = existing_urls
                else:
                    urls_to_process = article_urls

                if not urls_to_process:
                    self.logger.warning(f"  No URLs to process for {date_display}")
                    continue

                if check_wayback:
                    self.logger.info(
                        f"  Checking Wayback status for {len(urls_to_process)} URLs..."
                    )
                    wayback_results = self.check_wayback_status_batch(urls_to_process)
                else:
                    wayback_results = [
                        (url, "Unknown", None) for url in urls_to_process
                    ]

                self.logger.info(f"  Extracting titles and generating CSV rows...")
                processed_for_date = 0
                archived_for_date = 0
                need_archiving_for_date = 0

                for i, url in enumerate(urls_to_process):
                    try:
                        wayback_status = wayback_results[i][1]
                        wayback_url = wayback_results[i][2]

                        if wayback_status == "Already Archived":
                            archived_for_date += 1
                            writer.writerow(
                                [
                                    date_display,
                                    "",
                                    url,
                                    wayback_status,
                                    "",
                                    "",
                                    "Already in Wayback",
                                ]
                            )
                            continue

                        html, _ = self.fetch_html_content(url)
                        if not html:
                            writer.writerow(
                                [
                                    date_display,
                                    "",
                                    url,
                                    wayback_status,
                                    "",
                                    "",
                                    "Failed to fetch content",
                                ]
                            )
                            continue

                        title = self.extract_title_from_html(html)
                        if not title:
                            title = self.extract_title_with_newspaper4k(url)

                        matched_keywords = (
                            self.check_cjkv_keywords(title, keyword_terms)
                            if title
                            else []
                        )
                        priority = self.calculate_article_priority(
                            title, matched_keywords
                        )
                        keywords_str = (
                            ",".join(matched_keywords) if matched_keywords else ""
                        )

                        writer.writerow(
                            [
                                date_display,
                                title,
                                url,
                                wayback_status,
                                priority,
                                keywords_str,
                                "",
                            ]
                        )

                        processed_for_date += 1
                        if wayback_status == "Not Archived":
                            need_archiving_for_date += 1

                        if (i + 1) % 10 == 0:
                            self.logger.info(
                                f"    Processed {i + 1}/{len(urls_to_process)} URLs"
                            )

                    except Exception as e:
                        self.logger.debug(f"Error processing {url}: {str(e)}")
                        writer.writerow(
                            [
                                date_display,
                                "",
                                url,
                                "Unknown",
                                "",
                                "",
                                f"Error: {str(e)}",
                            ]
                        )
                        continue

                total_days_processed += 1
                total_articles_found += processed_for_date
                total_already_archived += archived_for_date
                total_need_archiving += need_archiving_for_date
                total_nonexistent += (
                    len(article_urls) - len(urls_to_process) if verify_urls else 0
                )

                self.logger.info(
                    f"  Date {date_display}: "
                    f"{processed_for_date} processed, "
                    f"{need_archiving_for_date} need archiving, "
                    f"{archived_for_date} already archived"
                )

                if day < total_days - 1:
                    rate_delay = self.config["archiving"]["rate_limit_delay"]
                    self.logger.info(f"  Waiting {rate_delay}s before next date...")
                    time.sleep(rate_delay)

        execution_time = time.time() - start_time

        self.logger.info("=" * 80)
        self.logger.info("CSV Generation Complete!")
        self.logger.info(f"Output file: {output_file}")
        self.logger.info(f"Time taken: {execution_time:.1f} seconds")
        self.logger.info("=" * 80)
        self.logger.info(f"Days processed: {total_days_processed}")
        self.logger.info(f"Total articles found: {total_articles_found}")
        self.logger.info(f"Need archiving: {total_need_archiving}")
        self.logger.info(f"Already archived: {total_already_archived}")
        self.logger.info(f"Non-existent URLs: {total_nonexistent}")
        self.logger.info("=" * 80)

        return {
            "output_file": output_file,
            "days_processed": total_days_processed,
            "total_articles_found": total_articles_found,
            "need_archiving": total_need_archiving,
            "already_archived": total_already_archived,
            "nonexistent_urls": total_nonexistent,
            "execution_time": execution_time,
        }

    def generate_report(self):
        """生成存檔報告"""
        self.cursor.execute("SELECT COUNT(*) FROM archive_records")
        total = self.cursor.fetchone()[0]

        self.cursor.execute(
            "SELECT COUNT(*) FROM archive_records WHERE status = 'success'"
        )
        success = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM daily_progress")
        days = self.cursor.fetchone()[0]

        # 避免除以 0 錯誤
        success_rate = (success / total * 100) if total > 0 else 0

        report = f"""
{"=" * 60}
明報港聞 HK-GA 存檔報告
生成時間: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
{"=" * 60}
        
📊 總計:
• 處理天數: {days} 天
• 總嘗試: {total} 篇文章
• 成功: {success} 篇
• 成功率: {success_rate:.1f}%
        
📈 統計:
• 已嘗試: {self.stats["total_attempted"]}
• 成功: {self.stats["successful"]}
• 已存在: {self.stats["already_archived"]}
• 失敗: {self.stats["failed"]}
• Rate limited: {self.stats["rate_limited"]}
        
💾 文件:
• 數據庫: {self.config["database"]["path"]}
• 日誌: {self.config["logging"]["file"]}
{"=" * 60}
        """

        print(report)

        with open("output/archive_report.txt", "w", encoding="utf-8") as f:
            f.write(report)

        self.logger.info("報告已生成: output/archive_report.txt")

    def close(self):
        """關閉數據庫連接"""
        self.generate_report()
        self.conn.close()
        self.logger.info("數據庫連接已關閉")


def parse_date(date_str: str) -> datetime:
    """解析日期字符串"""
    for fmt in ["%Y-%m-%d", "%Y%m%d"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"無法解析日期: {date_str}")


def main():
    """主執行函數"""
    parser = argparse.ArgumentParser(
        description="明報加拿大港聞 (HK-GA) Wayback Machine 存檔工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 存檔指定日期範圍 (從配置文件讀取)
  python run_archiver.py

  # 存檔單一日期
  python run_archiver.py --date 2025-01-12

  # 存檔日期範圍
  python run_archiver.py --start 2025-01-01 --end 2025-01-31

  # 使用自定義配置文件
  python run_archiver.py --config my_config.json

  # 從今天開始回溯 N 天
  python run_archiver.py --backdays 30
        """,
    )

    parser.add_argument(
        "--config", default="config.json", help="配置文件路徑 (默認: config.json)"
    )
    parser.add_argument("--date", help="存檔指定日期 (格式: YYYY-MM-DD)")
    parser.add_argument("--start", help="開始日期 (格式: YYYY-MM-DD)")
    parser.add_argument("--end", help="結束日期 (格式: YYYY-MM-DD)")
    parser.add_argument("--backdays", type=int, help="從今天開始回溯 N 天")
    parser.add_argument("--report", action="store_true", help="僅生成報告，不執行存檔")
    parser.add_argument("--daily-limit", type=int, help="每日存檔限制 (覆蓋配置文件)")
    parser.add_argument(
        "--newspaper", action="store_true", help="使用 newspaper3k 發現文章 URL"
    )
    parser.add_argument(
        "--keyword",
        action="append",
        dest="keywords",
        default=[],
        help="關鍵詞 (可多次使用，如: --keyword 香港 --keyword 政治)",
    )
    parser.add_argument(
        "--keywords",
        dest="keywords_comma",
        help="關鍵詞列表 (逗號分隔，如: 香港,政治,中國)",
    )
    parser.add_argument(
        "--search-content",
        action="store_true",
        help="搜尋文章內容 (預設只搜尋標題，較慢)",
    )
    parser.add_argument(
        "--case-sensitive", action="store_true", help="區分大小寫 (預設不區分)"
    )
    parser.add_argument(
        "--enable-keywords",
        action="store_true",
        help="啟用關鍵詞過濾 (需要配合 --keyword 或 config.json)",
    )
    parser.add_argument(
        "--disable-keywords",
        action="store_true",
        help="禁用關鍵詞過濾 (覆蓋 config.json)",
    )
    parser.add_argument(
        "--generate-csv",
        action="store_true",
        help="Generate CSV for crowdsourced archiving (no actual archiving)",
    )
    parser.add_argument(
        "--csv-output",
        help="Output CSV file path for crowdsourced archiving",
    )
    parser.add_argument(
        "--csv-no-verify",
        action="store_true",
        help="Skip URL verification in CSV generation (faster)",
    )
    parser.add_argument(
        "--csv-no-wayback-check",
        action="store_true",
        help="Skip Wayback status check in CSV generation (faster)",
    )

    args = parser.parse_args()

    # 創建存檔器實例
    archiver = MingPaoHKGAArchiver(args.config)

    # 處理 daily limit 覆蓋
    if args.daily_limit:
        archiver.config["daily_limit"] = args.daily_limit
        archiver.logger.info(f"每日限制設為: {args.daily_limit}")

    # 如果使用 newspaper3k
    if args.newspaper:
        archiver.config["use_newspaper"] = True
        archiver.logger.info("啟用 newspaper3k URL 發現模式")

    # 處理關鍵詞參數
    if args.disable_keywords:
        archiver.config["keywords"]["enabled"] = False
        archiver.logger.info("已禁用關鍵詞過濾")

    if args.enable_keywords or args.keywords or args.keywords_comma:
        archiver.config["keywords"]["enabled"] = True
        archiver.logger.info("已啟用關鍵詞過濾")

    all_keywords = []
    if args.keywords:
        all_keywords.extend(args.keywords)
    if args.keywords_comma:
        all_keywords.extend([k.strip() for k in args.keywords_comma.split(",")])

    if all_keywords:
        archiver.config["keywords"]["terms"] = all_keywords
        archiver.logger.info(f"關鍵詞: {', '.join(all_keywords)}")

    if args.search_content:
        archiver.config["keywords"]["search_content"] = True
        archiver.logger.info("啟用內容搜尋 (標題 + 正文)")

    if args.case_sensitive:
        archiver.config["keywords"]["case_sensitive"] = True
        archiver.logger.info("區分大小寫")

    # 如果只需要報告
    if args.report:
        archiver.generate_report()
        archiver.close()
        return

    # 處理 CSV 生成
    if args.generate_csv:
        verify_urls = not args.csv_no_verify
        check_wayback = not args.csv_no_wayback_check
        output_file = args.csv_output

        end_date = datetime.now()
        if args.backdays:
            start_date = end_date - timedelta(days=args.backdays - 1)
        elif args.start and args.end:
            start_date = parse_date(args.start)
            end_date = parse_date(args.end)
        elif args.date:
            start_date = parse_date(args.date)
            end_date = start_date
        else:
            date_config = archiver.config["date_range"]
            start_date = parse_date(date_config["start"])
            end_date = parse_date(date_config["end"])

        archiver.logger.info("=" * 80)
        archiver.logger.info("CSV crowdsourced archiving generation mode")
        archiver.logger.info(
            f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )
        archiver.logger.info(f"Verify URLs: {verify_urls}")
        archiver.logger.info(f"Check Wayback: {check_wayback}")
        archiver.logger.info("=" * 80)

        try:
            result = archiver.generate_article_csv(
                start_date=start_date,
                end_date=end_date,
                output_file=output_file,
                verify_urls=verify_urls,
                check_wayback=check_wayback,
            )
            archiver.close()
            return
        except Exception as e:
            print(f"CSV generation error: {str(e)}")
            archiver.close()
            return

    # 處理日期參數
    today = datetime.now()

    if args.date:
        # 存檔單一日期
        target_date = parse_date(args.date)
        archiver.logger.info(f"存檔單一日期: {target_date.strftime('%Y-%m-%d')}")
        try:
            result = archiver.archive_date(target_date)
        except Exception as e:
            print(f"執行錯誤: {str(e)}")
            return
    elif args.start and args.end:
        # 存檔日期範圍
        start_date = parse_date(args.start)
        end_date = parse_date(args.end)
        archiver.logger.info(
            f"存檔日期範圍: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"
        )
        try:
            result = archiver.archive_date_range(start_date, end_date)
        except Exception as e:
            print(f"執行錯誤: {str(e)}")
            return
    elif args.backdays:
        # 回溯 N 天
        end_date = today
        start_date = today - timedelta(days=args.backdays - 1)
        archiver.logger.info(
            f"回溯 {args.backdays} 天: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"
        )
        try:
            result = archiver.archive_date_range(start_date, end_date)
        except Exception as e:
            print(f"執行錯誤: {str(e)}")
            return
    else:
        # 從配置文件讀取
        date_config = archiver.config["date_range"]
        start_date = parse_date(date_config["start"])
        end_date = parse_date(date_config["end"])
        try:
            result = archiver.archive_date_range(start_date, end_date)
        except Exception as e:
            print(f"執行錯誤: {str(e)}")
            return

    # 顯示最終統計
    archiver.logger.info("\n" + "=" * 60)
    archiver.logger.info("最終統計")
    archiver.logger.info("=" * 60)
    for key, value in archiver.stats.items():
        archiver.logger.info(f"  {key}: {value}")

    # 關閉
    archiver.close()
    archiver.logger.info("數據庫連接已關閉")


if __name__ == "__main__":
    main()
