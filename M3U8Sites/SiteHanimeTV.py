#!/usr/bin/env python
# coding: utf-8
"""Hanime.tv HLS downloader and browse/search adapter."""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

import cloudscraper
try:
    from curl_cffi import requests as cffi_requests
    _use_cffi = True
except ImportError:
    _use_cffi = False
from bs4 import BeautifulSoup

import config
import site_i18n
from M3U8Sites.M3U8Crawler import (
    M3U8Crawler,
    MirrorsBlockedError,
    get_resolution_pref,
    request_headers,
    select_variant,
)

HANIME_TV_ROOT = 'https://hanime.tv'
HANIME_TV_HOME = HANIME_TV_ROOT + '/'
HANIME_TV_SEARCH_HVS_API = 'https://auth.hanime.tv/api/v11/search_hvs'

_browser_local = threading.local()
_cache_lock = threading.Lock()
_catalog_cache = None
_catalog_timestamp = 0
_CATALOG_TTL = 3600  # 1 hour cache


def _get_node_path():
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        for cand in [
            os.path.join(exe_dir, 'node.exe'),
            os.path.join(exe_dir, 'bin', 'node.exe'),
            os.path.join(getattr(sys, '_MEIPASS', ''), 'node.exe')
        ]:
            if os.path.exists(cand):
                return cand
    node = shutil.which('node')
    if node:
        return node
    for candidate in [
        r'C:\Program Files\nodejs\node.exe',
        r'C:\Program Files (x86)\nodejs\node.exe',
        os.path.expanduser('~/.nvm/versions/node/current/bin/node'),
        '/usr/bin/node',
        '/usr/local/bin/node',
    ]:
        if os.path.exists(candidate):
            return candidate
    return 'node'


