"""Tests for MingPaoHKGAArchiver core functionality"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch
from mingpao_hkga_archiver import MingPaoHKGAArchiver


class TestMingPaoHKGAArchiver:
    """Test cases for MingPaoHKGAArchiver class"""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create temporary config file"""
        config = {
            "database": {"path": str(tmp_path / "test.db")},
            "logging": {"level": "DEBUG", "file": str(tmp_path / "test.log")},
            "archiving": {
                "rate_limit_delay": 0.1,
                "verify_first": False,
                "timeout": 10,
                "max_retries": 2,
                "retry_delay": 1,
            },
            "daily_limit": 100,
            "parallel": {
                "enabled": False,
                "max_workers": 1,
                "rate_limit_delay": 0.1,
            },
            "keywords": {
                "enabled": False,
                "terms": ["香港", "政治"],
                "case_sensitive": False,
                "language": "zh-TW",
                "script": "traditional",
                "normalization": "NFC",
                "logic": "or",
                "search_content": False,
                "parallel_workers": 1,
                "wayback_first": True,
            },
        }
        config_path = tmp_path / "test_config.json"
        with open(config_path, "w") as f:
            json.dump(config, f)
        return config_path

    @pytest.fixture
    def archiver(self, temp_config):
        """Create archiver instance with temp config"""
        return MingPaoHKGAArchiver(config_path=str(temp_config))

    def test_initialization(self, archiver):
        """Test archiver initialization"""
        assert archiver is not None
        assert hasattr(archiver, "config")
        assert hasattr(archiver, "logger")
        assert hasattr(archiver, "stats")
        assert archiver.stats["total_attempted"] == 0

    def test_load_config(self, archiver, temp_config):
        """Test config loading"""
        assert archiver.config["database"]["path"] == str(
            temp_config.parent / "test.db"
        )
        assert archiver.config["logging"]["level"] == "DEBUG"
        assert archiver.config["archiving"]["timeout"] == 10

    def test_setup_database_creates_tables(self, archiver):
        """Test database table creation"""
        # Check that tables exist
        archiver.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archive_records'"
        )
        assert archiver.cursor.fetchone() is not None

        archiver.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_progress'"
        )
        assert archiver.cursor.fetchone() is not None

    def test_record_attempt(self, archiver):
        """Test recording archive attempts"""
        url = "http://example.com/test.htm"
        result = {
            "status": "success",
            "wayback_url": "https://web.archive.org/web/2/http://example.com/test.htm",
            "http_status": 200,
            "error": None,
        }
        date_str = "20240101"

        archiver.record_attempt(url, result, date_str)

        # Verify record exists
        archiver.cursor.execute(
            "SELECT status FROM archive_records WHERE article_url = ?", (url,)
        )
        record = archiver.cursor.fetchone()
        assert record is not None
        assert record[0] == "success"  # status column

    def test_check_url_exists_positive(self, archiver):
        """Test checking if URL exists in database"""
        # First record an attempt
        url = "http://www.mingpaocanada.com/tor/htm/News/20240101/HK-gaa1_r.htm"
        result = {"status": "success", "wayback_url": "https://wayback.example.com"}
        archiver.record_attempt(url, result, "20240101")

        # Now check if it exists
        assert archiver.check_url_exists(url) is True

    def test_check_url_exists_negative(self, archiver):
        """Test checking if non-existent URL returns False"""
        assert archiver.check_url_exists("http://example.com/notexists.htm") is False

    @patch("mingpao_hkga_archiver.requests.Response")
    @patch("mingpao_hkga_archiver.requests")
    def test_archive_to_wayback_already_exists(
        self, mock_requests, mock_response, archiver
    ):
        """Test archiving URL that already exists"""
        url = "http://www.mingpaocanada.com/tor/htm/News/20240101/HK-gaa1_r.htm"

        # Mock response for Wayback save
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Location": "/web/20240101000000/http://example.com"
        }
        mock_requests.post.return_value = mock_response

        result = archiver.archive_to_wayback(url)

        assert result["status"] in ["success", "exists", "unknown"]

    @patch("mingpao_hkga_archiver.requests")
    def test_archive_to_wayback_rate_limited(self, mock_requests, archiver):
        """Test rate limiting response"""
        url = "http://example.com/rate-limited.htm"

        # Mock 429 response
        mock_response = Mock()
        mock_response.status_code = 429
        mock_requests.post.return_value = mock_response

        result = archiver.archive_to_wayback(url)

        assert result["status"] == "rate_limited"
        assert result["http_status"] == 429

    def test_archive_to_wayback_timeout(self, archiver):
        """Test timeout handling"""
        url = "http://example.com/timeout.htm"

        # Create a custom timeout exception class
        class MockTimeoutError(Exception):
            pass

        # Mock the _make_request to raise timeout
        with patch.object(
            archiver,
            "_make_request",
            side_effect=MockTimeoutError("Connection timeout"),
        ):
            result = archiver.archive_to_wayback(url)

            # Should handle timeout via generic exception handler
            assert result["status"] == "timeout" or result["status"] == "error"
            assert "timeout" in result["error"].lower()

    def test_close_database(self, archiver):
        """Test database connection closing"""
        archiver.close()
        # Should not raise exception
        assert True

    def test_merge_config_deep(self):
        """Test deep config merging"""
        default = {"a": {"b": 1, "c": 2}, "d": 3}
        user = {"a": {"b": 99}}

        archiver = MingPaoHKGAArchiver.__new__(MingPaoHKGAArchiver)
        archiver.merge_config(default, user)

        assert default["a"]["b"] == 99
        assert default["a"]["c"] == 2
        assert default["d"] == 3

    def test_setup_directories(self, archiver, tmp_path):
        """Test directory creation"""
        # Temporarily change working directory
        original_cwd = Path.cwd()
        try:
            # Change to temp directory for test
            import os

            os.chdir(tmp_path)

            archiver.setup_directories()

            assert (tmp_path / "output").exists()
            assert (tmp_path / "logs").exists()
        finally:
            os.chdir(original_cwd)


