#!/usr/bin/env python
# coding: utf-8
"""SubtitleCat provider implementation."""

from __future__ import annotations

import os
import re
from typing import List, Optional
from urllib.parse import quote, urljoin, urlparse

import requests

import config
from ssl_util import SharedSSLAdapter
from subtitle.models import OnlineSubtitleSearchResult
from subtitle.providers.base import SubtitleProvider


LANG_MAP = {
    'english': 'en',
    'en': 'en',
    'eng': 'en',
    'japanese': 'ja',
    'ja': 'ja',
    'jp': 'ja',
    'jpn': 'ja',
    'traditional chinese': 'zh-TW',
    'simplified chinese': 'zh-CN',
    'chinese': 'zh-TW',
    'zh-tw': 'zh-TW',
    'zh-cn': 'zh-CN',
    'zh': 'zh-TW',
    'zho': 'zh-TW',
    'chi': 'zh-TW',
    'korean': 'ko',
    'ko': 'ko',
    'kor': 'ko',
}

LANG_DISPLAY_NAMES = {
    'en': 'English',
    'ja': 'Japanese',
    'zh-TW': '繁體中文 (Traditional Chinese)',
    'zh-CN': '簡體中文 (Simplified Chinese)',
    'ko': 'Korean',
}


def normalize_lang_code(lang_str: str) -> str:
    s = str(lang_str or '').strip().lower()
    return LANG_MAP.get(s, s if s else 'unknown')


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    session.mount('http://', requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=1))
    session.mount('https://', SharedSSLAdapter(pool_connections=8, pool_maxsize=16, max_retries=1))
    return session


class SubtitleCatProvider(SubtitleProvider):
    """SubtitleCat provider implementation for subtitle search and download."""

    BASE_URL = "https://www.subtitlecat.com"

    def __init__(self):
        self._session = _make_session()

    @property
    def name(self) -> str:
        return "SubtitleCat"

    def search(self, query: str, language: Optional[str] = None) -> List[OnlineSubtitleSearchResult]:
        query = (query or '').strip()
        if not query:
            return []

        search_url = f"{self.BASE_URL}/index.php?search={quote(query)}"
        results: List[OnlineSubtitleSearchResult] = []

        try:
            resp = self._session.get(
                search_url,
                timeout=(10, 20),
                **config.proxy_request_kwargs()
            )
            if resp.status_code != 200:
                return []

            html = resp.text
            # Find all subtitle detail links in table: <a href="subs/1634/JUR-792.html">JUR-792</a>
            detail_matches = re.findall(r'<a href="([^"]*subs/[^"]+\.html)">([^<]+)</a>', html)
            
            # Deduplicate by detail page link
            seen_links = set()
            detail_pages = []
            for href, title in detail_matches:
                full_url = urljoin(self.BASE_URL, href)
                if full_url not in seen_links:
                    seen_links.add(full_url)
                    detail_pages.append((full_url, title.strip()))

            # Fetch language options from top 3 matching detail pages
            for detail_url, title in detail_pages[:3]:
                lang_results = self._parse_detail_page(detail_url, title)
                results.extend(lang_results)

        except Exception:
            pass

        # Filter by language if specified
        if language and language.lower() not in ('all', ''):
            target_lang = normalize_lang_code(language)
            results = [r for r in results if normalize_lang_code(r.language_code) == target_lang or normalize_lang_code(r.language) == target_lang]

        return results

    def _parse_detail_page(self, detail_url: str, title: str) -> List[OnlineSubtitleSearchResult]:
        results: List[OnlineSubtitleSearchResult] = []
        try:
            resp = self._session.get(
                detail_url,
                timeout=(10, 20),
                **config.proxy_request_kwargs()
            )
            if resp.status_code != 200:
                return []

            html = resp.text
            # Regex to match each subtitle block:
            # <span>LanguageName</span> and download links or translate buttons
            # Example direct link: <a ... href="/subs/1635/JUR-792-ar.srt" ...>Download</a>
            # Example block:
            # <div class="sub-single"> ... <span>English</span> ... <a href="/subs/1634/JUR-792-en.srt" ...>Download</a>
            
            blocks = re.findall(r'<div class="sub-single">(.*?)</div>\s*<!-- \./Sub single -->', html, flags=re.DOTALL)
            if not blocks:
                # Fallback splitting
                blocks = html.split('<div class="sub-single">')[1:]

            for block in blocks:
                # Extract language name
                lang_match = re.search(r'<span>([^<]+)</span>', block)
                if not lang_match:
                    continue
                raw_lang_name = lang_match.group(1).strip()
                if raw_lang_name.lower() in ('translate', 'download', 'size', 'downloads'):
                    continue

                # Check for direct download link
                dl_match = re.search(r'href="([^"]+\.srt)"', block)
                if dl_match:
                    srt_path = dl_match.group(1)
                    dl_url = urljoin(self.BASE_URL, srt_path)
                    
                    # Extract language code from filename (e.g. JUR-792-en.srt -> en)
                    lang_code_match = re.search(r'-([a-zA-Z\-]{2,6})\.srt$', srt_path)
                    lang_code = lang_code_match.group(1) if lang_code_match else normalize_lang_code(raw_lang_name)
                    
                    norm_code = normalize_lang_code(lang_code)
                    display_lang = LANG_DISPLAY_NAMES.get(norm_code, raw_lang_name)
                    
                    results.append(OnlineSubtitleSearchResult(
                        provider=self.name,
                        title=f"{title} ({display_lang})",
                        language=display_lang,
                        language_code=norm_code,
                        download_url=dl_url,
                        detail_url=detail_url,
                        source_format="srt"
                    ))

        except Exception:
            pass

        return results

    def download_subtitle(self, result: OnlineSubtitleSearchResult, destination_path: str) -> str:
        if not result.download_url:
            raise ValueError("No download URL provided in search result")

        resp = self._session.get(
            result.download_url,
            timeout=(10, 30),
            **config.proxy_request_kwargs()
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download subtitle (HTTP status {resp.status_code})")

        content = resp.content
        if not content or len(content) < 10:
            raise ValueError("Downloaded subtitle file is empty")

        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)
        with open(destination_path, 'wb') as f:
            f.write(content)

        return destination_path
