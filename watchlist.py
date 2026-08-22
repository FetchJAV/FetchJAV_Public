# -*- coding: utf-8 -*-
"""Actress & Studio Watchlist / RSS Auto-Download Manager for FetchJAV.

Allows users to follow actresses, studios, or series tags, automatically polls
supported sites for new releases, and queues matching videos for auto-download.
Also provides RSS feed generation, jav.guru scraper for popular actresses & studios,
and typo/fuzzy recommendation support.
"""

import difflib
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

try:
    import config
except ImportError:
    import JableTV_MissAV_Downloader_GUI_2026_master.config as config

logger = logging.getLogger('FetchJAV.Watchlist')


# ── Built-in Popular Fallback Databases ─────────────────────────────

POPULAR_ACTRESSES_FALLBACK = [
    {"name": "Yua Mikami", "kanji": "三上悠亜", "count": "800+"},
    {"name": "Eimi Fukada", "kanji": "深田えいみ", "count": "950+"},
    {"name": "Hatano Yui", "kanji": "波多野結衣", "count": "2100+"},
    {"name": "Shinoda Yu", "kanji": "篠田ゆう", "count": "1040+"},
    {"name": "Saika Kawakita", "kanji": "河北彩花", "count": "250+"},
    {"name": "Ootsuki Hibiki", "kanji": "大槻ひびき", "count": "1000+"},
    {"name": "Minami Aizawa", "kanji": "相沢みなみ", "count": "450+"},
    {"name": "Matsumoto Ichika", "kanji": "松本いちか", "count": "620+"},
    {"name": "Remu Suzumori", "kanji": "涼森れむ", "count": "320+"},
    {"name": "Arina Hashimoto", "kanji": "橋本ありな", "count": "550+"},
    {"name": "Hamasaki Mao", "kanji": "浜崎真緒", "count": "890+"},
    {"name": "Morisawa Kana", "kanji": "森沢かな", "count": "910+"},
    {"name": "Karen Yuzuriha", "kanji": "楪カレン", "count": "280+"},
    {"name": "Miru", "kanji": "坂道みる", "count": "420+"},
    {"name": "Tsukasa Aoi", "kanji": "葵つかさ", "count": "510+"},
    {"name": "Yayoi Mizuki", "kanji": "弥生みづき", "count": "910+"},
    {"name": "Minazuki Hikaru", "kanji": "水奈月ひかる", "count": "860+"},
    {"name": "Misono Waka", "kanji": "美園和花", "count": "830+"},
    {"name": "Hasumi Kurea", "kanji": "蓮実クレア", "count": "800+"},
    {"name": "Kobayakawa Reiko", "kanji": "小早川怜子", "count": "760+"},
    {"name": "Otsu Arisu", "kanji": "大津ありす", "count": "750+"},
    {"name": "Tenma Yui", "kanji": "天馬ゆい", "count": "710+"},
    {"name": "Kitagawa Erika", "kanji": "北川エリカ", "count": "700+"},
    {"name": "Kurata Mao", "kanji": "倉多まお", "count": "670+"},
    {"name": "Aika", "kanji": "AIKA", "count": "650+"},
    {"name": "Niimura Akari", "kanji": "新村あかり", "count": "640+"},
    {"name": "Kinoshita Himari", "kanji": "木下ひまり", "count": "640+"},
    {"name": "Kashiwagi Konatsu", "kanji": "柏木こなつ", "count": "600+"},
    {"name": "Misaki Kanna", "kanji": "美咲かんな", "count": "590+"},
    {"name": "Satsuki Ena", "kanji": "五月恵奈", "count": "590+"},
    {"name": "Nozomi Arimura", "kanji": "有村のぞみ", "count": "590+"},
    {"name": "Nagisa Mitsuki", "kanji": "渚みつき", "count": "580+"},
    {"name": "Tsubaki Rika", "kanji": "椿りか", "count": "580+"},
]

