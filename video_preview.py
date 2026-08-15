#!/usr/bin/env python
# coding: utf-8
"""Preview stream resolution and local HLS proxy support.

The GUI is CustomTkinter, so it cannot render site iframe embeds by itself.
This module resolves the same media URL used by the downloader and exposes a
localhost proxy that adds the headers/proxy settings needed by some hosts,
along with an intelligent LRU segment cache and background lookahead prefetcher
for near-zero-latency playback and instant seeking.
"""

from __future__ import annotations

from collections import OrderedDict
import concurrent.futures
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
import time
import uuid
from typing import Callable, Optional
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests

import config
from config import site_name_from_url
from ssl_util import SharedSSLAdapter


HOP_BY_HOP_HEADERS = {
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailer',
    'transfer-encoding',
    'upgrade',
}


@dataclass
class PreviewSource:
    page_url: str
    title: str = ''
    thumbnail: str = ''
    duration: str = ''
    site_name: str = ''
    media_url: str = ''
    media_kind: str = ''
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ''

    @property
    def is_playable(self) -> bool:
        return bool(self.media_url and not self.error)


def resolve_preview_source(
    url: str,
    listing: Optional[dict] = None,
    site_factory: Optional[Callable[..., object]] = None,
) -> PreviewSource:
    """Resolve a supported video page into a playable media URL.

    ``site_factory`` exists for tests; production uses ``M3U8Sites.CreateSite``.
    """
    listing = dict(listing or {})
    source = PreviewSource(
        page_url=url,
        title=str(listing.get('title') or ''),
        thumbnail=str(listing.get('thumbnail') or ''),
        duration=str(listing.get('duration') or ''),
        site_name=site_name_from_url(url),
    )
    try:
        if site_factory is None:
            import M3U8Sites
            site_factory = M3U8Sites.CreateSite
        job = site_factory(url, savepath='', silence=True)
        if job is None:
            source.error = 'Unsupported URL'
            return source
        if not job.is_url_vaildate():
            err = getattr(job, '_last_error', None)
            source.error = str(err or 'No playable stream was found')
            return source

        source.title = source.title or str(job.target_name() or '')
        source.thumbnail = source.thumbnail or str(getattr(job, '_imageUrl', '') or '')

        direct_url = str(getattr(job, '_direct_url', '') or '')
        m3u8_url = str(getattr(job, '_m3u8url', '') or '')
        if m3u8_url:
            source.media_url = m3u8_url
            source.media_kind = 'hls'
            if hasattr(job, '_m3u8_headers'):
                source.headers = _clean_headers(job._m3u8_headers())
        elif direct_url:
            source.media_url = direct_url
            source.media_kind = 'mp4'
            source.headers = dict(config.headers)
            ref = str(getattr(job, '_direct_referer', '') or '')
            if ref:
                source.headers['Referer'] = ref
        else:
            source.error = 'No playable stream was found'
    except Exception as exc:
        source.error = str(exc or 'Preview failed')
    return source


