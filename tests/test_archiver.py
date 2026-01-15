"""Tests for MingPaoHKGAArchiver core functionality"""

import pytest
import json
import os
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

    @patch("mingpao_hkga_archiver.WaybackMachineAvailabilityAPI")
    def test_check_wayback_exists_positive(self, mock_availability_api_class, archiver):
        """Test checking if URL exists in Wayback Machine (positive)"""
        url = "http://example.com/exists.htm"

        # Mock newest archive URL
        mock_instance = Mock()
        mock_newest = Mock()
        mock_newest.archive_url = (
            "https://web.archive.org/web/20240101/http://example.com/exists.htm"
        )
        mock_instance.newest.return_value = mock_newest
        mock_availability_api_class.return_value = mock_instance

        exists, wayback_url = archiver.check_wayback_exists(url)

        assert exists is True
        assert (
            wayback_url
            == "https://web.archive.org/web/20240101/http://example.com/exists.htm"
        )

    @patch("mingpao_hkga_archiver.WaybackMachineAvailabilityAPI")
    def test_check_wayback_exists_negative(self, mock_availability_api_class, archiver):
        """Test checking if URL exists in Wayback Machine (negative)"""
        url = "http://example.com/notexists.htm"

        # Mock no archive URL found
        mock_instance = Mock()
        mock_instance.newest.return_value = None
        mock_availability_api_class.return_value = mock_instance

        exists, wayback_url = archiver.check_wayback_exists(url)

        assert exists is False
        assert wayback_url is None

    @patch("mingpao_hkga_archiver.WaybackMachineSaveAPI")
    def test_archive_to_wayback_success(self, mock_save_api_class, archiver):
        """Test successful archiving with waybackpy"""
        url = "http://example.com/success.htm"

        # Mock successful save
        mock_instance = Mock()
        mock_instance.save.return_value = (
            "https://web.archive.org/web/20240101/http://example.com/success.htm"
        )
        mock_save_api_class.return_value = mock_instance

        # Mock check_wayback_exists to return False first
        with patch.object(archiver, "check_wayback_exists", return_value=(False, None)):
            result = archiver.archive_to_wayback(url)

            assert result["status"] == "success"
            assert (
                result["wayback_url"]
                == "https://web.archive.org/web/20240101/http://example.com/success.htm"
            )
            assert result["http_status"] == 200

    @patch("mingpao_hkga_archiver.WaybackMachineSaveAPI")
    def test_archive_to_wayback_rate_limited(self, mock_save_api_class, archiver):
        """Test rate limiting with waybackpy"""
        url = "http://example.com/rate-limited.htm"

        # Mock rate limit error from waybackpy (it usually raises Exception with error message)
        mock_instance = Mock()
        mock_instance.save.side_effect = Exception("HTTP 429: Too Many Requests")
        mock_save_api_class.return_value = mock_instance

        with patch.object(archiver, "check_wayback_exists", return_value=(False, None)):
            result = archiver.archive_to_wayback(url)

            assert result["status"] == "rate_limited"
            assert result["http_status"] == 429

    @patch("mingpao_hkga_archiver.WaybackMachineSaveAPI")
    def test_archive_to_wayback_timeout(self, mock_save_api_class, archiver):
        """Test timeout with waybackpy"""
        url = "http://example.com/timeout.htm"

        # Mock timeout error
        mock_instance = Mock()
        mock_instance.save.side_effect = Exception("Read timeout")
        mock_save_api_class.return_value = mock_instance

        with patch.object(archiver, "check_wayback_exists", return_value=(False, None)):
            result = archiver.archive_to_wayback(url)

            # Since retry logic is recursive, we might need to be careful with mocks if we want to test retries
            # But for a single attempt that fails with timeout:
            assert result["status"] == "timeout" or result["status"] == "error"

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