POPULAR_STUDIOS_FALLBACK = [
    {"name": "S1 NO.1 STYLE", "code": "S1", "count": "Top Maker"},
    {"name": "MOODYZ", "code": "MDYD", "count": "Top Maker"},
    {"name": "SOD Create", "code": "SOD", "count": "Top Maker"},
    {"name": "Prestige", "code": "ABW", "count": "Top Maker"},
    {"name": "IDEA POCKET", "code": "IPX", "count": "Top Maker"},
    {"name": "Madonna", "code": "JUL", "count": "Top Maker"},
    {"name": "Attackers", "code": "ATID", "count": "Top Maker"},
    {"name": "FALENO", "code": "FSDSS", "count": "Top Maker"},
    {"name": "Premium", "code": "PRED", "count": "Top Maker"},
    {"name": "WANZ FACTORY", "code": "WANZ", "count": "Top Maker"},
    {"name": "E-body", "code": "EBOD", "count": "Top Maker"},
    {"name": "Honnaka", "code": "HND", "count": "Top Maker"},
    {"name": "Kawaii", "code": "CAWD", "count": "Top Maker"},
    {"name": "K.M.Produce", "code": "KMP", "count": "Top Maker"},
    {"name": "caribbeancom", "code": "CARIB", "count": "Uncensored"},
    {"name": "1Pondo", "code": "1PON", "count": "Uncensored"},
    {"name": "Heyzo", "code": "HEYZO", "count": "Uncensored"},
    {"name": "Tokyo Hot", "code": "TOKYOHOT", "count": "Uncensored"},
    {"name": "Glory Quest", "code": "GQE", "count": "Popular"},
    {"name": "Natural High", "code": "NHDTA", "count": "Popular"},
    {"name": "Fitch", "code": "FSET", "count": "Popular"},
    {"name": "Oppai", "code": "PPPD", "count": "Popular"},
    {"name": "Das !", "code": "DASD", "count": "Popular"},
    {"name": "Hunter", "code": "HTHD", "count": "Popular"},
]

POPULAR_TAGS_FALLBACK = [
    {"name": "Chinese Subtitles", "code": "chinese-subtitle"},
    {"name": "Uncensored Leaked", "code": "uncensored-leaked"},
    {"name": "4K Ultra HD", "code": "4k"},
    {"name": "Creampie", "code": "creampie"},
    {"name": "Milf", "code": "milf"},
    {"name": "Slender", "code": "slender"},
    {"name": "Big Tits", "code": "big-tits"},
    {"name": "Uniform", "code": "uniform"},
    {"name": "Cosplay", "code": "cosplay"},
    {"name": "Debut", "code": "debut"},
]


# ── JAV.guru Scraper & Cache ─────────────────────────────────────────

_javguru_cache_lock = threading.Lock()
_cached_popular_actresses: Optional[List[dict]] = None
_cached_popular_studios: Optional[List[dict]] = None
_last_fetch_time: float = 0


def fetch_popular_actresses_from_javguru(timeout: int = 8) -> List[dict]:
    """Fetch popular actress list from jav.guru with fallback database."""
    global _cached_popular_actresses, _last_fetch_time

    with _javguru_cache_lock:
        if _cached_popular_actresses and (time.time() - _last_fetch_time < 3600):
            return list(_cached_popular_actresses)

    actresses = []
    try:
        url = "https://jav.guru/jav-actress-list/"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/actress/' in href and a.text.strip():
                    raw_text = a.text.strip()
                    lines = [ln.strip() for ln in raw_text.split('\n') if ln.strip()]
                    name = lines[0] if lines else raw_text
                    count = lines[1] if len(lines) > 1 else ""
                    if name and len(name) > 1 and not any(x['name'].lower() == name.lower() for x in actresses):
                        actresses.append({
                            "name": name,
                            "count": count,
                            "type": "actress",
                            "url": href,
                        })
    except Exception as ex:
        logger.debug(f"Failed to fetch actresses from jav.guru: {ex}")

    if not actresses:
        actresses = [
            {"name": item["name"], "count": item.get("count", ""), "type": "actress", "url": ""}
            for item in POPULAR_ACTRESSES_FALLBACK
        ]

    with _javguru_cache_lock:
        _cached_popular_actresses = actresses
        _last_fetch_time = time.time()

    return actresses


def fetch_popular_studios_from_javguru(timeout: int = 8) -> List[dict]:
    """Fetch popular studio/maker list from jav.guru with fallback database."""
    global _cached_popular_studios, _last_fetch_time

    with _javguru_cache_lock:
        if _cached_popular_studios and (time.time() - _last_fetch_time < 3600):
            return list(_cached_popular_studios)

    studios = []
    try:
        url = "https://jav.guru/jav-makers-list/"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/maker/' in href and a.text.strip():
                    name = a.text.strip()
                    if name and len(name) > 1 and not any(x['name'].lower() == name.lower() for x in studios):
                        studios.append({
                            "name": name,
                            "type": "studio",
                            "url": href,
                        })
    except Exception as ex:
        logger.debug(f"Failed to fetch studios from jav.guru: {ex}")

    if not studios:
        studios = [
            {"name": item["name"], "type": "studio", "url": ""}
            for item in POPULAR_STUDIOS_FALLBACK
        ]

    with _javguru_cache_lock:
        _cached_popular_studios = studios

    return studios


