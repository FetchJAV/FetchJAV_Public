#!/usr/bin/env python
# coding: utf-8
"""Subtitle Manager for FetchJAV Preview Player."""

from __future__ import annotations

import os
import re
import subprocess
import threading
from typing import Callable, List, Optional

from M3U8Sites.M3U8Crawler import locate_ffmpeg
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


_AUTO_SYNC_SCAN_SECONDS = 60.0
_AUTO_SYNC_MAX_OFFSET_MS = 300000
_SRT_TIME_RE = re.compile(r'\b(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})\b')
_FFMPEG_SILENCE_EVENT_RE = re.compile(
    r'silence_(start|end):\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))')


def _parse_first_cue_start_ms(file_path: str) -> Optional[int]:
    """Return the first subtitle cue start time (ms) from an SRT/VTT file."""
    try:
        with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as fh:
            for line in fh:
                match = _SRT_TIME_RE.search(line)
                if match:
                    h, m, s, ms = (int(g) for g in match.groups())
                    return ((h * 3600 + m * 60 + s) * 1000) + ms
    except Exception:
        pass
    return None


class SubtitleManager:
    """Manages subtitle tracks, online search, local loading, and VLC player track switching."""

    def __init__(self):
        self.cache = SubtitleCache()
        self.tracks: List[SubtitleTrack] = []
        self.active_track_id: Optional[str] = None
        self.current_video_info: dict = {}
        self.current_video_code: str = ""
        self._lock = threading.Lock()
        self._sync_offset_ms: int = 0
        self._sync_lock = threading.Lock()

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
        on_complete: Optional[Callable[[List[OnlineSubtitleSearchResult], Optional[str]], None]] = None,
        on_progress: Optional[Callable[[List[OnlineSubtitleSearchResult]], None]] = None,
    ) -> None:
        """Search online subtitles asynchronously off the UI thread.

        ``on_progress`` receives partial result batches as each provider finishes;
        ``on_complete`` is called once with the final merged list (or an error message).
        """
        def _worker():
            try:
                results = search_online_subtitles(
                    query, language=language, provider_name=provider_name,
                    on_result=on_progress,
                )
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

            with self._sync_lock:
                offset_ms = self._sync_offset_ms
            if offset_ms:
                self._apply_sync_offset_to_player(offset_ms, vlc_player)

            return True

    def get_tracks(self) -> List[SubtitleTrack]:
        with self._lock:
            return list(self.tracks)

    def get_active_track(self) -> Optional[SubtitleTrack]:
        with self._lock:
            return next((t for t in self.tracks if t.id == self.active_track_id), None)

    @staticmethod
    def _apply_sync_offset_to_player(offset_ms: int, vlc_player: Optional[object]) -> None:
        if vlc_player is None:
            return
        try:
            if hasattr(vlc_player, 'video_set_spu_delay'):
                vlc_player.video_set_spu_delay(int(offset_ms))
        except Exception:
            pass

    def get_sync_offset_ms(self) -> int:
        with self._sync_lock:
            return self._sync_offset_ms

    def set_sync_offset_ms(self, offset_ms: int, vlc_player: Optional[object] = None) -> int:
        """Set the subtitle time offset (ms, positive = subtitles shown later)."""
        clamped = int(max(-_AUTO_SYNC_MAX_OFFSET_MS, min(_AUTO_SYNC_MAX_OFFSET_MS, int(offset_ms or 0))))
        with self._sync_lock:
            self._sync_offset_ms = clamped
        self._apply_sync_offset_to_player(clamped, vlc_player)
        return clamped

    def reset_sync_offset(self, vlc_player: Optional[object] = None) -> int:
        return self.set_sync_offset_ms(0, vlc_player)

    def auto_sync_track(
        self,
        track: Optional[SubtitleTrack],
        media_url: str,
        headers: Optional[dict] = None,
        on_done: Optional[Callable[[int, Optional[str]], None]] = None,
    ) -> None:
        """Estimate the audio-sync offset for ``track`` off the UI thread.

        ``on_done(offset_ms, err)`` is invoked with the estimated offset in
        milliseconds (0 means already in sync) or an error message.
        """
        def _worker():
            try:
                offset_ms = self._detect_sync_offset_ms(track, media_url, headers or {})
                if on_done:
                    on_done(offset_ms, None)
            except Exception as exc:
                if on_done:
                    on_done(0, str(exc or 'Auto sync failed'))

        thread = threading.Thread(target=_worker, name='SubtitleAutoSync', daemon=True)
        thread.start()

    def _detect_sync_offset_ms(self, track: Optional[SubtitleTrack],
                               media_url: str, headers: dict) -> int:
        if track is None or not track.file_path or not os.path.isfile(track.file_path):
            raise RuntimeError('No active subtitle track to sync')
        first_cue_ms = _parse_first_cue_start_ms(track.file_path)
        if first_cue_ms is None:
            raise RuntimeError('Could not read the subtitle timing')
        onset_ms = self._detect_first_speech_onset_ms(media_url, headers)
        return int(max(-_AUTO_SYNC_MAX_OFFSET_MS,
                       min(_AUTO_SYNC_MAX_OFFSET_MS, onset_ms - first_cue_ms)))

    def _detect_first_speech_onset_ms(self, media_url: str, headers: dict) -> int:
        ffmpeg = locate_ffmpeg()
        if not ffmpeg:
            raise RuntimeError('ffmpeg is not available')
        if not media_url:
            raise RuntimeError('No media source available for the preview')

        cmd = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'info', '-y']
        if headers and not os.path.isfile(media_url):
            header_str = '\r\n'.join(
                f'{k}: {v}' for k, v in headers.items() if v)
            cmd += ['-headers', header_str]
        cmd += [
            '-t', str(_AUTO_SYNC_SCAN_SECONDS), '-i', media_url,
            '-af', 'silencedetect=noise=-30dB:d=0.3',
            '-f', 'null', '-',
        ]

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception as exc:
            raise RuntimeError(f'Could not start ffmpeg: {exc}')
        try:
            _, stderr = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            raise RuntimeError('Audio analysis timed out')
        if proc.returncode not in (0, 1):
            raise RuntimeError('ffmpeg could not read the media')

        output = (stderr or b'').decode('utf-8', errors='replace')
        events = _FFMPEG_SILENCE_EVENT_RE.findall(output)
        if not events:
            return 0
        for kind, value in events:
            if kind == 'end':
                return int(float(value) * 1000.0)
        return 0
