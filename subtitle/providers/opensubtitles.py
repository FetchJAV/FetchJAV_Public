#!/usr/bin/env python
# coding: utf-8
"""OpenSubtitles provider implementation."""

from __future__ import annotations

import gzip
import io
import os
from typing import List, Optional
from urllib.parse import quote

import requests

import config
from ssl_util import SharedSSLAdapter
from subtitle.models import OnlineSubtitleSearchResult
from subtitle.providers.base import SubtitleProvider
from subtitle.providers.subtitlecat import LANG_DISPLAY_NAMES, normalize_lang_code


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'TemporaryUserAgent v1.0',
        'Accept': 'application/json',
    })
    session.mount('http://', requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=1))
    session.mount('https://', SharedSSLAdapter(pool_connections=8, pool_maxsize=16, max_retries=1))
    return session


class OpenSubtitlesProvider(SubtitleProvider):
    """OpenSubtitles REST provider implementation."""

    BASE_URL = "https://rest.opensubtitles.org/search/query-"

    def __init__(self):
        self._session = _make_session()

    @property
    def name(self) -> str:
        return "OpenSubtitles"

    def search(self, query: str, language: Optional[str] = None) -> List[OnlineSubtitleSearchResult]:
        query = (query or '').strip()
        if not query:
            return []

        search_url = f"{self.BASE_URL}{quote(query)}"
        results: List[OnlineSubtitleSearchResult] = []

        try:
            resp = self._session.get(
                search_url,
                timeout=(8, 15),
                **config.proxy_request_kwargs()
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            if isinstance(data, list):
                for item in data[:10]:
                    sub_file_name = item.get('SubFileName') or item.get('MovieTitle') or query
                    lang_id = item.get('SubLanguageID') or item.get('ISO639') or 'en'
                    dl_link = item.get('SubDownloadLink') or item.get('ZipDownloadLink')
                    
                    if not dl_link:
                        continue

                    norm_lang = normalize_lang_code(lang_id)
                    display_lang = LANG_DISPLAY_NAMES.get(norm_lang, str(lang_id).capitalize())

                    results.append(OnlineSubtitleSearchResult(
                        provider=self.name,
                        title=f"{sub_file_name} ({display_lang})",
                        language=display_lang,
                        language_code=norm_lang,
                        download_url=dl_link,
                        detail_url=item.get('SubtitlesLink', ''),
                        source_format="srt"
                    ))

        except Exception:
            pass

        if language and language.lower() not in ('all', ''):
            target_lang = normalize_lang_code(language)
            results = [r for r in results if normalize_lang_code(r.language_code) == target_lang or normalize_lang_code(r.language) == target_lang]

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
        if not content:
            raise ValueError("Downloaded subtitle file is empty")

        # Decompress GZ if gzipped
        if content[:2] == b'\x1f\x8b':
            try:
                content = gzip.decompress(content)
            except Exception:
                pass

        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)
        with open(destination_path, 'wb') as f:
            f.write(content)

        return destination_path
