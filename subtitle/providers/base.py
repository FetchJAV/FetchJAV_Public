#!/usr/bin/env python
# coding: utf-8
"""Abstract base class for online subtitle providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from subtitle.models import OnlineSubtitleSearchResult


class SubtitleProvider(ABC):
    """Abstract interface for online subtitle providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the subtitle provider (e.g. SubtitleCat)."""
        pass

    @abstractmethod
    def search(self, query: str, language: Optional[str] = None) -> List[OnlineSubtitleSearchResult]:
        """Search for subtitles matching the query.
        
        Args:
            query: The search term (video code, catalog ID, or title).
            language: Optional language filter (e.g. 'en', 'ja', 'zh-TW').
            
        Returns:
            List of OnlineSubtitleSearchResult items.
        """
        pass

    @abstractmethod
    def download_subtitle(self, result: OnlineSubtitleSearchResult, destination_path: str) -> str:
        """Download a subtitle file specified by the search result to destination_path.
        
        Args:
            result: Target OnlineSubtitleSearchResult.
            destination_path: Local target file path to save the subtitle.
            
        Returns:
            The saved absolute local file path.
        """
        pass
