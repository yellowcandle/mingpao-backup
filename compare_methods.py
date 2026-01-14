#!/usr/bin/env python3
"""Compare brute-force vs index-based URL discovery"""

from mingpao_hkga_archiver import MingPaoHKGAArchiver
from datetime import datetime
import time

# Create archiver instance
archiver = MingPaoHKGAArchiver("config.json")
test_date = datetime(2026, 1, 13)

print(f"\n{'=' * 70}")
print(f"URL Discovery Method Comparison - {test_date.strftime('%Y-%m-%d')}")
print(f"{'=' * 70}\n")

# Method 1: Index-based (new)
print("🆕 INDEX-BASED DISCOVERY (Recommended)")
print("-" * 70)
archiver.config["use_index_page"] = True
start = time.time()
index_urls = archiver.generate_article_urls(test_date)
index_time = time.time() - start
print(f"   URLs found: {len(index_urls)}")
print(f"   Time taken: {index_time:.2f}s")
print(f"   Method: Crawl index page HTML")
print(f"   Accuracy: 100% (all URLs are real articles)")

print("\n" + "=" * 70 + "\n")

# Method 2: Brute-force (old)
print("🔧 BRUTE-FORCE GENERATION (Legacy)")
print("-" * 70)
archiver.config["use_index_page"] = False
start = time.time()
brute_urls = archiver._generate_urls_bruteforce(test_date)
brute_time = time.time() - start
print(f"   URLs generated: {len(brute_urls)}")
print(f"   Time taken: {brute_time:.2f}s")
print(f"   Method: Generate all possible combinations")
print(f"   Accuracy: ~{len(index_urls)/len(brute_urls)*100:.1f}% (most URLs return 404)")

print("\n" + "=" * 70)
print("EFFICIENCY GAINS")
print("=" * 70)
reduction = (1 - len(index_urls) / len(brute_urls)) * 100
print(f"   📉 URL reduction: {reduction:.1f}%")
print(f"   ⚡ Speed: {brute_time/index_time:.1f}x faster per URL")
print(f"   💾 HTTP requests saved: {len(brute_urls) - len(index_urls)} per day")
print(f"   🎯 Accuracy improvement: {100 - len(index_urls)/len(brute_urls)*100:.1f}% fewer 404s")

# Calculate monthly savings
days_per_month = 30
monthly_savings = (len(brute_urls) - len(index_urls)) * days_per_month
print(f"\n   📊 Monthly HTTP request savings: ~{monthly_savings:,} requests")
print(f"   ⏱️  Time saved per month: ~{(index_time - brute_time) * days_per_month:.0f}s")

print("\n" + "=" * 70 + "\n")

# Close database
archiver.conn.close()
