#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database repository for Ming Pao archive operations

Provides clean interface for database operations:
- Thread-safe connection management
- Batch operations for performance
- Proper indexing and query optimization
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
import logging
from dataclasses import dataclass


@dataclass
class ArchiveRecord:
    """Data model for archive records"""

    article_url: str
    wayback_url: Optional[str] = None
    archive_date: Optional[str] = None
    status: Optional[str] = None
    http_status: Optional[int] = None
    error_message: Optional[str] = None
    matched_keywords: Optional[str] = None
    checked_wayback: bool = False
    title_search_only: bool = False
    article_title: Optional[str] = None
    id: Optional[int] = None


@dataclass
class DailyProgress:
    """Data model for daily progress tracking"""

    date: str
    articles_found: int = 0
    articles_archived: int = 0
    articles_failed: int = 0
    articles_not_found: int = 0
    keywords_filtered: int = 0
    execution_time: float = 0.0
    completed_at: Optional[datetime] = None
    id: Optional[int] = None


@dataclass
class BatchProgress:
    """Data model for batch progress tracking"""

    batch_id: str
    start_date: str
    end_date: str
    status: str = "pending"  # pending, in_progress, completed, failed
    articles_found: int = 0
    articles_archived: int = 0
    articles_failed: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time: Optional[float] = None


