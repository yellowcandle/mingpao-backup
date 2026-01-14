#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strategy pattern for different archiving approaches

Provides interchangeable archiving strategies:
- Sequential processing (safe, simple)
- Parallel processing (fast for title-only filtering)
- Batch processing (cloud deployment)
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import logging


class ArchivingStrategy(ABC):
    """Abstract base class for archiving strategies"""

    @abstractmethod
    def archive_articles(
        self,
        articles: List[Dict],
        date_str: str,
        archiver,  # WaybackArchiver instance
        repository,  # ArchiveRepository instance
        stats_dict: Dict,
        stats_lock,
    ) -> Tuple[int, int, int]:
        """
        Archive articles using this strategy

        Args:
            articles: List of article data to archive
            date_str: Date string in YYYYMMDD format
            archiver: WaybackArchiver instance
            repository: ArchiveRepository instance
            stats_dict: Statistics dictionary to update
            stats_lock: Lock for thread-safe stats updates

        Returns:
            Tuple of (found, archived, failed) counts
        """
        pass


class SequentialStrategy(ArchivingStrategy):
    """
    Sequential archiving strategy

    Processes articles one by one:
    - Safe and reliable
    - Consistent rate limiting
    - Good for content search
    - Lower resource usage
    """

    def archive_articles(
        self,
        articles: List[Dict],
        date_str: str,
        archiver,
        repository,
        stats_dict,
        stats_lock,
    ) -> Tuple[int, int, int]:
        """Process articles sequentially"""
        found = archived = failed = 0
        total = len(articles)
        logger = logging.getLogger(__name__)

        for i, article in enumerate(articles):
            url = article["url"]
            found += 1

            # Use archiver to save URL
            result = archiver.archive_url(url, archiver.config)

            # Save result to database
            if "matched_keywords" in article:
                # Keyword mode
                article_record = repository.create_archive_record(
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
            else:
                # Regular mode
                article_record = repository.create_archive_record(
                    article_url=url,
                    wayback_url=result.wayback_url,
                    archive_date=date_str,
                    status=result.status,
                    http_status=result.http_status,
                    error_message=result.error,
                    checked_wayback=True,
                )

            repository.save_archive_record(article_record)

            # Update statistics
            with stats_lock:
                if result:
                    archived += 1
                else:
                    failed += 1
                stats_dict["total_attempted"] = stats_dict.get("total_attempted", 0) + 1

            # Progress logging
            if "matched_keywords" in article and result:
                logger.info(
                    f"✅ {', '.join(article.get('matched_keywords', []))}: {url[:60]}..."
                )

            if i % 10 == 0 or i == total - 1:
                logger.info(f"進度: {i + 1}/{total} 篇已處理...")

        return found, archived, failed


class ParallelStrategy(ArchivingStrategy):
    """
    Parallel archiving strategy

    Processes articles concurrently:
    - Faster for title-only filtering
    - Higher throughput
    - More complex error handling
    - Requires careful resource management
    """

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers

    def archive_articles(
        self,
        articles: List[Dict],
        date_str: str,
        archiver,
        repository,
        stats_dict,
        stats_lock,
    ) -> Tuple[int, int, int]:
        """Process articles in parallel"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        found = archived = failed = 0
        total = len(articles)
        logger = logging.getLogger(__name__)

        def process_article(article: Dict) -> Tuple[str, bool, Optional[object]]:
            """Worker function for processing single article"""
            url = article["url"]

            try:
                result = archiver.archive_url(url, archiver.config)
                return url, bool(result), result
            except Exception as e:
                logger.error(f"Error processing {url}: {e}")
                return url, False, None

        # Process in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(process_article, article): article
                for article in articles
            }
            completed = 0

            for future in as_completed(futures):
                completed += 1
                url, success, result = future.result()
                found += 1

                # Save result to database
                article_record = repository.create_archive_record(
                    article_url=url,
                    wayback_url=result.wayback_url if result else None,
                    archive_date=date_str,
                    status="success" if success else "failed",
                    http_status=result.http_status if result else None,
                    error_message=result.error if result else "Processing error",
                    checked_wayback=True,
                )
                repository.save_archive_record(article_record)

                # Update statistics
                with stats_lock:
                    if success:
                        archived += 1
                    else:
                        failed += 1
                    stats_dict["total_attempted"] = (
                        stats_dict.get("total_attempted", 0) + 1
                    )

                # Progress logging
                if completed % 10 == 0 or completed == total:
                    logger.info(f"進度: {completed}/{total} 篇已處理...")

        return found, archived, failed


class BatchStrategy(ArchivingStrategy):
    """
    Batch archiving strategy for cloud deployment

    Optimized for large-scale processing:
    - Database batch operations
    - Bulk statistics updates
    - Efficient memory usage
    - Progress checkpointing
    """

    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size

    def archive_articles(
        self,
        articles: List[Dict],
        date_str: str,
        archiver,
        repository,
        stats_dict,
        stats_lock,
    ) -> Tuple[int, int, int]:
        """Process articles in batches"""
        found = archived = failed = 0
        total = len(articles)
        logger = logging.getLogger(__name__)

        # Process in batches
        for batch_start in range(0, total, self.batch_size):
            batch_end = min(batch_start + self.batch_size, total)
            batch_articles = articles[batch_start:batch_end]

            logger.info(
                f"Processing batch {batch_start // self.batch_size + 1}: {len(batch_articles)} articles"
            )

            # Process this batch
            for article in batch_articles:
                url = article["url"]
                found += 1

                result = archiver.archive_url(url, archiver.config)

                # Create record (don't save immediately)
                article_record = repository.create_archive_record(
                    article_url=url,
                    wayback_url=result.wayback_url,
                    archive_date=date_str,
                    status=result.status,
                    http_status=result.http_status,
                    error_message=result.error,
                    checked_wayback=True,
                )

                # Batch save later
                # repository.save_archive_record(article_record)
                repository.save_archive_record(article_record)

                # Update counts
                if result:
                    archived += 1
                else:
                    failed += 1

            # Update batch progress
            progress_pct = (batch_end / total) * 100
            logger.info(f"Batch complete: {batch_end}/{total} ({progress_pct:.1f}%)")

        # Update final statistics
        with stats_lock:
            stats_dict["total_attempted"] = stats_dict.get("total_attempted", 0) + found

        return found, archived, failed


class StrategyFactory:
    """Factory for creating archiving strategies"""

    @staticmethod
    def create_strategy(strategy_type: str, config: Dict = None) -> ArchivingStrategy:
        """
        Create appropriate archiving strategy

        Args:
            strategy_type: Type of strategy ("sequential", "parallel", "batch")
            config: Configuration dictionary

        Returns:
            ArchivingStrategy instance
        """
        if strategy_type == "sequential":
            return SequentialStrategy()
        elif strategy_type == "parallel":
            max_workers = 3
            if config and "parallel" in config:
                max_workers = config["parallel"].get("max_workers", 3)
            return ParallelStrategy(max_workers=max_workers)
        elif strategy_type == "batch":
            batch_size = 100
            if config:
                batch_size = config.get("batch_size", 100)
            return BatchStrategy(batch_size=batch_size)
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")

    @staticmethod
    def get_default_strategy(config: Dict) -> str:
        """
        Get the best strategy based on configuration

        Args:
            config: Configuration dictionary

        Returns:
            Recommended strategy type
        """
        keywords_enabled = config.get("keywords", {}).get("enabled", False)
        search_content = config.get("keywords", {}).get("search_content", False)
        parallel_enabled = config.get("parallel", {}).get("enabled", False)

        if keywords_enabled and search_content:
            # Content search should be sequential due to rate limiting
            return "sequential"
        elif parallel_enabled and not keywords_enabled:
            # Title-only filtering can be parallel
            return "parallel"
        else:
            # Default to safe sequential approach
            return "sequential"


# Backward compatibility wrapper
def get_archiving_strategy(config: Dict) -> ArchivingStrategy:
    """
    Get appropriate archiving strategy for backward compatibility

    Args:
        config: Configuration dictionary

    Returns:
        ArchivingStrategy instance
    """
    strategy_type = StrategyFactory.get_default_strategy(config)
    return StrategyFactory.create_strategy(strategy_type, config)
