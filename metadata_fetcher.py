#!/usr/bin/env python
# coding: utf-8
"""Fetch accurate metadata for the preview info pane.

Scrapes the video's own detail page (JableTV / MissAV / SupJav) and
cross-references the other sites to fill missing fields (actress, director,
studio, tags) plus an actress photo. All fetches are defensive: failures
return empty dicts and never raise.
"""

import re
import threading
from contextlib import nullcontext
from urllib.parse import quote, urlsplit

import config
from bs4 import BeautifulSoup
from M3U8Sites.M3U8Crawler import fetch_with_mirrors


_CODE_RE = re.compile(r'([a-zA-Z]{2,6}[ _\-]?\d{3,6})')
_OG_TITLE_RE = re.compile(r'og:title"\s+content="([^"]+)"')
_OG_IMAGE_RE = re.compile(r'og:image"\s+content="([^"]+)"')


def site_key_from_url(url: str) -> str:
    host = (urlsplit(url or '').netloc or '').lower()
    if 'jable' in host or 'fs1.app' in host:
        return 'jable'
    if 'missav' in host:
        return 'missav'
    if 'supjav' in host:
        return 'supjav'
    return ''


def extract_video_code(text: str) -> str:
    m = _CODE_RE.search(text or '')
    if not m:
        return ''
    return m.group(1).upper().replace(' ', '').replace('_', '-')