def _clean_headers(headers: Optional[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in dict(headers or {}).items():
        if value is None:
            continue
        key_s = str(key).strip()
        if not key_s or key_s.lower() in HOP_BY_HOP_HEADERS:
            continue
        result[key_s] = str(value)
    if 'User-Agent' not in result and config.headers.get('User-Agent'):
        result['User-Agent'] = config.headers['User-Agent']
    return result


def _is_rewritable_uri(value: str) -> bool:
    uri = (value or '').strip()
    if not uri:
        return False
    lower = uri.lower()
    return not lower.startswith(('data:', 'skd:', 'urn:'))


def rewrite_hls_playlist(text: str, base_url: str, make_proxy_url: Callable[[str], str]) -> str:
    """Rewrite every playlist URI so VLC fetches it through the local proxy."""
    lines = []
    uri_attr_re = re.compile(r'URI=(["\'])(.*?)\1')
    for raw_line in (text or '').splitlines():
        line = raw_line
        stripped = raw_line.strip()
        if not stripped:
            lines.append(raw_line)
            continue
        if stripped.startswith('#'):
            def _replace_attr(match):
                quote_char, uri = match.group(1), match.group(2)
                if not _is_rewritable_uri(uri):
                    return match.group(0)
                proxied = make_proxy_url(urljoin(base_url, uri))
                return f'URI={quote_char}{proxied}{quote_char}'
            line = uri_attr_re.sub(_replace_attr, raw_line)
        elif _is_rewritable_uri(stripped):
            line = make_proxy_url(urljoin(base_url, stripped))
        lines.append(line)
    suffix = '\n' if text.endswith('\n') else ''
    return '\n'.join(lines) + suffix


def extract_hls_segments_and_keys(text: str, base_url: str) -> tuple[list[str], list[str]]:
    """Extract ordered segment URLs and encryption key/init URLs from an HLS playlist."""
    segments: list[str] = []
    keys: list[str] = []
    uri_attr_re = re.compile(r'URI=(["\'])(.*?)\1')
    for raw_line in (text or '').splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith('#'):
            if stripped.startswith(('#EXT-X-KEY:', '#EXT-X-MAP:', '#EXT-X-SESSION-KEY:')):
                for match in uri_attr_re.finditer(stripped):
                    uri = match.group(2)
                    if _is_rewritable_uri(uri):
                        keys.append(urljoin(base_url, uri))
        elif _is_rewritable_uri(stripped):
            lowered = stripped.split('?', 1)[0].lower()
            if not lowered.endswith(('.m3u8', '.m3u')):
                segments.append(urljoin(base_url, stripped))
    return segments, keys


def _strip_fake_header_data(data: bytes) -> bytes:
    """SupJav TV segments are MPEG-TS hidden behind a fake PNG header. Strip
    the fake header so VLC player receives valid MPEG-TS from the first 0x47 sync."""
    if not data or data[:1] == b'\x47':
        return data
    if data.startswith(b'\x89PNG\r\n\x1a\n') or data[:4] == b'\x89PNG':
        limit = min(len(data) - 188 * 4 - 1, 8000)
        i = 0
        while 0 <= i <= limit:
            j = data.find(b'\x47', i)
            if j < 0 or j > limit:
                break
            if all(data[j + 188 * n] == 0x47 for n in range(min(5, max(1, (len(data) - j) // 188)))):
                return data[j:]
            i = j + 1
    return data


def _looks_like_hls_playlist(url: str, content_type: str, body: bytes) -> bool:
    lowered_url = (url or '').split('?', 1)[0].lower()
    lowered_type = (content_type or '').lower()
    if (
        lowered_url.endswith(('.m3u8', '.m3u'))
        or 'mpegurl' in lowered_type
        or 'application/vnd.apple' in lowered_type
    ):
        return True
    if body:
        trimmed = body.lstrip()
        if (
            trimmed.startswith(b'#EXTM3U')
            or b'#EXT-X-STREAM-INF' in trimmed
            or b'#EXT-X-TARGETDURATION' in trimmed
            or b'#EXTINF:' in trimmed
        ):
            return True
    return False


def _make_session() -> requests.Session:
    session = requests.Session()
    session.mount(
        'http://',
        requests.adapters.HTTPAdapter(
            pool_connections=32,
            pool_maxsize=64,
            max_retries=1,
        ),
    )
    session.mount(
        'https://',
        SharedSSLAdapter(
            pool_connections=32,
            pool_maxsize=64,
            max_retries=1,
        ),
    )
    return session


class SegmentCache:
    """Thread-safe in-memory LRU cache for media segments, keys, and init data."""

    def __init__(self, max_bytes: int = 128 * 1024 * 1024):  # 128 MB cache
        self._max_bytes = max_bytes
        self._current_bytes = 0
        self._cache: OrderedDict[str, tuple[dict[str, str], bytes, str]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, url: str) -> Optional[tuple[dict[str, str], bytes, str]]:
        with self._lock:
            if url in self._cache:
                self._cache.move_to_end(url)
                return self._cache[url]
        return None

    def has(self, url: str) -> bool:
        with self._lock:
            return url in self._cache

    def put(self, url: str, headers: dict[str, str], data: bytes, content_type: str = '') -> None:
        size = len(data)
        if size > self._max_bytes:
            return
        with self._lock:
            if url in self._cache:
                _, old_data, _ = self._cache.pop(url)
                self._current_bytes -= len(old_data)
            while self._current_bytes + size > self._max_bytes and self._cache:
                _, (_, evicted_data, _) = self._cache.popitem(last=False)
                self._current_bytes -= len(evicted_data)
            self._cache[url] = (headers, data, content_type)
            self._current_bytes += size

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._current_bytes = 0


class PreviewProxyServer:
    """A high-performance localhost media proxy with LRU caching and lookahead prefetching."""

    def __init__(self):
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._sources: dict[str, dict] = {}
        self._session = _make_session()
        self._cache = SegmentCache(max_bytes=128 * 1024 * 1024)
        self._prefetch_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._in_flight: set[str] = set()
        self._in_flight_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self._server is not None:
            return

        if self._prefetch_pool is None:
            self._prefetch_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=4,
                thread_name_prefix='PreviewPrefetch',
            )

        owner = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                owner._handle(self, send_body=True)

            def do_HEAD(self):
                owner._handle(self, send_body=False)

            def log_message(self, fmt, *args):
                return

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name='PreviewProxyServer',
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        self._thread = None

        if self._prefetch_pool is not None:
            try:
                self._prefetch_pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._prefetch_pool = None

        self._cache.clear()
        with self._in_flight_lock:
            self._in_flight.clear()

        try:
            self._session.close()
        except Exception:
            pass

    def register(self, headers: Optional[dict]) -> str:
        self.start()
        token = uuid.uuid4().hex
        with self._lock:
            self._sources[token] = {
                'headers': _clean_headers(headers),
                'created_at': time.time(),
                'segments': [],
                'seg_map': {},
                'keys': [],
            }
        return token

    def proxied_url(self, token: str, target_url: str) -> str:
        if self._server is None:
            raise RuntimeError('Preview proxy is not running')
        port = int(self._server.server_address[1])
        encoded = quote(str(target_url or ''), safe='')
        return f'http://127.0.0.1:{port}/preview/{token}?url={encoded}'

    def _source(self, token: str) -> Optional[dict]:
        with self._lock:
            return self._sources.get(token)

    def _trigger_lookahead_prefetch(self, token: str, current_url: str, count: int = 4) -> None:
        """Prefetch subsequent segments into memory for instantaneous seeking & smooth playback."""
        pool = self._prefetch_pool
        if pool is None:
            return
        source = self._source(token)
        if not source:
            return
        seg_map = source.get('seg_map', {})
        segments = source.get('segments', [])
        idx = seg_map.get(current_url)
        if idx is None or idx < 0 or not segments:
            return

        next_urls = segments[idx + 1 : idx + 1 + count]
        for url in next_urls:
            if not self._cache.has(url):
                with self._in_flight_lock:
                    if url in self._in_flight:
                        continue
                    self._in_flight.add(url)
                try:
                    pool.submit(self._prefetch_worker, token, url)
                except Exception:
                    with self._in_flight_lock:
                        self._in_flight.discard(url)

    def _prefetch_worker(self, token: str, url: str) -> None:
        try:
            source = self._source(token)
            if not source or self._cache.has(url):
                return
            headers = dict(source.get('headers') or {})
            resp = self._session.get(
                url,
                headers=headers,
                timeout=(10, 30),
                stream=False,
                allow_redirects=True,
                **config.proxy_request_kwargs(),
            )
            if resp.status_code == 200 and resp.content:
                data = _strip_fake_header_data(resp.content)
                content_type = resp.headers.get('Content-Type', 'video/MP2T')
                cache_headers = {
                    k: str(v)
                    for k, v in resp.headers.items()
                    if k.lower() in {
                        'content-type',
                        'content-length',
                        'etag',
                        'last-modified',
                        'accept-ranges',
                    }
                }
                self._cache.put(url, cache_headers, data, content_type)
        except Exception:
            pass
        finally:
            with self._in_flight_lock:
                self._in_flight.discard(url)

    def _handle_cached_media(
        self,
        handler: BaseHTTPRequestHandler,
        url: str,
        token: str,
        cached: tuple[dict[str, str], bytes, str],
        send_body: bool,
    ) -> None:
        cache_headers, data, content_type = cached
        total_len = len(data)
        range_header = handler.headers.get('Range')

        # Trigger lookahead prefetching for consecutive segments
        self._trigger_lookahead_prefetch(token, url)

        if range_header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header.strip())
            if match:
                start_s, end_s = match.group(1), match.group(2)
                if start_s and end_s:
                    start = int(start_s)
                    end = min(int(end_s), total_len - 1)
                elif start_s:
                    start = int(start_s)
                    end = total_len - 1
                elif end_s:
                    suffix = int(end_s)
                    start = max(0, total_len - suffix)
                    end = total_len - 1
                else:
                    start = 0
                    end = total_len - 1

                if start >= total_len or start > end:
                    handler.send_response(416)
                    handler.send_header('Content-Range', f'bytes */{total_len}')
                    handler.send_header('Connection', 'close')
                    handler.end_headers()
                    return

                sliced = data[start : end + 1]
                handler.send_response(206)
                handler.send_header('Content-Type', content_type or 'video/MP2T')
                handler.send_header('Content-Range', f'bytes {start}-{end}/{total_len}')
                handler.send_header('Content-Length', str(len(sliced)))
                handler.send_header('Accept-Ranges', 'bytes')
                handler.send_header('Connection', 'close')
                handler.end_headers()
                if send_body:
                    try:
                        handler.wfile.write(sliced)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                return

        # Full cached segment response (200 OK)
        handler.send_response(200)
        handler.send_header('Content-Type', content_type or 'video/MP2T')
        handler.send_header('Content-Length', str(total_len))
        handler.send_header('Accept-Ranges', 'bytes')
        handler.send_header('Cache-Control', 'public, max-age=3600')
        handler.send_header('Connection', 'close')
        handler.end_headers()
        if send_body:
            try:
                handler.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _handle(self, handler: BaseHTTPRequestHandler, send_body: bool) -> None:
        parsed = urlparse(handler.path)
        match = re.fullmatch(r'/preview/([0-9a-f]{32})', parsed.path)
        if not match:
            self._send_text(handler, 404, 'Not found', send_body)
            return
        token = match.group(1)
        source = self._source(token)
        if not source:
            self._send_text(handler, 404, 'Preview source expired', send_body)
            return
        target_url = parse_qs(parsed.query).get('url', [''])[0]
        target_url = unquote(target_url)
        if not target_url.startswith(('http://', 'https://')):
            self._send_text(handler, 400, 'Invalid media URL', send_body)
            return

        # Fast RAM cache check for instant zero-latency playback & seek
        cached = self._cache.get(target_url)
        if cached is not None:
            self._handle_cached_media(handler, target_url, token, cached, send_body)
            return

        headers = dict(source.get('headers') or {})
        range_header = handler.headers.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            resp = self._session.get(
                target_url,
                headers=headers,
                timeout=(15, 60),
                stream=True,
                allow_redirects=True,
                **config.proxy_request_kwargs(),
            )
            content_type = resp.headers.get('Content-Type', '')
            lowered_url = (target_url or '').split('?', 1)[0].lower()
            lowered_type = (content_type or '').lower()
            is_definitely_hls = (
                lowered_url.endswith(('.m3u8', '.m3u'))
                or 'mpegurl' in lowered_type
                or 'application/vnd.apple' in lowered_type
            )

            # Detect HLS playlist by URL / Content-Type or inspecting initial chunk
            if is_definitely_hls or resp.status_code == 200:
                chunk_iterator = resp.iter_content(chunk_size=65536)
                try:
                    first_chunk = next(chunk_iterator)
                except StopIteration:
                    first_chunk = b''

                if is_definitely_hls or _looks_like_hls_playlist(target_url, content_type, first_chunk):
                    remaining = b''.join(chunk_iterator)
                    playlist_body = first_chunk + remaining
                    base = str(getattr(resp, 'url', '') or target_url)
                    text = playlist_body.decode(resp.encoding or 'utf-8', errors='replace')

                    # Track segments and encryption keys for forward lookahead prefetching
                    segments, keys = extract_hls_segments_and_keys(text, base)
                    if segments:
                        source['segments'] = segments
                        source['seg_map'] = {u: i for i, u in enumerate(segments)}
                        # Prefetch initial segments immediately for instant video startup
                        if self._prefetch_pool is not None:
                            for pre_url in segments[:3]:
                                if not self._cache.has(pre_url):
                                    with self._in_flight_lock:
                                        if pre_url not in self._in_flight:
                                            self._in_flight.add(pre_url)
                                            try:
                                                self._prefetch_pool.submit(self._prefetch_worker, token, pre_url)
                                            except Exception:
                                                self._in_flight.discard(pre_url)
                    if keys:
                        source['keys'] = keys
                        if self._prefetch_pool is not None:
                            for key_url in keys:
                                if not self._cache.has(key_url):
                                    with self._in_flight_lock:
                                        if key_url not in self._in_flight:
                                            self._in_flight.add(key_url)
                                            try:
                                                self._prefetch_pool.submit(self._prefetch_worker, token, key_url)
                                            except Exception:
                                                self._in_flight.discard(key_url)

                    body = rewrite_hls_playlist(
                        text,
                        base,
                        lambda url: self.proxied_url(token, url),
                    ).encode('utf-8')
                    handler.send_response(200)
                    handler.send_header('Content-Type', 'application/vnd.apple.mpegurl; charset=utf-8')
                    handler.send_header('Content-Length', str(len(body)))
                    handler.send_header('Cache-Control', 'no-store')
                    handler.send_header('Connection', 'close')
                    handler.end_headers()
                    if send_body:
                        try:
                            handler.wfile.write(body)
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    try:
                        resp.close()
                    except Exception:
                        pass
                    return
                else:
                    # Media chunk (TS / MP4): strip fake PNG header if present
                    first_chunk = _strip_fake_header_data(first_chunk)
                    handler.send_response(resp.status_code)
                    self._forward_headers(handler, resp)
                    handler.send_header('Accept-Ranges', 'bytes')
                    handler.send_header('Connection', 'close')
                    handler.end_headers()

                    downloaded_chunks: list[bytes] = []
                    if send_body:
                        try:
                            if first_chunk:
                                handler.wfile.write(first_chunk)
                                downloaded_chunks.append(first_chunk)
                            for chunk in chunk_iterator:
                                if chunk:
                                    handler.wfile.write(chunk)
                                    downloaded_chunks.append(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            pass

                    # Cache chunk in RAM for instant backward seeking / replay
                    if resp.status_code == 200 and downloaded_chunks:
                        full_data = b''.join(downloaded_chunks)
                        cache_headers = {
                            k: str(v)
                            for k, v in resp.headers.items()
                            if k.lower() in {
                                'content-type',
                                'content-length',
                                'etag',
                                'last-modified',
                                'accept-ranges',
                            }
                        }
                        self._cache.put(target_url, cache_headers, full_data, content_type)
                        self._trigger_lookahead_prefetch(token, target_url)

                    try:
                        resp.close()
                    except Exception:
                        pass
                    return

            # Non-200 responses
            handler.send_response(resp.status_code)
            self._forward_headers(handler, resp)
            handler.send_header('Connection', 'close')
            handler.end_headers()
            if send_body:
                try:
                    for chunk in resp.iter_content(chunk_size=262144):
                        if chunk:
                            handler.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            try:
                resp.close()
            except Exception:
                pass
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                self._send_text(handler, 502, f'Preview proxy failed: {exc}', send_body)
            except Exception:
                pass

    @staticmethod
    def _forward_headers(handler: BaseHTTPRequestHandler, resp: requests.Response) -> None:
        forwarded = {
            'content-type',
            'content-length',
            'content-range',
            'accept-ranges',
            'cache-control',
            'expires',
            'last-modified',
            'etag',
        }
        for key, value in resp.headers.items():
            key_l = str(key).lower()
            if key_l in forwarded and key_l not in HOP_BY_HOP_HEADERS:
                handler.send_header(str(key), str(value))

    @staticmethod
    def _send_text(
        handler: BaseHTTPRequestHandler,
        status: int,
        message: str,
        send_body: bool = True,
    ) -> None:
        body = (message or '').encode('utf-8', errors='replace')
        handler.send_response(status)
        handler.send_header('Content-Type', 'text/plain; charset=utf-8')
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Connection', 'close')
        handler.end_headers()
        if send_body:
            handler.wfile.write(body)
