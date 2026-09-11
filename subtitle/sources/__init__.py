"""Subtitle sources module."""

from .generated import find_generated_subtitles
from .local import process_local_subtitle
from .online import search_online_subtitles, download_online_subtitle

__all__ = [
    "find_generated_subtitles",
    "process_local_subtitle",
    "search_online_subtitles",
    "download_online_subtitle",
]
