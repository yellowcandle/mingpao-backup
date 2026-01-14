#!/usr/bin/env python3
"""
Batch archiving script for Ming Pao articles back to 2013

This script orchestrates large-scale archival by:
1. Breaking the date range into monthly batches
2. Calling Modal endpoints for each batch
3. Tracking progress in the database
4. Handling failures and resuming

Usage:
    uv run python batch_archive.py --start 2013-01-01 --end 2025-12-31
    uv run python batch_archive.py --back-years 13  # Archive last 13 years
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import requests


class BatchArchiver:
    def __init__(self, endpoint_url: str, db_path: str = "hkga_archive.db"):
        self.endpoint = endpoint_url
        self.db_path = db_path
        self.setup_database()

    def setup_database(self):
        """Create progress tracking table if needed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS batch_progress (
                batch_id TEXT PRIMARY KEY,
                start_date TEXT,
                end_date TEXT,
                status TEXT,  -- pending, in_progress, completed, failed
                articles_found INTEGER DEFAULT 0,
                articles_archived INTEGER DEFAULT 0,
                articles_failed INTEGER DEFAULT 0,
                error_message TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                execution_time REAL
            )
        """)

        conn.commit()
        conn.close()

    def generate_monthly_batches(
        self, start_date: datetime, end_date: datetime
    ) -> List[Tuple[str, str]]:
        """Generate monthly date ranges from start to end"""
        batches = []
        current = start_date.replace(day=1)

        while current <= end_date:
            # Last day of current month
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1)
            else:
                next_month = current.replace(month=current.month + 1)

            month_end = next_month - timedelta(days=1)

            # Don't go beyond end_date
            if month_end > end_date:
                month_end = end_date

            batch_id = current.strftime("%Y%m")
            batches.append(
                (batch_id, current.strftime("%Y-%m-%d"), month_end.strftime("%Y-%m-%d"))
            )

            current = next_month

        return batches

    def get_pending_batches(
        self, start_date: datetime, end_date: datetime
    ) -> List[Tuple[str, str, str]]:
        """Get batches that haven't been completed yet"""
        all_batches = self.generate_monthly_batches(start_date, end_date)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT batch_id FROM batch_progress WHERE status='completed'")
        completed = {row[0] for row in cursor.fetchall()}

        conn.close()

        pending = [batch for batch in all_batches if batch[0] not in completed]
        return pending

    def archive_batch(self, batch_id: str, start_date: str, end_date: str) -> Dict:
        """Archive a single monthly batch"""
        print(f"\n{'=' * 60}")
        print(f"Archiving batch: {batch_id} ({start_date} to {end_date})")
        print(f"{'=' * 60}")

        # Mark as in progress
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO batch_progress 
            (batch_id, start_date, end_date, status, started_at)
            VALUES (?, ?, ?, 'in_progress', CURRENT_TIMESTAMP)
        """,
            (batch_id, start_date, end_date),
        )
        conn.commit()
        conn.close()

        start_time = time.time()

        try:
            response = requests.post(
                self.endpoint,
                json={
                    "mode": "range",
                    "start": start_date,
                    "end": end_date,
                    "daily_limit": 2000,  # Reasonable limit per batch
                },
                timeout=86400,  # 24 hours max per batch
            )

            result = response.json()

            if result.get("status") == "success":
                stats = result.get("result", {})
                execution_time = time.time() - start_time

                # Update as completed
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE batch_progress 
                    SET status='completed',
                        articles_found=?,
                        articles_archived=?,
                        articles_failed=?,
                        completed_at=CURRENT_TIMESTAMP,
                        execution_time=?
                    WHERE batch_id=?
                """,
                    (
                        stats.get("found", 0),
                        stats.get("archived", 0),
                        stats.get("failed", 0),
                        execution_time,
                        batch_id,
                    ),
                )
                conn.commit()
                conn.close()

                print(f"✅ Batch {batch_id} completed:")
                print(f"   Found: {stats.get('found', 0)}")
                print(f"   Archived: {stats.get('archived', 0)}")
                print(f"   Failed: {stats.get('failed', 0)}")
                print(f"   Time: {execution_time:.1f}s")

                return {"status": "success", "batch_id": batch_id, **stats}

            else:
                error_msg = result.get("error", "Unknown error")
                raise Exception(error_msg)

        except Exception as e:
            execution_time = time.time() - start_time

            # Mark as failed
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE batch_progress 
                SET status='failed',
                    error_message=?,
                    completed_at=CURRENT_TIMESTAMP,
                    execution_time=?
                WHERE batch_id=?
            """,
                (str(e), execution_time, batch_id),
            )
            conn.commit()
            conn.close()

            print(f"❌ Batch {batch_id} failed: {e}")
            return {"status": "failed", "batch_id": batch_id, "error": str(e)}

    def get_progress_summary(self) -> Dict:
        """Get overall progress summary"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT status, COUNT(*), SUM(articles_archived)
            FROM batch_progress
            GROUP BY status
        """)

        summary = {
            "total_batches": 0,
            "completed": 0,
            "in_progress": 0,
            "failed": 0,
            "total_articles": 0,
            "pending": 0,
        }

        for row in cursor.fetchall():
            status, count, articles = row[0], row[1], row[2] or 0
            summary["total_batches"] += count
            summary["total_articles"] += articles

            if status == "completed":
                summary["completed"] = count
            elif status == "in_progress":
                summary["in_progress"] = count
            elif status == "failed":
                summary["failed"] = count

        conn.close()
        return summary

    def run(self, start_date: datetime, end_date: datetime, retry_failed: bool = False):
        """Run batch archiving"""
        print(
            f"\n🚀 Starting batch archival from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )

        if retry_failed:
            batches = self.get_failed_batches()
            print(f"Found {len(batches)} failed batches to retry")
        else:
            batches = self.get_pending_batches(start_date, end_date)
            print(f"Found {len(batches)} pending batches")

        if not batches:
            print("✨ All batches already completed!")
            return

        print(
            f"Estimated articles: ~{len(batches) * 1000} (assuming ~1000 articles/month)"
        )
        print(f"Estimated time: ~{len(batches) * 3} hours (at ~3 hours/month)")
        print("=" * 60)

        for i, (batch_id, start, end) in enumerate(batches, 1):
            print(
                f"\n📊 Progress: {i}/{len(batches)} batches ({i / len(batches) * 100:.1f}%)"
            )

            # Get current summary
            summary = self.get_progress_summary()
            print(
                f"   Completed: {summary['completed']} | Failed: {summary['failed']} | "
                f"Articles: {summary['total_articles']}"
            )

            # Archive this batch
            self.archive_batch(batch_id, start, end)

            # Progress checkpoint every 5 batches
            if i % 5 == 0:
                print(f"\n{'=' * 60}")
                print(f"📝 Checkpoint after {i} batches")
                print(f"{'=' * 60}")

            # Rate limiting between batches (30 seconds to be safe)
            if i < len(batches):
                print(f"⏳ Waiting 30s before next batch...")
                time.sleep(30)

        # Final summary
        print(f"\n{'=' * 60}")
        print("🎉 BATCH ARCHIVING COMPLETE!")
        print(f"{'=' * 60}")
        summary = self.get_progress_summary()
        print(f"Total batches: {summary['total_batches']}")
        print(f"Completed: {summary['completed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Total articles archived: {summary['total_articles']}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch archive Ming Pao articles to Wayback Machine"
    )
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument(
        "--end",
        help="End date (YYYY-MM-DD)",
        default=datetime.now().strftime("%Y-%m-%d"),
    )
    parser.add_argument(
        "--back-years", type=int, help="Archive N years back from today"
    )
    parser.add_argument(
        "--retry-failed", action="store_true", help="Retry failed batches only"
    )
    parser.add_argument("--endpoint", help="Modal endpoint URL", required=True)

    args = parser.parse_args()

    try:
        # Determine date range
        end_date = datetime.strptime(args.end, "%Y-%m-%d")

        if args.back_years:
            start_date = end_date - timedelta(days=args.back_years * 365)
            # Round to start of month
            start_date = start_date.replace(day=1)
        elif args.start:
            start_date = datetime.strptime(args.start, "%Y-%m-%d")
        else:
            print("Error: Must specify --start or --back-years")
            sys.exit(1)

        # Create batch archiver
        archiver = BatchArchiver(args.endpoint)

        # Run batch archiving
        archiver.run(start_date, end_date, retry_failed=args.retry_failed)

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
