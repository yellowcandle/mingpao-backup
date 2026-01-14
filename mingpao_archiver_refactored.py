#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Refactored Ming Pao Canada HK-GA Wayback Machine Archiver

This is the main orchestrator that coordinates specialized components:
- URLGenerator: Generates and discovers article URLs
- WaybackArchiver: Handles Wayback Machine operations
- KeywordFilter: Filters articles by Traditional Chinese keywords
- DatabaseRepository: Manages database operations
- RateLimiter: Controls request timing

Benefits of refactoring:
- Single responsibility principle
- Easier testing and maintenance
- Better separation of concerns
- More modular and extensible design
"""

import time
import argparse
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple
import logging
import sys

# Import specialized components
from url_generator import URLGenerator
from wayback_archiver import WaybackArchiver
from keyword_filter import KeywordFilter
from database_repository import (
    ArchiveRepository,
    ArchiveRecord,
    DailyProgress,
)


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


class MingPaoArchiver:
    """
    Main archiver class that coordinates all components

    This refactored version follows the Single Responsibility Principle:
    - Orchestrates workflow between components
    - Handles high-level business logic
    - Manages configuration and lifecycle
    - Delegates specific tasks to specialized classes
    """

    BASE_URL = "http://www.mingpaocanada.com/tor"

    def __init__(self, config_path: str = "config.json"):
        """Initialize the archiver with all components"""
        self.config = self.load_config(config_path)
        self.setup_logging()

        # Initialize repository first
        self.repository = ArchiveRepository(self.config["database"]["path"])

        # Initialize rate limiter
        rate_limit_delay = self.config["archiving"]["rate_limit_delay"]
        self.rate_limiter = RateLimiter(delay=rate_limit_delay, max_burst=1)

        # Initialize statistics first
        self.stats = {
            "total_attempted": 0,
            "successful": 0,
            "failed": 0,
            "already_archived": 0,
            "rate_limited": 0,
            "not_found": 0,
            "unknown": 0,
            "timeout": 0,
            "error": 0,
        }
        self.stats_lock = threading.Lock()

        # Initialize components that depend on stats
        self.url_generator = URLGenerator(self.BASE_URL, self._make_request)
        self.wayback_archiver = WaybackArchiver(
            make_request=self._make_request,
            rate_limiter=self.rate_limiter,
            stats_dict=self.stats,
            stats_lock=self.stats_lock,
        )
        self.keyword_filter = KeywordFilter(
            fetch_content_func=self.fetch_html_content,
            extract_title_func=self.extract_title_from_html,
            config=self.config.get("keywords", {}),
        )

        # Setup directories
        self.setup_directories()

        self.logger.info("=" * 60)
        self.logger.info("明報加拿大港聞 (HK-GA) Wayback Machine 存檔工具 (Refactored)")
        self.logger.info(f"啟動時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 60)

    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Rate-limited HTTP request wrapper"""
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

    def load_config(self, config_path: str) -> Dict:
        """Load and merge configuration"""
        default_config = {
            "database": {"path": "hkga_archive.db"},
            "logging": {"level": "INFO", "file": "logs/hkga_archiver.log"},
            "archiving": {
                "rate_limit_delay": 3,
                "verify_first": False,
                "timeout": 30,
                "max_retries": 3,
                "retry_delay": 10,
            },
            "daily_limit": 2000,
            "date_range": {"start": "2025-01-01", "end": "2025-01-31"},
            "use_newspaper": False,
            "use_newspaper4k_titles": False,
            "use_index_page": True,
            "parallel": {"enabled": False, "max_workers": 2, "rate_limit_delay": 3.0},
            "keywords": {
                "enabled": False,
                "terms": [
                    "香港",
                    "政治",
                    "中國",
                    "台灣",
                    "國安法",
                    "選舉",
                    "示威",
                    "黎智英",
                ],
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
            import json

            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                self.merge_config(default_config, user_config)
                return default_config
        except FileNotFoundError:
            self.logger = logging.getLogger(__name__)
            self.logger.warning(f"配置文件 {config_path} 不存在，使用默認配置")
            return default_config

    def merge_config(self, default: Dict, user: Dict):
        """Recursively merge user config into default"""
        for key, value in user.items():
            if key in default and isinstance(default[key], dict):
                self.merge_config(default[key], value)
            else:
                default[key] = value

    def setup_logging(self):
        """Setup logging system"""
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

    def setup_directories(self):
        """Create necessary directories"""
        Path("output").mkdir(exist_ok=True)
        Path("logs").mkdir(exist_ok=True)

    def fetch_html_content(self, url: str, timeout: int = 15) -> Tuple[str, bool]:
        """Fetch HTML content with Wayback fallback"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }

            wayback_first = self.keyword_filter.should_check_wayback_first()

            # Check Wayback first
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

            # Try original site with retry
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

    def extract_title_from_html(self, html: str) -> str:
        """Extract title with proper encoding handling"""
        if not html:
            return ""

        try:
            import re

            # Try og:title first
            og_title_match = re.search(
                r'<meta\s+property="og:title"\s+content="([^"]+)"',
                html,
                re.IGNORECASE,
            )
            if og_title_match:
                title = og_title_match.group(1)
                return self.keyword_filter.normalize_cjkv_text(title.strip())

            # Fallback to <title> tag
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1)
                title = re.sub(r"\s+", " ", title).strip()

                # Try different encodings for Traditional Chinese
                encodings_to_try = ["big5-hkscs", "big5", "utf-8"]

                for enc in encodings_to_try:
                    try:
                        decoded = title.encode("ISO-8859-1").decode(enc)
                        normalized = self.keyword_filter.normalize_cjkv_text(decoded)
                        if normalized and any(
                            "\u4e00" <= c <= "\u9fff" for c in normalized
                        ):
                            return normalized
                    except (UnicodeDecodeError, LookupError):
                        continue

                return self.keyword_filter.normalize_cjkv_text(title)

        except Exception as e:
            self.logger.debug(f"Title extraction failed: {str(e)}")

        return ""

    def check_url_exists(self, url: str) -> bool:
        """Check if URL exists (legacy method for compatibility)"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            response = self._make_request(
                "HEAD", url, timeout=10, allow_redirects=True, headers=headers
            )
            return response.status_code == 200
        except Exception as e:
            self.logger.debug(f"檢查 URL 失敗: {url} - {str(e)}")
            return False

    def _get_urls_to_process(
        self, target_date: datetime, archive_mode: str = "all"
    ) -> List[Dict]:
        """Get URLs to process with filtering applied"""

        # Generate URLs using URL generator
        article_urls = self.url_generator.generate_article_urls(target_date)

        self.logger.info(
            f"生成 {len(article_urls)} 個 URL，開始{'關鍵詞' if archive_mode == 'keywords' else ''}過濾..."
        )

        if not article_urls:
            self.logger.warning("沒有生成任何 URL")
            return []

        # Check existing URLs in database
        existing_urls = self.repository.get_existing_urls(article_urls)

        if archive_mode == "keywords":
            # Apply keyword filtering
            matching_articles = self.keyword_filter.filter_urls(article_urls)
            articles_to_process = [
                a for a in matching_articles if a["url"] not in existing_urls
            ]

            if matching_articles:
                self.logger.info(
                    f"待處理: {len(articles_to_process)} 篇匹配文章 ({len(existing_urls)} 個已存在)"
                )
            else:
                self.logger.warning("沒有找到匹配的關鍵詞文章")
                articles_to_process = []
        else:
            # Process all URLs
            articles_to_process = [
                {"url": url} for url in article_urls if url not in existing_urls
            ]
            self.logger.info(
                f"待處理: {len(articles_to_process)} 個新 URL ({len(existing_urls)} 個已存在)"
            )

            # Verify URLs if configured
            if self.config["archiving"]["verify_first"]:
                articles_to_process = [
                    {"url": url}
                    for url in articles_to_process
                    if self.check_url_exists(url["url"])
                ]

        return articles_to_process

    def archive_date(self, target_date: datetime, mode: str = "all") -> Dict:
        """Archive articles for a single date"""
        date_str = target_date.strftime("%Y%m%d")
        title_mode = f"{'關鍵詞' if mode == 'keywords' else ''}過濾"

        self.logger.info("=" * 60)
        self.logger.info(
            f"開始處理 ({title_mode}): {date_str} ({target_date.strftime('%Y-%m-%d %A')})"
        )
        self.logger.info("=" * 60)

        if mode == "keywords":
            keywords = self.keyword_filter.get_keywords()
            self.logger.info(f"關鍵詞: {', '.join(keywords)}")

        start_time = time.time()
        articles_to_process = self._get_urls_to_process(target_date, mode)

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

        # Process articles
        found = archived = failed = 0

        if mode == "all":
            found, archived, failed = self._archive_sequential(
                articles_to_process, date_str, mode
            )
        else:
            found, archived, failed = self._archive_sequential(
                articles_to_process, date_str, mode
            )

        # Record progress
        execution_time = time.time() - start_time
        filtered = (
            len(self.url_generator.generate_article_urls(target_date))
            - len(articles_to_process)
            if mode == "keywords"
            else 0
        )

        daily_progress = DailyProgress(
            date=date_str,
            articles_found=found,
            articles_archived=archived,
            articles_failed=failed,
            articles_not_found=0 if mode == "all" else 0,
            keywords_filtered=filtered,
            execution_time=execution_time,
            completed_at=datetime.now(),
        )
        self.repository.save_daily_progress(daily_progress)

        self.logger.info("=" * 60)
        self.logger.info(f"完成: {date_str}")
        if mode == "keywords":
            self.logger.info(
                f"  找到: {found} | 成功: {archived} | 失敗: {failed} | 過濾: {filtered}"
            )
        else:
            self.logger.info(f"  找到: {found} | 成功: {archived} | 失敗: {failed}")
        self.logger.info(f"  時間: {execution_time:.1f} 秒")
        self.logger.info("=" * 60)

        return {
            "date": date_str,
            "found": found,
            "archived": archived,
            "failed": failed,
            "not_found": 0,
            "filtered": filtered,
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

            # Use Wayback archiver
            result = self.wayback_archiver.archive_url(url, self.config["archiving"])

            if mode == "keywords":
                # Save keyword result
                article_record = ArchiveRecord(
                    article_url=url,
                    wayback_url=result.wayback_url,
                    archive_date=date_str,
                    status=result.status,
                    http_status=result.http_status,
                    error_message=result.error,
                    matched_keywords=",".join(article.get("matched_keywords", [])),
                    checked_wayback=True,
                    title_search_only=article.get("title_search_only", False),
                    article_title=article.get("title"),
                )
                self.repository.save_archive_record(article_record)

                if result:
                    archived += 1
                    self.logger.info(
                        f"✅ {', '.join(article.get('matched_keywords', []))}: {url[:60]}..."
                    )
                else:
                    failed += 1
            else:
                # Extract title for all articles (prefer Wayback if available)
                title = None
                try:
                    html, _ = self.fetch_html_content(url)
                    if html:
                        title = self.extract_title_from_html(html)
                        self.logger.debug(f"Extracted title: {title[:50] if title else 'None'}...")
                except Exception as e:
                    self.logger.debug(f"Failed to extract title for {url}: {str(e)}")

                # Save regular result
                article_record = ArchiveRecord(
                    article_url=url,
                    wayback_url=result.wayback_url,
                    archive_date=date_str,
                    status=result.status,
                    http_status=result.http_status,
                    error_message=result.error,
                    checked_wayback=True,
                    article_title=title,
                )
                self.repository.save_archive_record(article_record)

                if result:
                    archived += 1
                else:
                    failed += 1

            if found >= self.config["daily_limit"]:
                self.logger.warning(f"達到每日限制: {self.config['daily_limit']}")
                break

            if i % 10 == 0 or i == total - 1:
                self.logger.info(f"進度: {i + 1}/{total} 篇已處理...")

        return found, archived, failed

    def archive_date_range(
        self, start_date: datetime, end_date: datetime, mode: str = "all"
    ) -> Dict:
        """Archive articles for a date range"""
        results = []
        current_date = start_date

        while current_date <= end_date:
            result = self.archive_date(current_date, mode)
            results.append(result)
            current_date += timedelta(days=1)

        # Aggregate results
        total_found = sum(r["found"] for r in results)
        total_archived = sum(r["archived"] for r in results)
        total_failed = sum(r["failed"] for r in results)
        total_filtered = sum(r["filtered"] for r in results)
        total_time = sum(r["time"] for r in results)

        return {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "days_processed": len(results),
            "found": total_found,
            "archived": total_archived,
            "failed": total_failed,
            "filtered": total_filtered,
            "time": total_time,
            "daily_results": results,
        }

    def generate_report(self):
        """Generate and display archive statistics"""
        stats = self.repository.get_archive_statistics()

        self.logger.info("=" * 60)
        self.logger.info("最終統計")
        self.logger.info("=" * 60)

        if stats:
            total = stats.get("total", 0)
            successful = stats.get("success", 0) + stats.get("exists", 0)
            failed = stats.get("failed", 0)
            timeout = stats.get("timeout", 0)
            rate_limited = stats.get("rate_limited", 0)
            error = stats.get("error", 0)

            self.logger.info(f"文章嘗試: {total}")
            self.logger.info(f"成功存檔: {successful}")
            self.logger.info(f"失敗: {failed}")
            self.logger.info(f"超時: {timeout}")
            self.logger.info(f"Rate limited: {rate_limited}")
            self.logger.info(f"其他錯誤: {error}")

            if total > 0:
                success_rate = (successful / total) * 100
                self.logger.info(f"成功率: {success_rate:.1f}%")
        else:
            self.logger.info("無統計數據")

        self.logger.info("=" * 60)

    def close(self):
        """Cleanup resources"""
        self.repository.close()


def parse_date(date_str: str) -> datetime:
    """Parse date string in various formats"""
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid date format: {date_str}")


def main():
    """Main entry point for command line usage"""
    parser = argparse.ArgumentParser(
        description="明報加拿大港聞 Wayback Machine 存檔工具 (Refactored)"
    )
    parser.add_argument("--date", help="存檔單一日期 (YYYY-MM-DD)")
    parser.add_argument("--start", help="開始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", help="結束日期 (YYYY-MM-DD)")
    parser.add_argument("--backdays", type=int, help="回溯 N 天")
    parser.add_argument("--config", default="config.json", help="配置文件路徑")
    parser.add_argument("--report", action="store_true", help="僅生成報告")
    parser.add_argument("--daily-limit", type=int, help="覆蓋每日限制")

    args = parser.parse_args()

    # Initialize archiver
    archiver = MingPaoArchiver(args.config)

    try:
        if args.report:
            archiver.generate_report()
        elif args.date:
            target_date = parse_date(args.date)
            archiver.archive_date(target_date)
        elif args.start and args.end:
            start_date = parse_date(args.start)
            end_date = parse_date(args.end)
            archiver.archive_date_range(start_date, end_date)
        elif args.backdays:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=args.backdays)
            archiver.archive_date_range(start_date, end_date)
        else:
            # Use config date range
            date_range = archiver.config["date_range"]
            start_date = parse_date(date_range["start"])
            end_date = parse_date(date_range["end"])
            archiver.archive_date_range(start_date, end_date)

    except KeyboardInterrupt:
        print("\n⛔ 用戶中斷執行")
        print("進度已保存至數據庫，下次執行會從中斷處繼續")
    except Exception as e:
        print(f"❌ 執行錯誤: {str(e)}")
        raise
    finally:
        archiver.close()


if __name__ == "__main__":
    main()
