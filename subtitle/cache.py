#!/usr/bin/env python
# coding: utf-8
"""Cache manager for downloaded and converted subtitles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from typing import List, Optional

import config


def _sanitize_path_segment(segment: str) -> str:
    """Sanitize string to be safe as a directory/file name."""
    if not segment:
        return "default"
    # Replace dangerous chars with underscore
    clean = re.sub(r'[/\\:*?"<>|]', '_', str(segment).strip())
    # Remove leading dots to prevent hidden files or relative path tricks
    clean = clean.lstrip('. ')
    return clean if clean else "default"


def _default_cache_root() -> str:
    base = (os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
            or os.path.join(os.path.expanduser('~'), '.cache'))
    return os.path.join(base, 'FetchJAV', 'subtitles')


class SubtitleCache:
    """Manages cached subtitle files on disk."""

    def __init__(self, root_dir: Optional[str] = None):
        if root_dir is None:
            root_dir = _default_cache_root()
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)

    def _video_key(self, video_identifier: str) -> str:
        """Create a safe directory name for a video code or URL."""
        sanitized = _sanitize_path_segment(video_identifier)
        if len(sanitized) > 64:
            hash_suffix = hashlib.sha256(video_identifier.encode('utf-8')).hexdigest()[:8]
            sanitized = f"{sanitized[:50]}_{hash_suffix}"
        return sanitized

    def get_video_cache_dir(self, video_identifier: str) -> str:
        key = self._video_key(video_identifier)
        cache_dir = os.path.join(self.root_dir, key)
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def save_subtitle_file(
        self,
        video_identifier: str,
        lang_code: str,
        filename: str,
        source_path: str,
        metadata: Optional[dict] = None
    ) -> str:
        """Copy or save a subtitle file into the video's cache directory."""
        v_dir = self.get_video_cache_dir(video_identifier)
        lang_dir = os.path.join(v_dir, _sanitize_path_segment(lang_code))
        os.makedirs(lang_dir, exist_ok=True)

        safe_name = _sanitize_path_segment(filename)
        if not safe_name.lower().endswith(('.srt', '.vtt', '.ass', '.ssa')):
            safe_name += '.srt'

        target_path = os.path.join(lang_dir, safe_name)
        if os.path.abspath(source_path) != os.path.abspath(target_path):
            shutil.copy2(source_path, target_path)

        # Save metadata info sidecar
        meta_path = target_path + '.json'
        meta_data = {
            'video_identifier': video_identifier,
            'lang_code': lang_code,
            'filename': safe_name,
            'cached_at': time.time(),
            'metadata': metadata or {},
        }
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        return target_path

    def save_subtitle_bytes(
        self,
        video_identifier: str,
        lang_code: str,
        filename: str,
        content: bytes,
        metadata: Optional[dict] = None
    ) -> str:
        """Write raw subtitle content into the video's cache directory."""
        v_dir = self.get_video_cache_dir(video_identifier)
        lang_dir = os.path.join(v_dir, _sanitize_path_segment(lang_code))
        os.makedirs(lang_dir, exist_ok=True)

        safe_name = _sanitize_path_segment(filename)
        if not safe_name.lower().endswith(('.srt', '.vtt', '.ass', '.ssa')):
            safe_name += '.srt'

        target_path = os.path.join(lang_dir, safe_name)
        with open(target_path, 'wb') as f:
            f.write(content)

        meta_path = target_path + '.json'
        meta_data = {
            'video_identifier': video_identifier,
            'lang_code': lang_code,
            'filename': safe_name,
            'cached_at': time.time(),
            'metadata': metadata or {},
        }
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        return target_path

    def list_cached_subtitles(self, video_identifier: str) -> List[dict]:
        """List all cached subtitle files for a video code/identifier.

        Read-only: does not create the video cache directory (unlike
        :meth:`get_video_cache_dir`), so it is safe to call per video while
        rendering browse grids.
        """
        v_dir = os.path.join(self.root_dir, self._video_key(video_identifier))
        results = []
        if not os.path.isdir(v_dir):
            return results

        for root, _, files in os.walk(v_dir):
            for file in files:
                if file.endswith(('.srt', '.vtt', '.ass', '.ssa')):
                    file_path = os.path.join(root, file)
                    lang_code = os.path.basename(root)
                    meta_path = file_path + '.json'
                    meta = {}
                    if os.path.isfile(meta_path):
                        try:
                            with open(meta_path, 'r', encoding='utf-8') as f:
                                meta = json.load(f)
                        except Exception:
                            pass

                    results.append({
                        'path': file_path,
                        'filename': file,
                        'lang_code': lang_code,
                        'metadata': meta,
                    })

        return results

    def cached_languages(self, video_identifier: str) -> List[str]:
        """Language codes with at least one cached subtitle file for a video.

        Read-only: never creates the video cache directory (unlike
        :meth:`list_cached_subtitles`), so it is safe to call per video while
        rendering browse grids.
        """
        v_dir = os.path.join(self.root_dir, self._video_key(video_identifier))
        if not os.path.isdir(v_dir):
            return []
        langs = []
        for entry in os.scandir(v_dir):
            if not entry.is_dir():
                continue
            has_file = False
            for root, _, files in os.walk(entry.path):
                if any(f.lower().endswith(('.srt', '.vtt', '.ass', '.ssa'))
                       for f in files):
                    has_file = True
                    break
            if has_file:
                langs.append(entry.name)
        return sorted(langs)

    def get_cache_stats(self) -> dict:
        """Return count of cached subtitle files and total bytes used on disk."""
        file_count = 0
        total_bytes = 0
        if not os.path.isdir(self.root_dir):
            return {'file_count': 0, 'total_bytes': 0}
        try:
            for root, _, files in os.walk(self.root_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total_bytes += os.path.getsize(fp)
                        if f.lower().endswith(('.srt', '.vtt', '.ass', '.ssa')):
                            file_count += 1
                    except OSError:
                        pass
        except Exception:
            pass
        return {'file_count': file_count, 'total_bytes': total_bytes}

    def clear_all(self) -> int:
        """Remove all cached subtitle files and directories.
        Returns the number of subtitle files deleted."""
        removed_count = 0
        if not os.path.isdir(self.root_dir):
            return 0
        try:
            for entry in os.listdir(self.root_dir):
                item_path = os.path.join(self.root_dir, entry)
                try:
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        if item_path.lower().endswith(('.srt', '.vtt', '.ass', '.ssa')):
                            removed_count += 1
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        for root, _, files in os.walk(item_path):
                            for f in files:
                                if f.lower().endswith(('.srt', '.vtt', '.ass', '.ssa')):
                                    removed_count += 1
                        shutil.rmtree(item_path, ignore_errors=True)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            os.makedirs(self.root_dir, exist_ok=True)
        except Exception:
            pass
        return removed_count
