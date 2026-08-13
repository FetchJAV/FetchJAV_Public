#!/usr/bin/env python
# coding: utf-8
"""Processes user-uploaded local subtitle files."""

from __future__ import annotations

import os
from typing import Optional

from subtitle.cache import SubtitleCache
from subtitle.models import SubtitleSourceType, SubtitleState, SubtitleTrack
from subtitle.parser import convert_to_srt_file, load_and_normalize_subtitle


def process_local_subtitle(
    file_path: str,
    video_identifier: str,
    cache: Optional[SubtitleCache] = None
) -> SubtitleTrack:
    """Process a user-selected local subtitle file (.srt/.vtt/.ass/.ssa)."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File does not exist: {file_path}")

    filename = os.path.basename(file_path)
    stem, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext not in ('.srt', '.vtt', '.ass', '.ssa'):
        raise ValueError(f"Unsupported subtitle format: {ext}")

    # Load and validate content syntax
    cues, detected_ext = load_and_normalize_subtitle(file_path)
    if not cues:
        raise ValueError("No valid timing cues found in subtitle file")

    if cache is None:
        cache = SubtitleCache()

    # Convert VTT/ASS/SSA to SRT if needed
    if ext != '.srt':
        temp_srt_name = f"converted_{stem}.srt"
        v_dir = cache.get_video_cache_dir(video_identifier)
        temp_srt_path = os.path.join(v_dir, temp_srt_name)
        ready_path = convert_to_srt_file(file_path, temp_srt_path)
        sub_format = "srt"
    else:
        ready_path = file_path
        sub_format = "srt"

    track_name = f"Local: {filename}"
    return SubtitleTrack(
        id=f"local_{hash(file_path) & 0xffffffff:x}",
        name=track_name,
        language="User File",
        language_code="user",
        source=SubtitleSourceType.LOCAL_FILE,
        file_path=ready_path,
        format=sub_format,
        state=SubtitleState.READY
    )