class ArchiveRepository:
    """
    Repository pattern for database operations

    Features:
    - Thread-safe connection management
    - Batch operations for performance
    - Automatic schema creation
    - Proper transaction handling
    """

    def __init__(self, db_path: str = "hkga_archive.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._ensure_database()

    def _ensure_database(self):
        """Create database and tables if they don't exist"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Archive records table
            cursor.execute("""
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

            # Daily progress table
            cursor.execute("""
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

            # Batch progress table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS batch_progress (
                    batch_id TEXT PRIMARY KEY,
                    start_date TEXT,
                    end_date TEXT,
                    status TEXT,
                    articles_found INTEGER DEFAULT 0,
                    articles_archived INTEGER DEFAULT 0,
                    articles_failed INTEGER DEFAULT 0,
                    error_message TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    execution_time REAL
                )
            """)

            # Create indexes for performance
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_status ON archive_records(status)",
                "CREATE INDEX IF NOT EXISTS idx_date ON archive_records(archive_date)",
                "CREATE INDEX IF NOT EXISTS idx_keywords ON archive_records(matched_keywords)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_article_url ON archive_records(article_url)",
                "CREATE INDEX IF NOT EXISTS idx_url_status ON archive_records(article_url, status)",
            ]

            for index_sql in indexes:
                cursor.execute(index_sql)

            conn.commit()
            self.logger.debug("Database schema initialized")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a new database connection"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA encoding = 'UTF-8'")
        return conn

    # Archive Records Operations

    def save_archive_record(self, record: ArchiveRecord) -> bool:
        """Save or update an archive record"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO archive_records
                    (article_url, wayback_url, archive_date, status, http_status, 
                     error_message, matched_keywords, checked_wayback, title_search_only, 
                     article_title, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (
                        record.article_url,
                        record.wayback_url,
                        record.archive_date,
                        record.status,
                        record.http_status,
                        record.error_message,
                        record.matched_keywords,
                        record.checked_wayback,
                        record.title_search_only,
                        record.article_title,
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            self.logger.error(f"Failed to save archive record: {e}")
            return False

    def get_existing_urls(self, urls: List[str]) -> Set[str]:
        """
        Batch check which URLs already exist in database

        Args:
            urls: List of URLs to check

        Returns:
            Set of URLs that already exist
        """
        if not urls:
            return set()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(urls))
                query = f"SELECT article_url FROM archive_records WHERE article_url IN ({placeholders})"
                cursor.execute(query, urls)
                return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            self.logger.error(f"Failed to check existing URLs: {e}")
            return set()

    def get_archive_records_by_date(self, date: str) -> List[ArchiveRecord]:
        """Get all archive records for a specific date"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM archive_records 
                    WHERE archive_date = ? 
                    ORDER BY id
                """,
                    (date,),
                )

                records = []
                for row in cursor.fetchall():
                    records.append(self._row_to_archive_record(row))
                return records
        except Exception as e:
            self.logger.error(f"Failed to get archive records for date {date}: {e}")
            return []

    def _row_to_archive_record(self, row: tuple) -> ArchiveRecord:
        """Convert database row to ArchiveRecord object"""
        return ArchiveRecord(
            id=row[0],
            article_url=row[1],
            wayback_url=row[2],
            archive_date=row[3],
            status=row[4],
            http_status=row[5],
            error_message=row[6],
            matched_keywords=row[8],
            checked_wayback=bool(row[9]),
            title_search_only=bool(row[10]),
            article_title=row[11],
        )

    # Daily Progress Operations

    def save_daily_progress(self, progress: DailyProgress) -> bool:
        """Save or update daily progress"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO daily_progress
                    (date, articles_found, articles_archived, articles_failed, 
                     articles_not_found, keywords_filtered, execution_time, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        progress.date,
                        progress.articles_found,
                        progress.articles_archived,
                        progress.articles_failed,
                        progress.articles_not_found,
                        progress.keywords_filtered,
                        progress.execution_time,
                        progress.completed_at,
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            self.logger.error(f"Failed to save daily progress: {e}")
            return False

    def get_daily_progress(self, date: str) -> Optional[DailyProgress]:
        """Get daily progress for a specific date"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM daily_progress WHERE date = ?
                """,
                    (date,),
                )

                row = cursor.fetchone()
                if row:
                    return self._row_to_daily_progress(row)
                return None
        except Exception as e:
            self.logger.error(f"Failed to get daily progress for date {date}: {e}")
            return None

    def _row_to_daily_progress(self, row: tuple) -> DailyProgress:
        """Convert database row to DailyProgress object"""
        return DailyProgress(
            date=row[0],
            articles_found=row[1],
            articles_archived=row[2],
            articles_failed=row[3],
            articles_not_found=row[4],
            execution_time=row[5],
            completed_at=datetime.fromisoformat(row[6]) if row[6] else None,
            keywords_filtered=row[7],
        )

    # Batch Progress Operations

    def save_batch_progress(self, progress: BatchProgress) -> bool:
        """Save or update batch progress"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO batch_progress
                    (batch_id, start_date, end_date, status, articles_found, 
                     articles_archived, articles_failed, error_message, started_at, 
                     completed_at, execution_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        progress.batch_id,
                        progress.start_date,
                        progress.end_date,
                        progress.status,
                        progress.articles_found,
                        progress.articles_archived,
                        progress.articles_failed,
                        progress.error_message,
                        progress.started_at,
                        progress.completed_at,
                        progress.execution_time,
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            self.logger.error(f"Failed to save batch progress: {e}")
            return False

    def get_batch_progress(self, batch_id: str) -> Optional[BatchProgress]:
        """Get batch progress for a specific batch ID"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM batch_progress WHERE batch_id = ?
                """,
                    (batch_id,),
                )

                row = cursor.fetchone()
                if row:
                    return self._row_to_batch_progress(row)
                return None
        except Exception as e:
            self.logger.error(f"Failed to get batch progress for batch {batch_id}: {e}")
            return None

    def get_completed_batches(self) -> Set[str]:
        """Get set of completed batch IDs"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT batch_id FROM batch_progress WHERE status = 'completed'
                """)
                return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            self.logger.error(f"Failed to get completed batches: {e}")
            return set()

    def _row_to_batch_progress(self, row: tuple) -> BatchProgress:
        """Convert database row to BatchProgress object"""
        return BatchProgress(
            batch_id=row[0],
            start_date=row[1],
            end_date=row[2],
            status=row[3],
            articles_found=row[4],
            articles_archived=row[5],
            articles_failed=row[6],
            error_message=row[7],
            started_at=datetime.fromisoformat(row[8]) if row[8] else None,
            completed_at=datetime.fromisoformat(row[9]) if row[9] else None,
            execution_time=row[10],
        )

    # Statistics Operations

    def get_archive_statistics(self) -> Dict[str, int]:
        """Get overall archive statistics"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT status, COUNT(*) 
                    FROM archive_records 
                    GROUP BY status
                """)

                stats = {}
                for status, count in cursor.fetchall():
                    stats[status] = count

                # Add total count
                stats["total"] = sum(stats.values())
                return stats
        except Exception as e:
            self.logger.error(f"Failed to get statistics: {e}")
            return {}

    def close(self):
        """Close database connections (cleanup)"""
        # Note: Using connection-per-operation pattern, no persistent connections to close
        pass
