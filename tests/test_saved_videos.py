import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config


class TestSavedVideos(unittest.TestCase):
    def setUp(self):
        # Clear saved videos before each test
        config.clear_saved_videos()

    def tearDown(self):
        config.clear_saved_videos()

    def test_saved_videos_crud(self):
        # Test initial state
        self.assertEqual(config.get_saved_videos(), [])
        self.assertFalse(config.is_video_saved('https://jable.tv/videos/test-001/'))

        # Test adding a video
        v1 = {
            'url': 'https://jable.tv/videos/test-001/',
            'title': 'Test Video 1',
            'thumbnail': 'https://example.com/thumb1.jpg',
            'duration': '12:34',
            'site_name': 'JableTV'
        }
        res = config.add_saved_video(v1)
        self.assertTrue(res)
        self.assertTrue(config.is_video_saved('https://jable.tv/videos/test-001/'))

        saved = config.get_saved_videos()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['url'], 'https://jable.tv/videos/test-001/')
        self.assertEqual(saved[0]['title'], 'Test Video 1')
        self.assertEqual(saved[0]['site_name'], 'JableTV')

        # Test toggling existing video (removes it)
        toggled = config.toggle_saved_video(v1)
        self.assertFalse(toggled)
        self.assertFalse(config.is_video_saved('https://jable.tv/videos/test-001/'))
        self.assertEqual(config.get_saved_videos(), [])

        # Test toggling non-existing video (adds it)
        v2 = {
            'url': 'https://missav.ai/cn/test-002',
            'title': 'Test Video 2',
            'site_name': 'MissAV'
        }
        toggled_2 = config.toggle_saved_video(v2)
        self.assertTrue(toggled_2)
        self.assertTrue(config.is_video_saved('https://missav.ai/cn/test-002'))

        # Test clearing saved videos
        config.clear_saved_videos()
        self.assertEqual(config.get_saved_videos(), [])


if __name__ == '__main__':
    unittest.main()
