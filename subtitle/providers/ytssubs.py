#!/usr/bin/env python
# coding: utf-8
"""YTS Subtitles provider implementation."""

from __future__ import annotations

import base64
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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    session.mount('http://', requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=1))
    session.mount('https://', SharedSSLAdapter(pool_connections=8, pool_maxsize=16, max_retries=1))
    return session


class YtsSubtitlesProvider(SubtitleProvider):
    """YTS Subtitles provider implementation."""

    BASE_URL = "https://yts-subs.com"

    def __init__(self):
        self._session = _make_session()

    @property
    def name(self) -> str:
        return "YTS Subtitles"

    def search(self, query: str, language: Optional[str] = None) -> List[OnlineSubtitleSearchResult]:
        query = (query or '').strip()
        if not query:
            return []

        search_url = f"{self.BASE_URL}/search/{quote(query)}"
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
            # Find movie detail links: href="/movie-imdb/tt..."
            movie_links = re.findall(r'href="([^"]*movie-imdb/[^"]+)"', html)
            seen_movies = set()
            unique_movies = []
            for link in movie_links:
                full_url = urljoin(self.BASE_URL, link)
                if full_url not in seen_movies:
                    seen_movies.add(full_url)
                    unique_movies.append(full_url)

            # Inspect top 2 matching movie pages
            for movie_url in unique_movies[:2]:
                results.extend(self._parse_movie_page(movie_url, query))

        except Exception:
            pass

        if language and language.lower() not in ('all', ''):
            target_lang = normalize_lang_code(language)
            results = [r for r in results if normalize_lang_code(r.language_code) == target_lang or normalize_lang_code(r.language) == target_lang]

        return results

    def _parse_movie_page(self, movie_url: str, query: str) -> List[OnlineSubtitleSearchResult]:
        results: List[OnlineSubtitleSearchResult] = []
        try:
            resp = self._session.get(
                movie_url,
                timeout=(10, 20),
                **config.proxy_request_kwargs()
            )
            if resp.status_code != 200:
                return []

            html = resp.text
            # Extract movie title from h1 or title tag
            title_m = re.search(r'<h1>([^<]+)</h1>', html)
            movie_title = title_m.group(1).strip() if title_m else query

            # Find table rows with subtitle links:
            # Example link: /subtitles/avatar-fire-and-ash-2025-english-yify-2128771
            sub_matches = re.findall(r'href="(/subtitles/[^"]+)"', html)
            seen_subs = set()

            for sub_path in sub_matches:
                full_sub_url = urljoin(self.BASE_URL, sub_path)
                if full_sub_url in seen_subs:
                    continue
                seen_subs.add(full_sub_url)

                # Infer language from URL slug (e.g. avatar-2025-english-yify-1234 -> english)
                lang_m = re.search(r'-([a-zA-Z]+)-yify-\d+$', sub_path)
                raw_lang = lang_m.group(1) if lang_m else 'English'
                norm_lang = normalize_lang_code(raw_lang)
                display_lang = LANG_DISPLAY_NAMES.get(norm_lang, raw_lang.capitalize())

                results.append(OnlineSubtitleSearchResult(
                    provider=self.name,
                    title=f"{movie_title} ({display_lang})",
                    language=display_lang,
                    language_code=norm_lang,
                    download_url=full_sub_url,
                    detail_url=movie_url,
                    source_format="zip"
                ))

        except Exception:
            pass

        return results

    def download_subtitle(self, result: OnlineSubtitleSearchResult, destination_path: str) -> str:
        if not result.download_url:
            raise ValueError("No download URL provided in search result")

        zip_url = ""
        # 1. Fetch detail page if download_url is detail page
        if '/subtitles/' in result.download_url:
            resp = self._session.get(
                result.download_url,
                timeout=(10, 20),
                **config.proxy_request_kwargs()
            )
            if resp.status_code == 200:
                html = resp.text
                data_link_m = re.search(r'data-link="([^"]+)"', html)
                if data_link_m:
                    try:
                        zip_url = base64.b64decode(data_link_m.group(1)).decode('utf-8')
                    except Exception:
                        pass
                if not zip_url:
                    zip_m = re.search(r'href="([^"]*subtitle[^"]*\.zip)"', html)
                    if zip_m:
                        zip_url = urljoin(self.BASE_URL, zip_m.group(1))

        if not zip_url:
            zip_url = result.download_url

        resp = self._session.get(
            zip_url,
            timeout=(10, 30),
            **config.proxy_request_kwargs()
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download subtitle archive (HTTP {resp.status_code})")

        content = resp.content
        if not content:
            raise ValueError("Downloaded subtitle file is empty")

        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)

        # Handle ZIP unpacking if content is a ZIP file
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

        # Write directly if raw SRT/VTT
        with open(destination_path, 'wb') as f:
            f.write(content)

        return destination_path