# ── Typo & Fuzzy Recommendations ─────────────────────────────────────

def fuzzy_search_recommendations(query: str, limit: int = 5) -> List[dict]:
    """Return close actress, studio, or tag matches for a user search/typo."""
    q = (query or '').strip().lower()
    if not q or len(q) < 2:
        return []

    candidates: List[Tuple[str, str, str]] = []  # (Display Name, Type, Normalized)

    for item in POPULAR_ACTRESSES_FALLBACK:
        candidates.append((item['name'], 'actress', item['name'].lower()))
        if item.get('kanji'):
            candidates.append((item['name'], 'actress', item['kanji'].lower()))

    for item in POPULAR_STUDIOS_FALLBACK:
        candidates.append((item['name'], 'studio', item['name'].lower()))
        if item.get('code'):
            candidates.append((item['name'], 'studio', item['code'].lower()))

    for item in POPULAR_TAGS_FALLBACK:
        candidates.append((item['name'], 'tag', item['name'].lower()))
        if item.get('code'):
            candidates.append((item['name'], 'tag', item['code'].lower()))

    scored: List[Tuple[float, str, str]] = []
    seen = set()

    for disp_name, itype, norm in candidates:
        if disp_name in seen:
            continue

        if q in norm or norm in q:
            score = 0.95
        else:
            score = difflib.SequenceMatcher(None, q, norm).ratio()

        if score >= 0.5:
            seen.add(disp_name)
            scored.append((score, disp_name, itype))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [{"name": name, "type": itype, "score": score} for score, name, itype in scored[:limit]]


# ── Watchlist Item & Manager ──────────────────────────────────────────

class WatchlistItem:
    """Represents a tracked entity (Actress, Studio, Tag, or Keyword)."""

    def __init__(
        self,
        name: str,
        item_type: str = 'actress',  # 'actress', 'studio', 'tag', 'keyword'
        site: str = 'All',
        auto_download: bool = False,
        known_urls: Optional[List[str]] = None,
        created_at: Optional[int] = None,
        last_checked: Optional[int] = None,
    ):
        self.name = name.strip()
        self.item_type = item_type
        self.site = site
        self.auto_download = auto_download
        self.known_urls: Set[str] = set(known_urls or [])
        self.created_at = created_at or int(time.time())
        self.last_checked = last_checked or 0

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'type': self.item_type,
            'site': self.site,
            'auto_download': self.auto_download,
            'known_urls': list(self.known_urls),
            'created_at': self.created_at,
            'last_checked': self.last_checked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'WatchlistItem':
        return cls(
            name=data.get('name', ''),
            item_type=data.get('type', 'actress'),
            site=data.get('site', 'All'),
            auto_download=data.get('auto_download', False),
            known_urls=data.get('known_urls', []),
            created_at=data.get('created_at'),
            last_checked=data.get('last_checked'),
        )


