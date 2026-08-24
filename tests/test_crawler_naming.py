# coding: utf-8
"""Segment temp-file naming (collision-free by playlist index) and AES IV derivation
(implicit IV = media-sequence base + segment index; explicit IV overrides)."""
import sys
import types


def _stub(name, factory=None):
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = factory() if factory else types.ModuleType(name)


_stub('cloudscraper')
_stub('customtkinter')

from Crypto.Cipher import AES
from M3U8Sites.M3U8Crawler import M3U8Crawler


def test_seg_savename_unique_by_index():
    fake = types.SimpleNamespace(_temp_folder='/tmp/x')
    n0 = M3U8Crawler._seg_savename(fake, 0)
    n1 = M3U8Crawler._seg_savename(fake, 1)
    assert n0 != n1
    assert n0.endswith('000000.mp4')
    assert n1.endswith('000001.mp4')


def test_seg_savename_no_collision_on_shared_basename():
    # The bug: seg.ts?n=1 and seg.ts?n=2 (and same-named files in different dirs) share a
    # basename and collided into one temp file — silent corruption. Index naming can't.
    fake = types.SimpleNamespace(_temp_folder='/tmp/x')
    urls = ['https://a/seg.ts?n=1', 'https://a/seg.ts?n=2', 'https://b/seg.ts']
    names = [M3U8Crawler._seg_savename(fake, i) for i in range(len(urls))]
    assert len(set(names)) == len(urls)   # all distinct despite identical basenames


def test_make_cipher_implicit_iv_uses_media_sequence():
    key = b'0' * 16
    fake = types.SimpleNamespace(_key_content=key, _key_iv=None, _media_sequence=100)
    plaintext = b'A' * 16
    iv = (5 + 100).to_bytes(16, 'big')      # segment index 5 + EXT-X-MEDIA-SEQUENCE 100
    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(plaintext)
    cipher = M3U8Crawler._make_cipher(fake, 5)
    assert cipher.decrypt(enc) == plaintext


def test_make_cipher_explicit_iv_overrides_index():
    key = b'0' * 16
    fake = types.SimpleNamespace(_key_content=key,
                                 _key_iv='0x000102030405060708090a0b0c0d0e0f',
                                 _media_sequence=999)
    iv = bytes.fromhex('000102030405060708090a0b0c0d0e0f')
    plaintext = b'B' * 16
    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(plaintext)
    cipher = M3U8Crawler._make_cipher(fake, 7)   # explicit IV ignores seq/media_sequence
    assert cipher.decrypt(enc) == plaintext


def test_make_cipher_none_without_key():
    fake = types.SimpleNamespace(_key_content=None, _key_iv=None, _media_sequence=0)
    assert M3U8Crawler._make_cipher(fake, 0) is None


def test_crawler_source_subtitle_evidence_is_bound_to_its_source_site():
    crawler = object.__new__(M3U8Crawler)
    crawler._url = 'https://jable.tv/videos/ipzz-905/'
    crawler._source_subtitle_evidence = ()

    crawler.add_source_subtitle_evidence(
        ('missav-category-chinese-subtitle',))
    assert crawler.source_subtitle_evidence() == ()

    crawler.add_source_subtitle_evidence(
        ('jable-category-chinese-subtitle',))
    assert crawler.source_subtitle_evidence() == (
        'jable-category-chinese-subtitle',)


def test_prepare_crawl_reports_resumed_progress(tmp_path):
    crawler = object.__new__(M3U8Crawler)
    crawler._temp_folder = str(tmp_path)
    crawler._tsList = [f'https://example.test/seg_{i}.ts' for i in range(10)]

    # Simulate 6 segments already downloaded on disk
    for i in range(6):
        seg_file = tmp_path / f"{i:06d}.mp4"
        seg_file.write_bytes(b'TS_DATA_1234')

    progress_reports = []
    crawler._progress_callback = lambda done, total, speed: progress_reports.append((done, total, speed))
    crawler._startCrawl = lambda: None  # Mock start crawl

    M3U8Crawler._prepareCrawl(crawler)

    # Must find 4 pending segments out of 10
    assert len(crawler._pending_set) == 4
    # Initial progress report must show 6/10 completed (60%), not 0%
    assert progress_reports == [(6, 10, 0)]


def test_apply_filename_mode_default_keeps_full_title():
    from M3U8Sites.M3U8Crawler import _apply_filename_mode

    assert _apply_filename_mode('IPX-580 大姐姐', 'full-title') == 'IPX-580 大姐姐'
    assert _apply_filename_mode('IPX-580 大姐姐', 'nonsense') == 'IPX-580 大姐姐'


def test_apply_filename_mode_code_only_splits_at_first_whitespace():
    from M3U8Sites.M3U8Crawler import _apply_filename_mode

    assert _apply_filename_mode(
        'FC2-PPV-1234567 人気シリーズ', 'code-only') == 'FC2-PPV-1234567'
    # A title with no whitespace stays unchanged.
    assert _apply_filename_mode('FC2-PPV-1234567', 'code-only') == 'FC2-PPV-1234567'
    # Unicode whitespace counts too.
    assert _apply_filename_mode(
        'ABC-123\u3000タイトル', 'code-only') == 'ABC-123'
    assert _apply_filename_mode('', 'code-only') == ''


def test_download_incomplete_error_reports_remaining_segments():
    from M3U8Sites.M3U8Crawler import DownloadIncompleteError

    error = DownloadIncompleteError(7)
    assert error.remaining_segments == 7
    assert '7' in str(error)
    assert DownloadIncompleteError(None).remaining_segments >= 1


def test_missav_caps_segment_workers_and_shares_request_gate():
    from M3U8Sites.SiteMissAV import SiteMissAV

    assert SiteMissAV.segment_worker_cap == 4
    assert SiteMissAV.segment_retry_rounds == 10
    assert SiteMissAV.segment_retry_base_delay == 1.5
    assert SiteMissAV.segment_retry_max_delay == 8.0
    gate = getattr(SiteMissAV, '_segment_request_gate', None)
    assert gate is not None
    assert gate._initial_value == 8


def test_crawler_init_caps_and_reads_shared_filename_mode(monkeypatch):
    import config
    from M3U8Sites.SiteMissAV import SiteMissAV

    monkeypatch.setattr(config, 'get_max_workers_per_video', lambda: 16)
    # An unrecognizable URL makes __init__ return early (no network), but only
    # after worker capping and filename-mode resolution have run.
    missav = SiteMissAV('https://missav.ai/not-a-video-path', silence=True)
    assert missav._max_workers == 4
    assert missav._filename_mode in ('full-title', 'code-only')

    base = M3U8Crawler('https://jable.tv/definitely-not-real', silence=True)
    assert base._max_workers == 16
    assert base._segment_retry_rounds >= 1
    assert base._segment_retry_max_delay >= base._segment_retry_base_delay

