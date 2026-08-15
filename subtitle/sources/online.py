#!/usr/bin/env python
# coding: utf-8
"""Coordinates online subtitle providers, parallel multi-query search, download, and caching."""

from __future__ import annotations

import concurrent.futures
import os
import re
from typing import Callable, List, Optional

from subtitle.cache import SubtitleCache
from subtitle.models import OnlineSubtitleSearchResult, SubtitleSourceType, SubtitleState, SubtitleTrack
from subtitle.parser import load_and_normalize_subtitle
from subtitle.providers.base import SubtitleProvider
from subtitle.providers.opensubtitles import OpenSubtitlesProvider
from subtitle.providers.podnapisi import PodnapisiProvider
from subtitle.providers.subdl import SubDLProvider
from subtitle.providers.subtitlecat import SubtitleCatProvider
from subtitle.providers.ytssubs import YtsSubtitlesProvider


_DEFAULT_PROVIDERS: List[SubtitleProvider] = [
    SubtitleCatProvider(),
    YtsSubtitlesProvider(),
    OpenSubtitlesProvider(),
    SubDLProvider(),
    PodnapisiProvider(),
]


def get_provider_by_name(name: str) -> SubtitleProvider:
    for p in _DEFAULT_PROVIDERS:
        if p.name.casefold() == name.casefold():
            return p
    return SubtitleCatProvider()


def generate_query_variants(query: str) -> List[str]:
    """Generate search variants for video codes and titles (e.g. JUR-900 -> JUR-900, JUR900, JUR 900)."""
    q = (query or '').strip()
    if not q:
        return []
    variants = [q]

    m = re.match(r'^([a-zA-Z]{2,6})[\-_ ]+(\d{3,5})$', q)
    if m:
        prefix, num = m.group(1).upper(), m.group(2)
        v_dash = f"{prefix}-{num}"
        v_flat = f"{prefix}{num}"
        v_space = f"{prefix} {num}"
        for v in (v_dash, v_flat, v_space):
            if v.casefold() not in [x.casefold() for x in variants]:
                variants.append(v)

    return variants


def search_online_subtitles(
    query: str,
    language: Optional[str] = None,
    providers: Optional[List[SubtitleProvider]] = None,
    provider_name: Optional[str] = None,
    on_result: Optional[Callable[[List[OnlineSubtitleSearchResult]], None]] = None
) -> List[OnlineSubtitleSearchResult]:
    """Search online subtitle providers concurrently for matching subtitles with query expansion.

    ``on_result`` (if given) is invoked as each provider finishes, receiving its result
    batch, so callers can display results progressively instead of waiting for all providers.
    """
    if provider_name and provider_name.lower() not in ('all', 'all providers', ''):
        providers_to_use = [get_provider_by_name(provider_name)]
    else:
        providers_to_use = providers if providers is not None else _DEFAULT_PROVIDERS

    queries_to_search = generate_query_variants(query)
    results: List[OnlineSubtitleSearchResult] = []
    seen_keys = set()

    def _search_single(p: SubtitleProvider, q: str):
        try:
            return p.search(q, language=language)
        except Exception:
            return []

    tasks = []
    for p in providers_to_use:
        for q in queries_to_search:
            tasks.append((p, q))

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tasks) or 1, 10)) as executor:
        future_map = {executor.submit(_search_single, p, q): (p, q) for p, q in tasks}
        for future in concurrent.futures.as_completed(future_map):
            try:
                sub_list = future.result()
                if sub_list:
                    if on_result is not None:
                        on_result(list(sub_list))
                    for sub in sub_list:
                        key = (sub.provider, sub.download_url, sub.title)
                        if key not in seen_keys:
                            seen_keys.add(key)
                            results.append(sub)
            except Exception:
                pass

    return results


def download_online_subtitle(
    result: OnlineSubtitleSearchResult,
    video_identifier: str,
    cache: Optional[SubtitleCache] = None,
    provider: Optional[SubtitleProvider] = None
) -> SubtitleTrack:
    """Download an online subtitle, validate format, cache locally, and return a SubtitleTrack."""
    if cache is None:
        cache = SubtitleCache()

    if provider is None:
        provider = get_provider_by_name(result.provider)

    v_dir = cache.get_video_cache_dir(video_identifier)
    filename = f"{result.provider}_{result.language_code}_{hash(result.download_url) & 0xffffffff:x}.srt"
    temp_download_path = os.path.join(v_dir, f"temp_{filename}")

    # 1. Download
    provider.download_subtitle(result, temp_download_path)

    # 2. Validate and parse
    cues, _ = load_and_normalize_subtitle(temp_download_path)
    if not cues:
        if os.path.isfile(temp_download_path):
            os.remove(temp_download_path)
        raise ValueError("Downloaded file is not a valid subtitle file")

    # 3. Save to cache permanently
    cached_path = cache.save_subtitle_file(
        video_identifier=video_identifier,
        lang_code=result.language_code,
        filename=filename,
        source_path=temp_download_path,
        metadata={
            'provider': result.provider,
            'title': result.title,
            'language': result.language,
            'download_url': result.download_url,
        }
    )

    if os.path.isfile(temp_download_path) and os.path.abspath(temp_download_path) != os.path.abspath(cached_path):
        try:
            os.remove(temp_download_path)
        except Exception:
            pass

    track_name = f"{result.language} ({result.provider})"
    return SubtitleTrack(
        id=f"online_{hash(result.download_url) & 0xffffffff:x}",
        name=track_name,
        language=result.language,
        language_code=result.language_code,
        source=SubtitleSourceType.ONLINE,
        file_path=cached_path,
        format="srt",
        state=SubtitleState.READY
    )
