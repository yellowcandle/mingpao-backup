#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
URL generation strategies for Ming Pao Canada articles

Provides different strategies for generating and discovering article URLs:
- Index-based crawling (recommended, efficient)
- Brute-force generation (fallback)
- Newspaper3k discovery (deprecated)
"""

import re
import requests
from datetime import datetime
from typing import List
from abc import ABC, abstractmethod
import logging


class URLGenerationStrategy(ABC):
    """Abstract base class for URL generation strategies"""

    @abstractmethod
    def generate_urls(self, target_date: datetime) -> List[str]:
        """Generate article URLs for the given date"""
        pass


class IndexBasedStrategy(URLGenerationStrategy):
    """
    Fetch URLs from the daily index page (recommended approach)

    More efficient than brute-force:
    - Only returns existing articles (~30-40 per day)
    - No 404 errors
    - Automatically discovers new URL patterns
    """

    def __init__(self, base_url: str, request_func):
        self.base_url = base_url
        self.make_request = request_func
        self.logger = logging.getLogger(__name__)

    def generate_urls(self, target_date: datetime) -> List[str]:
        date_str = target_date.strftime("%Y%m%d")
        index_url = f"{self.base_url}/htm/News/{date_str}/HK-GAindex_r.htm"

        try:
            self.logger.debug(f"從索引頁爬取: {index_url}")
            response = self.make_request(
                "GET",
                index_url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            )

            if response.status_code != 200:
                self.logger.warning(
                    f"索引頁不存在 ({response.status_code})，需要回退到暴力模式: {date_str}"
                )
                return []  # Signal to fall back to brute force

            # Parse HTML to extract article URLs
            article_urls = set()

            # Find all href attributes in listing sections
            pattern = r'href="([^"]*htm/News/\d{8}/HK-[^"]+_r\.htm)"'
            matches = re.findall(pattern, response.text)

            for relative_path in matches:
                # Skip index pages
                if "index" in relative_path.lower():
                    continue

                # Convert relative path to absolute URL
                absolute_url = relative_path.replace("../../../", f"{self.base_url}/")
                article_urls.add(absolute_url)

            article_list = sorted(list(article_urls))
            self.logger.info(
                f"從索引頁發現 {len(article_list)} 篇文章 (日期: {date_str})"
            )
            return article_list

        except requests.exceptions.RequestException as e:
            self.logger.warning(f"索引頁爬取失敗: {str(e)}，回退到暴力模式")
            return []  # Signal to fall back to brute force


class BruteForceStrategy(URLGenerationStrategy):
    """
    Generate all possible URLs using known prefixes and number ranges

    Note: This generates many non-existent URLs (~1,120 per day)
    Should only be used as a fallback when index page is unavailable
    """

    # HK-GA (Hong Kong News) prefixes
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

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.logger = logging.getLogger(__name__)

    def generate_urls(self, target_date: datetime) -> List[str]:
        date_str = target_date.strftime("%Y%m%d")
        base_path = f"{self.base_url}/htm/News/{date_str}"

        article_urls = []

        for prefix in self.HK_GA_PREFIXES:
            for num in range(1, 9):  # HK-gaa1 through HK-gaa8
                url = f"{base_path}/HK-{prefix}{num}_r.htm"
                article_urls.append(url)

        self.logger.debug(f"暴力生成 {len(article_urls)} 個可能 URL 給日期 {date_str}")
        return article_urls


class URLGenerator:
    """
    Main URL generator that coordinates different strategies
    """

    def __init__(self, base_url: str, request_func):
        self.base_url = base_url
        self.make_request = request_func
        self.logger = logging.getLogger(__name__)

        # Initialize strategies
        self.index_strategy = IndexBasedStrategy(base_url, request_func)
        self.brute_force_strategy = BruteForceStrategy(base_url)

    def generate_article_urls(self, target_date: datetime) -> List[str]:
        """
        Generate article URLs using the best available strategy

        Args:
            target_date: Date to generate URLs for

        Returns:
            List of article URLs
        """
        # Try index-based approach first (recommended)
        urls = self.index_strategy.generate_urls(target_date)

        if urls:
            return urls

        # Fall back to brute force if index page unavailable
        self.logger.info("索引頁不可用，使用暴力生成模式")
        return self.brute_force_strategy.generate_urls(target_date)
