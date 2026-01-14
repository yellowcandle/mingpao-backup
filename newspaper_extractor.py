#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ming Pao Article Extractor using newspaper4k

功能：
- 使用 newspaper4k 提取文章全文、元數據
- 支援中文語言（繁體和簡體）
- 更快速、更可靠的內容提取
- 不依賴網站結構發現 URL（推薦使用 URL 生成模式）

使用方法：
    from newspaper_extractor import extract_article, extract_article_batch

    # 單篇文章提取
    article = extract_article("http://www.mingpaocanada.com/tor/htm/News/20250112/HK-gaa1_r.htm")
    print(article['title'], article['text'][:200])

    # 批量提取
    urls = ["http://...", "http://..."]
    articles = extract_article_batch(urls)
"""

from newspaper import article as newspaper_article
from typing import List, Dict, Optional
import logging
import time

logger = logging.getLogger(__name__)


def extract_article(
    url: str,
    language: str = "zh",
    nlp: bool = False,
    timeout: int = 30
) -> Optional[Dict]:
    """
    使用 newspaper4k 提取單篇文章內容

    Args:
        url: 文章 URL
        language: 語言代碼 ('zh' for Chinese, 'en' for English)
        nlp: 是否執行 NLP 提取關鍵詞和摘要（較慢）
        timeout: 請求超時時間（秒）

    Returns:
        包含文章數據的字典，失敗時返回 None
        {
            'url': str,
            'title': str,
            'authors': List[str],
            'publish_date': datetime,
            'text': str,
            'top_image': str,
            'images': List[str],
            'keywords': List[str],  # 僅當 nlp=True
            'summary': str,         # 僅當 nlp=True
        }
    """
    try:
        # newspaper4k 的簡化 API - 自動下載和解析
        article = newspaper_article(url, language=language)

        result = {
            "url": article.url,
            "title": article.title,
            "authors": article.authors,
            "publish_date": article.publish_date,
            "text": article.text,
            "top_image": article.top_image,
            "images": list(article.images),
            "keywords": [],
            "summary": "",
        }

        # 可選的 NLP 處理
        if nlp:
            try:
                article.nlp()
                result["keywords"] = article.keywords or []
                result["summary"] = article.summary or ""
            except Exception as nlp_error:
                logger.debug(f"NLP 處理失敗: {nlp_error}")

        logger.debug(f"✓ 提取成功: {url[:60]}... - {result['title'][:40] if result['title'] else 'No title'}")
        return result

    except Exception as e:
        logger.error(f"✗ 提取失敗: {url[:60]}... - {str(e)}")
        return None


def extract_article_batch(
    urls: List[str],
    language: str = "zh",
    nlp: bool = False,
    delay: float = 1.0,
    max_retries: int = 2
) -> List[Dict]:
    """
    批量提取文章內容

    Args:
        urls: 文章 URL 列表
        language: 語言代碼
        nlp: 是否執行 NLP
        delay: 每次請求間隔（秒）
        max_retries: 失敗重試次數

    Returns:
        成功提取的文章列表
    """
    articles = []
    total = len(urls)

    for idx, url in enumerate(urls, 1):
        logger.info(f"處理 {idx}/{total}: {url[:70]}...")

        retry_count = 0
        while retry_count <= max_retries:
            article = extract_article(url, language=language, nlp=nlp)

            if article:
                articles.append(article)
                break
            else:
                retry_count += 1
                if retry_count <= max_retries:
                    logger.info(f"重試 {retry_count}/{max_retries}...")
                    time.sleep(delay * 2)

        # Rate limiting
        if idx < total:
            time.sleep(delay)

    logger.info(f"批量提取完成: {len(articles)}/{total} 成功")
    return articles


def extract_title_only(url: str, language: str = "zh", timeout: int = 10) -> Optional[str]:
    """
    快速提取文章標題（不下載全文）

    Args:
        url: 文章 URL
        language: 語言代碼
        timeout: 超時時間

    Returns:
        文章標題，失敗時返回 None
    """
    try:
        article = newspaper_article(url, language=language)
        return article.title
    except Exception as e:
        logger.debug(f"標題提取失敗: {url[:60]}... - {str(e)}")
        return None


class MingPaoExtractor:
    """
    明報文章提取器 (使用 newspaper4k)

    向後兼容的包裝類，保持與舊代碼的兼容性
    """

    MINGPAO_CA_BASE = "http://www.mingpaocanada.com/tor"
    MINGPAO_HK_BASE = "http://www.mingpao.com"

    def __init__(self, language: str = "zh", timeout: int = 30):
        """初始化提取器"""
        self.language = language
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    def extract_full_article(self, article_url: str, nlp: bool = True) -> Dict:
        """下載、解析並執行 NLP 提取"""
        return extract_article(article_url, language=self.language, nlp=nlp) or {}

    def download_and_parse_article(self, article_url: str) -> Dict:
        """下載並解析單篇文章（不執行 NLP）"""
        return extract_article(article_url, language=self.language, nlp=False) or {}

    def batch_extract(
        self, urls: List[str], max_articles: int = 50, delay: float = 1.0
    ) -> List[Dict]:
        """批量提取文章"""
        return extract_article_batch(
            urls[:max_articles],
            language=self.language,
            nlp=True,
            delay=delay
        )


def demo():
    """演示用法"""
    logging.basicConfig(level=logging.INFO)

    print("\n=== newspaper4k 文章提取演示 ===\n")

    # 測試 URL（使用 BBC 中文作為示例）
    test_url = "https://www.bbc.com/zhongwen/simp/chinese-news-67084358"

    print("1. 基礎提取（標題、正文、作者）:")
    article = extract_article(test_url)
    if article:
        print(f"   標題: {article['title']}")
        print(f"   作者: {article['authors']}")
        print(f"   正文預覽: {article['text'][:100]}...")
        print(f"   圖片數量: {len(article['images'])}")
    else:
        print("   提取失敗")

    print("\n2. 帶 NLP 的提取（關鍵詞、摘要）:")
    article_nlp = extract_article(test_url, nlp=True)
    if article_nlp:
        print(f"   關鍵詞: {article_nlp['keywords'][:5]}")
        print(f"   摘要: {article_nlp['summary'][:150]}...")

    print("\n3. 快速標題提取:")
    title = extract_title_only(test_url)
    print(f"   標題: {title}")

    print("\n4. 批量提取:")
    test_urls = [
        test_url,
        "https://www.bbc.com/zhongwen/simp/world-67084359",
    ]
    articles = extract_article_batch(test_urls[:2], delay=1.0)
    print(f"   成功提取: {len(articles)} 篇")


if __name__ == "__main__":
    demo()
