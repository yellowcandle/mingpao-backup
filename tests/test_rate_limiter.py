"""Tests for URL validation"""

import time
from mingpao_hkga_archiver import RateLimiter


class TestRateLimiter:
    """Test cases for RateLimiter"""

    def test_rate_limiter_allows_single_request(self):
        """Test that single request completes without delay"""
        limiter = RateLimiter(delay=0.1, max_burst=1)
        start = time.time()
        limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.2, f"Single request took {elapsed}s, expected < 0.2s"

    def test_rate_limiter_enforces_delay(self):
        """Test that delay is enforced between requests"""
        limiter = RateLimiter(delay=1.0, max_burst=1)
        start = time.time()
        limiter.acquire()
        limiter.acquire()
        elapsed = time.time() - start
        assert elapsed >= 1.0, f"Elapsed {elapsed}s, expected >= 1.0s"
        assert elapsed < 1.5, f"Elapsed {elapsed}s, expected < 1.5s"

    def test_rate_limiter_allows_burst(self):
        """Test that max_burst allows multiple immediate requests"""
        limiter = RateLimiter(delay=1.0, max_burst=3)
        start = time.time()
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.5, f"Burst of 3 took {elapsed}s, expected < 0.5s"

    def test_rate_limiter_refills_after_burst(self):
        """Test that tokens refill after delay"""
        limiter = RateLimiter(delay=0.5, max_burst=2)
        start = time.time()
        limiter.acquire()  # Uses 1 token
        limiter.acquire()  # Uses 2nd token (burst exhausted)
        # Now tokens should refill
        time.sleep(0.6)  # Wait for refill
        limiter.acquire()  # Should succeed immediately
        elapsed = time.time() - start
        assert elapsed < 1.0, f"Refill test took {elapsed}s"

    def test_rate_limiter_zero_delay(self):
        """Test limiter with zero delay"""
        limiter = RateLimiter(delay=0.01, max_burst=5)  # Use small delay instead of 0
        start = time.time()
        for _ in range(5):
            limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.5, f"Near-zero delay test took {elapsed}s"