def _load_catalog():
    """Fetch or return cached full catalog of hanime.tv videos."""
    global _catalog_cache, _catalog_timestamp
    now = time.time()
    with _cache_lock:
        if _catalog_cache is not None and (now - _catalog_timestamp) < _CATALOG_TTL:
            return _catalog_cache

    try:
        session = None
        if _use_cffi:
            try:
                session = cffi_requests.Session(impersonate='chrome')
            except Exception:
                session = None
        if session is None:
            session = cloudscraper.create_scraper(browser=request_headers, delay=10)

        resp = session.get(
            HANIME_TV_SEARCH_HVS_API,
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': HANIME_TV_HOME},
            timeout=30,
            **config.proxy_request_kwargs(),
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                with _cache_lock:
                    _catalog_cache = data
                    _catalog_timestamp = now
                return data
    except Exception as e:
        print(f"[HanimeTV] Failed to load catalog: {e}")

    with _cache_lock:
        if _catalog_cache is not None:
            return _catalog_cache
    return []


def _no_window_kwargs():
    """Build kwargs to completely suppress console window popups on Windows."""
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = si
    return kwargs


def _extract_video_manifest(slug):
    """Execute Node extractor to perform handshake and get stream m3u8 URLs with automatic retries."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    extractor_path = os.path.join(script_dir, 'hanimetv_extractor.mjs')
    node_path = _get_node_path()

    last_error = None
    for attempt in range(1, 4):
        try:
            proc = subprocess.run(
                [node_path, extractor_path, slug],
                capture_output=True,
                text=True,
                cwd=script_dir,
                timeout=25,
                **_no_window_kwargs(),
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                if data.get('status') == 'ok' and data.get('sources'):
                    return data
            last_error = f"Exit code {proc.returncode}: {proc.stderr or proc.stdout}"
        except Exception as e:
            last_error = str(e)
        time.sleep(0.4 * attempt)

    raise Exception(f"HanimeTV extractor error: {last_error}")


def _resolve_canonical_slug(slug_or_url):
    """Resolve an input slug or URL to the exact canonical slug in the Hanime.tv catalog."""
    if not slug_or_url:
        return ''
    slug = slug_or_url.rstrip('/').rsplit('/', 1)[-1]
    catalog = _load_catalog()
    if not catalog:
        return slug

    # 1. Exact match
    for item in catalog:
        if item.get('slug') == slug:
            return slug

    # 2. Normalized slug match
    norm_target = re.sub(r'[^a-zA-Z0-9]', '', slug.lower())
    for item in catalog:
        s = item.get('slug', '')
        if re.sub(r'[^a-zA-Z0-9]', '', s.lower()) == norm_target:
            return s

    # 3. Match against title / name
    for item in catalog:
        name = item.get('name', '')
        if name and re.sub(r'[^a-zA-Z0-9]', '', name.lower()) == norm_target:
            return item.get('slug')

    # 4. Fuzzy series + part match (e.g. 'resort-boin-1' -> 'resort-boin-uncensored-re-release-1')
    try:
        from video_identity import extract_series_info, normalize_series_key
        target_base, target_part, _ = extract_series_info(slug.replace('-', ' '))
        if target_base and target_part:
            norm_base = normalize_series_key(target_base)
            for item in catalog:
                i_slug = item.get('slug', '')
                i_name = item.get('name', '')
                b1, p1, _ = extract_series_info(i_slug.replace('-', ' '))
                b2, p2, _ = extract_series_info(i_name)
                if ((b1 and (normalize_series_key(b1) == norm_base or norm_base in normalize_series_key(b1)) and p1 == target_part) or
                    (b2 and (normalize_series_key(b2) == norm_base or norm_base in normalize_series_key(b2)) and p2 == target_part)):
                    return i_slug
    except Exception:
        pass

    return slug


class SiteHanimeTV(M3U8Crawler):
    """Downloader for hanime.tv videos."""

    website_pattern = r'https?://(?:[a-zA-Z0-9-]+\.)?hanime\.tv/videos/hentai/([a-zA-Z0-9\-_]+)'
    website_dirname_pattern = website_pattern

    @classmethod
    def validate_url(cls, url):
        if not url:
            return None
        url = str(url).strip()
        try:
            parsed = urlsplit(url)
        except Exception:
            return None
        if parsed.scheme.lower() not in ('http', 'https'):
            return None
        host = (parsed.hostname or '').lower()
        if 'hanime.tv' not in host:
            return None
        m = re.search(r'/videos/hentai/([a-zA-Z0-9\-_]+)', parsed.path)
        if m:
            return m.group(1)
        return None

    def get_url_infos(self):
        raw_slug = self.validate_url(self._url)
        if not raw_slug:
            raise Exception(f"無效的 Hanime.tv 網址: {self._url}")

        slug = _resolve_canonical_slug(raw_slug)

        self._extra_headers = {
            'Referer': f'https://hanime.tv/videos/hentai/{slug}',
            'Origin': 'https://hanime.tv',
        }

        # 1. Fetch metadata from page
        try:
            session = None
            if _use_cffi:
                try:
                    session = cffi_requests.Session(impersonate='chrome')
                except Exception:
                    session = None
            if session is None:
                session = cloudscraper.create_scraper(browser=request_headers, delay=10)

            resp = session.get(
                self._url,
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': HANIME_TV_HOME},
                timeout=20,
                **config.proxy_request_kwargs(),
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, 'html.parser')
                meta_title = soup.find('meta', property='og:title')
                if meta_title and meta_title.get('content'):
                    t = meta_title['content'].strip()
                    t = re.sub(r'\s*-\s*hanime\.tv\s*$', '', t, flags=re.I)
                    t = re.sub(r'^Watch\s+', '', t, flags=re.I)
                    t = re.sub(r'\s+Hentai Video in.*$', '', t, flags=re.I)
                    self._targetName = t
                meta_img = soup.find('meta', property='og:image')
                if meta_img and meta_img.get('content'):
                    self._imageUrl = meta_img['content']
        except Exception:
            pass

        # Fallback metadata from catalog if needed
        if not self._targetName:
            catalog = _load_catalog()
            for item in catalog:
                if item.get('slug') == slug or item.get('slug') == raw_slug:
                    self._targetName = item.get('name') or slug
                    self._imageUrl = item.get('poster_url') or item.get('cover_url')
                    break
        if not self._targetName:
            self._targetName = slug

        # 2. Extract sources via node handshake extractor
        manifest_info = _extract_video_manifest(slug)
        sources = manifest_info.get('sources', [])
        if not sources:
            raise Exception(f"無法取得影片串流來源: {self._url}")

        # Sort sources by resolution / preference
        pref = get_resolution_pref()
        selected_url = None

        if pref in ('1080', '720', '480', '360'):
            target_h = int(pref)
            exact = [s for s in sources if s.get('height') == target_h and s.get('url')]
            if exact:
                selected_url = exact[0]['url']

        if not selected_url:
            if pref == 'lowest':
                sorted_sources = sorted([s for s in sources if s.get('url')], key=lambda x: x.get('height', 0))
            else:
                sorted_sources = sorted([s for s in sources if s.get('url')], key=lambda x: x.get('height', 0), reverse=True)
            if sorted_sources:
                selected_url = sorted_sources[0]['url']

        if not selected_url:
            selected_url = sources[0]['url']

        self._m3u8url = selected_url

        # 3. Calculate playlist duration
        try:
            import requests as _requests
            hls_resp = _requests.get(
                selected_url,
                headers=self._extra_headers,
                timeout=10,
                **config.proxy_request_kwargs(),
            )
            if hls_resp.status_code == 200:
                extinfs = [float(m.group(1)) for m in [re.search(r'#EXTINF:([0-9\.]+)', l) for l in hls_resp.text.splitlines()] if m]
                if extinfs:
                    total_sec = int(sum(extinfs))
                    mins = total_sec // 60
                    secs = total_sec % 60
                    hrs = mins // 60
                    mins = mins % 60
                    if hrs > 0:
                        self._duration = f'{hrs}:{mins:02d}:{secs:02d}'
                    else:
                        self._duration = f'{mins:02d}:{secs:02d}'
                    _save_duration(slug, self._duration)
                    _save_duration(raw_slug, self._duration)
                    _save_duration(self._url, self._duration)
        except Exception:
            pass


_duration_cache_lock = threading.Lock()
_duration_cache = {}


def _get_duration_cache_file():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = os.path.join(base, 'FetchJAV')
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, 'hanimetv_durations.json')


def _load_duration_cache():
    global _duration_cache
    with _duration_cache_lock:
        if not _duration_cache:
            cache_file = _get_duration_cache_file()
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        _duration_cache = json.load(f)
                except Exception:
                    _duration_cache = {}
            else:
                _duration_cache = {}
        return dict(_duration_cache)


def _save_duration(key, duration):
    if not key or not duration:
        return
    global _duration_cache
    with _duration_cache_lock:
        _duration_cache[str(key)] = str(duration)
        cache_file = _get_duration_cache_file()
        try:
            tmp = cache_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(_duration_cache, f, indent=2)
            if os.path.exists(tmp):
                os.replace(tmp, cache_file)
        except Exception:
            pass


def get_hanimetv_duration_fast(slug_or_url: str) -> str:
    """Quickly resolve or look up duration for a Hanime.tv video."""
    if not slug_or_url:
        return ''
    slug = slug_or_url.rstrip('/').rsplit('/', 1)[-1] if '/' in slug_or_url else slug_or_url
    cache = _load_duration_cache()
    if slug in cache:
        return cache[slug]
    if slug_or_url in cache:
        return cache[slug_or_url]

    try:
        canon_slug = _resolve_canonical_slug(slug)
        manifest = _extract_video_manifest(canon_slug)
        sources = manifest.get('sources', [])
        if not sources:
            return ''
        hls_url = sources[0].get('url')
        if not hls_url:
            return ''

        import requests as _requests
        resp = _requests.get(
            hls_url,
            headers={'Referer': f'https://hanime.tv/videos/hentai/{canon_slug}', 'Origin': 'https://hanime.tv'},
            timeout=8,
            **config.proxy_request_kwargs()
        )
        if resp.status_code == 200:
            extinfs = [float(m.group(1)) for m in [re.search(r'#EXTINF:([0-9\.]+)', l) for l in resp.text.splitlines()] if m]
            if extinfs:
                total_sec = int(sum(extinfs))
                mins = total_sec // 60
                secs = total_sec % 60
                hrs = mins // 60
                mins = mins % 60
                dur = f'{hrs}:{mins:02d}:{secs:02d}' if hrs > 0 else f'{mins:02d}:{secs:02d}'
                _save_duration(slug, dur)
                _save_duration(canon_slug, dur)
                _save_duration(slug_or_url, dur)
                return dur
    except Exception:
        pass
    return ''


class HanimeTVBrowser:
    """Browser catalog adapter for hanime.tv."""

    _url_root = HANIME_TV_ROOT

    get_video_duration = staticmethod(get_hanimetv_duration_fast)

    FEEDS = [
        ('新作上市', 'https://hanime.tv/browse/newest'),
        ('最近更新', 'https://hanime.tv/browse/recent'),
        ('熱門排行', 'https://hanime.tv/browse/trending'),
        ('最多觀看', 'https://hanime.tv/browse/views'),
        ('最多喜歡', 'https://hanime.tv/browse/likes'),
    ]

    TAGS = [
        ('無碼', 'uncensored'),
        ('中出', 'creampie'),
        ('口交', 'blow job'),
        ('人妻/熟女', 'milf'),
        ('女僕', 'maid'),
        ('精靈', 'elf'),
        ('女高中生', 'school girl'),
        ('純愛', 'vanilla'),
        ('3D', '3d'),
        ('Cosplay', 'cosplay'),
        ('巨乳', 'big boobs'),
        ('強姦', 'rape'),
        ('NTR', 'ntr'),
        ('後宮', 'harem'),
        ('百合', 'yuri'),
        ('扶他', 'futanari'),
    ]

    BRANDS = [
        ('Queen Bee', 'Queen Bee'),
        ('PoRin', 'PoRin'),
        ('Bunnywalker', 'Bunnywalker'),
        ('Pink Pineapple', 'Pink Pineapple'),
        ('T-Rex', 'T-Rex'),
        ('Mary Jane', 'Mary Jane'),
        ('MS Pictures', 'MS Pictures'),
        ('Seven', 'Seven'),
        ('Suzuki Mirano', 'Suzuki Mirano'),
        ('Mousou Zoku', 'Mousou Zoku'),
    ]

    CATEGORIES = [
        *FEEDS,
        *[(name, f'https://hanime.tv/browse/tags/{quote(slug)}') for name, slug in TAGS],
    ]

    @classmethod
    def fetch_categories(cls, lang=''):
        cats = []
        is_en = (lang or '').lower().startswith('en') or site_i18n.get_lang() == 'en'
        for name, url in cls.CATEGORIES:
            entry = site_i18n.CATEGORY_I18N.get(url, {})
            if is_en and entry.get('en'):
                fallback = entry['en']
            else:
                fallback = name
            localized_name = site_i18n.loc(site_i18n.CATEGORY_I18N, url, fallback)
            cats.append({'name': localized_name, 'url': url, 'count': 0})
        return cats

    @classmethod
    def page_url(cls, base, page):
        if page <= 1:
            return base
        parsed = urlsplit(str(base or ''))
        pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != 'page']
        pairs.append(('page', str(int(page))))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), ''))

    @classmethod
    def search_url(cls, query):
        q = quote(str(query or '').strip())
        return f'https://hanime.tv/search?q={q}'

    @classmethod
    def search(cls, query):
        return cls.fetch_page(cls.search_url(query))

    @classmethod
    def fetch_page(cls, url):
        catalog = _load_catalog()
        if not catalog:
            return []

        parsed = urlsplit(str(url or ''))
        path = parsed.path.rstrip('/')
        qs = dict(parse_qsl(parsed.query))

        page = int(qs.get('page', 1) or 1)
        page_size = 24

        filtered = list(catalog)

        # Handle Search query
        if 'q' in qs or path == '/search':
            query = qs.get('q', '').strip().lower()
            if query:
                terms = query.split()
                filtered = [
                    v for v in filtered
                    if all(
                        t in (v.get('name') or '').lower() or
                        t in (v.get('search_titles') or '').lower() or
                        t in (v.get('brand') or '').lower() or
                        t in (v.get('slug') or '').lower() or
                        any(t in tag.lower() for tag in v.get('tags', []))
                        for t in terms
                    )
                ]
            # Default search sort: latest / most recent releases first
            filtered.sort(key=lambda x: max(x.get('released_at_unix', 0) or 0, x.get('created_at_unix', 0) or 0), reverse=True)

        # Handle Tags
        elif '/browse/tags/' in path:
            tag = unquote(path.split('/browse/tags/')[-1]).lower()
            filtered = [
                v for v in filtered
                if any(tag in t.lower() for t in v.get('tags', []))
            ]
            # Default tag browse sort: latest / most recent releases first
            filtered.sort(key=lambda x: max(x.get('released_at_unix', 0) or 0, x.get('created_at_unix', 0) or 0), reverse=True)

        # Handle Brands
        elif '/browse/brands/' in path:
            brand = unquote(path.split('/browse/brands/')[-1]).lower()
            filtered = [
                v for v in filtered
                if (v.get('brand') or '').lower() == brand
            ]
            filtered.sort(key=lambda x: max(x.get('released_at_unix', 0) or 0, x.get('created_at_unix', 0) or 0), reverse=True)

        # Handle Feeds & Sorting
        order = qs.get('order', '')
        if path == '/browse/trending' or order == 'trending':
            filtered.sort(key=lambda x: (x.get('likes', 0) * 10 + x.get('views', 0) / 100), reverse=True)
        elif path == '/browse/recent' or order == 'recent' or order == 'created_at_desc':
            filtered.sort(key=lambda x: x.get('created_at_unix', 0), reverse=True)
        elif path == '/browse/views' or order == 'views_desc':
            filtered.sort(key=lambda x: x.get('views', 0), reverse=True)
        elif path == '/browse/likes' or order == 'likes_desc':
            filtered.sort(key=lambda x: x.get('likes', 0), reverse=True)
        elif path == '/browse/newest' or order == 'released_at_desc':
            filtered.sort(key=lambda x: x.get('released_at_unix', 0), reverse=True)
        elif not ('q' in qs or path == '/search' or '/browse/tags/' in path or '/browse/brands/' in path):
            filtered.sort(key=lambda x: max(x.get('released_at_unix', 0) or 0, x.get('created_at_unix', 0) or 0), reverse=True)

        # Paginate
        start = (page - 1) * page_size
        end = start + page_size
        page_items = filtered[start:end]

        dur_cache = _load_duration_cache()

        videos = []
        for item in page_items:
            slug = item.get('slug')
            if not slug:
                continue
            video_url = f'https://hanime.tv/videos/hentai/{slug}'
            poster_url = item.get('poster_url') or ''
            cover_url = item.get('cover_url') or ''
            thumb_url = poster_url or cover_url
            name = item.get('name') or slug
            views = item.get('views')
            brand = item.get('brand') or ''
            tags = item.get('tags') or []
            dur = dur_cache.get(slug) or dur_cache.get(video_url) or ''

            videos.append({
                'title': name,
                'url': video_url,
                'thumbnail': thumb_url,
                'img': thumb_url,
                'poster_url': poster_url,
                'cover_url': cover_url,
                'duration': dur,
                'views': f"{views:,}" if isinstance(views, int) else str(views or ''),
                'author': brand,
                'tags': tags,
            })

        return videos
