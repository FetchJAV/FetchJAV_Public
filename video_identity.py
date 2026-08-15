#!/usr/bin/env python
# coding: utf-8
"""Cross-site video identity and version classification for SmallTool."""

from collections import defaultdict
import re
from urllib.parse import unquote, urlsplit


DEFAULT_VERSION_PREFERENCE = 'chinese-subtitle'
VALID_VERSION_PREFERENCES = frozenset({
    'chinese-subtitle',
    'uncensored',
    'standard',
    'english-subtitle',
    'reducing-mosaic',
})

SOURCE_PRIORITY = {
    'JableTV': 0,
    'MissAV': 1,
    'SupJav': 2,
}

# These tokens are deliberately closed and small because they are persisted by
# the Modern queue.  They mean that the source version itself already carries
# Chinese subtitles (normally burned into the picture), not merely that a
# Chinese-language site UI or an unrelated title string was observed.
TRUSTED_CHINESE_SUBTITLE_EVIDENCE = frozenset({
    'jable-category-chinese-subtitle',
    'missav-category-chinese-subtitle',
    'missav-url-chinese-subtitle',
    'supjav-category-chinese-subtitle',
})
MAX_SOURCE_SUBTITLE_EVIDENCE_TEXT = 512
_TRUSTED_MISSAV_HOSTS = frozenset({
    'missav.ai', 'www.missav.ai',
    'missav.ws', 'www.missav.ws',
    'missav.live', 'www.missav.live',
    'missav123.com', 'www.missav123.com',
})
_TRUSTED_JABLE_HOSTS = frozenset({
    'jable.tv', 'www.jable.tv',
    'fs1.app', 'www.fs1.app',
})
_TRUSTED_SUPJAV_HOSTS = frozenset({
    'supjav.com', 'www.supjav.com',
})

_TARGET_VERSION = {
    'category:chinese-subtitle': 'chinese-subtitle',
    'category:chinese-subtitles': 'chinese-subtitle',
    'feed:chinese-subtitle': 'chinese-subtitle',
    'category:english-subtitles': 'english-subtitle',
    'category:uncensored': 'uncensored',
    'feed:uncensored-leak': 'uncensored',
    'category:reducing-mosaic': 'reducing-mosaic',
    'category:censored': 'standard',
}

_VERSION_SUFFIXES = (
    '-uncensored-leak',
    '-chinese-subtitle',
    '-chinese-subtitles',
    '-english-subtitle',
    '-english-subtitles',
    '-reducing-mosaic',
    '-reduced-mosaic',
)


def site_from_url(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or '').casefold()
    except (TypeError, ValueError):
        return ''
    if host == 'jable.tv' or host.endswith('.jable.tv'):
        return 'JableTV'
    if host == 'fs1.app' or host.endswith('.fs1.app'):
        return 'JableTV'
    if (host.startswith('missav.') or host == 'missav123.com' or
            host.endswith('.missav123.com')):
        return 'MissAV'
    if host == 'supjav.com' or host.endswith('.supjav.com'):
        return 'SupJav'
    return ''