class WatchlistManager:
    """Manages watchlist items, periodic polling, and auto-download queuing."""

    def __init__(self, download_manager=None, on_new_video_cb=None):
        self.download_manager = download_manager
        self.on_new_video_cb = on_new_video_cb
        self._lock = threading.Lock()
        self._poller_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._poll_interval_seconds = 3600

    def get_items(self) -> List[WatchlistItem]:
        with self._lock:
            raw = config.get_watchlist()
            return [WatchlistItem.from_dict(item) for item in raw if isinstance(item, dict)]

    def add_item(self, name: str, item_type: str = 'actress', site: str = 'All', auto_download: Optional[bool] = None) -> bool:
        if auto_download is None:
            auto_download = config.get_watchlist_auto_download()
        item = WatchlistItem(name=name, item_type=item_type, site=site, auto_download=auto_download)
        with self._lock:
            return config.add_watchlist_item(item.to_dict())

    def remove_item(self, name: str, item_type: Optional[str] = None) -> bool:
        with self._lock:
            return config.remove_watchlist_item(name, item_type=item_type)

    def is_in_watchlist(self, name: str, item_type: Optional[str] = None) -> bool:
        return config.is_in_watchlist(name, item_type=item_type)

    def toggle_item(self, name: str, item_type: str = 'actress', site: str = 'All') -> bool:
        with self._lock:
            return config.toggle_watchlist_item(name, item_type=item_type, site=site)

    def toggle_auto_download(self, name: str, item_type: Optional[str] = None) -> bool:
        with self._lock:
            items = config.get_watchlist()
            for it in items:
                if isinstance(it, dict) and it.get('name', '').lower() == name.lower():
                    if item_type is None or it.get('type') == item_type:
                        it['auto_download'] = not it.get('auto_download', False)
                        config.set_watchlist(items)
                        return True
            return False

    def check_updates(self, sites_dict: dict) -> List[dict]:
        """Poll sites for each watchlist item and return newly discovered videos."""
        items = self.get_items()
        if not items:
            return []

        downloaded_urls = {
            h.get('url') for h in config.get_download_history() if isinstance(h, dict) and h.get('url')
        }
        saved_urls = {
            s.get('url') for s in config.get_saved_videos() if isinstance(s, dict) and s.get('url')
        }

        discovered_new: List[dict] = []

        for item in items:
            search_query = item.name
            target_sites = [item.site] if item.site != 'All' and item.site in sites_dict else list(sites_dict.keys())

            for s_key in target_sites:
                site_info = sites_dict.get(s_key, {})
                browser_cls = site_info.get('browser')
                if not browser_cls:
                    continue

                try:
                    results = []
                    if hasattr(browser_cls, 'search'):
                        results = browser_cls.search(search_query) or []

                    for vid in results:
                        if not isinstance(vid, dict):
                            continue
                        url = (vid.get('url') or vid.get('page_url') or '').strip()
                        if not url:
                            continue

                        if url in item.known_urls or url in downloaded_urls or url in saved_urls:
                            continue

                        item.known_urls.add(url)
                        vid['watchlist_match'] = item.name
                        vid['watchlist_type'] = item.item_type
                        vid['site_name'] = s_key
                        discovered_new.append(vid)

                        if item.auto_download and config.get_watchlist_auto_download():
                            if self.download_manager and hasattr(self.download_manager, 'add'):
                                try:
                                    self.download_manager.add(url)
                                    logger.info(f"Auto-downloaded watchlist item: {vid.get('title')} ({url})")
                                except Exception as e:
                                    logger.warning(f"Failed to auto-download {url}: {e}")

                        if self.on_new_video_cb:
                            try:
                                self.on_new_video_cb(vid)
                            except Exception:
                                pass

                except Exception as ex:
                    logger.debug(f"Error checking watchlist item {item.name} on {s_key}: {ex}")

            item.last_checked = int(time.time())

        with self._lock:
            config.set_watchlist([it.to_dict() for it in items])

        return discovered_new

    def start_background_poller(self, sites_dict: dict, interval_seconds: int = 3600):
        """Start background polling thread."""
        self._poll_interval_seconds = interval_seconds
        self._stop_event.clear()

        def _poller():
            logger.info("Watchlist background poller started.")
            while not self._stop_event.is_set():
                try:
                    self.check_updates(sites_dict)
                except Exception as ex:
                    logger.error(f"Error in watchlist poller loop: {ex}")

                for _ in range(max(1, self._poll_interval_seconds // 5)):
                    if self._stop_event.is_set():
                        break
                    time.sleep(5)

        if self._poller_thread is None or not self._poller_thread.is_alive():
            self._poller_thread = threading.Thread(target=_poller, daemon=True, name='WatchlistPoller')
            self._poller_thread.start()

    def stop_background_poller(self):
        """Stop background poller."""
        self._stop_event.set()


def generate_rss_feed(items: List[dict], title: str = "FetchJAV Watchlist Feed") -> str:
    """Generate a standard RSS 2.0 XML feed from video items."""
    rss = ET.Element('rss', version='2.0')
    channel = ET.SubElement(rss, 'channel')

    c_title = ET.SubElement(channel, 'title')
    c_title.text = title
    c_link = ET.SubElement(channel, 'link')
    c_link.text = "https://github.com/DeepanshuK2002/FetchJAV"
    c_desc = ET.SubElement(channel, 'description')
    c_desc.text = "Automated RSS feed for FetchJAV watched actresses and studios"

    for v in items:
        if not isinstance(v, dict):
            continue
        v_url = v.get('url', '')
        v_title = v.get('title', v_url)
        v_thumb = v.get('thumbnail') or v.get('img') or ''

        item = ET.SubElement(channel, 'item')
        it_title = ET.SubElement(item, 'title')
        it_title.text = v_title
        it_link = ET.SubElement(item, 'link')
        it_link.text = v_url
        it_guid = ET.SubElement(item, 'guid')
        it_guid.text = v_url
        if v_thumb:
            ET.SubElement(item, 'enclosure', url=v_thumb, type='image/jpeg')

    return ET.tostring(rss, encoding='utf-8', xml_declaration=True).decode('utf-8')
