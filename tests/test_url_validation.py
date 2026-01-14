"""Tests for URL validation"""

from mingpao_hkga_archiver import MingPaoHKGAArchiver


class TestURLValidation:
    """Test cases for _validate_url method"""

    def setup_method(self):
        """Setup archiver instance for tests"""
        self.archiver = MingPaoHKGAArchiver(config_path="config.json")

    def test_valid_http_url(self):
        """Test valid HTTP URL"""
        url = "http://www.mingpaocanada.com/tor/htm/News/20240101/HK-gaa1_r.htm"
        assert self.archiver._validate_url(url) is True

    def test_valid_https_url(self):
        """Test valid HTTPS URL"""
        url = "https://www.mingpaocanada.com/tor/htm/News/20240101/HK-gaa1_r.htm"
        assert self.archiver._validate_url(url) is True

    def test_valid_url_with_query_params(self):
        """Test URL with query parameters"""
        url = "http://example.com/path?param=value"
        assert self.archiver._validate_url(url) is True

    def test_invalid_javascript_url(self):
        """Test JavaScript URL (command injection attempt)"""
        url = "javascript:alert(1)"
        assert self.archiver._validate_url(url) is False

    def test_invalid_shell_command_url(self):
        """Test URL with shell command injection"""
        url = "http://example.com/path; rm -rf /"
        assert self.archiver._validate_url(url) is False

    def test_invalid_pipe_url(self):
        """Test URL with pipe character"""
        url = "http://example.com/path | cat /etc/passwd"
        assert self.archiver._validate_url(url) is False

    def test_invalid_backtick_url(self):
        """Test URL with backtick command substitution"""
        url = "http://example.com/path`whoami`"
        assert self.archiver._validate_url(url) is False

    def test_invalid_dollar_sign_url(self):
        """Test URL with shell variable expansion"""
        url = "http://example.com/path$HOME"
        assert self.archiver._validate_url(url) is False

    def test_invalid_scheme(self):
        """Test URL with invalid scheme"""
        url = "ftp://example.com/path"
        assert self.archiver._validate_url(url) is False

    def test_invalid_no_scheme(self):
        """Test URL without scheme"""
        url = "example.com/path"
        assert self.archiver._validate_url(url) is False

    def test_empty_url(self):
        """Test empty URL"""
        url = ""
        assert self.archiver._validate_url(url) is False

    def test_malformed_url(self):
        """Test malformed URL"""
        url = "http:///invalid"
        assert self.archiver._validate_url(url) is False

    def test_valid_mingpao_url_patterns(self):
        """Test various valid Ming Pao URL patterns"""
        test_urls = [
            "http://www.mingpaocanada.com/tor/htm/News/20240101/HK-gaa1_r.htm",
            "http://www.mingpaocanada.com/tor/htm/News/20240102/HK-gaa99_r.htm",
            "http://www.mingpaocanada.com/tor/htm/News/20250115/HK-gzz9_r.htm",
            "https://web.archive.org/web/2/http://www.mingpaocanada.com/tor/htm/News/20240101/HK-gaa1_r.htm",
        ]
        for url in test_urls:
            assert self.archiver._validate_url(url) is True, f"Failed for {url}"
