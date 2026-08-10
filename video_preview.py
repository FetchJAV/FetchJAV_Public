#!/usr/bin/env python
# coding: utf-8
"""Preview stream resolution and local HLS proxy support.

The GUI is CustomTkinter, so it cannot render site iframe embeds by itself.
This module resolves the same media URL used by the downloader and exposes a
localhost proxy that adds the headers/proxy settings needed by some hosts.
"""

from __future__ import annotations

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


def site_name_from_url(url: str) -> str:
    host = (urlparse(url or '').netloc or '').lower()
    if 'jable' in host or 'fs1.app' in host:
        return 'JableTV'
    if 'missav' in host:
        return 'MissAV'
    if 'supjav' in host:
        return 'SupJav'
    return host or 'Video'


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


def _looks_like_hls_playlist(url: str, content_type: str, body: bytes) -> bool:
    lowered_url = (url or '').split('?', 1)[0].lower()
    lowered_type = (content_type or '').lower()
    return (
        lowered_url.endswith(('.m3u8', '.m3u'))
        or 'mpegurl' in lowered_type
        or 'application/vnd.apple' in lowered_type
        or body.lstrip().startswith(b'#EXTM3U')
    )


def _make_session() -> requests.Session:
    session = requests.Session()
    session.mount(
        'http://',
        requests.adapters.HTTPAdapter(
            pool_connections=16,
            pool_maxsize=32,
            max_retries=1,
        ),
    )
    session.mount(
        'https://',
        SharedSSLAdapter(
            pool_connections=16,
            pool_maxsize=32,
            max_retries=1,
        ),
    )
    return session


class PreviewProxyServer:
    """A localhost-only media proxy for preview playback."""

    def __init__(self):
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._sources: dict[str, dict] = {}
        self._session = _make_session()

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self._server is not None:
            return

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

        headers = dict(source.get('headers') or {})
        range_header = handler.headers.get('Range')
        if range_header:
            headers['Range'] = range_header
        try:
            resp = self._session.get(
                target_url,
                headers=headers,
                timeout=(10, 60),
                stream=True,
                allow_redirects=True,
                **config.proxy_request_kwargs(),
            )
            content_type = resp.headers.get('Content-Type', '')
            if _looks_like_hls_playlist(target_url, content_type, b''):
                playlist_body = resp.content
                if not _looks_like_hls_playlist(target_url, content_type, playlist_body):
                    raise ValueError('Playlist response did not contain #EXTM3U')
                base = str(getattr(resp, 'url', '') or target_url)
                text = playlist_body.decode(resp.encoding or 'utf-8', errors='replace')
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
                    handler.wfile.write(body)
                try:
                    resp.close()
                except Exception:
                    pass
                return

            handler.send_response(resp.status_code)
            self._forward_headers(handler, resp)
            handler.send_header('Connection', 'close')
            handler.end_headers()
            if send_body:
                for chunk in resp.iter_content(chunk_size=262144):
                    if chunk:
                        handler.wfile.write(chunk)
            try:
                resp.close()
            except Exception:
                pass
        except Exception as exc:
            self._send_text(handler, 502, f'Preview proxy failed: {exc}', send_body)

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
