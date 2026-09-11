#!/usr/bin/env python
# coding: utf-8
"""Unit tests for FetchJAV Preview Subtitle System."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from subtitle.cache import SubtitleCache
from subtitle.manager import SubtitleManager
from subtitle.models import (
    OnlineSubtitleSearchResult,
    SubtitleSourceType,
    SubtitleState,
    SubtitleTrack,
)
from subtitle.parser import (
    convert_to_srt_file,
    parse_ass,
    parse_srt,
    parse_vtt,
    sanitize_text,
)
from subtitle.providers.subtitlecat import SubtitleCatProvider
from subtitle.sources.generated import find_generated_subtitles
from subtitle.sources.local import process_local_subtitle
from subtitle.sources.online import download_online_subtitle, search_online_subtitles


class TestSubtitleParser(unittest.TestCase):
    def test_sanitize_text(self):
        text = "Hello <script>alert(1)</script> world! {\\b1}Bold{\\b0}"
        clean = sanitize_text(text)
        self.assertEqual(clean, "Hello  world! Bold")

    def test_parse_srt(self):
        srt_data = """1
00:00:01,000 --> 00:00:04,000
Hello World!

2
00:00:05,500 --> 00:00:08,200
Second cue
"""
        cues = parse_srt(srt_data)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 4000)
        self.assertEqual(cues[0].text, "Hello World!")
        self.assertEqual(cues[1].start_ms, 5500)
        self.assertEqual(cues[1].end_ms, 8200)

    def test_parse_vtt(self):
        vtt_data = """WEBVTT

00:00:01.000 --> 00:00:04.000 line:80%
WebVTT Test Line
"""
        cues = parse_vtt(vtt_data)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 4000)
        self.assertEqual(cues[0].text, "WebVTT Test Line")

    def test_parse_ass(self):
        ass_data = """[Script Info]
