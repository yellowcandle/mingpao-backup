"""Tests for database operations"""

import pytest
import json
from mingpao_hkga_archiver import MingPaoHKGAArchiver


class TestDatabaseOperations:
    """Test cases for database operations"""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create temporary database"""
        db_path = tmp_path / "test.db"
        return db_path

    @pytest.fixture
    def archiver_with_db(self, temp_db):
        """Create archiver with temp database"""
        config = {
            "database": {"path": str(temp_db)},
            "logging": {"level": "DEBUG", "file": "/tmp/test.log"},
            "archiving": {
                "rate_limit_delay": 0.1,
                "verify_first": False,
                "timeout": 10,
                "max_retries": 2,
                "retry_delay": 1,
            },
        }
        config_path = temp_db.parent / "test_config.json"
        with open(config_path, "w") as f:
            json.dump(config, f)

        return MingPaoHKGAArchiver(config_path=str(config_path))

    def test_database_created(self, temp_db, archiver_with_db):
        """Test that database file is created"""
        assert temp_db.exists()

    def test_tables_created(self, archiver_with_db):
        """Test that required tables are created"""
        archiver_with_db.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in archiver_with_db.cursor.fetchall()]

        assert "archive_records" in tables
        assert "daily_progress" in tables

    def test_archive_records_schema(self, archiver_with_db):
        """Test archive_records table schema"""
        archiver_with_db.cursor.execute("PRAGMA table_info(archive_records)")
        columns = {row[1]: row[2] for row in archiver_with_db.cursor.fetchall()}

        expected_columns = {
            "id": "INTEGER",
            "article_url": "TEXT",
            "wayback_url": "TEXT",
            "archive_date": "TEXT",
            "status": "TEXT",
            "http_status": "INTEGER",
            "error_message": "TEXT",
            "created_at": "TIMESTAMP",
            "updated_at": "TIMESTAMP",
        }

        for col_name, col_type in expected_columns.items():
            assert col_name in columns

    def test_daily_progress_schema(self, archiver_with_db):
        """Test daily_progress table schema"""
        archiver_with_db.cursor.execute("PRAGMA table_info(daily_progress)")
        columns = {row[1] for row in archiver_with_db.cursor.fetchall()}

        expected_columns = {
            "date",
            "articles_found",
            "articles_archived",
            "articles_failed",
            "articles_not_found",
            "execution_time",
            "completed_at",
        }

        for col_name in expected_columns:
            assert col_name in columns

    def test_record_attempt_inserts_record(self, archiver_with_db):
        """Test inserting archive record"""
        url = "http://example.com/test.htm"
        result = {
            "status": "success",
            "wayback_url": "https://wayback.example.com",
            "http_status": 200,
            "error": None,
        }
        date_str = "20240101"

        archiver_with_db.record_attempt(url, result, date_str)

        # Verify record
        archiver_with_db.cursor.execute(
            "SELECT status, wayback_url, archive_date FROM archive_records WHERE article_url = ?",
            (url,),
        )
        record = archiver_with_db.cursor.fetchone()
        assert record is not None
        assert record[0] == "success"
        assert record[1] == "https://wayback.example.com"
        assert record[2] == date_str

    def test_record_attempt_updates_existing(self, archiver_with_db):
        """Test updating existing record"""
        url = "http://example.com/update.htm"
        old_result = {"status": "failed", "wayback_url": None}
        new_result = {"status": "success", "wayback_url": "https://wayback.example.com"}
        date_str = "20240101"

        # Insert first
        archiver_with_db.record_attempt(url, old_result, date_str)

        # Update
        archiver_with_db.record_attempt(url, new_result, date_str)

        # Verify update
        archiver_with_db.cursor.execute(
            "SELECT status FROM archive_records WHERE article_url = ?", (url,)
        )
        record = archiver_with_db.cursor.fetchone()
        assert record[0] == "success"

    def test_record_daily_progress(self, archiver_with_db):
        """Test recording daily progress"""
        date_str = "20240101"
        archiver_with_db._record_daily_progress(
            date_str,
            found=10,
            archived=8,
            failed=2,
            not_found=0,
            filtered=5,
            execution_time=30.5,
        )

        # Verify record
        archiver_with_db.cursor.execute(
            "SELECT * FROM daily_progress WHERE date = ?", (date_str,)
        )
        record = archiver_with_db.cursor.fetchone()
        assert record is not None
        assert record[1] == 10  # articles_found
        assert record[2] == 8  # articles_archived
        assert record[3] == 2  # articles_failed
        assert record[5] == 30.5  # execution_time

    def test_check_url_exists_positive(self, archiver_with_db):
        """Test checking existing URL"""
        url = "http://www.mingpaocanada.com/tor/htm/News/20240101/HK-gaa1_r.htm"
        archiver_with_db.record_attempt(
            url,
            {"status": "success", "wayback_url": "https://wayback.example.com"},
            "20240101",
        )

        assert archiver_with_db.check_url_exists(url) is True

    def test_check_url_exists_negative(self, archiver_with_db):
        """Test checking non-existent URL"""
        assert (
            archiver_with_db.check_url_exists("http://example.com/notexists.htm")
            is False
        )

    def test_check_urls_exist_in_db(self, archiver_with_db):
        """Test batch URL existence check"""
        urls = [
            "http://example.com/test1.htm",
            "http://example.com/test2.htm",
        ]

        # Insert one
        archiver_with_db.record_attempt(
            urls[0],
            {"status": "success", "wayback_url": "https://wayback.example.com"},
            "20240101",
        )

        existing = archiver_with_db.check_urls_exist_in_db(urls)
        assert len(existing) == 1
        assert urls[0] in existing
        assert urls[1] not in existing

    def test_database_unique_constraint(self, archiver_with_db):
        """Test that duplicate URLs are rejected"""
        url = "http://example.com/duplicate.htm"

        # Insert first record
        archiver_with_db.record_attempt(
            url, {"status": "failed", "wayback_url": None}, "20240101"
        )

        # Insert duplicate (should update due to INSERT OR REPLACE)
        archiver_with_db.record_attempt(
            url,
            {"status": "success", "wayback_url": "https://wayback.example.com"},
            "20240101",
        )

        # Should only have one record
        archiver_with_db.cursor.execute(
            "SELECT COUNT(*) FROM archive_records WHERE article_url = ?", (url,)
        )
        count = archiver_with_db.cursor.fetchone()[0]
        assert count == 1

    def test_database_close_and_reopen(self, temp_db):
        """Test closing and reopening database connection"""
        config = {
            "database": {"path": str(temp_db)},
            "logging": {"level": "DEBUG"},
            "archiving": {"rate_limit_delay": 0.1, "timeout": 10},
        }

        # Create archiver
        config_path = temp_db.parent / "config.json"
        with open(config_path, "w") as f:
            json.dump(config, f)

        archiver1 = MingPaoHKGAArchiver(config_path=str(config_path))

        # Insert data
        url = "http://example.com/persistent.htm"
        archiver1.record_attempt(
            url,
            {"status": "success", "wayback_url": "https://wayback.example.com"},
            "20240101",
        )

        # Close
        archiver1.close()

        # Reopen
        archiver2 = MingPaoHKGAArchiver(config_path=str(config_path))

        # Check data persists
        archiver2.cursor.execute(
            "SELECT status FROM archive_records WHERE article_url = ?", (url,)
        )
        record = archiver2.cursor.fetchone()
        assert record[0] == "success"

        archiver2.close()
