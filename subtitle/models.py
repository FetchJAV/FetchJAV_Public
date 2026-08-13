#!/usr/bin/env python
# coding: utf-8
"""Data models for FetchJAV Preview Subtitle System."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SubtitleSourceType(str, Enum):
    GENERATED = "generated"
    LOCAL_FILE = "local"
    ONLINE = "online"


class SubtitleState(str, Enum):
    READY = "ready"
    GENERATING = "generating"
    DOWNLOADING = "downloading"
    ERROR = "error"


@dataclass
class SubtitleTrack:
    id: str
    name: str
    language: str
    language_code: str
    source: SubtitleSourceType
    file_path: str = ""
    format: str = "srt"
    active: bool = False
    state: SubtitleState = SubtitleState.READY
    error_msg: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "language": self.language,
            "language_code": self.language_code,
            "source": self.source.value if isinstance(self.source, SubtitleSourceType) else str(self.source),
            "file_path": self.file_path,
            "format": self.format,
            "active": self.active,
            "state": self.state.value if isinstance(self.state, SubtitleState) else str(self.state),
            "error_msg": self.error_msg,
        }


@dataclass
class OnlineSubtitleSearchResult:
    provider: str
    title: str
    language: str
    language_code: str
    download_url: str
    detail_url: str = ""
    size_str: str = ""
    downloads_str: str = ""
    source_format: str = "srt"