Title: Test ASS

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,ASS Subtitle Line\\NSecond Line
"""
        cues = parse_ass(ass_data)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 4000)
        self.assertIn("ASS Subtitle Line", cues[0].text)

    def test_convert_to_srt_file(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            vtt_path = os.path.join(tmp_dir, "test.vtt")
            srt_path = os.path.join(tmp_dir, "out.srt")
            with open(vtt_path, "w", encoding="utf-8") as f:
                f.write("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nConverted cue\n")
            
            res_path = convert_to_srt_file(vtt_path, srt_path)
            self.assertTrue(os.path.isfile(res_path))
            with open(res_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Converted cue", content)
            self.assertIn("00:00:01,000 --> 00:00:03,000", content)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestSubtitleCache(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.cache = SubtitleCache(root_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_and_list_cache(self):
        sub_file = os.path.join(self.tmp_dir, "source.srt")
        with open(sub_file, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nTest\n")

        saved_path = self.cache.save_subtitle_file(
            video_identifier="ABC-123",
            lang_code="en",
            filename="ABC-123.en.srt",
            source_path=sub_file,
            metadata={"provider": "TestProvider"}
        )
        self.assertTrue(os.path.isfile(saved_path))
        
        cached_items = self.cache.list_cached_subtitles("ABC-123")
        self.assertEqual(len(cached_items), 1)
        self.assertEqual(cached_items[0]['filename'], "ABC-123.en.srt")

    def test_cache_stats_and_clear_all(self):
        stats_empty = self.cache.get_cache_stats()
        self.assertEqual(stats_empty['file_count'], 0)
        self.assertEqual(stats_empty['total_bytes'], 0)

        other_tmp = tempfile.mkdtemp()
        try:
            sub_file = os.path.join(other_tmp, "source2.srt")
            with open(sub_file, "w", encoding="utf-8") as f:
                f.write("1\n00:00:01,000 --> 00:00:02,000\nHello World\n")

            self.cache.save_subtitle_file("DEF-456", "zh", "DEF-456.zh.srt", sub_file)
            self.cache.save_subtitle_file("GHI-789", "ja", "GHI-789.ja.srt", sub_file)

            stats = self.cache.get_cache_stats()
            self.assertEqual(stats['file_count'], 2)
            self.assertGreater(stats['total_bytes'], 0)

            removed = self.cache.clear_all()
            self.assertEqual(removed, 2)

            stats_after = self.cache.get_cache_stats()
            self.assertEqual(stats_after['file_count'], 0)
            self.assertEqual(stats_after['total_bytes'], 0)
            self.assertEqual(self.cache.list_cached_subtitles("DEF-456"), [])
        finally:
            shutil.rmtree(other_tmp, ignore_errors=True)


class TestSubtitleCatProvider(unittest.TestCase):
    @patch("subtitle.providers.subtitlecat.requests.Session.get")
    def test_search_and_detail(self, mock_get):
        html_search = """
        <table class="sub-table">
          <tbody>
            <tr><td><a href="subs/1234/ABC-123.html">ABC-123</a></td></tr>
          </tbody>
        </table>
        """
        html_detail = """
        <div class="sub-single">
          <span>English</span>
          <a href="/subs/1234/ABC-123-en.srt">Download</a>
        </div>
        <!-- ./Sub single -->
        """

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = html_search

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = html_detail

        mock_get.side_effect = [mock_resp1, mock_resp2]

        provider = SubtitleCatProvider()
        results = provider.search("ABC-123")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].language_code, "en")
        self.assertIn("ABC-123-en.srt", results[0].download_url)


class TestYtsSubtitlesProvider(unittest.TestCase):
    @patch("subtitle.providers.ytssubs.requests.Session.get")
    def test_search_yts(self, mock_get):
        html_search = '<a href="/movie-imdb/tt12345">Movie Title (2025)</a>'
        html_detail = '<h1>Movie Title (2025)</h1><a href="/subtitles/movie-2025-english-yify-123">Link</a>'

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = html_search

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = html_detail

        mock_get.side_effect = [mock_resp1, mock_resp2]

        from subtitle.providers.ytssubs import YtsSubtitlesProvider
        provider = YtsSubtitlesProvider()
        results = provider.search("Movie Title")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].provider, "YTS Subtitles")
        self.assertEqual(results[0].language_code, "en")


class TestOpenSubtitlesProvider(unittest.TestCase):
    @patch("subtitle.providers.opensubtitles.requests.Session.get")
    def test_search_opensubtitles(self, mock_get):
        mock_json = [
            {
                "SubFileName": "Test.Sub.srt",
                "SubLanguageID": "eng",
                "SubDownloadLink": "https://dl.opensubtitles.org/test.srt"
            }
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_json
        mock_get.return_value = mock_resp

        from subtitle.providers.opensubtitles import OpenSubtitlesProvider
        provider = OpenSubtitlesProvider()
        results = provider.search("Test Sub")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].provider, "OpenSubtitles")
        self.assertEqual(results[0].language_code, "en")


class TestSubtitleManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.mgr = SubtitleManager()
        self.mgr.cache = SubtitleCache(root_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_local_and_select_track(self):
        sub_file = os.path.join(self.tmp_dir, "local_test.srt")
        with open(sub_file, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:02,000\nLocal test\n")

        self.mgr.current_video_code = "XYZ-999"
        track = self.mgr.add_local_track(sub_file)
        self.assertIsNotNone(track)
        self.assertEqual(track.source, SubtitleSourceType.LOCAL_FILE)

        mock_vlc = MagicMock()
        success = self.mgr.set_active_track(track.id, mock_vlc)
        self.assertTrue(success)
        self.assertEqual(self.mgr.active_track_id, track.id)
        mock_vlc.video_set_subtitle_file.assert_called_once_with(track.file_path)

        # Disable track
        self.mgr.set_active_track(None, mock_vlc)
        self.assertIsNone(self.mgr.active_track_id)
        mock_vlc.video_set_spu.assert_called_once_with(-1)


if __name__ == "__main__":
    unittest.main()