def _norm_list(values) -> list:
    out = []
    for v in values or []:
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def _fmt_duration(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ''
    if seconds <= 0:
        return ''
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


def _clean_tags(tags, meta: dict) -> list:
    """Drop tag noise: actress/director/studio/series names and code."""
    exclude = set()
    for v in meta.get('actress') or []:
        exclude.add(str(v).strip().lower())
    for k in ('director', 'studio', 'series', 'code'):
        val = meta.get(k)
        if val:
            exclude.add(str(val).strip().lower())
    out = []
    for t in tags or []:
        s = str(t).strip()
        if not s or s.lower() in exclude or len(s) > 40:
            continue
        if s not in out:
            out.append(s)
    return out


def _is_logo_like(url: str) -> bool:
    low = (url or '').lower()
    return any(token in low for token in ('logo', 'favicon', '/icon.', 'placeholder'))


_cache = {}
_cache_lock = threading.Lock()


def _cached(url: str):
    with _cache_lock:
        return _cache.get(url)


def _store(url: str, data: dict):
    with _cache_lock:
        if len(_cache) > 200:
            for k in list(_cache)[:40]:
                _cache.pop(k, None)
        _cache[url] = data


def _merge_missing(result: dict, other: dict, append_lists: bool = True):
    for k, v in (other or {}).items():
        if not v:
            continue
        if not result.get(k):
            result[k] = v
        elif isinstance(result[k], list) and isinstance(v, list):
            if append_lists:
                for x in v:
                    if x not in result[k]:
                        result[k].append(x)


# ── JableTV ────────────────────────────────────────────────────────────────

def _fetch_jable(url: str) -> dict:
    try:
        from M3U8Sites.SiteJableTV import _make_scraper, _apply_jable_lang
    except Exception:
        return {}
    try:
        with _make_scraper() as scraper:
            try:
                _apply_jable_lang(scraper)
            except Exception:
                pass
            resp, _host, reason = fetch_with_mirrors(
                scraper, url, 'jable',
                lambda r: 'og:title' in r.text, timeout=25)
        if reason != 'ok' or resp is None:
            return {}
        soup = BeautifulSoup(resp.text, 'html.parser')
        meta = {}
        m = _OG_TITLE_RE.search(resp.text)
        if m:
            meta['title'] = m.group(1)
        m = _OG_IMAGE_RE.search(resp.text)
        if m:
            meta['thumbnail'] = m.group(1)
        models = []
        for a in soup.select('.models a[href*="/models/"], a.model[href*="/models/"]'):
            href = (a.get('href') or '').rstrip('/')
            if href.endswith('/models'):
                continue
            name = (a.get('title') or '').strip()
            if not name:
                span = a.find('span')
                if span is not None:
                    name = (span.get('title') or '').strip()
            if not name:
                name = a.get_text(' ', strip=True).strip()
            if name and len(name) > 1 and name not in models:
                models.append(name)
        meta['actress'] = models
        return meta
    except Exception:
        return {}


# ── MissAV ─────────────────────────────────────────────────────────────────

def _fetch_missav(url: str) -> dict:
    try:
        from M3U8Sites.SiteMissAV import MissAVBrowser
        scraper = MissAVBrowser._get_scraper()
    except Exception:
        return {}
    try:
        resp, _host, reason = fetch_with_mirrors(
            scraper, url, 'missav',
            lambda r: 'og:title' in r.text, timeout=25,
            headers_factory=lambda host: {'Referer': f'https://{host}/', 'Origin': f'https://{host}'})
        if reason != 'ok' or resp is None:
            return {}
        soup = BeautifulSoup(resp.text, 'html.parser')
        meta = {}
        m = _OG_TITLE_RE.search(resp.text)
        if m:
            meta['title'] = m.group(1)
        m = _OG_IMAGE_RE.search(resp.text)
        if m:
            meta['thumbnail'] = m.group(1)
        m = re.search(r'og:video:duration"\s+content="([^"]+)"', resp.text)
        if m:
            meta['duration'] = _fmt_duration(m.group(1))
        m = re.search(r'og:video:release_date"\s+content="([^"]+)"', resp.text)
        if m:
            meta['release_date'] = m.group(1)
        m = re.search(r'og:video:director"\s+content="([^"]+)"', resp.text)
        if m:
            meta['director'] = m.group(1)
        actors = _norm_list(re.findall(r'og:video:actor"\s+content="([^"]+)"', resp.text))
        actress_urls = []
        for a in soup.select('a[href*="/actresses/"]'):
            href = (a.get('href') or '').strip()
            path = urlsplit(href).path.rstrip('/')
            if not path or not re.match(r'^/actresses/[^/]+$', path):
                continue
            seg = path.rsplit('/', 1)[-1].lower()
            if seg in ('ranking', 'saved', 'actresses'):
                continue
            name = a.get_text(' ', strip=True)
            if name and name not in actors:
                actors.append(name)
            if href and href not in actress_urls:
                actress_urls.append(href)
        meta['actress'] = actors
        if actress_urls:
            meta['actress_urls'] = actress_urls
        # 番號 / 標題 / 女優 / 類型 / 系列 / 發行商 / 導演 / 發行日期 / 標籤 rows
        rows = {}
        for div in soup.select('div.text-secondary'):
            span = div.find('span')
            if not span:
                continue
            label = span.get_text(' ', strip=True).rstrip('：:').strip()
            if not label:
                continue
            val = div.get_text(' ', strip=True)
            val = re.sub(r'^\s*[^:：]*[：:]\s*', '', val).strip()
            if val:
                rows[label] = val
        if rows.get('番號'):
            meta['code'] = rows['番號'].strip().upper()
        if not meta.get('title') and rows.get('標題'):
            meta['title'] = rows['標題']
        if not meta.get('actress') and rows.get('女優'):
            meta['actress'] = [x.strip() for x in rows['女優'].split(',') if x.strip()]
        if not meta.get('director') and rows.get('導演'):
            meta['director'] = rows['導演']
        if rows.get('發行商'):
            meta['studio'] = rows['發行商']
        if rows.get('發行日期'):
            meta['release_date'] = meta.get('release_date') or rows['發行日期']
        if rows.get('系列'):
            meta['series'] = rows['系列']
        genre_tags = [x.strip() for x in rows.get('類型', '').split(',') if x.strip()]
        tag_tags = [x.strip() for x in rows.get('標籤', '').split(',') if x.strip()]
        meta['tags'] = _clean_tags(genre_tags + tag_tags, meta)
        return meta
    except Exception:
        return {}


def _fetch_actress_page_photo(url: str) -> str:
    if not url:
        return ''
    try:
        from M3U8Sites.SiteMissAV import MissAVBrowser
        scraper = MissAVBrowser._get_scraper()
        resp, _host, reason = fetch_with_mirrors(
            scraper, url, 'missav',
            lambda r: 'og:image' in r.text or 'og:title' in r.text, timeout=20,
            headers_factory=lambda host: {'Referer': f'https://{host}/', 'Origin': f'https://{host}'})
        if reason != 'ok' or resp is None:
            return ''
        m = _OG_IMAGE_RE.search(resp.text)
        photo = m.group(1) if m else ''
        return '' if _is_logo_like(photo) else photo
    except Exception:
        return ''


def _fetch_actress_photo_from_missav(name: str) -> str:
    if not name:
        return ''
    return _fetch_actress_page_photo('https://missav.ai/actresses/' + quote(name))


# ── SupJav ─────────────────────────────────────────────────────────────────

def _fetch_supjav(url: str) -> dict:
    try:
        from M3U8Sites.SiteSupJav import _make_scraper
    except Exception:
        return {}
    try:
        with _make_scraper() as scraper:
            resp, _host, reason = fetch_with_mirrors(
                scraper, url, 'supjav',
                lambda r: len(r.content) > 8000, timeout=25)
        if reason != 'ok' or resp is None:
            return {}
        soup = BeautifulSoup(resp.text, 'html.parser')
        meta = {}
        pm = soup.select_one('div.post-meta')
        if pm:
            h = pm.find('h2') or pm.find('h1')
            if h:
                meta['title'] = h.get_text(' ', strip=True)
            img = pm.find('img')
            if img:
                meta['thumbnail'] = img.get('src') or ''
        cast = [a.get_text(' ', strip=True) for a in soup.select('a[href*="/category/cast/"]')]
        makers = [a.get_text(' ', strip=True) for a in soup.select('a[href*="/category/maker/"]')]
        tags = [a.get_text(' ', strip=True) for a in soup.select('a[href*="/tag/"]')]
        meta['actress'] = _norm_list(cast)
        if makers:
            meta['studio'] = ', '.join(_norm_list(makers))
        if tags:
            meta['tags'] = _norm_list(tags)
        meta_box = soup.select_one('div.meta')
        if meta_box:
            m = re.search(r'(20\d{2}/\d{1,2}/\d{1,2})', meta_box.get_text(' ', strip=True))
            if m:
                meta['release_date'] = m.group(1)
        return meta
    except Exception:
        return {}


# ── JavGuru (English: actress / studio / director / tags) ────────────────

def _make_cloud_scraper():
    from M3U8Sites.SiteSupJav import _make_scraper
    return _make_scraper()


def _fetch_jav_guru_actress_photo(page_url: str, scraper=None) -> str:
    """Resolve an actress's portrait URL from her jav.guru actress page."""
    if not page_url:
        return ''
    key = 'jg-actress:' + page_url
    cached = _cached(key)
    if cached is not None:
        return cached
    try:
        if scraper is None:
            active = _make_cloud_scraper()
            ctx = active
        else:
            active = scraper
            ctx = nullcontext(scraper)
        with ctx:
            resp, _host, reason = fetch_with_mirrors(
                active, page_url, 'javguru',
                lambda r: 'cp-avatar' in r.text or len(r.content) > 8000, timeout=20)
        if reason != 'ok' or resp is None:
            return ''
        soup = BeautifulSoup(resp.text, 'html.parser')
        photo = ''
        av = soup.select_one('img.cp-avatar')
        if av is not None:
            photo = (av.get('src') or av.get('data-src') or av.get('data-lazy-src') or '').strip()
        if not photo:
            for img in soup.find_all('img'):
                src = (img.get('src') or img.get('data-src')
                       or img.get('data-lazy-src') or '').strip()
                if src and not _is_logo_like(src):
                    photo = src
                    break
        if photo and not _is_logo_like(photo):
            _store(key, photo)
            return photo
    except Exception:
        pass
    return ''


def _fetch_jav_guru(url: str) -> dict:
    """Scrape a jav.guru video page (English actress/studio/director/tags)."""
    try:
        with _make_cloud_scraper() as scraper:
            resp, _host, reason = fetch_with_mirrors(
                scraper, url, 'javguru',
                lambda r: 'infometa' in r.text or 'Movie Information' in r.text, timeout=25)
        if reason != 'ok' or resp is None:
            return {}
        soup = BeautifulSoup(resp.text, 'html.parser')
        article = soup.find('article')
        root = article or soup
        meta = {}
        h1 = root.find('h1')
        if h1:
            meta['title'] = h1.get_text(' ', strip=True)
        for img in root.find_all('img'):
            src = (img.get('src') or img.get('data-src')
                   or img.get('data-lazy-src') or '').strip()
            if src and not _is_logo_like(src):
                meta['thumbnail'] = src
                break

        actress_links = []
        for li in root.select('div.infometa li'):
            strong = li.find('strong')
            if strong is None:
                continue
            label = strong.get_text(' ', strip=True).rstrip('：:').strip()
            if not label:
                continue
            text = li.get_text(' ', strip=True)
            if label == 'Code':
                val = text.split(':', 1)[-1].strip()
                if val:
                    meta['code'] = val.upper()
            elif label == 'Release Date':
                val = text.split(':', 1)[-1].strip()
                if val:
                    meta['release_date'] = val
            elif label == 'Director':
                a = li.find('a')
                if a is not None:
                    meta['director'] = a.get_text(' ', strip=True)
            elif label == 'Studio':
                a = li.find('a')
                if a is not None:
                    meta['studio'] = a.get_text(' ', strip=True)
            elif label == 'Tags':
                tags = [a.get_text(' ', strip=True) for a in li.find_all('a')]
                meta['tags'] = _clean_tags(tags, meta)
            elif label == 'Actress':
                for a in li.find_all('a', href=True):
                    name = a.get_text(' ', strip=True).strip()
                    if name:
                        actress_links.append((name, str(a['href'])))
        meta['actress'] = _norm_list([n for n, _ in actress_links])
        photos = []
        with _make_cloud_scraper() as scraper:
            for _name, href in actress_links:
                photo = _fetch_jav_guru_actress_photo(href, scraper)
                if photo and photo not in photos:
                    photos.append(photo)
                if len(photos) >= 8:
                    break
        if photos:
            meta['actress_photos'] = photos
        return meta
    except Exception:
        return {}


# ── JAV Database (English database fallback) ──────────────────────────────

def _fetch_javdatabase(url: str) -> dict:
    """Scrape a www.javdatabase.com movie page (English metadata + actress shots)."""
    try:
        with _make_cloud_scraper() as scraper:
            resp, _host, reason = fetch_with_mirrors(
                scraper, url, 'javdatabase',
                lambda r: 'movietable' in r.text and 'entry-content' in r.text, timeout=25)
        if reason != 'ok' or resp is None:
            return {}
        soup = BeautifulSoup(resp.text, 'html.parser')
        meta = {}
        h1 = soup.find('h1')
        if h1:
            meta['title'] = h1.get_text(' ', strip=True)
        for img in soup.find_all('img'):
            alt = (img.get('alt') or '').strip().lower()
            src = (img.get('src') or img.get('data-src') or '').strip()
            if 'movie cover' in alt and src and not _is_logo_like(src):
                meta['thumbnail'] = src
                break

        def _row_value(label):
            for p in soup.select('.movietable p.mb-1'):
                b = p.find('b')
                if b is None:
                    continue
                if b.get_text(' ', strip=True).rstrip('：:').strip() == label:
                    return p
            return None

        p = _row_value('Release Date')
        if p is not None:
            val = p.get_text(' ', strip=True).split(':', 1)[-1].strip()
            if val:
                meta['release_date'] = val
        p = _row_value('Runtime')
        if p is not None:
            m = re.search(r'(\d+)\s*min', p.get_text(' ', strip=True))
            if m:
                meta['duration'] = _fmt_duration(int(m.group(1)) * 60)
        p = _row_value('Studio')
        if p is not None:
            a = p.find('a')
            if a is not None:
                meta['studio'] = a.get_text(' ', strip=True)
        p = _row_value('Director')
        if p is not None:
            a = p.find('a')
            if a is not None:
                meta['director'] = a.get_text(' ', strip=True)
        p = _row_value('Genre(s)')
        if p is not None:
            tags = [a.get_text(' ', strip=True) for a in p.find_all('a')]
            meta['tags'] = _clean_tags(tags, meta)
        p = _row_value('Idol(s)/Actress(es)')
        if p is not None:
            act = [a.get_text(' ', strip=True) for a in p.find_all('a')]
            meta['actress'] = _norm_list(act)
        p = _row_value('DVD ID')
        if p is not None and not meta.get('code'):
            val = p.get_text(' ', strip=True).split(':', 1)[-1].strip()
            if val:
                meta['code'] = val.upper()

        photos = []
        for img in soup.find_all('img'):
            src = (img.get('src') or img.get('data-src') or '').strip()
            alt = (img.get('alt') or '').strip()
            if '/idolimages/' in src and alt and not _is_logo_like(src):
                if src not in photos:
                    photos.append(src)
        if photos:
            meta['actress_photos'] = photos
        return meta
    except Exception:
        return {}


# ── Lightweight tag lookup for "More from this category" ───────────────────

def fetch_tags_for_code(code: str) -> list:
    """Fetch a video's English tags with a single page request per source —
    lightweight enough to rank recommendation candidates by tag overlap."""
    code = (code or '').strip()
    if not code:
        return []
    slug = code.lower().replace(' ', '-').replace('_', '-')
    key = 'jg-tags:' + slug
    cached = _cached(key)
    if cached is not None:
        return list(cached)

    tags = []
    try:
        with _make_cloud_scraper() as scraper:
            resp, _host, reason = fetch_with_mirrors(
                scraper, 'https://jav.guru/{}/'.format(slug), 'javguru',
                lambda r: 'infometa' in r.text or len(r.content) > 8000, timeout=20)
        if reason == 'ok' and resp is not None:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for li in soup.select('div.infometa li'):
                strong = li.find('strong')
                if strong is None:
                    continue
                if strong.get_text(' ', strip=True).rstrip('：:').strip() == 'Tags':
                    tags = [a.get_text(' ', strip=True) for a in li.find_all('a')]
                    break
    except Exception:
        tags = []
    tags = _norm_list(_clean_tags(tags, {}))

    if not tags:
        # Fall back to JAV Database genres (one extra request).
        try:
            with _make_cloud_scraper() as scraper:
                resp, _host, reason = fetch_with_mirrors(
                    scraper, 'https://www.javdatabase.com/movies/{}/'.format(slug),
                    'javdatabase',
                    lambda r: 'movietable' in r.text or len(r.content) > 8000, timeout=20)
            if reason == 'ok' and resp is not None:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for p in soup.select('.movietable p.mb-1'):
                    b = p.find('b')
                    if b is None:
                        continue
                    if b.get_text(' ', strip=True).rstrip('：:').strip() == 'Genre(s)':
                        tags = _clean_tags(
                            [a.get_text(' ', strip=True) for a in p.find_all('a')], {})
                        break
        except Exception:
            pass
        tags = _norm_list(tags)

    if tags:
        _store(key, list(tags))
    return list(tags)


# ── search helpers ─────────────────────────────────────────────────────────

def _find_missav_url(code: str) -> str:
    try:
        from M3U8Sites.SiteMissAV import MissAVBrowser
        vids = MissAVBrowser.search(code)
        if vids and isinstance(vids, list) and vids[0]:
            return str(vids[0].get('url') or '')
    except Exception:
        pass
    return ''


def _find_supjav_url(code: str) -> str:
    try:
        from M3U8Sites.SiteSupJav import SupJavBrowser
        vids = SupJavBrowser.search(code)
        if vids and isinstance(vids, list) and vids[0]:
            return str(vids[0].get('url') or '')
    except Exception:
        pass
    return ''


def _resolve_actress_photo(result: dict, own_key: str) -> str:
    urls = result.get('actress_urls') or []
    for u in urls:
        photo = _fetch_actress_page_photo(u)
        if photo:
            return photo
    actress = result.get('actress') or []
    for name in actress:
        photo = _fetch_actress_photo_from_missav(name)
        if photo:
            return photo
    return ''


# ── orchestration ──────────────────────────────────────────────────────────

def fetch_video_metadata(video: dict) -> dict:
    """Return a metadata dict for a preview video, cached per URL.

    Fields: title, thumbnail, actress (list), director, studio, tags (list),
    release_date, duration, code, actress_photo, actress_photos (list).

    English identity fields (actress / director / studio / tags / release date)
    come from JavGuru then JAV Database; the video's own page and MissAV /
    SupJav only fill in anything those two still miss (e.g. duration).
    """
    if not isinstance(video, dict):
        return {}
    url = str(video.get('url') or video.get('page_url') or '').strip()
    if not url:
        return {}

    cached = _cached(url)
    if cached is not None:
        return dict(cached)

    result = {}
    own_key = site_key_from_url(url)
    try:
        if own_key == 'jable':
            result = _fetch_jable(url) or {}
        elif own_key == 'missav':
            result = _fetch_missav(url) or {}
        elif own_key == 'supjav':
            result = _fetch_supjav(url) or {}
    except Exception:
        result = result or {}

    code = (result.get('code') or extract_video_code(
        '{} {} {}'.format(result.get('title') or '', url, video.get('title') or '')))
    if code:
        result['code'] = code
        # English-first identity fields from JavGuru / JAV Database
        code_slug = code.lower().replace(' ', '-').replace('_', '-')
        jg = _fetch_jav_guru('https://jav.guru/{}/'.format(code_slug)) or {}
        jd = _fetch_javdatabase('https://www.javdatabase.com/movies/{}/'.format(code_slug)) or {}
        english = {}
        _merge_missing(english, jg)
        _merge_missing(english, jd, append_lists=False)
        if english:
            for k in ('actress', 'director', 'studio', 'tags', 'release_date'):
                if english.get(k):
                    result[k] = english[k]
            for k in ('title', 'thumbnail', 'duration'):
                if not result.get(k) and english.get(k):
                    result[k] = english[k]
            for k in ('actress', 'tags'):
                result[k] = _norm_list(result.get(k))

            # Actress portraits: JavGuru photos first; fill any missing actresses
            # with JAV Database's per-idol portrait by name.
            photos = list(jg.get('actress_photos') or [])
            jd_photos = list(jd.get('actress_photos') or [])
            jd_map = {}
            jd_names = jd.get('actress') or []
            for i, nm in enumerate(jd_names):
                if i < len(jd_photos):
                    jd_map[str(nm).strip().lower()] = jd_photos[i]
            for i, nm in enumerate(result.get('actress') or []):
                if i < len(photos):
                    continue
                p = jd_map.get(str(nm).strip().lower())
                if p and p not in photos:
                    photos.append(p)
            if not photos and jd_photos:
                photos = list(jd_photos)
            if photos:
                result['actress_photos'] = photos

        need_more = not (result.get('actress') and result.get('director')
                         and result.get('studio') and result.get('tags'))
        if own_key != 'missav' and need_more:
            mav_url = _find_missav_url(code)
            if mav_url:
                _merge_missing(result, _fetch_missav(mav_url), append_lists=False)
        if own_key != 'supjav' and need_more:
            sup_url = _find_supjav_url(code)
            if sup_url:
                _merge_missing(result, _fetch_supjav(sup_url), append_lists=False)

    photos = result.get('actress_photos') or []
    if not photos:
        photo = _resolve_actress_photo(result, own_key)
        if photo:
            photos = [photo]
    result['actress_photos'] = photos
    result['actress_photo'] = photos[0] if photos else ''

    _store(url, result)
    return dict(result)
