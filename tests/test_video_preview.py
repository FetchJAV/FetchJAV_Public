import requests

from video_preview import (
    PreviewProxyServer,
    SegmentCache,
    extract_hls_segments_and_keys,
    resolve_preview_source,
    rewrite_hls_playlist,
)


def test_rewrite_hls_playlist_routes_segments_keys_and_variants_through_proxy():
    source = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="keys/main.key"
#EXT-X-MAP:URI='init.mp4'
#EXT-X-STREAM-INF:BANDWIDTH=1200000
variant/720p.m3u8
#EXTINF:6.0,
seg-1.ts
https://cdn.example.com/seg-2.ts
"""

    rewritten = rewrite_hls_playlist(
        source,
        'https://media.example.com/path/master.m3u8',
        lambda url: 'local:' + url,
    )

    assert 'URI="local:https://media.example.com/path/keys/main.key"' in rewritten
    assert "URI='local:https://media.example.com/path/init.mp4'" in rewritten
    assert 'local:https://media.example.com/path/variant/720p.m3u8' in rewritten
    assert 'local:https://media.example.com/path/seg-1.ts' in rewritten
    assert 'local:https://cdn.example.com/seg-2.ts' in rewritten


def test_extract_hls_segments_and_keys():
    source = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="keys/main.key"
#EXT-X-MAP:URI='init.mp4'
#EXT-X-STREAM-INF:BANDWIDTH=1200000
variant/720p.m3u8
#EXTINF:6.0,
seg-1.ts
https://cdn.example.com/seg-2.ts
"""
    segments, keys = extract_hls_segments_and_keys(source, 'https://media.example.com/path/master.m3u8')
    assert len(keys) == 2
    assert keys[0] == 'https://media.example.com/path/keys/main.key'
    assert keys[1] == 'https://media.example.com/path/init.mp4'
    assert len(segments) == 2
    assert segments[0] == 'https://media.example.com/path/seg-1.ts'
    assert segments[1] == 'https://cdn.example.com/seg-2.ts'


def test_segment_cache_lru_eviction():
    cache = SegmentCache(max_bytes=100)
    data1 = b'A' * 40
    data2 = b'B' * 40
    data3 = b'C' * 40

    cache.put('https://cdn.example/seg1.ts', {}, data1, 'video/MP2T')
    cache.put('https://cdn.example/seg2.ts', {}, data2, 'video/MP2T')
    assert cache.has('https://cdn.example/seg1.ts')
    assert cache.has('https://cdn.example/seg2.ts')

    # Adding seg3 should evict seg1 (oldest) because total exceeds 100
    cache.put('https://cdn.example/seg3.ts', {}, data3, 'video/MP2T')
    assert not cache.has('https://cdn.example/seg1.ts')
    assert cache.has('https://cdn.example/seg2.ts')
    assert cache.has('https://cdn.example/seg3.ts')


def test_preview_proxy_serves_cached_media_and_supports_range():
    proxy = PreviewProxyServer()
    try:
        token = proxy.register({})
        seg_url = 'https://cdn.example/sample.ts'
        fake_data = b'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        proxy._cache.put(seg_url, {}, fake_data, 'video/MP2T')

        proxied = proxy.proxied_url(token, seg_url)

        # 1. Full content request
        resp = requests.get(proxied, timeout=5)
        assert resp.status_code == 200
        assert resp.content == fake_data
        assert resp.headers.get('Content-Type') == 'video/MP2T'

        # 2. Byte-range request
        resp_range = requests.get(proxied, headers={'Range': 'bytes=0-9'}, timeout=5)
        assert resp_range.status_code == 206
        assert resp_range.content == b'0123456789'
        assert resp_range.headers.get('Content-Range') == f'bytes 0-9/{len(fake_data)}'
    finally:
        proxy.stop()


def test_resolve_preview_source_prefers_hls_metadata_from_downloader_job():
    class FakeJob:
        _imageUrl = 'https://img.example/poster.jpg'
        _m3u8url = 'https://cdn.example/master.m3u8'

        def is_url_vaildate(self):
            return True

        def target_name(self):
            return 'Fetched Title'

        def _m3u8_headers(self):
            return {'Referer': 'https://site.example/', 'User-Agent': 'UA'}

    source = resolve_preview_source(
        'https://jable.tv/videos/abc-123/',
        listing={'title': 'Listing Title', 'duration': '1:02:03'},
        site_factory=lambda *args, **kwargs: FakeJob(),
    )

    assert source.is_playable
    assert source.title == 'Listing Title'
    assert source.duration == '1:02:03'
    assert source.media_kind == 'hls'
    assert source.media_url == 'https://cdn.example/master.m3u8'
    assert source.thumbnail == 'https://img.example/poster.jpg'
    assert source.headers['Referer'] == 'https://site.example/'


def test_resolve_preview_source_supports_direct_mp4_jobs():
    class FakeJob:
        _direct_url = 'https://stream.example/video.mp4'
        _direct_referer = 'https://stream.example/embed/'
        _m3u8url = ''
        _imageUrl = ''

        def is_url_vaildate(self):
            return True

        def target_name(self):
            return 'Direct Title'

    source = resolve_preview_source(
        'https://supjav.com/123.html',
        site_factory=lambda *args, **kwargs: FakeJob(),
    )

    assert source.is_playable
    assert source.media_kind == 'mp4'
    assert source.media_url == 'https://stream.example/video.mp4'
    assert source.headers['Referer'] == 'https://stream.example/embed/'


def test_preview_proxy_register_returns_local_url():
    proxy = PreviewProxyServer()
    try:
        token = proxy.register({'Referer': 'https://site.example/'})
        proxied = proxy.proxied_url(token, 'https://cdn.example/master.m3u8')
        assert proxied.startswith('http://127.0.0.1:')
        assert '/preview/' in proxied
        assert 'https%3A%2F%2Fcdn.example%2Fmaster.m3u8' in proxied
    finally:
        proxy.stop()
