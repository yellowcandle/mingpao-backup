#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keyword filtering for Traditional Chinese articles

Handles filtering articles by Traditional Chinese keywords:
- URL-based filtering for performance
- Content-based filtering for completeness
- Unicode normalization for consistent matching
- Parallel processing support
"""

import unicodedata
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Set
import logging


class KeywordFilter:
    """
    Filters articles based on Traditional Chinese keywords

    Features:
    - URL-only filtering (fast, parallel)
    - Content-based filtering (comprehensive)
    - Unicode normalization for CJKV text
    - OR/AND logic support
    - Thread-safe operations
    """

    def __init__(
        self, fetch_content_func: callable, extract_title_func: callable, config: Dict
    ):
        """
        Initialize keyword filter

        Args:
            fetch_content_func: Function to fetch HTML content
            extract_title_func: Function to extract title from HTML
            config: Keywords configuration
        """
        self.fetch_content = fetch_content_func
        self.extract_title = extract_title_func
        self.config = config
        self.logger = logging.getLogger(__name__)

    def should_filter_url(self, url: str) -> bool:
        """Check if URL filtering should be applied"""
        return self.config.get("enabled", False)

    def get_keywords(self) -> List[str]:
        """Get list of configured keywords"""
        return self.config.get("terms", [])

    def is_case_sensitive(self) -> bool:
        """Check if matching should be case sensitive"""
        return self.config.get("case_sensitive", False)

    def should_search_content(self) -> bool:
        """Check if content search is enabled (vs title-only)"""
        return self.config.get("search_content", False)

    def get_parallel_workers(self) -> int:
        """Get number of parallel workers"""
        return self.config.get("parallel_workers", 2)

    def should_check_wayback_first(self) -> bool:
        """Check if Wayback should be checked before original site"""
        return self.config.get("wayback_first", True)

    def normalize_cjkv_text(self, text: str) -> str:
        """
        Normalize CJKV text for consistent matching

        Args:
            text: Text to normalize

        Returns:
            Normalized text
        """
        if not text:
            return ""

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)

        try:
            # Normalize to NFC form
            return unicodedata.normalize("NFC", text)
        except Exception:
            return text

    def check_keywords(
        self, text: str, terms: List[str], case_sensitive: bool = False
    ) -> List[str]:
        """
        Check CJKV keywords in text using OR logic

        Args:
            text: Text to search in
            terms: List of terms to search for
            case_sensitive: Whether matching should be case sensitive

        Returns:
            List of matched terms
        """
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

    def _process_url_sequential(
        self, url: str, terms: List[str], case_sensitive: bool, search_content: bool
    ) -> Optional[Dict]:
        """
        Process single URL for keyword matching (sequential)

        Args:
            url: URL to process
            terms: Keywords to match
            case_sensitive: Case sensitivity setting
            search_content: Whether to search full content

        Returns:
            Article data dict if matched, None otherwise
        """
        try:
            html, from_wayback = self.fetch_content(url)
            if not html:
                return None

            title = self.extract_title(html)
            title_matches = self.check_keywords(title, terms, case_sensitive)

            if title_matches:
                return {
                    "url": url,
                    "should_archive": True,
                    "title": title,
                    "matched_keywords": title_matches,
                    "from_wayback": from_wayback,
                    "title_search_only": True,
                }

            if search_content:
                content_matches = self.check_keywords(html, terms, case_sensitive)
                if content_matches:
                    all_matches = list(set(title_matches + content_matches))
                    return {
                        "url": url,
                        "should_archive": True,
                        "title": title,
                        "matched_keywords": all_matches,
                        "from_wayback": from_wayback,
                        "title_search_only": False,
                    }

        except Exception as e:
            self.logger.debug(f"關鍵詞過濾失敗: {url[:50]} - {str(e)}")

        return None

    def _process_url_parallel(
        self, url: str, terms: List[str], case_sensitive: bool
    ) -> Optional[Dict]:
        """
        Process single URL for keyword matching (parallel, title-only)

        Args:
            url: URL to process
            terms: Keywords to match
            case_sensitive: Case sensitivity setting

        Returns:
            Article data dict if matched, None otherwise
        """
        try:
            html, from_wayback = self.fetch_content(url)
            if not html:
                return None

            title = self.extract_title(html)
            title_matches = self.check_keywords(title, terms, case_sensitive)

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

    def filter_urls_sequential(self, urls: List[str]) -> List[Dict]:
        """
        Sequential keyword filtering with optional content search

        Args:
            urls: List of URLs to filter

        Returns:
            List of matching article data
        """
        terms = self.get_keywords()
        case_sensitive = self.is_case_sensitive()
        search_content = self.should_search_content()

        self.logger.info(
            f"開始關鍵詞過濾: {len(terms)} 個關鍵詞, 搜尋內容: {search_content}"
        )

        matching_articles = []
        total = len(urls)

        for i, url in enumerate(urls):
            result = self._process_url_sequential(
                url, terms, case_sensitive, search_content
            )
            if result:
                matching_articles.append(result)

            if i % 20 == 0:
                self.logger.info(
                    f"進度: {i}/{total}, 找到: {len(matching_articles)} 篇匹配"
                )

        percentage = (len(matching_articles) / total * 100) if total > 0 else 0
        self.logger.info(
            f"關鍵詞過濾完成: {len(matching_articles)}/{total} 篇匹配 ({percentage:.1f}%)"
        )

        return matching_articles

    def filter_urls_parallel(self, urls: List[str]) -> List[Dict]:
        """
        Parallel keyword filtering (title-only for performance)

        Args:
            urls: List of URLs to filter

        Returns:
            List of matching article data
        """
        terms = self.get_keywords()
        case_sensitive = self.is_case_sensitive()
        workers = self.get_parallel_workers()

        self.logger.info(
            f"開始關鍵詞過濾 (並行 {workers} workers): {len(terms)} 個關鍵詞"
        )

        matching_articles = []
        total = len(urls)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self._process_url_parallel, url, terms, case_sensitive
                ): url
                for url in urls
            }
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

    def filter_urls(self, urls: List[str]) -> List[Dict]:
        """
        Filter URLs by keywords with appropriate strategy

        Args:
            urls: List of URLs to filter

        Returns:
            List of matching article data
        """
        if not self.should_filter_url():
            return [{"url": url, "should_archive": True} for url in urls]

        terms = self.get_keywords()
        if not terms:
            self.logger.warning("關鍵詞列表為空，跳過過濾")
            return [{"url": url, "should_archive": True} for url in urls]

        search_content = self.should_search_content()

        # Use parallel processing for title-only filtering
        if not search_content:
            return self.filter_urls_parallel(urls)
        else:
            # Use sequential processing for content search (due to rate limiting)
            return self.filter_urls_sequential(urls)
