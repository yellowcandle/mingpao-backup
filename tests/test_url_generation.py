"""Tests for URL generation"""

from datetime import datetime
from mingpao_hkga_archiver import MingPaoHKGAArchiver


class TestURLGeneration:
    """Test cases for URL generation methods"""

    def setup_method(self):
        """Setup archiver instance for tests"""
        self.archiver = MingPaoHKGAArchiver(config_path="config.json")

    def test_generate_urls_with_date(self):
        """Test URL generation for specific date"""
        date = datetime(2024, 1, 1)
        urls = self.archiver.generate_article_urls(date)

        # Should generate URLs
        assert len(urls) > 0

        # All URLs should contain the date
        date_str = date.strftime("%Y%m%d")
        for url in urls:
            assert date_str in url
            assert url.startswith("http://www.mingpaocanada.com/tor/htm/News/")
            assert url.endswith("_r.htm")

    def test_generate_urls_for_weekday(self):
        """Test URL generation for a weekday (Monday)"""
        # 2024-01-01 is Monday
        date = datetime(2024, 1, 1)
        urls = self.archiver.generate_article_urls(date)

        # Should generate typical number of URLs
        assert len(urls) > 20
        assert len(urls) < 100

    def test_url_format_correctness(self):
        """Test that generated URLs match expected format"""
        date = datetime(2024, 3, 15)
        urls = self.archiver.generate_article_urls(date)

        for url in urls:
            assert url.startswith("http://www.mingpaocanada.com/tor/htm/News/")
            assert "/20240315/" in url
            assert url.endswith("_r.htm")

    def test_no_duplicate_urls(self):
        """Test that generated URLs are unique"""
        date = datetime(2024, 6, 30)
        urls = self.archiver.generate_article_urls(date)

        # Check no duplicates
        assert len(urls) == len(set(urls))

    def test_prefixes_coverage(self):
        """Test that URLs cover expected prefixes"""
        date = datetime(2024, 2, 28)
        urls = self.archiver.generate_article_urls(date)

        # Should have URLs with different prefixes
        prefixes = set()
        for url in urls:
            # Extract prefix from HK-xxxN pattern
            import re

            match = re.search(r"/HK-([a-z]+)\d+_r\.htm$", url)
            if match:
                prefixes.add(match.group(1))

        # Should have multiple different prefixes
        assert len(prefixes) > 5
