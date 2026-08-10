from video_preview import (
    PreviewProxyServer,
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
