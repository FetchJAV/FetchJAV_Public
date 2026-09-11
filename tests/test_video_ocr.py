# -*- coding: utf-8 -*-
"""Unit tests for Hardcoded Video-OCR Subtitle Extractor."""

import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image, ImageDraw
import config
from video_ocr import (
    format_srt_timestamp,
    SubtitleCue,
    VideoOCRExtractor,
    extract_subtitles_via_ocr,
)


def test_srt_timestamp_formatting():
    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_srt_timestamp(65.123) == "00:01:05,123"
    assert format_srt_timestamp(3661.5) == "01:01:01,500"


def test_subtitle_cue_to_srt():
    cue = SubtitleCue(start_time=1.5, end_time=4.2, text="Hello world! Test subtitle.")
    srt_block = cue.to_srt_block(1)
    assert "1\n" in srt_block
    assert "00:00:01,500 --> 00:00:04,200\n" in srt_block
    assert "Hello world! Test subtitle.\n" in srt_block


def test_cue_merging():
    extractor = VideoOCRExtractor(fps=2.0, min_duration=0.5, similarity_threshold=0.8)
    raw_cues = [
        (1.0, "This is a subtitle line"),
        (1.5, "This is a subtitle line"),
        (2.0, "This is a subtitle line!"),
        (4.0, "Another different line"),
        (4.5, "Another different line"),
    ]
    merged = extractor._merge_raw_cues(raw_cues)
    assert len(merged) == 2
    assert merged[0].start_time == 1.0
    assert merged[0].end_time == 2.5
    assert "This is a subtitle line" in merged[0].text
    assert merged[1].start_time == 4.0
    assert merged[1].end_time == 5.0
    assert merged[1].text == "Another different line"


def test_image_preprocessing():
    extractor = VideoOCRExtractor()
    img = Image.new('RGB', (300, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "SUBTITLE TEST", fill=(0, 0, 0))

    preprocessed = extractor.preprocess_frame(img)
    assert preprocessed is not None
    assert preprocessed.size == (300, 100)


def test_ocr_config_preferences():
    # Test enabled toggle
    original_enabled = config.get_video_ocr_enabled()
    config.set_video_ocr_enabled(False)
    assert config.get_video_ocr_enabled() is False
    config.set_video_ocr_enabled(True)
    assert config.get_video_ocr_enabled() is True

    # Test language preference
    config.set_video_ocr_lang('zh')
    assert config.get_video_ocr_lang() == 'zh'
    config.set_video_ocr_lang('en')
    assert config.get_video_ocr_lang() == 'en'
    config.set_video_ocr_lang('ko')
    assert config.get_video_ocr_lang() == 'ko'
    config.set_video_ocr_lang('invalid_lang')
    assert config.get_video_ocr_lang() == 'zh'

    # Test backend preference
    config.set_video_ocr_backend('rapidocr')
    assert config.get_video_ocr_backend() == 'rapidocr'
    config.set_video_ocr_backend('auto')
    assert config.get_video_ocr_backend() == 'auto'

    # Test auto mode preference
    config.set_video_ocr_auto_mode('always')
    assert config.get_video_ocr_auto_mode() == 'always'
    config.set_video_ocr_auto_mode('on_hardcoded_detected')
    assert config.get_video_ocr_auto_mode() == 'on_hardcoded_detected'

    # Restore original enabled state
    config.set_video_ocr_enabled(original_enabled)


def test_ocr_image_recognition():
    extractor = VideoOCRExtractor(backend='auto')
    img = Image.new('RGB', (400, 100), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "FETCHJAV TEST 123", fill=(255, 255, 255))

    text = extractor.ocr_image(img, lang='en')
    assert isinstance(text, str)
    # Check that text recognition found digits/words if OCR model is present
    if extractor._ocr_backend == 'rapidocr':
        assert "FETCHJAV" in text or "TEST" in text or "123" in text


def test_ocr_cancel_check():
    extractor = VideoOCRExtractor()
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_vid:
        tmp_vid_path = tmp_vid.name
    with tempfile.NamedTemporaryFile(suffix='.srt', delete=False) as tmp_srt:
        tmp_srt_path = tmp_srt.name

    try:
        # If cancel check returns True, extraction must abort immediately
        res = extractor.extract_from_video(
            video_path=tmp_vid_path,
            output_srt_path=tmp_srt_path,
            cancel_check=lambda: True
        )
        assert res is False
    finally:
        for p in (tmp_vid_path, tmp_srt_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
