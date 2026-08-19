#!/usr/bin/env python
# coding: utf-8
"""TnaFlix.com direct-MP4 downloader and browse/search adapter."""

import re
import threading
from html import unescape
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import requests as _requests
from bs4 import BeautifulSoup

import config
from M3U8Sites.M3U8Crawler import request_headers, get_resolution_pref
from M3U8Sites.SiteSupJav import SiteSupJav

TNAFLIX_ROOT = 'https://www.tnaflix.com'
TNAFLIX_HOME = TNAFLIX_ROOT + '/'
_browser_local = threading.local()


def _make_session():
    session = _requests.Session()
    session.headers.update({
        'User-Agent': request_headers.get(
            'User-Agent',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': TNAFLIX_HOME,
    })
    return session


def _request(session, url, **kwargs):
    return session.get(
        url,
        timeout=kwargs.pop('timeout', 30),
        allow_redirects=True,
        **config.proxy_request_kwargs(),
        **kwargs,
    )


def _clean(value):
    return ' '.join(unescape(str(value or '')).replace('\xa0', ' ').split())


def _extract_source_height(source_tag, src_url):
    """Extract numeric height (e.g. 1080, 720, 480) from <source> tag or url."""
    size = source_tag.get('size') or source_tag.get('res') or source_tag.get('label') or ''
    if str(size).isdigit():
        return int(size)
    m = re.search(r'(?<!\d)(\d{3,4})\s*p?', str(size), re.I)
    if m:
        return int(m.group(1))
    m_url = re.search(r'[-_.](\d{3,4})p', src_url, re.I)
    if m_url:
        return int(m_url.group(1))
    return None


def _extract_mp4_sources(soup):
    """Extract progressive-MP4 sources from <source> tags inside <video>."""
    sources = []
    seen = set()

    def _add(raw_url, height=None):
        url = unescape(str(raw_url or '').strip()).replace('\\/', '/')
        if not url or url.startswith('/'):
            return
        try:
            parsed = urlsplit(url)
        except ValueError:
            return
        if parsed.scheme.casefold() not in ('http', 'https') or url in seen:
            return
        seen.add(url)
        sources.append({'url': url, 'height': height})

    for source in soup.select('video source[src]'):
        src = source.get('src', '')
        height = _extract_source_height(source, src)
        _add(src, height)

    video = soup.select_one('video#video-player, video[src]')
    if video and video.get('src'):
        v_src = video.get('src', '')
        height = _extract_source_height(video, v_src)
        _add(v_src, height)

    return sources


def _select_source(sources, preference):
    items = list(sources or [])
    if not items:
        return None
    known = [i for i in items if isinstance(i.get('height'), int)]
    pref = str(preference or '').strip().casefold()
    if pref == 'lowest':
        return min(known, key=lambda i: i['height']) if known else items[0]
    if pref in {'1080', '720', '480', '360', '240', '144'}:
        if not known:
            return items[0]
        target = int(pref)
        at_or_below = [i for i in known if i['height'] <= target]
        if at_or_below:
            return max(at_or_below, key=lambda i: i['height'])
        return min(known, key=lambda i: i['height'])
    # Default to highest resolution available
    return max(known, key=lambda i: i['height']) if known else items[0]


def _parse_iso8601_duration(dur_str):
    if not dur_str:
        return ''
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', str(dur_str), re.I)
    if m:
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        seconds = int(m.group(3) or 0)
        if hours > 0:
            return f'{hours}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'
    return str(dur_str).strip()


def _parse_cards(soup, listing_url=''):
    """Parse video cards from a category/search/featured page."""
    videos = []
    seen = set()
    for card in soup.select('div.col-xs-6.col-md-4.col-lg-4.col-xl-3.mb-3, div.col-xs-6'):
        a_tag = card.select_one('a[href]')
        if not a_tag:
            continue
        href = a_tag.get('href', '')
        if not href or 'video' not in href:
            continue
        video_url = urljoin(TNAFLIX_ROOT, href)
        if video_url in seen:
            continue
        seen.add(video_url)

        img = a_tag.find('img')
        thumbnail = ''
        if img:
            for attr in ('data-src', 'data-original', 'data-thumb', 'src'):
                val = (img.get(attr) or '').strip()
                if val and 'placeholder' not in val.lower() and not val.endswith('.svg'):
                    thumbnail = val
                    break
            if thumbnail and not thumbnail.startswith('http'):
                thumbnail = urljoin(TNAFLIX_ROOT, thumbnail)

        duration_el = card.select_one('span.video-duration, div.video-duration, span.thumb-icon.video-duration, div.thumb-icon.video-duration, span.thumb-icon, div.thumb-icon')
        duration = _clean(duration_el.get_text(strip=True) if duration_el else '')
        title = ''

        if img and img.get('alt'):
            title = _clean(img['alt'])

        if not title:
            slug = href.rstrip('/').rsplit('/', 1)[-1] if '/' in href else ''
            title = slug.replace('-', ' ').replace('_', ' ').strip()

        if not title:
            title = 'TnaFlix Video'

        item = {
            'url': video_url,
            'title': title,
            'thumbnail': thumbnail,
            'duration': duration,
            'site_name': 'TnaFlix',
        }
        if listing_url:
            item['_source_listing_url'] = listing_url
        videos.append(item)
    return videos


class SiteTnaFlix(SiteSupJav):
    """Download adapter for tnaflix.com video pages (direct MP4)."""
    website_pattern = r'https?://(?:www\.)?tnaflix\.com/.+video\d+.*'
    website_dirname_pattern = r'https?://(?:www\.)?tnaflix\.com/.+video(\d+)'
    direct_site_name = 'TnaFlix'
    direct_default_referer = TNAFLIX_HOME

    _direct_url = None
    _direct_referer = None

    @classmethod
    def validate_url(cls, url):
        if not url:
            return None
        url = str(url).strip()
        try:
            parsed = urlsplit(url)
        except Exception:
            return None
        host = (parsed.hostname or '').lower()
        if 'tnaflix.com' not in host:
            return None
        m = re.search(r'video(\d+)', parsed.path, re.I)
        if m:
            return m.group(1)
        return None

    def is_url_vaildate(self):
        return bool(self._m3u8url or getattr(self, '_direct_url', None))

    def get_url_infos(self):
        self._direct_url = None
        self._direct_referer = None
        self._m3u8url = None

        session = _make_session()
        try:
            response = _request(session, self._url)
            if response.status_code != 200:
                raise Exception(
                    f'TnaFlix page read failed (HTTP {response.status_code})')
            soup = BeautifulSoup(response.text, 'html.parser')
            sources = _extract_mp4_sources(soup)

            if not sources:
                raise Exception(
                    'This TnaFlix video has no available MP4 download sources')

            selected = _select_source(sources, self._get_resolution_pref())
            if not selected:
                raise Exception(
                    'This TnaFlix video has no available MP4 download sources')

            title = ''
            meta = soup.select_one('meta[property="og:title"][content]')
            if meta:
                title = _clean(meta.get('content'))
            if not title:
                h1 = soup.select_one('h1')
                title = _clean(h1.get_text(strip=True) if h1 else '')
            if not title:
                title_el = soup.select_one('.video-title, .videoDetails h1')
                title = _clean(title_el.get_text(strip=True) if title_el else '')
            if not title:
                title = 'TnaFlix Video'

            image_url = ''
            og_img = soup.select_one('meta[property="og:image"][content]')
            if og_img and og_img.get('content') and 'placeholder' not in og_img.get('content'):
                image_url = og_img.get('content', '')
            if not image_url:
                v_el = soup.select_one('video[poster]')
                if v_el and v_el.get('poster') and 'placeholder' not in v_el.get('poster'):
                    image_url = v_el.get('poster', '')
            if not image_url:
                tw_img = soup.select_one('meta[name="twitter:image"][content]')
                if tw_img and tw_img.get('content'):
                    image_url = tw_img.get('content', '')

            duration = ''
            import json as _json
            for s in soup.find_all('script', type='application/ld+json'):
                try:
                    ld = _json.loads(s.get_text())
                    if isinstance(ld, dict) and ld.get('duration'):
                        duration = _parse_iso8601_duration(ld['duration'])
                        break
                except Exception:
                    pass
            if not duration:
                dur_el = soup.select_one('.video-duration, .thumb-icon.video-duration, .thumb-icon')
                if dur_el:
                    duration = _clean(dur_el.get_text(strip=True))

            self._targetName = title
            self._imageUrl = image_url or None
            self._duration = duration or None
            self._direct_url = selected['url']
            self._direct_referer = self._url
            self._extra_headers = {'Referer': self._url}
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _get_resolution_pref(self):
        try:
            return get_resolution_pref()
        except Exception:
            return ''


class TnaFlixBrowser:
    """Browse/search adapter for tnaflix.com."""
    _url_root = TNAFLIX_ROOT

    # Complete list of categories from TnaFlix
    CATEGORIES = (
        ('Featured / Latest', f'{TNAFLIX_ROOT}/featured'),
        ('Amateur Porn', f'{TNAFLIX_ROOT}/amateur-porn'),
        ('Anal & Ass Fucking', f'{TNAFLIX_ROOT}/anal-porn'),
        ('Arabian Porn', f'{TNAFLIX_ROOT}/arabian-porn'),
        ('Asian Girls Fucking', f'{TNAFLIX_ROOT}/asian-porn'),
        ('Babes Fucking', f'{TNAFLIX_ROOT}/babe-videos'),
        ('BBW & Fat Sex', f'{TNAFLIX_ROOT}/bbw-porn'),
        ('BDSM Porn', f'{TNAFLIX_ROOT}/bdsm-porn'),
        ('Bizarre Sex', f'{TNAFLIX_ROOT}/bizarre-porn'),
        ('Blonde Girls Fucking', f'{TNAFLIX_ROOT}/blonde-porn'),
        ('Blowjobs & Oral Sex', f'{TNAFLIX_ROOT}/blowjob-videos'),
        ('Brunette Girls Fucking', f'{TNAFLIX_ROOT}/brunette-porn'),
        ('Bukkake Porn', f'{TNAFLIX_ROOT}/bukkake-porn'),
        ('Cartoon Sex', f'{TNAFLIX_ROOT}/cartoon-porn'),
        ('Celebrity', f'{TNAFLIX_ROOT}/celebrity-porn'),
        ('Classic Adult Videos', f'{TNAFLIX_ROOT}/classic-porn'),
        ('Creampie Sex', f'{TNAFLIX_ROOT}/creampie-videos'),
        ('Cumshots', f'{TNAFLIX_ROOT}/cum-videos'),
        ('Czech Porn', f'{TNAFLIX_ROOT}/czech-porn'),
        ('Ebony Girls Fucking', f'{TNAFLIX_ROOT}/ebony-porn'),
        ('Euro Porn', f'{TNAFLIX_ROOT}/euro-porn'),
        ('Facial Cum Shots', f'{TNAFLIX_ROOT}/facial-porn'),
        ('Fat Girls Fucking', f'{TNAFLIX_ROOT}/fat-porn'),
        ('Fetish Sex', f'{TNAFLIX_ROOT}/fetish-videos'),
        ('Fisting Sex', f'{TNAFLIX_ROOT}/fisting-videos'),
        ('Foot Fetish', f'{TNAFLIX_ROOT}/feet-porn'),
        ('French Porn', f'{TNAFLIX_ROOT}/french-porn'),
        ('Gay / Bi-Male Sex', f'{TNAFLIX_ROOT}/gay-porn'),
        ('German Porn', f'{TNAFLIX_ROOT}/german-porn'),
        ('Granny Sex', f'{TNAFLIX_ROOT}/granny-porn'),
        ('HD Porn', f'{TNAFLIX_ROOT}/hd-videos'),
        ('Hairy Girls Fucking', f'{TNAFLIX_ROOT}/hairy-porn'),
        ('Handjobs Porn', f'{TNAFLIX_ROOT}/handjobs-porn'),
        ('Hardcore Porn Videos', f'{TNAFLIX_ROOT}/hardcore-porn'),
        ('Hentai Sex Movies', f'{TNAFLIX_ROOT}/hentai-porn'),
        ('Homemade Porn', f'{TNAFLIX_ROOT}/homemade-porn'),
        ('Huge Cocks', f'{TNAFLIX_ROOT}/big-cock'),
        ('Huge Tits', f'{TNAFLIX_ROOT}/big-boobs'),
        ('Indian Girls Fucking', f'{TNAFLIX_ROOT}/indian-porn'),
        ('Interracial Porn', f'{TNAFLIX_ROOT}/interracial-porn'),
        ('Japanese porn', f'{TNAFLIX_ROOT}/japanese-porn'),
        ('Latina Girls Fucking', f'{TNAFLIX_ROOT}/latina-porn'),
        ('Lesbian Sex', f'{TNAFLIX_ROOT}/lesbian-porn'),
        ('MILF', f'{TNAFLIX_ROOT}/milf-porn'),
        ('Massage Porn', f'{TNAFLIX_ROOT}/massage-porn'),
        ('Masturbating', f'{TNAFLIX_ROOT}/masturbation-videos'),
        ('Mature Sex', f'{TNAFLIX_ROOT}/mature-porn'),
        ('POV Sex Videos', f'{TNAFLIX_ROOT}/pov-porn'),
        ('Petite Girls Fucking', f'{TNAFLIX_ROOT}/petite-porn'),
        ('Piss Porn', f'{TNAFLIX_ROOT}/piss-videos'),
        ('Pregnant', f'{TNAFLIX_ROOT}/pregnant-porn'),
        ('Public Sex Videos', f'{TNAFLIX_ROOT}/public-porn'),
        ('Reality Porn', f'{TNAFLIX_ROOT}/reality-porn'),
        ('Redhead Girls Fucking', f'{TNAFLIX_ROOT}/redhead-porn'),
        ('Russian Porn', f'{TNAFLIX_ROOT}/russian-porn'),
        ('Sex Toys', f'{TNAFLIX_ROOT}/toy-videos'),
        ('Shemale/Trans Sex', f'{TNAFLIX_ROOT}/shemale-porn'),
        ('Softcore Porn', f'{TNAFLIX_ROOT}/softcore-videos'),
        ('Solo Porn', f'{TNAFLIX_ROOT}/solo-porn'),
        ('Spanking Videos', f'{TNAFLIX_ROOT}/spanking-videos'),
        ('Squirting Videos', f'{TNAFLIX_ROOT}/squirting-videos'),
        ('Storyline Sex', f'{TNAFLIX_ROOT}/storyline-porn'),
        ('Teens', f'{TNAFLIX_ROOT}/teen-porn'),
        ('Thai Porn', f'{TNAFLIX_ROOT}/thai-porn'),
        ('VR Porn', f'{TNAFLIX_ROOT}/vr-porn'),
        ('Webcam Shows', f'{TNAFLIX_ROOT}/webcam-shows'),
    )

    # Organized sidebar tag & category groups for TnaFlix
    SIDEBAR_TAG_GROUPS = {
        'Featured & Trending': [
            ('Featured', f'{TNAFLIX_ROOT}/featured'),
            ('New Videos', f'{TNAFLIX_ROOT}/new'),
            ('Top Rated', f'{TNAFLIX_ROOT}/toprated'),
            ('HD Porn (1080p)', f'{TNAFLIX_ROOT}/hd-videos'),
            ('VR Porn', f'{TNAFLIX_ROOT}/vr-porn'),
            ('Webcam Shows', f'{TNAFLIX_ROOT}/webcam-shows'),
        ],
        'Popular Categories': [
            ('Amateur', f'{TNAFLIX_ROOT}/amateur-porn'),
            ('Anal', f'{TNAFLIX_ROOT}/anal-porn'),
            ('Asian', f'{TNAFLIX_ROOT}/asian-porn'),
            ('Babes', f'{TNAFLIX_ROOT}/babe-videos'),
            ('Big Cock', f'{TNAFLIX_ROOT}/big-cock'),
            ('Big Tits', f'{TNAFLIX_ROOT}/big-boobs'),
            ('Blowjob', f'{TNAFLIX_ROOT}/blowjob-videos'),
            ('Creampie', f'{TNAFLIX_ROOT}/creampie-videos'),
            ('Cumshots', f'{TNAFLIX_ROOT}/cum-videos'),
            ('Facial', f'{TNAFLIX_ROOT}/facial-porn'),
            ('Hardcore', f'{TNAFLIX_ROOT}/hardcore-porn'),
            ('Hentai', f'{TNAFLIX_ROOT}/hentai-porn'),
            ('Homemade', f'{TNAFLIX_ROOT}/homemade-porn'),
            ('Interracial', f'{TNAFLIX_ROOT}/interracial-porn'),
            ('Japanese', f'{TNAFLIX_ROOT}/japanese-porn'),
            ('Latina', f'{TNAFLIX_ROOT}/latina-porn'),
            ('Lesbian', f'{TNAFLIX_ROOT}/lesbian-porn'),
            ('Masturbation', f'{TNAFLIX_ROOT}/masturbation-videos'),
            ('Mature', f'{TNAFLIX_ROOT}/mature-porn'),
            ('MILF', f'{TNAFLIX_ROOT}/milf-porn'),
            ('POV', f'{TNAFLIX_ROOT}/pov-porn'),
            ('Public', f'{TNAFLIX_ROOT}/public-porn'),
            ('Sex Toys', f'{TNAFLIX_ROOT}/toy-videos'),
            ('Squirting', f'{TNAFLIX_ROOT}/squirting-videos'),
            ('Teen', f'{TNAFLIX_ROOT}/teen-porn'),
            ('Threesome', f'{TNAFLIX_ROOT}/search.php?what=threesome'),
        ],
        'Ethnicity & Region': [
            ('Arabian', f'{TNAFLIX_ROOT}/arabian-porn'),
            ('Asian', f'{TNAFLIX_ROOT}/asian-porn'),
            ('Czech', f'{TNAFLIX_ROOT}/czech-porn'),
            ('Ebony', f'{TNAFLIX_ROOT}/ebony-porn'),
            ('Euro', f'{TNAFLIX_ROOT}/euro-porn'),
            ('French', f'{TNAFLIX_ROOT}/french-porn'),
            ('German', f'{TNAFLIX_ROOT}/german-porn'),
            ('Indian', f'{TNAFLIX_ROOT}/indian-porn'),
            ('Japanese', f'{TNAFLIX_ROOT}/japanese-porn'),
            ('Latina', f'{TNAFLIX_ROOT}/latina-porn'),
            ('Russian', f'{TNAFLIX_ROOT}/russian-porn'),
            ('Thai', f'{TNAFLIX_ROOT}/thai-porn'),
        ],
        'Appearance & Types': [
            ('BBW & Fat', f'{TNAFLIX_ROOT}/bbw-porn'),
            ('Blonde', f'{TNAFLIX_ROOT}/blonde-porn'),
            ('Brunette', f'{TNAFLIX_ROOT}/brunette-porn'),
            ('Fat Girls', f'{TNAFLIX_ROOT}/fat-porn'),
            ('Granny', f'{TNAFLIX_ROOT}/granny-porn'),
            ('Hairy', f'{TNAFLIX_ROOT}/hairy-porn'),
            ('Petite', f'{TNAFLIX_ROOT}/petite-porn'),
            ('Pregnant', f'{TNAFLIX_ROOT}/pregnant-porn'),
            ('Redhead', f'{TNAFLIX_ROOT}/redhead-porn'),
            ('Shemale / Trans', f'{TNAFLIX_ROOT}/shemale-porn'),
        ],
        'Acts & Fetishes': [
            ('BDSM', f'{TNAFLIX_ROOT}/bdsm-porn'),
            ('Bizarre', f'{TNAFLIX_ROOT}/bizarre-porn'),
            ('Blowjob & Oral', f'{TNAFLIX_ROOT}/blowjob-videos'),
            ('Bondage', f'{TNAFLIX_ROOT}/search.php?what=bondage'),
            ('Bukkake', f'{TNAFLIX_ROOT}/bukkake-porn'),
            ('Celebrity', f'{TNAFLIX_ROOT}/celebrity-porn'),
            ('Classic Adult', f'{TNAFLIX_ROOT}/classic-porn'),
            ('Cuckold', f'{TNAFLIX_ROOT}/search.php?what=cuckold'),
            ('Fetish', f'{TNAFLIX_ROOT}/fetish-videos'),
            ('Fingering', f'{TNAFLIX_ROOT}/search.php?what=fingering'),
            ('Fisting', f'{TNAFLIX_ROOT}/fisting-videos'),
            ('Foot Fetish', f'{TNAFLIX_ROOT}/feet-porn'),
            ('Handjobs', f'{TNAFLIX_ROOT}/handjobs-porn'),
            ('Massage', f'{TNAFLIX_ROOT}/massage-porn'),
            ('Pissing', f'{TNAFLIX_ROOT}/piss-videos'),
            ('Reality Porn', f'{TNAFLIX_ROOT}/reality-porn'),
            ('Softcore', f'{TNAFLIX_ROOT}/softcore-videos'),
            ('Solo', f'{TNAFLIX_ROOT}/solo-porn'),
            ('Spanking', f'{TNAFLIX_ROOT}/spanking-videos'),
            ('Storyline', f'{TNAFLIX_ROOT}/storyline-porn'),
        ],
        'All Categories (A-Z)': CATEGORIES,
    }

    HOMEPAGE_SECTIONS = (
        ('Featured', f'{TNAFLIX_ROOT}/featured'),
        ('New', f'{TNAFLIX_ROOT}/new'),
        ('Top Rated', f'{TNAFLIX_ROOT}/toprated'),
        ('HD Videos', f'{TNAFLIX_ROOT}/hd-videos'),
    )

    @classmethod
    def _get_session(cls):
        session = getattr(_browser_local, 'session', None)
        if session is None:
            session = _make_session()
            _browser_local.session = session
        return session

    @classmethod
    def fetch_categories(cls, **kwargs):
        import site_i18n
        return [{
            'name': site_i18n.loc(site_i18n.CATEGORY_I18N, url, name),
            'url': url,
            'count': 0,
        } for name, url in cls.CATEGORIES]

    @classmethod
    def _listing_url_allowed(cls, url):
        try:
            parsed = urlsplit(str(url or ''))
        except ValueError:
            return False
        host = (parsed.hostname or '').lower()
        return (
            parsed.scheme.casefold() in ('http', 'https') and
            'tnaflix.com' in host and
            parsed.path.rstrip('/') not in ('', '/')
        )

    @classmethod
    def fetch_page(cls, url):
        if not cls._listing_url_allowed(url):
            return []
        try:
            response = _request(cls._get_session(), url)
        except Exception:
            return []
        if response.status_code != 200:
            return []
        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            return _parse_cards(soup, str(url))
        except Exception:
            return []

    @classmethod
    def page_url(cls, base, page):
        if page <= 1:
            return base
        parsed = urlsplit(str(base or ''))
        if parsed.query or 'search.php' in parsed.path:
            q_dict = dict(parse_qsl(parsed.query))
            q_dict['page'] = str(int(page))
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(q_dict), ''))
        path = parsed.path.rstrip('/')
        path_parts = path.rsplit('/', 1)
        if len(path_parts) == 2 and path_parts[1].isdigit():
            path = path_parts[0]
        return urlunsplit((
            parsed.scheme, parsed.netloc, f'{path}/{int(page)}', '', ''))

    @classmethod
    def search_url(cls, query):
        q = quote(str(query or '').strip())
        return f'{TNAFLIX_ROOT}/search.php?what={q}'

    @classmethod
    def search(cls, query):
        return cls.fetch_page(cls.search_url(query))

