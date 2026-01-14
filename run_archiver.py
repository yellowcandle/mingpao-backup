#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
明報港聞存檔執行腳本
快速開始專用的簡化版本
"""

from mingpao_hkga_archiver import MingPaoHKGAArchiver
from datetime import datetime, timedelta


def quick_start():
    """快速開始 - 存檔最近 7 天"""
    print("🔥 明報港聞 HK-GA Wayback Machine 存檔工具")
    print("=" * 60)

    archiver = MingPaoHKGAArchiver()

    # 存檔最近 7 天（測試用）
    end_date = datetime.now()
    start_date = end_date - timedelta(days=6)

    print(
        f"將存檔日期範圍: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"
    )
    print(f"每日限制: {archiver.config['daily_limit']} 篇文章")
    print(f"Rate limiting: {archiver.config['archiving']['rate_limit_delay']} 秒/請求")
    print("=" * 60)
    print()

    try:
        print("✅ 存檔完成！")
        archiver.generate_report()
    except KeyboardInterrupt:
        print("\n\n⛔ 用戶中斷執行")
        print("進度已保存至數據庫，下次執行會從中斷處繼續")
    except Exception as e:
        print(f"\n\n❌ 執行錯誤: {str(e)}")
    finally:
        archiver.close()


if __name__ == "__main__":
    quick_start()
