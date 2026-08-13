#!/usr/bin/env python
# coding: utf-8
"""Subtitle Manager for FetchJAV Preview Player."""

from __future__ import annotations

import os
import threading
from typing import Callable, List, Optional

from subtitle.cache import SubtitleCache
from subtitle.models import (
    OnlineSubtitleSearchResult,
    SubtitleSourceType,
    SubtitleState,
    SubtitleTrack,
)
from subtitle.sources.generated import find_generated_subtitles
from subtitle.sources.local import process_local_subtitle
from subtitle.sources.online import download_online_subtitle, search_online_subtitles
from video_identity import video_code


class SubtitleManager:
    """Manages subtitle tracks, online search, local loading, and VLC player track switching."""

    def __init__(self):
        self.cache = SubtitleCache()
        self.tracks: List[SubtitleTrack] = []
        self.active_track_id: Optional[str] = None
        self.current_video_info: dict = {}
        self.current_video_code: str = ""
        self._lock = threading.Lock()

    def load_tracks_for_video(self, video_info: dict, media_path: Optional[str] = None) -> List[SubtitleTrack]:
        """Discover and load all available subtitle tracks for the specified video."""
        with self._lock:
            self.current_video_info = video_info or {}
            self.current_video_code = video_code(self.current_video_info) or (self.current_video_info.get('title') or 'preview')
            self.tracks.clear()

            # 1. Discover Generated Subtitles
            gen_tracks = find_generated_subtitles(self.current_video_info, media_path)
            self.tracks.extend(gen_tracks)

            # 2. Discover Cached Subtitles (Online / Local from previous sessions)
            cached_items = self.cache.list_cached_subtitles(self.current_video_code)
            for item in cached_items:
                meta = item.get('metadata', {}).get('metadata', {})
                provider_name = meta.get('provider', 'Online')
                lang = meta.get('language', item.get('lang_code', 'Subtitle'))
                track_name = f"{lang} ({provider_name})"

                # Avoid duplicate paths
                if not any(t.file_path == item['path'] for t in self.tracks):
                    self.tracks.append(SubtitleTrack(
                        id=f"cached_{hash(item['path']) & 0xffffffff:x}",
                        name=track_name,
                        language=lang,
                        language_code=item.get('lang_code', 'en'),
                        source=SubtitleSourceType.ONLINE,
                        file_path=item['path'],
                        format="srt",
                        state=SubtitleState.READY
                    ))

            # Automatically activate first available generated subtitle if present
            if self.tracks and self.active_track_id is None:
                self.tracks[0].active = True
                self.active_track_id = self.tracks[0].id

            return list(self.tracks)

    def add_local_track(self, file_path: str) -> SubtitleTrack:
        """Process and register a local subtitle file."""
        track = process_local_subtitle(
            file_path=file_path,
            video_identifier=self.current_video_code,
            cache=self.cache
        )
        with self._lock:
            # Check for existing track with same file path
            for t in self.tracks:
                if t.file_path == track.file_path:
                    return t
            self.tracks.append(track)
        return track

    def search_online_async(
        self,
        query: str,
        language: Optional[str] = None,
        provider_name: Optional[str] = None,
        on_complete: Optional[Callable[[List[OnlineSubtitleSearchResult], Optional[str]], None]] = None
    ) -> None:
        """Search online subtitles asynchronously off the UI thread."""
        def _worker():
            try:
                results = search_online_subtitles(query, language=language, provider_name=provider_name)
                if on_complete:
                    on_complete(results, None)
            except Exception as exc:
                if on_complete:
                    on_complete([], str(exc or "Search failed"))

        thread = threading.Thread(target=_worker, name="SubtitleOnlineSearch", daemon=True)
        thread.start()

    def download_online_track_async(
        self,
        result: OnlineSubtitleSearchResult,
        on_complete: Optional[Callable[[Optional[SubtitleTrack], Optional[str]], None]] = None
    ) -> None:
        """Download an online subtitle asynchronously off the UI thread."""
        def _worker():
            try:
                track = download_online_subtitle(
                    result=result,
                    video_identifier=self.current_video_code,
                    cache=self.cache
                )
                with self._lock:
                    if not any(t.file_path == track.file_path for t in self.tracks):
                        self.tracks.append(track)
                if on_complete:
                    on_complete(track, None)
            except Exception as exc:
                if on_complete:
                    on_complete(None, str(exc or "Download failed"))

        thread = threading.Thread(target=_worker, name="SubtitleOnlineDownload", daemon=True)
        thread.start()

    def set_active_track(self, track_id: Optional[str], vlc_player: Optional[object] = None) -> bool:
        """Set the active subtitle track and update VLC player if provided."""
        with self._lock:
            if not track_id or track_id.lower() in ('off', 'none'):
                self.active_track_id = None
                for t in self.tracks:
                    t.active = False
                if vlc_player and hasattr(vlc_player, 'video_set_spu'):
                    try:
                        vlc_player.video_set_spu(-1)
                    except Exception:
                        pass
                return True

            target_track = next((t for t in self.tracks if t.id == track_id), None)
            if not target_track:
                return False

            for t in self.tracks:
                t.active = (t.id == track_id)

            self.active_track_id = track_id

            if vlc_player and target_track.file_path and os.path.isfile(target_track.file_path):
                if hasattr(vlc_player, 'video_set_subtitle_file'):
                    try:
                        vlc_player.video_set_subtitle_file(target_track.file_path)
                    except Exception:
                        pass

            return True

    def get_tracks(self) -> List[SubtitleTrack]:
        with self._lock:
            return list(self.tracks)

    def get_active_track(self) -> Optional[SubtitleTrack]:
        with self._lock:
            return next((t for t in self.tracks if t.id == self.active_track_id), None)
