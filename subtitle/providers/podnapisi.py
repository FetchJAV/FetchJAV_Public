#!/usr/bin/env python
# coding: utf-8
"""Podnapisi provider implementation."""

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


class PodnapisiProvider(SubtitleProvider):
    """Podnapisi provider implementation."""

    BASE_URL = "https://www.podnapisi.net"

    def __init__(self):
        self._session = _make_session()

    @property
    def name(self) -> str:
        return "Podnapisi"

    def search(self, query: str, language: Optional[str] = None) -> List[OnlineSubtitleSearchResult]:
        query = (query or '').strip()
        if not query:
            return []

        search_url = f"{self.BASE_URL}/subtitles/search/?keywords={quote(query)}"
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
            # Regex to find subtitle download links and titles in table:
            # Example link: /subtitles/en-movie-title-2025/abc1 or /subtitles/download/...
            sub_matches = re.findall(r'href="(/subtitles/[^"]+)"[^>]*>([^<]+)</a>', html)
            seen = set()

            for href, title_text in sub_matches:
                full_url = urljoin(self.BASE_URL, href)
                if full_url in seen or '/search' in href or '/user/' in href:
                    continue
                seen.add(full_url)

                title_clean = title_text.strip()
                if not title_clean or title_clean.lower() in ('download', 'details', 'subtitles'):
                    continue

                # Infer language code from url slug (e.g., /subtitles/en-...)
                lang_code = 'en'
                lang_match = re.search(r'/subtitles/([a-z]{2}(?:-[a-z]{2})?)-', href)
                if lang_match:
                    lang_code = lang_match.group(1)

                norm_lang = normalize_lang_code(lang_code)
                display_lang = LANG_DISPLAY_NAMES.get(norm_lang, lang_code.upper())

                dl_url = full_url if '/download' in full_url else f"{full_url}/download"

                results.append(OnlineSubtitleSearchResult(
                    provider=self.name,
                    title=f"{title_clean} ({display_lang})",
                    language=display_lang,
                    language_code=norm_lang,
                    download_url=dl_url,
                    detail_url=full_url,
                    source_format="zip"
                ))

        except Exception:
            pass

        if language and language.lower() not in ('all', ''):
            target_lang = normalize_lang_code(language)
            results = [r for r in results if normalize_lang_code(r.language_code) == target_lang or normalize_lang_code(r.language) == target_lang]

        return results[:20]

    def download_subtitle(self, result: OnlineSubtitleSearchResult, destination_path: str) -> str:
        if not result.download_url:
            raise ValueError("No download URL provided in search result")

        resp = self._session.get(
            result.download_url,
            timeout=(10, 30),
            **config.proxy_request_kwargs()
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download subtitle from Podnapisi (HTTP {resp.status_code})")

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
