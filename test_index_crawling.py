#!/usr/bin/env python3
"""Test index-based URL discovery"""

from mingpao_hkga_archiver import MingPaoHKGAArchiver
from datetime import datetime

# Create archiver instance
archiver = MingPaoHKGAArchiver("config.json")

# Test with recent date
test_date = datetime(2026, 1, 13)
print(f"\n{'=' * 60}")
print(f"Testing index-based URL discovery for: {test_date.strftime('%Y-%m-%d')}")
print(f"{'=' * 60}\n")

# Generate URLs using index page
urls = archiver.generate_article_urls(test_date)

print(f"\n✅ Found {len(urls)} articles:")
print(f"{'=' * 60}")
for i, url in enumerate(urls, 1):
    # Extract article ID from URL
    article_id = url.split('/')[-1].replace('.htm', '')
    print(f"{i:3d}. {article_id:20s} -> {url}")

print(f"\n{'=' * 60}")
print(f"Summary:")
print(f"  Date: {test_date.strftime('%Y-%m-%d')}")
print(f"  Method: Index page crawling")
print(f"  Total articles: {len(urls)}")
print(f"{'=' * 60}\n")

# Close database connection
archiver.conn.close()
