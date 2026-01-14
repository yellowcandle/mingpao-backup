#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wayback Machine archiver module

Handles saving URLs to Internet Archive Wayback Machine using:
- internetarchive Python library for checking existing archives
- HTTP Wayback save API as primary method
- Proper rate limiting and error handling
"""

import time
import threading
from typing import Dict, Optional, Callable
import logging


class ArchiveResult:
    """Result object for Wayback archiving operations"""

    def __init__(
        self,
        status: str,
        wayback_url: Optional[str] = None,
        http_status: Optional[int] = None,
        error: Optional[str] = None,
        retry_count: int = 0,
    ):
        self.status = status  # success, exists, failed, timeout, rate_limited, error
        self.wayback_url = wayback_url
        self.http_status = http_status
        self.error = error
        self.retry_count = retry_count

    def to_dict(self) -> Dict:
        """Convert to dictionary format for backward compatibility"""
        return {
            "status": self.status,
            "wayback_url": self.wayback_url,
            "http_status": self.http_status,
            "error": self.error,
        }

    def __bool__(self) -> bool:
        """Return True if operation was successful or already exists"""
        return self.status in ["success", "exists"]

    def __str__(self) -> str:
        return f"ArchiveResult(status={self.status}, url={self.wayback_url})"


class WaybackArchiver:
    """
    Handles saving URLs to Wayback Machine

    Features:
    - Check existing archives with internetarchive library
    - Rate limiting through external limiter
    - Comprehensive error handling and retries
    - Thread-safe statistics tracking
    """

    WAYBACK_SAVE_URL = "https://web.archive.org/save/{url}"

    def __init__(
        self,
        make_request: Callable,
        rate_limiter: Optional[object] = None,
        stats_dict: Optional[Dict] = None,
        stats_lock: Optional[threading.Lock] = None,
    ):
        """
        Initialize archiver

        Args:
            make_request: Rate-limited HTTP request function
            rate_limiter: Optional rate limiter object
            stats_dict: Dictionary to track statistics
            stats_lock: Lock for thread-safe statistics updates
        """
        self.make_request = make_request
        self.rate_limiter = rate_limiter
        self.stats = stats_dict or {}
        self.stats_lock = stats_lock or threading.Lock()
        self.logger = logging.getLogger(__name__)

    def _update_stats(self, key: str, increment: int = 1):
        """Thread-safe statistics update"""
        if self.stats_lock:
            with self.stats_lock:
                self.stats[key] = self.stats.get(key, 0) + increment

    def _check_existing_archive(self, url: str) -> Optional[ArchiveResult]:
        """
        Check if URL already exists in Wayback Machine

        Uses internetarchive Python library for more reliable checking
        """
        self.logger.debug(f"📥 檢查是否已有存檔: {url}")

        try:
            import internetarchive as ia

            # Search for existing archive of this URL
            search_results = list(
                ia.search_items(
                    f"originalurl:{url}",
                    fields=["identifier"],
                    params={"limit": 1},
                )
            )

            if search_results:
                wayback_check = f"https://web.archive.org/web/2/{url}"
                self.logger.info(f"⚡ 已有存檔: {url}")
                self.logger.info(f"   Wayback: {wayback_check}")
                self._update_stats("already_archived")
                return ArchiveResult(
                    status="exists", wayback_url=wayback_check, http_status=200
                )

        except Exception as search_error:
            self.logger.debug(f"搜尋存檔失敗，使用 HTTP: {search_error}")

        return None

    def _save_via_http(self, url: str, config: Dict) -> ArchiveResult:
        """
        Save URL using HTTP Wayback save API

        Args:
            url: URL to save
            config: Archiving configuration

        Returns:
            ArchiveResult with operation outcome
        """
        self.logger.debug(f"🔄 使用 HTTP 存檔: {url}")
        wayback_target = self.WAYBACK_SAVE_URL.format(url=url)

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            response = self.make_request(
                "POST", wayback_target, timeout=config["timeout"], headers=headers
            )

            # Handle successful save
            if response.status_code == 200:
                return self._handle_success_response(response, url, config)

            # Handle rate limiting
            elif response.status_code in (429, 403):
                self.logger.warning(f"🚫 Rate limited: {url}")
                self._update_stats("rate_limited")
                return ArchiveResult(
                    status="rate_limited",
                    http_status=response.status_code,
                    error="Rate limited",
                )

            # Handle other HTTP errors
            else:
                # Try to check if archived despite error status
                fallback_result = self._check_fallback_archived(url, config)
                if fallback_result:
                    return fallback_result

                self.logger.warning(f"⚠️ HTTP 存檔失敗 ({response.status_code}): {url}")
                self._update_stats("failed")
                return ArchiveResult(
                    status="failed",
                    http_status=response.status_code,
                    error=f"HTTP {response.status_code}",
                )

        except Exception as e:
            self.logger.error(f"💥 例外錯誤: {url} - {str(e)}")
            self._update_stats("failed")
            return ArchiveResult(status="error", error=str(e))

    def _handle_success_response(
        self, response, url: str, config: Dict
    ) -> ArchiveResult:
        """Handle successful response from Wayback save API"""
        if "Content-Location" in response.headers:
            wayback_url = (
                f"https://web.archive.org{response.headers['Content-Location']}"
            )
            self.logger.info(f"✅ 存檔成功: {url}")
            self.logger.info(f"   Wayback: {wayback_url}")
            self._update_stats("successful")
            return ArchiveResult(
                status="success", wayback_url=wayback_url, http_status=200
            )
        else:
            # No Content-Location header, check if archived anyway
            fallback_result = self._check_fallback_archived(url, config)
            if fallback_result:
                self._update_stats("successful")
                return fallback_result
            else:
                self.logger.warning(f"未知存檔狀態: {url}")
                self._update_stats("unknown")
                return ArchiveResult(
                    status="unknown",
                    http_status=response.status_code,
                    error="Save returned 200 but no Content-Location",
                )

    def _check_fallback_archived(
        self, url: str, config: Dict
    ) -> Optional[ArchiveResult]:
        """Fallback check if URL was archived despite non-success response"""
        wayback_check = f"https://web.archive.org/web/2/{url}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            check_resp = self.make_request(
                "GET", wayback_check, timeout=config["timeout"], headers=headers
            )
            if check_resp.status_code == 200:
                self._update_stats("already_archived")
                return ArchiveResult(
                    status="success", wayback_url=wayback_check, http_status=200
                )
        except Exception:
            pass  # Fallback check failed, continue with original error

        return None

    def archive_url(
        self, url: str, config: Dict, retry_count: int = 0
    ) -> ArchiveResult:
        """
        Archive single URL to Wayback Machine

        Args:
            url: URL to archive
            config: Archiving configuration
            retry_count: Current retry attempt number

        Returns:
            ArchiveResult with operation outcome
        """
        # Check existing archive first
        existing = self._check_existing_archive(url)
        if existing:
            return existing

        # Try to save via HTTP
        result = self._save_via_http(url, config)

        # Handle retries for timeouts
        if (
            result.status == "error"
            and result.error
            and "timeout" in result.error.lower()
        ):
            if retry_count < config["max_retries"]:
                self.logger.warning(
                    f"⏱️ 存檔超時，重試 {retry_count + 1}/{config['max_retries']}: {url}"
                )
                time.sleep(config["retry_delay"])
                return self.archive_url(url, config, retry_count + 1)
            else:
                self.logger.error(f"⏱️ 存檔超時（重試次數用盡）: {url}")
                self._update_stats("timeout")
                return ArchiveResult(status="timeout", error="Timeout after retries")

        return result
