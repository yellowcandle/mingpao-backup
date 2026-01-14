#!/usr/bin/env python3
"""測試腳本 - 驗證存檔器功能"""

from mingpao_hkga_archiver import MingPaoHKGAArchiver


def test_url_check():
    """測試 URL 檢查功能"""
    print("🧪 測試 URL 檢查功能")
    print("=" * 60)

    archiver = MingPaoHKGAArchiver()

    # 測試幾個已知的有效 URL
    test_urls = [
        "http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa1_r.htm",
        "http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa2_r.htm",
        "http://www.mingpaocanada.com/tor/htm/News/20250111/HK-gaa1_r.htm",
    ]

    for url in test_urls:
        exists = archiver.check_url_exists(url)
        status = "✅ 存在" if exists else "❌ 不存在"
        print(f"{status}: {url}")