def normalize_source_subtitle_evidence(value) -> tuple[str, ...]:
    """Return only bounded, reviewed source-subtitle evidence tokens.

    Queue CSV files and SmallTool state are user-writable local data.  Unknown
    or oversized values therefore fail closed instead of becoming a reason to
    skip subtitle work.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        if len(value) > MAX_SOURCE_SUBTITLE_EVIDENCE_TEXT:
            return ()
        values = value.split('|')
        if len(values) > len(TRUSTED_CHINESE_SUBTITLE_EVIDENCE):
            return ()
    elif isinstance(value, (list, tuple, set, frozenset)):
        if len(value) > len(TRUSTED_CHINESE_SUBTITLE_EVIDENCE):
            return ()
        values = value
    else:
        return ()

    normalized = {
        str(item).strip()
        for item in values
        if isinstance(item, str)
        and len(item) <= MAX_SOURCE_SUBTITLE_EVIDENCE_TEXT
        and str(item).strip() in TRUSTED_CHINESE_SUBTITLE_EVIDENCE
    }
    return tuple(sorted(normalized))


def _trusted_source_site(url: str) -> str:
    try:
        parsed = urlsplit(str(url or ''))
        scheme = (parsed.scheme or '').casefold()
        host = (parsed.hostname or '').casefold()
    except (TypeError, ValueError):
        return ''
    if scheme != 'https' or parsed.username or parsed.password:
        return ''
    if host in _TRUSTED_JABLE_HOSTS:
        return 'JableTV'
    if host in _TRUSTED_MISSAV_HOSTS:
        return 'MissAV'
    if host in _TRUSTED_SUPJAV_HOSTS:
        return 'SupJav'
    return ''


def _trusted_listing_evidence(site: str, listing_url: str) -> str:
    try:
        parsed = urlsplit(str(listing_url or ''))
        scheme = (parsed.scheme or '').casefold()
        host = (parsed.hostname or '').casefold()
        path = unquote(parsed.path or '').casefold()
    except (TypeError, ValueError):
        return ''
    if scheme != 'https' or parsed.username or parsed.password:
        return ''

    if site == 'JableTV':
        if host not in _TRUSTED_JABLE_HOSTS:
            return ''
        if path.rstrip('/') == '/categories/chinese-subtitle':
            return 'jable-category-chinese-subtitle'
        return ''

    if site == 'MissAV':
        if host not in _TRUSTED_MISSAV_HOSTS:
            return ''
        if re.fullmatch(
                r'/dm\d+/(?:(?:cn|en|ja|ko|ms|th)/)?'
                r'chinese-subtitle/?',
                path):
            return 'missav-category-chinese-subtitle'
        return ''

    if site == 'SupJav':
        if host not in _TRUSTED_SUPJAV_HOSTS:
            return ''
        if re.fullmatch(
                r'/(?:(?:zh|ja)/)?category/chinese-subtitles/?',
                path):
            return 'supjav-category-chinese-subtitle'
    return ''


def trusted_chinese_subtitle_evidence(video: dict) -> tuple[str, ...]:
    """Collect fail-closed evidence that a source version carries Chinese text.

    This intentionally does not call :func:`video_versions`: that broader
    classifier accepts display-title heuristics for browsing and deduplication,
    which are too weak to suppress requested subtitle generation.
    """
    if not isinstance(video, dict):
        return ()

    stored_evidence = normalize_source_subtitle_evidence(
        video.get('_source_subtitle_evidence')
        or video.get('source_subtitle_evidence'))
    evidence = set()
    url = str(video.get('url') or '')
    derived_site = _trusted_source_site(url)
    claimed_site = str(video.get('_site') or video.get('site') or '').strip()
    if claimed_site not in SOURCE_PRIORITY:
        claimed_site = ''
    # Evidence is useful only when it is attached to a concrete, trusted
    # source video URL.  Metadata tokens alone never authorize skipping work.
    if not derived_site:
        return ()
    # Conflicting site metadata is not trusted for category evidence.
    site = derived_site
    site_consistent = not claimed_site or derived_site == claimed_site
    evidence_for_site = {
        'JableTV': {'jable-category-chinese-subtitle'},
        'MissAV': {
            'missav-category-chinese-subtitle',
            'missav-url-chinese-subtitle',
        },
        'SupJav': {'supjav-category-chinese-subtitle'},
    }.get(site, set())
    if site_consistent:
        evidence.update(
            token for token in stored_evidence
            if token in evidence_for_site)

    if derived_site == 'MissAV':
        try:
            source_host = (urlsplit(url).hostname or '').casefold()
        except (TypeError, ValueError):
            source_host = ''
        if source_host in _TRUSTED_MISSAV_HOSTS:
            slug = url_slug(url)
            if slug.endswith(('-chinese-subtitle', '-chinese-subtitles')):
                evidence.add('missav-url-chinese-subtitle')

    target_id = str(video.get('_target_id') or '')
    target_evidence = {
        ('JableTV', 'category:chinese-subtitle'):
            'jable-category-chinese-subtitle',
        ('MissAV', 'feed:chinese-subtitle'):
            'missav-category-chinese-subtitle',
        ('SupJav', 'category:chinese-subtitles'):
            'supjav-category-chinese-subtitle',
    }.get((site, target_id))
    if site_consistent and target_evidence:
        evidence.add(target_evidence)

    listing_evidence = _trusted_listing_evidence(
        site, video.get('_source_listing_url')
        or video.get('source_listing_url'))
    if site_consistent and listing_evidence:
        evidence.add(listing_evidence)

    return normalize_source_subtitle_evidence(evidence)


def url_slug(url: str) -> str:
    try:
        path = unquote(urlsplit(url).path).rstrip('/')
        return path.rsplit('/', 1)[-1].casefold()
    except (AttributeError, TypeError, ValueError):
        return ''


def _strip_version_suffixes(text: str) -> str:
    changed = True
    while changed:
        changed = False
        for suffix in _VERSION_SUFFIXES:
            if text.endswith(suffix):
                text = text[:-len(suffix)]
                changed = True
                break
    return text


def canonical_code(text: str) -> str:
    """Extract a stable JAV code from a URL slug or listing title."""
    value = unquote(str(text or '')).casefold()
    value = _strip_version_suffixes(value.strip().rstrip('/'))

    match = re.search(
        r'(?<![a-z0-9])fc2\s*[-_ ]?\s*ppv\s*[-_ ]*(\d{4,9})(?!\d)',
        value, re.I)
    if match:
        return f'fc2-ppv-{match.group(1)}'

    match = re.search(
        r'(?<![a-z0-9])fc2\s*[-_ ]+(\d{4,9})(?!\d)', value, re.I)
    if match:
        return f'fc2-{match.group(1)}'

    match = re.search(
        r'(?<![a-z0-9])([a-z0-9]{1,15})[-_ ]+(\d{6})[-_](\d{3,4})(?!\d)',
        value, re.I)
    if match and re.search(r'[a-z]', match.group(1), re.I):
        return (f'{match.group(1)}-{match.group(2)}-{match.group(3)}'
                .casefold())

    match = re.search(r'(?<!\d)(\d{6})[-_](\d{3,4})(?!\d)', value)
    if match:
        return f'{match.group(1)}-{match.group(2)}'

    match = re.search(
        r'(?<![a-z0-9])([a-z0-9]{1,10}(?:-[a-z0-9]{1,10}){0,2})'
        r'[-_]+(\d{2,9})(?!\d)',
        value, re.I)
    if match and re.search(r'[a-z]', match.group(1), re.I):
        prefix = match.group(1).replace('_', '-').casefold()
        return f'{prefix}-{match.group(2)}'
    return ''


def video_code(video: dict) -> str:
    stored = str(video.get('_code') or video.get('code') or '').strip()
    if stored:
        return stored.casefold()

    site = video.get('_site') or video.get('site') or site_from_url(
        video.get('url', ''))
    if site in {'JableTV', 'MissAV'}:
        slug = _strip_version_suffixes(url_slug(video.get('url', '')))
        code = canonical_code(slug)
        if code:
            return code

    code = canonical_code(video.get('title', ''))
    if code:
        return code
    return ''


def video_versions(video: dict) -> set[str]:
    stored = video.get('_versions') or video.get('versions')
    if isinstance(stored, str) and stored in VALID_VERSION_PREFERENCES:
        return {stored}
    if isinstance(stored, (list, tuple, set, frozenset)):
        valid = {str(item) for item in stored
                 if str(item) in VALID_VERSION_PREFERENCES}
        if valid:
            return valid

    versions = set()
    target_version = _TARGET_VERSION.get(str(video.get('_target_id') or ''))
    if target_version:
        versions.add(target_version)

    slug = url_slug(video.get('url', ''))
    if slug.endswith('-uncensored-leak'):
        versions.add('uncensored')
    if slug.endswith(('-chinese-subtitle', '-chinese-subtitles')):
        versions.add('chinese-subtitle')
    if slug.endswith(('-english-subtitle', '-english-subtitles')):
        versions.add('english-subtitle')
    if slug.endswith(('-reducing-mosaic', '-reduced-mosaic')):
        versions.add('reducing-mosaic')

    title = str(video.get('title') or '').casefold()
    if ('chinese subtitle' in title or '中文字幕' in title or
            re.search(r'\[\s*中字\s*\]', title)):
        versions.add('chinese-subtitle')
    if 'english subtitle' in title or '英文字幕' in title:
        versions.add('english-subtitle')
    if ('reducing mosaic' in title or 'reduced mosaic' in title or
            'mosaic reduced' in title or
            '破壞版' in title or '破坏版' in title):
        versions.add('reducing-mosaic')
    if ('uncensored' in title or 'uncensored leak' in title or
            '無碼' in title or '无码' in title or
            slug.endswith('-uncensored-leak')):
        versions.add('uncensored')

    if not versions:
        versions.add('standard')
    return versions


def normalize_version_preference(value) -> str:
    pref = str(value or '').strip().casefold()
    if pref == 'uncensored-leak':
        pref = 'uncensored'
    if pref in VALID_VERSION_PREFERENCES:
        return pref
    return DEFAULT_VERSION_PREFERENCE


def dedupe_video_candidates(videos: list[dict], preference: str):
    """Deduplicate by code across categories/sites using version then source priority."""
    preference = normalize_version_preference(preference)
    url_versions = defaultdict(set)
    url_source_subtitle_evidence = defaultdict(set)
    records = []

    for index, video in enumerate(videos):
        url = str(video.get('url') or '').strip().casefold()
        versions = video_versions(video)
        if url:
            url_versions[url].update(versions)
            url_source_subtitle_evidence[url].update(
                trusted_chinese_subtitle_evidence(video))
        records.append((index, video, url, video_code(video), versions))

    kept = []
    kept_records = []
    identity_indexes = {}
    decisions = []

    for index, video, url, code, versions in records:
        if url:
            versions = set(url_versions[url])
            if len(versions) > 1:
                versions.discard('standard')
            video['_versions'] = sorted(versions)
            source_evidence = normalize_source_subtitle_evidence(
                url_source_subtitle_evidence[url])
            if source_evidence:
                # The same concrete source URL can appear in multiple official
                # listings. Preserve only the dedicated trusted evidence; the
                # broader `_versions` classifier is never used as this gate.
                video['_source_subtitle_evidence'] = source_evidence
            else:
                video.pop('_source_subtitle_evidence', None)
        if code:
            video['_code'] = code
        identity = f'code:{code}' if code else (f'url:{url}' if url else '')
        if not identity:
            kept.append(video)
            kept_records.append((index, video, url, code, versions))
            continue

        existing_index = identity_indexes.get(identity)
        if existing_index is None:
            identity_indexes[identity] = len(kept)
            kept.append(video)
            kept_records.append((index, video, url, code, versions))
            continue

        existing_record = kept_records[existing_index]
        existing_video = existing_record[1]
        existing_versions = existing_record[4]

        candidate_score = (
            0 if preference in versions else 1,
            0 if video.get('_already_seen') else 1,
            SOURCE_PRIORITY.get(video.get('_site'), 99),
            index,
        )
        existing_score = (
            0 if preference in existing_versions else 1,
            0 if existing_video.get('_already_seen') else 1,
            SOURCE_PRIORITY.get(existing_video.get('_site'), 99),
            existing_record[0],
        )
        if candidate_score < existing_score:
            kept[existing_index] = video
            kept_records[existing_index] = (
                index, video, url, code, versions)
            decisions.append((existing_video, video, code or url))
        else:
            decisions.append((video, existing_video, code or url))

    return kept, decisions


# ── Subtitle-language outline badges on preview cards ────────────────
SUBTITLE_BADGE_LANG_FILES = ('ja', 'en', 'zh-TW', 'zh-CN', 'zh', 'ko')
SUBTITLE_BADGE_ORDER = ('EN', 'JA', 'CH', 'KO')
SUBTITLE_BADGE_COLORS = {
    'EN': '#42A5F5',
    'JA': '#EF5350',
    'CH': '#66BB6A',
    'ZH': '#66BB6A',
    'KO': '#AB47BC',
}


def badge_langs_from_label(label: str) -> tuple[str, ...]:
    """Map a subtitle language label/code to display badge codes ('EN', 'JA', 'CH', 'KO')."""
    s = str(label or '').strip()
    if not s:
        return ()
    low = s.casefold()

    # Handle language codes and translation pairs (e.g., 'ja-en', 'zh-TW', 'zh-CN')
    if re.fullmatch(r'[a-z]{2,3}-[a-z]{2,3}', low):
        parts = low.split('-')
        target = parts[-1]
        if target in ('en', 'eng'):
            return ('EN',)
        if target in ('zh', 'cn', 'tw', 'chs', 'cht', 'zho', 'chi', 'ch'):
            return ('CH',)
        if target in ('ja', 'jp', 'jpn'):
            return ('JA',)
        if target in ('ko', 'kor'):
            return ('KO',)

    tokens = [t for t in re.split(r'[^a-z0-9\u4e00-\u9fff\u3040-\u30ff]+', low) if t]
    found = set()
    for token in tokens:
        if ('中文' in token or '繁體' in token or '簡體' in token or '简体' in token or '繁体' in token
                or '漢語' in token or '汉语' in token or '普通话' in token or '中字' in token
                or '国语' in token or '國語' in token or '汉化' in token or '漢化' in token):
            found.add('CH')
            continue
        if ('日本語' in token or '日语' in token or '日文' in token or '日字' in token or '日語' in token):
            found.add('JA')
            continue
        if ('韩文' in token or '韓文' in token or '韩语' in token or '韓國' in token or '韩国' in token):
            found.add('KO')
            continue
        if token in ('en', 'eng', 'english', 'engsub') or 'english' in token or token.endswith('-en'):
            found.add('EN')
            continue
        if token in ('ja', 'jp', 'jpn', 'japanese', 'jasub') or 'japan' in token or token.endswith('-ja'):
            found.add('JA')
            continue
        if token in ('zh', 'zho', 'chi', 'chinese', 'chs', 'cht', 'cn', 'tw', 'ch') or 'chinese' in token or token.endswith(('-zh', '-cn', '-tw', '-ch')):
            found.add('CH')
            continue
        if token in ('ko', 'kor', 'korean') or 'korean' in token or token.endswith('-ko'):
            found.add('KO')
            continue
    return tuple(l for l in SUBTITLE_BADGE_ORDER if l in found)


def detect_subtitle_langs(video: dict, dest: str = '',
                          cache: object = None,
                          listing_url: str = '') -> tuple[str, ...]:
    """Return subtitle language codes ('EN', 'JA', 'CH', ...) for a video preview card.

    Detects translated / subtitled videos from:
    1. Video title heuristics (e.g. 中字, 中文字幕, 英字, 英文字幕, Eng Sub, 日文字幕, etc.)
    2. URL slug and path patterns (e.g. -chinese-subtitle, -english-subtitle, -c, etc.)
    3. Classified video versions and trusted subtitle evidence
    4. Listing category URL (e.g. browsing Chinese subtitle category)
    5. Video tags, categories, genres, or explicit subtitle metadata
    6. Local downloaded / generated subtitle files (.srt/.vtt/.ass in dest folder)
    7. Cached online / provider subtitle tracks in SubtitleCache
    """
    if not isinstance(video, dict):
        return ()

    found = set()

    # 1. Check title for explicit subtitle / translation language indicators
    title = str(video.get('title') or '')
    if title:
        title_l = title.casefold()
        if (re.search(r'(?:\[|\(|【|（|\b)(?:中字|中文字幕|中文|繁中|簡中|简中|繁體中字|簡體中字|漢化|汉化|chinese\s*sub(?:title)?s?|cn\s*sub(?:title)?s?)(?:\]|\)|】|）|\b)', title, re.I)
                or '中文字幕' in title or '中字' in title or '繁中' in title or '簡中' in title or '简中' in title
                or 'chinese subtitle' in title_l or 'chinese sub' in title_l or 'chinese subtitles' in title_l):
            found.add('CH')

        if (re.search(r'(?:\[|\(|【|（|\b)(?:英字|英文字幕|英语字幕|英語字幕|english\s*sub(?:title)?s?|eng\s*sub(?:title)?s?|engsub)(?:\]|\)|】|）|\b)', title, re.I)
                or '英文字幕' in title or '英字' in title or '英语字幕' in title or '英語字幕' in title
                or 'english subtitle' in title_l or 'english sub' in title_l or 'english subtitles' in title_l
                or 'eng sub' in title_l or 'engsub' in title_l):
            found.add('EN')

        if (re.search(r'(?:\[|\(|【|（|\b)(?:日字|日文字幕|日本語字幕|日語字幕|日语字幕|japanese\s*sub(?:title)?s?|jap\s*sub(?:title)?s?|jasub)(?:\]|\)|】|）|\b)', title, re.I)
                or '日文字幕' in title or '日字' in title or '日本語字幕' in title or '日語字幕' in title or '日语字幕' in title
                or 'japanese subtitle' in title_l or 'japanese sub' in title_l or 'japanese subtitles' in title_l or 'jap sub' in title_l):
            found.add('JA')

        if (re.search(r'(?:\[|\(|【|（|\b)(?:韓字|韓文字幕|韩文字幕|korean\s*sub(?:title)?s?|kor\s*sub(?:title)?s?)(?:\]|\)|】|）|\b)', title, re.I)
                or '韓文字幕' in title or '韩文字幕' in title or '韓字' in title or '韩字' in title
                or 'korean subtitle' in title_l or 'korean sub' in title_l):
            found.add('KO')

    # 2. Check URL slug / path for subtitle indications
    url = str(video.get('url') or '').strip()
    if url:
        url_l = url.casefold()
        slug = url_slug(url)
        path = url_l.split('?', 1)[0].rstrip('/')

        if (slug.endswith(('-chinese-subtitle', '-chinese-subtitles', '-c', '_c'))
                or '/chinese-subtitle' in url_l
                or '/chinese-subtitles' in url_l
                or path.endswith('-c')
                or '-c/' in url_l
                or '_c/' in url_l
                or re.search(r'[-_]c(?:/|$|\?)', url_l)):
            found.add('CH')

        if (slug.endswith(('-english-subtitle', '-english-subtitles', '-e', '-eng', '_e', '_eng'))
                or '/english-subtitle' in url_l
                or '/english-subtitles' in url_l
                or path.endswith(('-e', '-eng'))):
            found.add('EN')

        if (slug.endswith(('-japanese-subtitle', '-japanese-subtitles', '-ja', '_ja'))
                or '/japanese-subtitle' in url_l
                or '/japanese-subtitles' in url_l):
            found.add('JA')

    # 3. Check video versions & trusted subtitle evidence
    try:
        vers = video_versions(video)
        if 'chinese-subtitle' in vers:
            found.add('CH')
        if 'english-subtitle' in vers:
            found.add('EN')
        if 'japanese-subtitle' in vers:
            found.add('JA')
    except Exception:
        pass

    try:
        if trusted_chinese_subtitle_evidence(video):
            found.add('CH')
    except Exception:
        pass

    # 4. Check listing category URL
    if listing_url:
        lu_l = str(listing_url).casefold()
        if 'chinese-subtitle' in lu_l or 'chinese-subtitles' in lu_l:
            found.add('CH')
        elif 'english-subtitle' in lu_l or 'english-subtitles' in lu_l:
            found.add('EN')
        elif 'japanese-subtitle' in lu_l or 'japanese-subtitles' in lu_l:
            found.add('JA')

    # 5. Check video tags, categories, genres, or explicit subtitle metadata
    for field_name in ('tags', 'categories', 'genres', 'subtitles', 'subtitle_langs', 'sub_langs'):
        raw_vals = video.get(field_name)
        if isinstance(raw_vals, (list, tuple, set)):
            for val in raw_vals:
                found.update(badge_langs_from_label(str(val)))
        elif isinstance(raw_vals, str) and raw_vals:
            found.update(badge_langs_from_label(raw_vals))

    # 6. Check local downloaded / generated subtitle files
    try:
        code = video_code(video)
    except Exception:
        code = ''

    if code:
        import os
        try:
            dest_dir = os.path.abspath(dest or 'download')
            for lang in SUBTITLE_BADGE_LANG_FILES:
                if (os.path.isfile(os.path.join(dest_dir, f'{code}.{lang}.srt'))
                        or os.path.isfile(os.path.join(dest_dir, f'{code}.{lang}.vtt'))
                        or os.path.isfile(os.path.join(dest_dir, f'{code}.{lang}.ass'))):
                    found.update(badge_langs_from_label(lang))
            if os.path.isfile(os.path.join(dest_dir, f'{code}.srt')):
                if not found:
                    found.add('CH')
        except Exception:
            pass

        # 7. SubtitleCache lookup
        if cache is not None or len(found) < len(SUBTITLE_BADGE_ORDER):
            try:
                sub_cache = cache
                if sub_cache is None:
                    from subtitle_domain import SubtitleCache
                    sub_cache = SubtitleCache()
                for item in sub_cache.list_cached_subtitles(code):
                    meta = item.get('metadata') or {}
                    inner = meta.get('metadata') or {}
                    language = inner.get('language') or meta.get('language') or ''
                    label = language or str(item.get('lang_code') or '')
                    found.update(badge_langs_from_label(label))
            except Exception:
                pass

    return tuple(l for l in SUBTITLE_BADGE_ORDER if l in found)
