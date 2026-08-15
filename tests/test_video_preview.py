import threading

import requests

import config
from video_preview import (
    PreviewProxyServer,
    SegmentCache,
    extract_hls_segments_and_keys,
    resolve_preview_source,
    rewrite_hls_playlist,
    _strip_fake_header_data,
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


def test_resolve_preview_source_requests_site_default_server():
    calls = []

    class FakeJob:
        _m3u8url = 'https://cdn.example/master.m3u8'
        _imageUrl = ''
        _direct_url = ''
        _direct_referer = ''
        _extra_headers = {'Referer': 'https://supjav.com/'}

        def is_url_vaildate(self):
            return True

        def target_name(self):
            return 'Title'

        def _m3u8_headers(self):
            return dict(self._extra_headers)

    source = resolve_preview_source(
        'https://supjav.com/449233.html',
        listing={},
        site_factory=lambda *args, **kwargs: calls.append(kwargs) or FakeJob(),
    )

    assert source.is_playable
    assert source.media_kind == 'hls'
    assert calls and calls[0].get('prefer_site_default') is True


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


def test_proxy_preserves_percent_encoded_segment_urls(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    monkeypatch.setattr(config, 'proxy_request_kwargs', lambda: {})

    seen = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            seen.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', '4')
            self.end_headers()
            self.wfile.write(b'data')

        def log_message(self, fmt, *args):
            return

    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    upstream_port = upstream.server_address[1]
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    proxy = PreviewProxyServer()
    try:
        token = proxy.register({})
        # Signed CDN segment URLs contain literal percent-encoded sequences that the
        # proxy must NOT double-decode (regression: unquote(parse_qs(...)) corrupted
        # them and the CDN answered 403).
        target = f'http://127.0.0.1:{upstream_port}/seg.ts?token=a%2Cb%7Cc&x=1%252F2'
        resp = requests.get(proxy.proxied_url(token, target), timeout=10)
        assert resp.status_code == 200
        assert seen and seen[0] == '/seg.ts?token=a%2Cb%7Cc&x=1%252F2'
    finally:
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()


def test_forward_headers_drops_content_length_only_when_requested():
    class FakeResp:
        headers = {
            'Content-Type': 'video/MP2T',
            'Content-Length': '9999',
            'Content-Range': 'bytes 0-99/188',
            'Connection': 'keep-alive',
            'Transfer-Encoding': 'chunked',
        }

    captured = []

    class FakeHandler:
        def send_header(self, key, value):
            captured.append((str(key).lower(), str(value)))

    PreviewProxyServer._forward_headers(FakeHandler(), FakeResp(), drop_content_length=True)
    assert ('content-type', 'video/MP2T') in captured
    assert ('content-range', 'bytes 0-99/188') in captured
    assert ('content-length', '9999') not in captured
    assert 'connection' not in [key for key, _ in captured]
    assert 'transfer-encoding' not in [key for key, _ in captured]

    captured.clear()
    PreviewProxyServer._forward_headers(FakeHandler(), FakeResp(), drop_content_length=False)
    assert ('content-length', '9999') in captured


def test_proxy_strips_fake_png_header_and_drops_stale_content_length(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    monkeypatch.setattr(config, 'proxy_request_kwargs', lambda: {})

    packet = bytearray(188)
    packet[0] = 0x47
    packet[1:] = bytes((index % 187) + 1 for index in range(187))
    ts_segment = b''.join(bytes(packet) for _ in range(5))
    wrapped = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100 + ts_segment
    assert wrapped[:8] == b'\x89PNG\r\n\x1a\n'
    stripped = _strip_fake_header_data(wrapped)
    assert stripped == ts_segment
    assert len(stripped) != len(wrapped)

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            if self.path != '/seg.ts':
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'video/MP2T')
            self.send_header('Content-Length', str(len(wrapped)))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            self.wfile.write(wrapped)

        def log_message(self, fmt, *args):
            return

    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    upstream_port = upstream.server_address[1]
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    proxy = PreviewProxyServer()
    try:
        token = proxy.register({})
        proxied = proxy.proxied_url(token, f'http://127.0.0.1:{upstream_port}/seg.ts')
        resp = requests.get(proxied, timeout=10)
        assert resp.status_code == 200
        assert resp.content == ts_segment
        assert resp.content[:1] == b'\x47'
        assert resp.headers.get('Content-Length') is None
    finally:
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()
