#!/usr/bin/env python
# coding: utf-8
"""SubDL provider implementation."""

from __future__ import annotations

import io
import os
import re
from typing import List, Optional
from urllib.parse import quote, urljoin
import zipfile

import requests

import config
from ssl_util import SharedSSLAdapter
from subtitle.models import OnlineSubtitleSearchResult
from subtitle.providers.base import SubtitleProvider
from subtitle.providers.subtitlecat import LANG_DISPLAY_NAMES, normalize_lang_code


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    session.mount('http://', requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=1))
    session.mount('https://', SharedSSLAdapter(pool_connections=8, pool_maxsize=16, max_retries=1))
    return session


class SubDLProvider(SubtitleProvider):
    """SubDL provider implementation for web and API subtitle searches."""

    BASE_URL = "https://subdl.com"

    def __init__(self):
        self._session = _make_session()

    @property
    def name(self) -> str:
        return "SubDL"

    def search(self, query: str, language: Optional[str] = None) -> List[OnlineSubtitleSearchResult]:
        query = (query or '').strip()
        if not query:
            return []

        results: List[OnlineSubtitleSearchResult] = []
        search_url = f"{self.BASE_URL}/search?query={quote(query)}"

        try:
            resp = self._session.get(
                search_url,
                timeout=(10, 20),
                **config.proxy_request_kwargs()
            )
            if resp.status_code == 200:
                html = resp.text
                # Find subtitle detail page links: href="/subtitle/sd12345/..." or href="/subtitle/..."
                detail_links = re.findall(r'href="([^"]*/subtitle/[^"]+)"', html)
                seen = set()
                unique_links = []
                for link in detail_links:
                    full_url = urljoin(self.BASE_URL, link)
                    if full_url not in seen and '/search' not in full_url:
                        seen.add(full_url)
                        unique_links.append(full_url)

                for detail_url in unique_links[:5]:
                    results.extend(self._parse_detail_page(detail_url, query))
        except Exception:
            pass

        if language and language.lower() not in ('all', ''):
            target_lang = normalize_lang_code(language)
            results = [r for r in results if normalize_lang_code(r.language_code) == target_lang or normalize_lang_code(r.language) == target_lang]

        return results

    def _parse_detail_page(self, detail_url: str, query: str) -> List[OnlineSubtitleSearchResult]:
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
            title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
            title = title_match.group(1).strip() if title_match else query

            # Extract download links and languages
            # Example link: href="/dl/sd12345/en" or href="/subtitle/download/..."
            dl_matches = re.findall(r'href="([^"]*(?:/dl/|/subtitle/download/|/download/)[^"]+)"', html)
            seen_dl = set()

            for dl_path in dl_matches:
                full_dl_url = urljoin(self.BASE_URL, dl_path)
                if full_dl_url in seen_dl:
                    continue
                seen_dl.add(full_dl_url)

                # Try to guess language from link path or text surrounding it
                lang_code = 'en'
                parts = dl_path.strip('/').split('/')
                if len(parts) >= 1 and len(parts[-1]) <= 6:
                    lang_code = parts[-1]

                norm_lang = normalize_lang_code(lang_code)
                display_lang = LANG_DISPLAY_NAMES.get(norm_lang, lang_code.upper())

                results.append(OnlineSubtitleSearchResult(
                    provider=self.name,
                    title=f"{title} ({display_lang})",
                    language=display_lang,
                    language_code=norm_lang,
                    download_url=full_dl_url,
                    detail_url=detail_url,
                    source_format="zip" if ".zip" in full_dl_url else "srt"
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
            raise RuntimeError(f"Failed to download subtitle from SubDL (HTTP {resp.status_code})")

        content = resp.content
        if not content:
            raise ValueError("Downloaded subtitle file is empty")

        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)

        if content[:4] == b'PK\x03\x04':
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    subtitle_names = [n for n in z.namelist() if n.lower().endswith(('.srt', '.vtt', '.ass', '.ssa'))]
                    if not subtitle_names:
                        subtitle_names = [n for n in z.namelist() if not n.endswith('/')]
                    if subtitle_names:
                        target_member = subtitle_names[0]
                        sub_data = z.read(target_member)
                        with open(destination_path, 'wb') as f:
                            f.write(sub_data)
                        return destination_path
            except Exception:
                pass

        with open(destination_path, 'wb') as f:
            f.write(content)

        return destination_path
