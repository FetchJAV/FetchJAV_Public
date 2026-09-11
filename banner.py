#!/usr/bin/env python
# coding: utf-8
"""Remote announcement banner for FetchJAV Desktop.

Fetches a small JSON manifest from the project website so news, update
notices, or ads can be shown (or withdrawn) on user desktops without
shipping a new build.

Manifest format (served over HTTPS, e.g. GitHub Pages):
    {
      "id": "news-2026-08-22",          # unique per announcement
      "active": true,
      "type": "info" | "update" | "ad",
      "title": "...",
      "message": "...",
      "url": "https://...",             # optional click-through link
      "start": "YYYY-MM-DD",            # optional schedule (inclusive)
      "end": "YYYY-MM-DD",              # optional expiry (inclusive)
      "min_version": "0.1.5",           # optional version targeting
      "max_version": "0.2.0"
    }
"""

import hashlib
import json
import os
import threading
from datetime import date, datetime

import requests

import config

BANNER_URL = 'https://fetchjav.github.io/FetchJAV_Public/banner.json'
FETCH_TIMEOUT = 5
IMAGE_TIMEOUT = 20
CACHE_TTL_SEC = 3600
ALLOWED_TYPES = {'info', 'update', 'ad'}

_lock = threading.Lock()
_cached_manifest = None
_cached_at = 0.0
_dismissed_cache = None
_dismissed_lock = threading.Lock()


def _app_dir() -> str:
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'FetchJAV')


def _cache_path() -> str:
    return os.path.join(_app_dir(), 'banner_cache.json')


def _image_dir() -> str:
    return os.path.join(_app_dir(), 'banner_images')


def _dismissed_path() -> str:
    return os.path.join(_app_dir(), 'dismissed_banners.json')


def _parse_moment(value) -> 'datetime | None':
    """Accept YYYY-MM-DD or a full ISO timestamp; naive = local time."""
    text = str(value or '').strip()
    if not text:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.combine(date.fromisoformat(text), datetime.min.time())
    except Exception:
        return None


def _version_tuple(version: str):
    parts = []
    for chunk in str(version).strip().split('.'):
        digits = ''
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _clean_url(value) -> str:
    url = str(value or '').strip()
    if url.lower().startswith(('http://', 'https://')) and len(url) <= 500:
        return url
    return ''


def validate_manifest(raw) -> 'dict | None':
    """Return a cleaned manifest dict if raw is an active, currently-valid banner."""
    if not isinstance(raw, dict) or raw.get('active') is not True:
        return None

    bid = str(raw.get('id') or '').strip()
    title = str(raw.get('title') or '').strip()
    if not bid or not title:
        return None

    btype = str(raw.get('type') or 'info').strip().lower()
    if btype not in ALLOWED_TYPES:
        btype = 'info'

    start = _parse_moment(raw.get('start'))
    end = _parse_moment(raw.get('end'))
    now = datetime.now()
    if start and now < start:
        return None
    if end and now > end:
        return None

    min_ver = str(raw.get('min_version') or '').strip()
    max_ver = str(raw.get('max_version') or '').strip()

    return {
        'id': bid[:80],
        'type': btype,
        'title': title[:120],
        'message': str(raw.get('message') or '').strip()[:300],
        'url': _clean_url(raw.get('url')),
        'image': _clean_url(raw.get('image')),
        'start': raw.get('start') or '',
        'end': raw.get('end') or '',
        'min_version': min_ver,
        'max_version': max_ver,
    }


def matches_versions(manifest: dict, current_version: str) -> bool:
    min_ver = manifest.get('min_version')
    max_ver = manifest.get('max_version')
    cur = _version_tuple(current_version)
    if min_ver and cur < _version_tuple(min_ver):
        return False
    if max_ver and cur > _version_tuple(max_ver):
        return False
    return True


def dismissed_ids() -> set:
    global _dismissed_cache
    with _dismissed_lock:
        if _dismissed_cache is None:
            try:
                with open(_dismissed_path(), 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    _dismissed_cache = {str(x) for x in raw if x}
                else:
                    _dismissed_cache = set()
            except Exception:
                _dismissed_cache = set()
        return set(_dismissed_cache)


def _persist_dismissed(ids: set) -> None:
    try:
        os.makedirs(_app_dir(), exist_ok=True)
        with open(_dismissed_path(), 'w', encoding='utf-8') as f:
            json.dump(sorted(ids), f)
    except Exception:
        pass


def remember_dismissed(banner_id: str) -> None:
    global _dismissed_cache
    with _dismissed_lock:
        ids = set(_dismissed_cache) if _dismissed_cache is not None else dismissed_ids()
        ids.add(str(banner_id))
        ids = set(sorted(ids)[-50:])
        _dismissed_cache = set(ids)
    threading.Thread(target=_persist_dismissed, args=(set(ids),), daemon=True).start()


def _read_cache():
    try:
        with open(_cache_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('manifest'), dict):
            import time as _time
            return dict(data['manifest']), float(data.get('fetched_at') or 0)
    except Exception:
        pass
    return None, 0.0


def _write_cache(manifest: dict) -> None:
    try:
        os.makedirs(_app_dir(), exist_ok=True)
        import time as _time
        with open(_cache_path(), 'w', encoding='utf-8') as f:
            json.dump({'fetched_at': _time.time(), 'manifest': manifest}, f)
    except Exception:
        pass


def fetch_image(url: str) -> str:
    """Download a banner image to the local cache; return its path or ''."""
    if not url:
        return ''
    try:
        os.makedirs(_image_dir(), exist_ok=True)
        name = hashlib.sha1(url.encode('utf-8')).hexdigest()[:16] + '.img'
        path = os.path.join(_image_dir(), name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        proxy_kwargs = {}
        try:
            proxy_kwargs = config.proxy_request_kwargs()
        except Exception:
            pass
        resp = requests.get(url, timeout=IMAGE_TIMEOUT, **proxy_kwargs)
        if resp.status_code == 200 and resp.content:
            tmp = path + '.part'
            with open(tmp, 'wb') as f:
                f.write(resp.content)
            os.replace(tmp, path)
            return path
    except Exception:
        pass
    return ''


def fetch_manifest(current_version: str = '', force: bool = False) -> 'dict | None':
    """Return the manifest to display, or None.

    Uses the network at most once per CACHE_TTL_SEC; falls back to the last
    cached manifest (re-validated against its schedule) when offline.
    """
    global _cached_manifest, _cached_at

    with _lock:
        now_local = _now()
        if not force and _cached_manifest is not None \
                and (now_local - _cached_at) < CACHE_TTL_SEC:
            manifest = _cached_manifest
        else:
            manifest = None
            try:
                proxy_kwargs = config.proxy_request_kwargs()
            except Exception:
                proxy_kwargs = {}
            try:
                resp = requests.get(BANNER_URL, timeout=FETCH_TIMEOUT,
                                    **proxy_kwargs)
                if resp.status_code == 200:
                    parsed = validate_manifest(resp.json())
                    if parsed is not None:
                        manifest = parsed
                        _write_cache(parsed)
                        _cached_manifest = parsed
                        _cached_at = now_local
            except Exception:
                manifest = None

            if manifest is None:
                cached, fetched_at = _read_cache()
                if cached is not None and validate_manifest(cached) is not None:
                    manifest = cached
                    _cached_manifest = cached
                    _cached_at = fetched_at

        if manifest is None:
            return None
        if current_version and not matches_versions(manifest, current_version):
            return None
        if manifest.get('image'):
            manifest['_image_path'] = fetch_image(manifest['image'])
        return manifest


def _now() -> float:
    import time as _time
    return _time.time()