class TestMingPaoHKGAArchiverKeywordMatching:
    """Test keyword matching functionality"""

    @pytest.fixture
    def archiver_with_keywords(self, tmp_path):
        """Create archiver with keywords enabled"""
        config = {
            "database": {"path": str(tmp_path / "test.db")},
            "logging": {"level": "DEBUG"},
            "archiving": {
                "rate_limit_delay": 0.1,
                "verify_first": False,
                "timeout": 10,
                "max_retries": 2,
                "retry_delay": 1,
            },
            "keywords": {
                "enabled": True,
                "terms": ["香港", "政治"],
                "case_sensitive": False,
                "language": "zh-TW",
                "script": "traditional",
                "normalization": "NFC",
                "logic": "or",
                "search_content": False,
                "parallel_workers": 1,
                "wayback_first": True,
            },
        }
        config_path = tmp_path / "test_config.json"
        with open(config_path, "w") as f:
            json.dump(config, f)
        return MingPaoHKGAArchiver(config_path=str(config_path))

    def test_check_cjkv_keywords_match(self, archiver_with_keywords):
        """Test CJKV keyword matching"""
        text = "香港政治新聞"
        keywords = ["香港", "政治"]

        result = archiver_with_keywords.check_cjkv_keywords(
            text, keywords, case_sensitive=False
        )

        assert "香港" in result
        assert "政治" in result
        assert len(result) == 2

    def test_check_cjkv_keywords_no_match(self, archiver_with_keywords):
        """Test CJKV keyword non-matching"""
        text = "財經新聞"
        keywords = ["香港", "政治"]

        result = archiver_with_keywords.check_cjkv_keywords(
            text, keywords, case_sensitive=False
        )

        assert len(result) == 0

    def test_normalize_cjkv_text_nfc(self, archiver_with_keywords):
        """Test Unicode normalization NFC"""
        # Test with different normalization forms
        text = "香港"  # Should work in NFC
        normalized = archiver_with_keywords.normalize_cjkv_text(text)
        assert normalized is not None
        assert isinstance(normalized, str)

    def test_keyword_filtering_enabled(self, archiver_with_keywords):
        """Test keyword filtering enabled in config"""
        assert archiver_with_keywords.config["keywords"]["enabled"] is True
        assert len(archiver_with_keywords.config["keywords"]["terms"]) == 2
