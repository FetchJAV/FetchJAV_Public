#!/usr/bin/env python
# coding: utf-8
"""Modern GUI for JableTV, MissAV, and SupJav Downloader by ALOS — CustomTkinter Material Design."""

import os
import sys
import re
import io
import csv
import time
import shutil
import queue
import importlib.util
import webbrowser
import threading
import concurrent.futures
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox
from typing import Optional
from urllib.parse import urlsplit

import customtkinter as ctk

def _resolve_resource_path(rel_path: str) -> str:
    """Find a resource path across development repo and PyInstaller bundle locations."""
    candidates = []
    if getattr(sys, '_MEIPASS', None):
        candidates.append(os.path.join(sys._MEIPASS, rel_path))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path))
    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        candidates.append(os.path.join(app_dir, rel_path))
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]

def _setup_vlc_environment():
    """Ensure VLC DLL paths and environment variables are configured on Windows."""
    if sys.platform == 'win32':
        candidates = [
            os.environ.get('PYTHON_VLC_LIB_PATH', ''),
            os.environ.get('PYTHON_VLC_MODULE_PATH', ''),
            r'C:\Program Files\VideoLAN\VLC',
            r'C:\Program Files (x86)\VideoLAN\VLC',
            os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), 'VideoLAN', 'VLC'),
            os.path.join(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'), 'VideoLAN', 'VLC'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'VideoLAN', 'VLC'),
        ]
        for p in candidates:
            if p and os.path.isdir(p) and os.path.isfile(os.path.join(p, 'libvlc.dll')):
                if hasattr(os, 'add_dll_directory'):
                    try:
                        os.add_dll_directory(p)
                    except Exception:
                        pass
                if not os.environ.get('PYTHON_VLC_LIB_PATH'):
                    os.environ['PYTHON_VLC_LIB_PATH'] = os.path.join(p, 'libvlc.dll')
                if p not in os.environ.get('PATH', ''):
                    os.environ['PATH'] = p + os.pathsep + os.environ.get('PATH', '')
                break

# Apply custom SVG chevron arrow (d="m19.5 8.25-7.5 7.5-7.5-7.5") & icon-only hover color for CTkOptionMenu
try:
    import customtkinter.windows.widgets.core_rendering.draw_engine as _draw_engine_mod
    def _custom_draw_dropdown_arrow(self, x_position, y_position, size):
        x_position, y_position, size = round(x_position), round(y_position), round(size)
        requires_recoloring = False
        if not self._canvas.find_withtag('dropdown_arrow'):
            self._canvas.create_line(0, 0, 0, 0, tags='dropdown_arrow', width=max(2, round(size / 5)), joinstyle=tk.ROUND, capstyle=tk.ROUND)
            self._canvas.tag_raise('dropdown_arrow')
            requires_recoloring = True
        w = size * 0.42
        h = size * 0.22
        self._canvas.coords('dropdown_arrow',
                            x_position - w, y_position - h,
                            x_position, y_position + h,
                            x_position + w, y_position - h)
        return requires_recoloring

    _draw_engine_mod.DrawEngine.draw_dropdown_arrow = _custom_draw_dropdown_arrow

    DROPDOWN_ARROW_COLOR = ('#AAAAAA', '#555555')

    _orig_om_draw = ctk.CTkOptionMenu._draw
    def _custom_om_draw(self, no_color_updates=False):
        _orig_om_draw(self, no_color_updates)
        if hasattr(self, '_canvas') and self._canvas:
            try:
                if self._state == tk.DISABLED:
                    col = self._apply_appearance_mode(self._text_color_disabled)
                else:
                    arr_c = getattr(self, '_dropdown_arrow_color', DROPDOWN_ARROW_COLOR)
                    col = self._apply_appearance_mode(arr_c)
                self._canvas.itemconfig("dropdown_arrow", fill=col)
            except Exception:
                pass

    ctk.CTkOptionMenu._draw = _custom_om_draw

    def _custom_om_on_enter(self, event=0):
        self._close_on_next_click = self._dropdown_menu.is_open()
        if self._hover is True and self._state == tk.NORMAL and len(self._values) > 0:
            self._canvas.itemconfig("inner_parts_right",
                                    outline=self._apply_appearance_mode(self._button_hover_color),
                                    fill=self._apply_appearance_mode(self._button_hover_color))
            self._canvas.itemconfig("dropdown_arrow", fill=self._apply_appearance_mode(ACCENT))

    def _custom_om_on_leave(self, event=0):
        self._canvas.itemconfig("inner_parts_right",
                                outline=self._apply_appearance_mode(self._button_color),
                                fill=self._apply_appearance_mode(self._button_color))
        arr_c = getattr(self, '_dropdown_arrow_color', DROPDOWN_ARROW_COLOR)
        self._canvas.itemconfig("dropdown_arrow", fill=self._apply_appearance_mode(arr_c))

    ctk.CTkOptionMenu._on_enter = _custom_om_on_enter
    ctk.CTkOptionMenu._on_leave = _custom_om_on_leave
except Exception:
    pass

import requests
try:
    from curl_cffi import requests as cffi_requests
    _use_cffi = True
except ImportError:
    _use_cffi = False
from PIL import Image, ImageDraw, ImageTk

import config
import M3U8Sites
import site_i18n
import updater
from ssl_util import SharedSSLAdapter, get_shared_ssl_context
from M3U8Sites.SiteJableTV import JableTVBrowser
from M3U8Sites.SiteMissAV import MissAVBrowser
from M3U8Sites.SiteSupJav import SupJavBrowser
from M3U8Sites.SiteHanime1 import Hanime1Browser
from M3U8Sites.SiteHanimeTV import HanimeTVBrowser
from M3U8Sites.SiteTnaFlix import TnaFlixBrowser
from M3U8Sites.M3U8Crawler import MirrorsBlockedError
from config import headers
from locales import T, set_lang, get_lang, ui_font, LANGUAGES, state_label
from subtitle_engine import (
    SubtitleCancelled,
    generate_subtitles,
    normalize_recognition_quality,
    normalize_subtitle_mode,
    prefetch_subtitle_models,
)
from translation_settings_ui import (
    ModalOverlay,
    open_translation_settings_dialog,
    translation_failure_message,
    translation_provider_summary,
)
from video_identity import (
    SUBTITLE_BADGE_COLORS,
    SUBTITLE_BADGE_LANG_FILES,
    SUBTITLE_BADGE_ORDER,
    badge_langs_from_label,
    detect_dub_langs,
    detect_subtitle_langs,
    detect_video_card_badges,
    normalize_source_subtitle_evidence,
    trusted_chinese_subtitle_evidence,
    video_code,
    video_versions,
    extract_series_info,
    is_same_series,
    normalize_series_key,
)
from subtitle import SubtitleManager, SubtitleTrack, SubtitleSourceType
from subtitle.cache import SubtitleCache
from video_preview import PreviewProxyServer, PreviewSource, resolve_preview_source
from metadata_fetcher import fetch_video_metadata
from ui_theme import (
    ACCENT, ACCENT_HOVER, ACCENT_DIM,
    SUCCESS, SUCCESS_DIM, WARNING, WARNING_DIM, ERROR_C, ERROR_DIM,
    BG_DARK, BG_CARD, BG_CARD_HOVER, BG_INPUT, BG_HEADER, BG_SECTION,
    BG_SIDEBAR, BG_BADGE, TEXT_PRI, TEXT_SEC, TEXT_DIM, TEXT_LINK,
    BORDER, BORDER_HOVER, BORDER_CARD, WHITE, CARD_RADIUS, CONTROL_RADIUS,
    browse_columns_for_width,
)
import analytics

APP_VERSION = '0.1.6'

# issue #24: startup breadcrumbs — no-op if crashlog unavailable
try:
    from crashlog import breadcrumb as _crumb
except Exception:
    def _crumb(msg):
        pass

DEFAULT_CONCURRENT = 2
MAX_CONCURRENT = 32
SETTINGS_INLINE_HELP_WRAP = 620
MAX_VISIBLE_ROWS = 200
ROW_BUILD_BUDGET = 40
MAX_PERSIST_ROWS = 1000
HARD_LOAD_LIMIT = 5000
CSV_PATH = config.queue_csv_path()
ERR_BLOCKED = '__cf_blocked__'
INFLIGHT_STATES = frozenset({
    '準備中', '下載中', '等待中', '字幕準備中', '字幕辨識中', '字幕翻譯中',
})


def _hex_to_rgb(h):
    h = (h or '').lstrip('#')
    if len(h) != 6:
        return (0, 0, 0)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return '#%02X%02X%02X' % rgb


def _brighten(hex_color, factor=1.2):
    r, g, b = _hex_to_rgb(hex_color)
    r = min(255, int(r * factor))
    g = min(255, int(g * factor))
    b = min(255, int(b * factor))
    return _rgb_to_hex((r, g, b))


def _dim_color(hex_color, bg_hex, alpha=0.12):
    fr, fg, fb = _hex_to_rgb(hex_color)
    br, bg, bb = _hex_to_rgb(bg_hex)
    r = int(fr * (1 - alpha) + br * alpha)
    g = int(fg * (1 - alpha) + bg * alpha)
    b = int(fb * (1 - alpha) + bb * alpha)
    return _rgb_to_hex((r, g, b))


SITES = {
    'JableTV': {'browser': JableTVBrowser},
    'MissAV': {'browser': MissAVBrowser},
    'SupJav': {'browser': SupJavBrowser},
    'Hanime1': {'browser': Hanime1Browser},
    'HanimeTV': {'browser': HanimeTVBrowser},
    'TnaFlix': {'browser': TnaFlixBrowser},
}

_ALL_SITE_KEYS = tuple(SITES.keys())


# English "popular tags" group shown at the top of the JableTV sidebar.
# Only slugs that actually exist on jable.tv are listed (others return 404).
JABLE_EN_TAG_GROUPS = [
    ('Big Tits', 'big-tits'),
    ('Blowjob', 'blowjob'),
    ('Creampie', 'creampie'),
    ('Married Woman', 'wife'),
    ('Shaved', 'hairless-pussy'),
    ('Titty Fuck', 'tit-wank'),
]

# MissAV homepage header mega-menu (English locale), mirrored into the sidebar
# above the Categories group. Each entry is (header_label, [(name, url)]).
MISS_AV_HEADER_NAV = [
    ('English subtitle', [
        ('English subtitle', 'https://missav.ai/dm23/en/english-subtitle'),
    ]),
    ('Watch JAV', [
        ('Recent update', 'https://missav.ai/dm539/en/new'),
        ('New Releases', 'https://missav.ai/dm635/en/release'),
        ('Uncensored leak', 'https://missav.ai/dm817/en/uncensored-leak'),
        ('Actress list', 'https://missav.ai/en/actresses'),
        ('Actress ranking', 'https://missav.ai/en/actresses/ranking'),
        ('Genre', 'https://missav.ai/en/genres'),
        ('Maker', 'https://missav.ai/en/makers'),
        ('VR', 'https://missav.ai/en/genres/VR'),
        ('Most viewed today', 'https://missav.ai/dm301/en/today-hot'),
        ('Most viewed by week', 'https://missav.ai/dm170/en/weekly-hot'),
        ('Most viewed by month', 'https://missav.ai/dm273/en/monthly-hot'),
    ]),
    ('Amateur', [
        ('SIRO', 'https://missav.ai/dm36/en/siro'),
        ('LUXU', 'https://missav.ai/dm34/en/luxu'),
        ('GANA', 'https://missav.ai/dm34/en/gana'),
        ('PRESTIGE PREMIUM', 'https://missav.ai/dm1004/en/maan'),
        ('S-CUTE', 'https://missav.ai/dm38/en/scute'),
        ('ARA', 'https://missav.ai/dm34/en/ara'),
    ]),
    ('Uncensored', [
        ('Uncensored leak', 'https://missav.ai/dm817/en/uncensored-leak'),
        ('FC2', 'https://missav.ai/dm597/en/fc2'),
        ('HEYZO', 'https://missav.ai/dm2208642/en/heyzo'),
        ('Tokyo Hot', 'https://missav.ai/dm42/en/tokyohot'),
        ('1pondo', 'https://missav.ai/dm5199603/en/1pondo'),
        ('Caribbeancom', 'https://missav.ai/dm7704788/en/caribbeancom'),
        ('Caribbeancompr', 'https://missav.ai/dm91887/en/caribbeancompr'),
        ('10musume', 'https://missav.ai/dm7208981/en/10musume'),
        ('pacopacomama', 'https://missav.ai/dm3600557/en/pacopacomama'),
        ('Gachinco', 'https://missav.ai/dm150/en/gachinco'),
        ('XXX-AV', 'https://missav.ai/dm42/en/xxxav'),
        ('Married Slash', 'https://missav.ai/dm37/en/marriedslash'),
        ('Naughty 4610', 'https://missav.ai/dm33/en/naughty4610'),
        ('Naughty 0930', 'https://missav.ai/dm37/en/naughty0930'),
    ]),
    ('Asia AV', [
        ('Madou', 'https://missav.ai/dm63/en/madou'),
        ('TWAV', 'https://missav.ai/dm31/en/twav'),
        ('Furuke', 'https://missav.ai/dm15/en/furuke'),
        ('Korean Live', 'https://missav.ai/en/klive'),
        ('Chinese Live', 'https://missav.ai/en/clive'),
    ]),
]


_STATE_PRIORITY = {
    '下載中': 0,
    '字幕準備中': 1,
    '字幕辨識中': 2,
    '字幕翻譯中': 3,
    '準備中': 4,
    '等待中': 5,
    '未完成': 6,
    '封鎖/解析失敗': 7,
    '網址錯誤': 8,
    '未偵測到日語語音': 9,
    '已下載': 9,
    '已取消': 10,
}

_SUBTITLE_STATE_BY_STAGE = {
    'queued': '字幕準備中',
    'runtime': '字幕準備中',
    'model': '字幕準備中',
    'translation_model': '字幕模型準備中',
    'audio': '字幕準備中',
    'transcribe_ja': '字幕辨識中',
    'translate_en': '字幕翻譯中',
    'translate_zh': '字幕翻譯中',
}


# ── Subtitle and Dub outline badges on browse cards ──────────────────
_SUBTITLE_BADGE_LANG_FILES = SUBTITLE_BADGE_LANG_FILES
_SUBTITLE_BADGE_ORDER = SUBTITLE_BADGE_ORDER
_SUBTITLE_BADGE_COLORS = SUBTITLE_BADGE_COLORS
_badge_langs_from_label = badge_langs_from_label
_available_subtitle_langs = detect_subtitle_langs
_detect_video_card_badges = detect_video_card_badges


def _visible_window(items, cap):
    ordered = sorted(
        enumerate(items),
        key=lambda pair: (_STATE_PRIORITY.get(pair[1].state, 8), -pair[0]))
    return [item for _, item in ordered[:cap]]


def _select_persist(items, cap):
    terminal = {'已下載', '未偵測到日語語音', '已取消', '網址錯誤'}
    resumable = [i for i in items if i.state not in terminal]
    terminal_items = [i for i in items if i.state in terminal]
    budget = max(0, cap - len(resumable))
    kept_terminal = terminal_items[-budget:] if budget > 0 else []
    keep_ids = {id(i) for i in resumable} | {id(i) for i in kept_terminal}
    return [i for i in items if id(i) in keep_ids]


# ── Download Manager ────────────────────────────────────────────────
class DownloadItem:
    __slots__ = (
        'url', 'name', 'state', 'progress', 'speed', 'error', 'dest',
        'source_subtitle_evidence', 'resume',
    )

    def __init__(
            self, url: str, name: str = '', state: str = '', dest: str = '',
            source_subtitle_evidence=(), resume: bool = False):
        self.url = url
        self.name = name or url.rstrip('/').split('/')[-1]
        self.state = state
        self.progress = 0
        self.speed = ''
        self.error = ''
        self.dest = dest or ''
        self.resume = bool(resume)
        self.source_subtitle_evidence = trusted_chinese_subtitle_evidence({
            'url': url,
            '_source_subtitle_evidence': source_subtitle_evidence,
        })


class _DownloadTask:
    """One URL moving through the download and optional subtitle queues."""

    __slots__ = (
        'url', 'dest', 'epoch', 'job', 'subtitle_mode',
        'source_subtitle_evidence', 'cancelled',
    )

    def __init__(
            self, url: str, dest: str, epoch: int,
            source_subtitle_evidence=()):
        self.url = url
        self.dest = dest
        self.epoch = epoch
        self.job = None
        self.subtitle_mode = 'none'
        self.source_subtitle_evidence = (
            normalize_source_subtitle_evidence(
                source_subtitle_evidence))
        self.cancelled = threading.Event()


class DownloadManager:
    """Thread-safe manager with separate download and subtitle queues."""

    def __init__(self, on_update=None, max_concurrent: int = DEFAULT_CONCURRENT,
                 subtitle_mode_getter=None):
        self._on_update = on_update
        self._subtitle_mode_getter = subtitle_mode_getter or config.get_subtitle_pref
        self._pending: list[_DownloadTask] = []
        self._active: dict[str, _DownloadTask] = {}
        self._subtitle_pending: list[_DownloadTask] = []
        self._subtitle_active: dict[str, _DownloadTask] = {}
        self._items: dict[str, DownloadItem] = {}
        # RLock: enqueue() and cancel_all() call _set_state() while holding
        # the lock — a plain Lock would deadlock the caller (often the main
        # GUI thread, freezing the app).
        self._lock = threading.RLock()
        self._max_concurrent = max(
            1, min(int(max_concurrent), MAX_CONCURRENT))
        self._prep_sem = threading.Semaphore(1)
        self._cancel_epoch = 0

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @max_concurrent.setter
    def max_concurrent(self, value: int):
        self._max_concurrent = max(1, min(value, MAX_CONCURRENT))
        for _ in range(self._max_concurrent):
            self._try_next()

    def add_item(
            self, url: str, name: str = '', state: str = '', dest: str = '',
            source_subtitle_evidence=(), resume: bool = False):
        with self._lock:
            if url not in self._items:
                self._items[url] = DownloadItem(
                    url, name, state, dest, source_subtitle_evidence,
                    resume=resume)
            else:
                item = self._items.pop(url)
                if name:
                    item.name = name
                if state:
                    item.state = state
                if dest:
                    item.dest = dest
                item.resume = bool(resume)
                evidence = set(item.source_subtitle_evidence)
                evidence.update(trusted_chinese_subtitle_evidence({
                    'url': url,
                    '_source_subtitle_evidence':
                        source_subtitle_evidence,
                }))
                item.source_subtitle_evidence = (
                    normalize_source_subtitle_evidence(evidence))
                self._items[url] = item
            return self._items[url]

    def get_items(self) -> list[DownloadItem]:
        with self._lock:
            return list(self._items.values())

    def remove_item(self, url: str):
        with self._lock:
            self._items.pop(url, None)
            removed = [task for task in self._pending if task.url == url]
            self._pending = [task for task in self._pending if task.url != url]
            removed_subtitles = [
                task for task in self._subtitle_pending if task.url == url]
            self._subtitle_pending = [
                task for task in self._subtitle_pending if task.url != url]
            active = self._active.get(url)
            active_subtitle = self._subtitle_active.get(url)
            contexts = removed + removed_subtitles
            if active is not None:
                contexts.append(active)
            if active_subtitle is not None:
                contexts.append(active_subtitle)
            for task in contexts:
                task.cancelled.set()
        self._cancel_contexts(contexts)
        if removed_subtitles:
            self._try_next_subtitle()

    def enqueue(self, url: str, dest: str):
        start_task = None
        with self._lock:
            if self._url_inflight_locked(url):
                return
            item = self._items.get(url)
            if item:
                item.dest = dest or item.dest
                self._items[url] = self._items.pop(url)
            else:
                self._items[url] = DownloadItem(url, dest=dest)
                item = self._items[url]
            task = _DownloadTask(
                url, dest, self._cancel_epoch,
                item.source_subtitle_evidence)
            if len(self._active) < self._max_concurrent:
                self._active[url] = task
                start_task = task
            else:
                self._pending.append(task)
                self._set_state(url, '等待中')
        if start_task is not None:
            self._start_download_thread(start_task)

    def cancel_all(self, cleanup: bool = True):
        with self._lock:
            self._cancel_epoch += 1
            pending = list(self._pending)
            pending_subtitles = list(self._subtitle_pending)
            self._pending.clear()
            self._subtitle_pending.clear()
            active = list(self._active.values())
            active_subtitles = list(self._subtitle_active.values())
            contexts = pending + pending_subtitles + active + active_subtitles
            for task in contexts:
                task.cancelled.set()
                self._set_state(task.url, '已取消')
        self._cancel_contexts(contexts, cleanup=cleanup)

    def clear_all(self):
        self.cancel_all()
        with self._lock:
            self._items.clear()

    def _run(self, url: str, dest: str, epoch: int | None = None):
        """Compatibility entry point used by focused tests and older callers."""
        with self._lock:
            task = self._active.get(url)
            if task is None:
                item = self._items.get(url)
                task = _DownloadTask(
                    url, dest, self._cancel_epoch if epoch is None else epoch,
                    (
                        item.source_subtitle_evidence
                        if item is not None else ()))
                self._active[url] = task
        self._run_download(task)

    def _run_download(self, task: _DownloadTask):
        url = task.url
        self._set_context_state(task, '準備中')
        try:
            self._prep_sem.acquire()
            try:
                if self._context_cancelled(task):
                    self._complete_download(task, '已取消')
                    return
                job = M3U8Sites.CreateSite(url, task.dest)
                if (
                        job is not None
                        and hasattr(job, 'add_source_subtitle_evidence')):
                    job.add_source_subtitle_evidence(
                        task.source_subtitle_evidence)
                with self._lock:
                    if self._active.get(url) is task:
                        task.job = job
            finally:
                self._prep_sem.release()
            if self._context_cancelled(task):
                if job is not None:
                    try:
                        job._cancel_job = True
                    except Exception:
                        pass
                self._complete_download(task, '已取消')
                return
            if not job:
                self._complete_download(task, '網址錯誤')
                return
            if not job.is_url_vaildate():
                err = getattr(job, '_last_error', None)
                if isinstance(err, MirrorsBlockedError):
                    error = ERR_BLOCKED
                else:
                    error = str(err) if err else T('parse_failed_short')
                self._complete_download(
                    task, '封鎖/解析失敗', error=error)
                return
            if self._context_cancelled(task):
                try:
                    job._cancel_job = True
                except Exception:
                    pass
                self._complete_download(task, '已取消')
                return
            name = job.target_name() or ''
            self._set_context_state(task, '下載中', name=name)
            job._progress_callback = (
                lambda d, t, s: self._on_context_progress(task, d, t, s))
            if self._context_cancelled(task):
                try:
                    job._cancel_job = True
                except Exception:
                    pass
                self._complete_download(task, '已取消')
                return
            ok = job.start_download()
            if ok is False and not job._cancel_job:
                raise Exception(T('parse_failed_short'))
            if job._cancel_job or self._context_cancelled(task):
                self._complete_download(task, '已取消')
                return
            mode = normalize_subtitle_mode(self._subtitle_mode_getter())
            if mode != 'none':
                if self._queue_subtitle(task, mode):
                    return
                if self._context_cancelled(task):
                    self._complete_download(task, '已取消')
                    return
            self._complete_download(task, '已下載', progress=100)
        except Exception as exc:
            try:
                print(f'[下載失敗] {url}\n  {exc}', flush=True)
            except Exception:
                pass
            if self._context_cancelled(task):
                self._complete_download(task, '已取消')
            elif isinstance(exc, MirrorsBlockedError):
                self._complete_download(
                    task, '封鎖/解析失敗', error=ERR_BLOCKED)
            else:
                self._complete_download(task, '未完成', error=str(exc))

    def _try_next(self):
        task = None
        with self._lock:
            while self._pending and len(self._active) < self._max_concurrent:
                candidate = self._pending.pop(0)
                if (candidate.cancelled.is_set() or
                        candidate.epoch != self._cancel_epoch):
                    candidate.cancelled.set()
                    self._set_state(candidate.url, '已取消')
                    continue
                self._active[candidate.url] = candidate
                if candidate.url in self._items:
                    self._items[candidate.url] = self._items.pop(candidate.url)
                task = candidate
                break
        if task is not None:
            self._start_download_thread(task)

    def _queue_subtitle(self, task: _DownloadTask, mode: str) -> bool:
        with self._lock:
            if (self._active.get(task.url) is not task or
                    self._context_cancelled_locked(task)):
                return False
            task.subtitle_mode = mode
            self._active.pop(task.url, None)
            self._subtitle_pending.append(task)
            self._set_state(task.url, '字幕準備中', progress=0)
        # The video download slot is free before any subtitle work starts.
        self._try_next()
        self._try_next_subtitle()
        return True

    def _try_next_subtitle(self):
        task = None
        with self._lock:
            if self._subtitle_active:
                return
            while self._subtitle_pending:
                candidate = self._subtitle_pending.pop(0)
                if (candidate.cancelled.is_set() or
                        candidate.epoch != self._cancel_epoch):
                    candidate.cancelled.set()
                    self._set_state(candidate.url, '已取消')
                    continue
                self._subtitle_active[candidate.url] = candidate
                task = candidate
                break
        if task is not None:
            threading.Thread(
                target=self._run_subtitle, args=(task,), daemon=True).start()

    def _run_subtitle(self, task: _DownloadTask):
        job = task.job
        warning = ''
        completion_state = '已下載'

        def _subtitle_progress(stage, percent):
            state = _SUBTITLE_STATE_BY_STAGE.get(stage)
            if state:
                self._set_context_state(
                    task, state,
                    progress=percent if percent is not None else -1)

        try:
            if self._context_cancelled(task):
                raise SubtitleCancelled()
            evidence = set(task.source_subtitle_evidence)
            evidence_getter = getattr(
                job, 'source_subtitle_evidence', None)
            if callable(evidence_getter):
                evidence.update(normalize_source_subtitle_evidence(
                    evidence_getter()))
            evidence = normalize_source_subtitle_evidence(evidence)
            subtitle_kwargs = {
                'progress_callback': _subtitle_progress,
                'cancel_check': lambda: (
                    self._context_cancelled(task) or bool(job._cancel_job)),
            }
            if evidence:
                subtitle_kwargs['source_subtitle_evidence'] = evidence
            subtitle_result = generate_subtitles(
                job._get_video_savename(), task.subtitle_mode,
                **subtitle_kwargs)
            if (
                    subtitle_result.satisfied_by_source
                    and not subtitle_result.files):
                completion_state = '已下載'
                print(T('subtitle_source_chinese_skip'), flush=True)
            elif subtitle_result.no_speech:
                completion_state = '未偵測到日語語音'
            elif (
                    not subtitle_result.files
                    and not subtitle_result.satisfied_by_source):
                completion_state = '未完成'
                warning = T(
                    'subtitle_failed', error=T('subtitle_empty_result'))
        except SubtitleCancelled:
            task.cancelled.set()
        except Exception as exc:
            warning = T(
                'subtitle_failed',
                error=translation_failure_message(exc))

        if (task.cancelled.is_set() or self._context_cancelled(task) or
                bool(getattr(job, '_cancel_job', False))):
            self._complete_subtitle(task, '已取消')
        else:
            self._complete_subtitle(
                task, completion_state, progress=100,
                error=warning if warning else None)

    def _start_download_thread(self, task: _DownloadTask):
        threading.Thread(
            target=self._run_download, args=(task,), daemon=True).start()

    def _url_inflight_locked(self, url: str) -> bool:
        return (
            url in self._active
            or url in self._subtitle_active
            or any(task.url == url for task in self._pending)
            or any(task.url == url for task in self._subtitle_pending)
        )

    def _context_inflight_locked(self, task: _DownloadTask) -> bool:
        return (
            self._active.get(task.url) is task
            or self._subtitle_active.get(task.url) is task
            or any(candidate is task for candidate in self._pending)
            or any(candidate is task for candidate in self._subtitle_pending)
        )

    def _context_cancelled_locked(self, task: _DownloadTask) -> bool:
        return (
            task.cancelled.is_set()
            or task.epoch != self._cancel_epoch
            or not self._context_inflight_locked(task)
        )

    def _context_cancelled(self, task: _DownloadTask) -> bool:
        with self._lock:
            return self._context_cancelled_locked(task)

    def _set_context_state(self, task: _DownloadTask, state: str,
                           name: str = '', progress: int = -1, error=None):
        with self._lock:
            if self._context_cancelled_locked(task):
                return
            self._set_state(
                task.url, state, name=name, progress=progress, error=error)

    def _complete_download(self, task: _DownloadTask, state: str,
                           progress: int = -1, error=None):
        with self._lock:
            if self._active.get(task.url) is not task:
                return
            if self._context_cancelled_locked(task) and state != '已取消':
                state, progress, error = '已取消', -1, None
            self._set_state(
                task.url, state, progress=progress, error=error)
            self._active.pop(task.url, None)
        self._try_next()

    def _complete_subtitle(self, task: _DownloadTask, state: str,
                           progress: int = -1, error=None):
        with self._lock:
            if self._subtitle_active.get(task.url) is not task:
                return
            if self._context_cancelled_locked(task) and state != '已取消':
                state, progress, error = '已取消', -1, None
            self._set_state(
                task.url, state, progress=progress, error=error)
            self._subtitle_active.pop(task.url, None)
        self._try_next_subtitle()

    @staticmethod
    def _cancel_contexts(contexts, cleanup: bool = True):
        seen = set()
        for task in contexts:
            if id(task) in seen:
                continue
            seen.add(id(task))
            task.cancelled.set()
            job = task.job
            if not job or not hasattr(job, 'cancel_download'):
                continue
            try:
                job.cancel_download(cleanup=cleanup)
            except TypeError:
                try:
                    job.cancel_download()
                except Exception:
                    pass
            except Exception:
                pass
            if cleanup and hasattr(job, 'cleanup_temp'):
                try:
                    job.cleanup_temp()
                except Exception:
                    pass

    def _set_state(self, url: str, state: str, name: str = '', progress: int = -1, error=None):
        with self._lock:
            item = self._items.get(url)
            if item:
                item.state = state
                if name:
                    item.name = name
                if progress >= 0:
                    item.progress = progress
                if error is not None:
                    item.error = error
                elif state not in ('未完成', '封鎖/解析失敗'):
                    item.error = ''
                if state != '下載中':
                    item.speed = ''

    def _on_progress(self, url: str, done: int, total: int, speed_bps: float):
        if total <= 0:
            return
        pct = int(done * 100 / total)
        spd = (f'{speed_bps / 1024:.0f} KB/s' if speed_bps < 1024 * 1024
               else f'{speed_bps / 1024 / 1024:.1f} MB/s')
        with self._lock:
            item = self._items.get(url)
            if item:
                item.progress = pct
                item.speed = spd

    def _on_context_progress(self, task: _DownloadTask, done: int,
                             total: int, speed_bps: float):
        with self._lock:
            if (self._active.get(task.url) is not task or
                    self._context_cancelled_locked(task)):
                return
            self._on_progress(task.url, done, total, speed_bps)

    def save_csv(self, path: str):
        with self._lock:
            items = list(self._items.values())
        # Python 3.7+ dict insertion order is used as the recency proxy for
        # capped terminal history; resumable items are never dropped.
        items = _select_persist(items, MAX_PERSIST_ROWS)
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow([
                '狀態', '名稱', '進度', '速度', '網址', '目標',
                '字幕來源證據', '續傳',
            ])
            for item in items:
                w.writerow([item.state, item.name, f'{item.progress}%',
                            item.speed, item.url, item.dest,
                            '|'.join(item.source_subtitle_evidence),
                            '1' if item.resume else '0'])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def load_csv(self, path: str):
        try:
            if not os.path.exists(path):
                return
            with open(path, 'r', encoding='utf-8') as f:
                for idx, row in enumerate(csv.DictReader(f)):
                    if idx >= HARD_LOAD_LIMIT:
                        break
                    url = row.get('網址', '')
                    if url:
                        state = row.get('狀態', '')
                        if state in (
                                '下載中', '準備中', '等待中',
                                '字幕準備中', '字幕辨識中', '字幕翻譯中'):
                            state = '未完成'
                        item = self.add_item(
                            url, row.get('名稱', ''), state,
                            row.get('目標', ''),
                            row.get('字幕來源證據', ''))
                        item.resume = (row.get('續傳') == '1')
                        progress = (row.get('進度', '') or '').rstrip('%')
                        try:
                            item.progress = int(float(progress))
                        except (TypeError, ValueError):
                            pass
                        item.speed = row.get('速度', '') or ''
            # Keep load memory bounded after the safety read limit. Python 3.7+
            # dict insertion order is the recency proxy for terminal items.
            kept = _select_persist(self.get_items(), MAX_PERSIST_ROWS)
            keep_urls = {item.url for item in kept}
            with self._lock:
                for url in list(self._items.keys()):
                    if url not in keep_urls:
                        self._items.pop(url, None)
        except (OSError, UnicodeDecodeError, csv.Error):
            try:
                os.replace(path, path + '.bak')
            except Exception:
                pass

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def subtitle_active_count(self) -> int:
        with self._lock:
            return len(self._subtitle_active)

    @property
    def subtitle_pending_count(self) -> int:
        with self._lock:
            return len(self._subtitle_pending)

    @property
    def inflight_count(self) -> int:
        """Total running or queued downloads and subtitle tasks."""
        with self._lock:
            return (
                len(self._active) + len(self._pending)
                + len(self._subtitle_active) + len(self._subtitle_pending))

    def mark_inflight_for_resume(self):
        """Persist-flag every running/queued task so it can resume on the
        next launch. In-memory item states are reset to 未完成; the caller is
        responsible for saving the CSV before cancelling the contexts."""
        with self._lock:
            for item in self._items.values():
                if item.state in INFLIGHT_STATES:
                    item.state = '未完成'
                    item.speed = ''
                    item.resume = True

    def auto_resume_pending(self):
        """Re-enqueue items previously flagged for resume (e.g. the app was
        closed while tasks were running). Clears the flag so a later launch
        does not resume them a second time."""
        to_enqueue = []
        with self._lock:
            for item in self._items.values():
                if item.resume and item.state in ('未完成', '已取消'):
                    item.resume = False
                    item.progress = 0
                    item.speed = ''
                    item.error = ''
                    to_enqueue.append((item.url, item.dest or 'download'))
        for url, dest in to_enqueue:
            try:
                self.enqueue(url, dest or 'download')
            except Exception as exc:
                try:
                    print(f'[auto resume failed] {url}\n  {exc}', flush=True)
                except Exception:
                    pass


# ── Browse helper ────────────────────────────────────────────────────
def fetch_page_data(browser_cls, url: str) -> dict:
    """Fetch video list from a category/search URL. Returns dict with videos list."""
    try:
        videos = browser_cls.fetch_page(url)
        return {'videos': videos}
    except MirrorsBlockedError:
        raise
    except Exception as e:
        print(f'[瀏覽錯誤] {e}')
        return {'videos': []}


# ── Thumbnail loader ────────────────────────────────────────────────
_thumb_session: Optional[requests.Session] = None
_thumb_lock = threading.Lock()
_thumb_cache: dict = {}   # url -> PIL.Image (raw, not CTkImage; Tk root needed)
_thumb_cache_lock = threading.Lock()   # guards _thumb_cache mutation across the 4 worker threads
_THUMB_SIZE = (1920, 1080)  # High resolution HD cache box for uncompromised sharpness on 1080p/4K screens


def _create_height_fitted_hd_ctk_image(
    img: Image.Image,
    target_w: int,
    target_h: int
) -> ctk.CTkImage:
    """
    Render thumbnail with HEIGHT as the primary fitting dimension.

    Rules:
    - Preserve original aspect ratio.
    - Never crop.
    - Never stretch/distort.
    - Never upscale a source image beyond its native resolution.
    - Prefer matching the target height.
    - If the image is narrower than the frame, leave black space on the sides.
    - If the image cannot fit at the requested height without exceeding the
      frame width, scale it down to fit the width instead.
    """

    target_w = max(1, int(target_w))
    target_h = max(1, int(target_h))

    if not img:
        empty = Image.new("RGB", (target_w, target_h), (16, 16, 22))
        return ctk.CTkImage(
            light_image=empty,
            dark_image=empty,
            size=(target_w, target_h)
        )

    img = img.convert("RGB")

    iw, ih = img.size

    if iw <= 0 or ih <= 0:
        empty = Image.new("RGB", (target_w, target_h), (16, 16, 22))
        return ctk.CTkImage(
            light_image=empty,
            dark_image=empty,
            size=(target_w, target_h)
        )

    # ------------------------------------------------------------
    # 1. PRIMARY RULE: fit by HEIGHT
    # ------------------------------------------------------------
    height_scale = target_h / ih

    # Never upscale a source image.
    height_scale = min(height_scale, 1.0)

    nw = max(1, int(round(iw * height_scale)))
    nh = max(1, int(round(ih * height_scale)))

    # ------------------------------------------------------------
    # 2. If height-fitting makes the image wider than the frame,
    #    reduce it to fit the WIDTH instead.
    #
    #    This prevents horizontal cropping.
    # ------------------------------------------------------------
    if nw > target_w:
        width_scale = target_w / iw

        # Never upscale.
        width_scale = min(width_scale, 1.0)

        nw = max(1, int(round(iw * width_scale)))
        nh = max(1, int(round(ih * width_scale)))

    # ------------------------------------------------------------
    # 3. High-quality resize
    # ------------------------------------------------------------
    if (nw, nh) != (iw, ih):
        resample_filter = getattr(
            Image,
            "Resampling",
            Image
        ).LANCZOS

        fitted = img.resize(
            (nw, nh),
            resample_filter
        )
    else:
        fitted = img.copy()

    # ------------------------------------------------------------
    # 4. Black thumbnail frame
    # ------------------------------------------------------------
    canvas_img = Image.new(
        "RGB",
        (target_w, target_h),
        (16, 16, 22)
    )

    # Center horizontally.
    px = max(0, (target_w - nw) // 2)

    # Center vertically.
    py = max(0, (target_h - nh) // 2)

    canvas_img.paste(
        fitted,
        (px, py)
    )

    return ctk.CTkImage(
        light_image=canvas_img,
        dark_image=canvas_img,
        size=(target_w, target_h)
    )


def _make_circular_avatar(img: Image.Image, diameter: int) -> ctk.CTkImage:
    """Centre-crop ``img`` to a square and mask it to a circle."""
    try:
        diameter = max(1, int(diameter))
        if not img:
            square = Image.new('RGB', (diameter, diameter), (16, 16, 22))
        else:
            img = img.convert('RGBA')
            iw, ih = img.size
            side = min(iw, ih)
            if side <= 0:
                side = diameter
            left = (iw - side) // 2
            top = (ih - side) // 2
            square = img.crop((left, top, left + side, top + side))
            if square.size != (diameter, diameter):
                resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
                square = square.resize((diameter, diameter), resample_filter)
        mask = Image.new('L', (diameter, diameter), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, diameter, diameter), fill=255)
        square.putalpha(mask)
        return ctk.CTkImage(
            light_image=square,
            dark_image=square,
            size=(diameter, diameter)
        )
    except Exception:
        return _create_height_fitted_hd_ctk_image(img, diameter, diameter)


def _make_initials_avatar(text: str, diameter: int = 32, bg_color=None) -> ctk.CTkImage:
    """Generate a stylish circular avatar with initials."""
    diameter = max(16, int(diameter))
    img = Image.new('RGBA', (diameter, diameter), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if not bg_color:
        palette = [
            (255, 75, 110), (139, 92, 246), (59, 130, 246), (16, 185, 129),
            (245, 158, 11), (236, 72, 153), (99, 102, 241), (20, 184, 166)
        ]
        color_idx = sum(ord(c) for c in (text or 'A')) % len(palette)
        bg_color = palette[color_idx]

    draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=bg_color)

    clean_txt = (text or '?').strip()
    words = clean_txt.split()
    if len(words) >= 2:
        initials = (words[0][0] + words[1][0]).upper()
    else:
        initials = clean_txt[:2].upper() if len(clean_txt) >= 2 else clean_txt[:1].upper()

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    bbox = draw.textbbox((0, 0), initials, font=font) if font and hasattr(draw, 'textbbox') else (0, 0, 10, 10)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (diameter - tw) / 2
    ty = (diameter - th) / 2
    draw.text((tx, ty), initials, fill=(255, 255, 255, 255), font=font)

    return ctk.CTkImage(light_image=img, dark_image=img, size=(diameter, diameter))


def _get_thumb_session() -> requests.Session:
    global _thumb_session
    if _thumb_session is None:
        with _thumb_lock:
            if _thumb_session is None:
                s = requests.Session()
                s.mount('http://', requests.adapters.HTTPAdapter(pool_connections=8,
                                                                 pool_maxsize=32))
                s.mount('https://', SharedSSLAdapter(pool_connections=8,
                                                     pool_maxsize=32))
                _thumb_session = s
    return _thumb_session


def _thumbnail_request_context(url: str, site_key: str = ''):
    """Build thumbnail headers and a domain-scoped SupJav/Hanime clearance jar."""
    request_headers = dict(headers)
    cookies = None
    try:
        parsed = urlsplit(str(url or ''))
        host = (parsed.hostname or '').lower().rstrip('.')
    except (TypeError, ValueError):
        return request_headers, cookies

    if 'hanime.tv' in host or 'hanime-cdn' in host:
        request_headers['Referer'] = 'https://hanime.tv/'
        return request_headers, cookies

    if 'hanime1' in host:
        request_headers['Referer'] = 'https://hanime1.me/'
        return request_headers, cookies

    if 'tnaflix' in host:
        request_headers['Referer'] = 'https://www.tnaflix.com/'
        return request_headers, cookies

    trusted_supjav = (
        str(site_key or '').lower() == 'supjav'
        and parsed.scheme.lower() == 'https'
        and host in {'supjav.com', 'www.supjav.com', 'img.supjav.com'}
    )
    if not trusted_supjav:
        return request_headers, cookies

    request_headers['Referer'] = 'https://supjav.com/'
    override = config.get_cf_override('supjav.com') or {}
    if override.get('ua'):
        request_headers['User-Agent'] = override['ua']
    if override.get('cookie'):
        cookies = requests.cookies.RequestsCookieJar()
        cookies.set(
            'cf_clearance', override['cookie'], domain='.supjav.com',
            path='/', secure=True)
    return request_headers, cookies


def _fit_image(img: Image.Image, target_w: int, target_h: int) -> tuple[Image.Image, int, int]:
    """Scale img so the COMPLETE image fits inside target_w x target_h without cropping or zooming in beyond original size."""
    if not img or target_w <= 1 or target_h <= 1:
        return img, max(1, target_w), max(1, target_h)
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return img, max(1, target_w), max(1, target_h)
    scale = min(1.0, target_w / iw, target_h / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    if (nw, nh) != (iw, ih):
        img_scaled = img.resize((nw, nh), Image.LANCZOS)
    else:
        img_scaled = img
    return img_scaled, nw, nh


def _fetch_thumbnail(url: str, site_key: str = '') -> Optional[Image.Image]:
    """Download and decode a thumbnail; cached per-URL."""
    if not url:
        return None
    cached = _thumb_cache.get(url)
    if cached is not None:
        return cached
    request_headers, cookies = _thumbnail_request_context(url, site_key)
    attempts = [(request_headers, cookies)]
    if request_headers != headers or cookies is not None:
        # A saved browser context can expire. Match the listing fetcher's
        # behavior by trying one ordinary request before declaring failure.
        attempts.append((dict(headers), None))

    for attempt_headers, attempt_cookies in attempts:
        request_kwargs = {
            'headers': attempt_headers,
            'timeout': 12,
            **config.proxy_request_kwargs(),
        }
        if attempt_cookies is not None:
            request_kwargs['cookies'] = attempt_cookies
        response = None
        img = None
        try:
            response = _get_thumb_session().get(url, **request_kwargs)
            if response.status_code == 200:
                img = Image.open(io.BytesIO(response.content)).convert('RGB')
                img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
        except Exception:
            pass
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        # Fallback to curl_cffi if standard request failed
        if img is None and _use_cffi:
            try:
                cffi_headers = {k: v for k, v in attempt_headers.items() if str(k).lower() != 'user-agent'}
                cffi_resp = cffi_requests.get(
                    url,
                    headers=cffi_headers,
                    cookies=attempt_cookies,
                    timeout=12,
                    impersonate='chrome',
                    **config.proxy_request_kwargs()
                )
                if cffi_resp.status_code == 200:
                    img = Image.open(io.BytesIO(cffi_resp.content)).convert('RGB')
                    img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
            except Exception:
                pass

        if img is not None:
            with _thumb_cache_lock:
                _thumb_cache[url] = img
                if len(_thumb_cache) > 200:
                    for k in list(_thumb_cache.keys())[:40]:
                        _thumb_cache.pop(k, None)
            return img
    return None


def _fit_card_button_font(text, max_width, base_size=10, bold=False):
    """Return the largest font tuple (family, size[, 'bold']) whose text fits
    inside max_width px, so inline card buttons never clip when the window is
    resized small. Falls back to the smallest readable size (8)."""
    family = ui_font()
    weights = ('bold',) if bold else ()
    avail = max(10, (max_width or 0) - 6)
    for size in (base_size, base_size - 1, base_size - 2, 8):
        try:
            if tkfont.Font(family=family, size=size).measure(text) <= avail:
                return (family, size) + weights
        except Exception:
            continue
    return (family, 8) + weights


def _fetch_actress_portrait(url: str) -> Optional[Image.Image]:
    """Download an actress portrait from a Cloudflare-protected CDN (e.g.
    cdn.javmiku.com) using the browser-impersonating scraper; cached per-URL."""
    if not url:
        return None
    cached = _thumb_cache.get(url)
    if cached is not None:
        return cached
    img = None
    try:
        from metadata_fetcher import _make_cloud_scraper
        with _make_cloud_scraper() as scraper:
            response = scraper.get(
                url, timeout=15,
                headers={
                    'Referer': 'https://jav.guru/',
                    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
                },
                **config.proxy_request_kwargs())
            if response is not None and getattr(response, 'status_code', 0) == 200:
                img = Image.open(io.BytesIO(response.content)).convert('RGB')
                img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
            try:
                response.close()
            except Exception:
                pass
    except Exception:
        img = None
    if img is None:
        img = _fetch_thumbnail(url, '')
    if img is not None:
        with _thumb_cache_lock:
            _thumb_cache[url] = img
    return img


class SiteSelectorBar(ctk.CTkFrame):
    _DROPDOWN_THRESHOLD = 3

    def __init__(self, master, sites, selected, command=None, **kwargs):
        super().__init__(
            master,
            fg_color=BG_CARD,
            border_color=BORDER,
            border_width=1,
            corner_radius=CONTROL_RADIUS,
            **kwargs)
        self.sites = sites
        self.command = command
        self.selected = selected
        self.buttons = {}
        self._dropdown = None

        if len(sites) > self._DROPDOWN_THRESHOLD:
            self._site_var = ctk.StringVar(value=selected)
            self._dropdown = ctk.CTkOptionMenu(
                self, variable=self._site_var, values=list(sites),
                command=self._on_dropdown_change, width=120, height=30,
                corner_radius=6, font=(ui_font(), 11, 'bold'),
                fg_color=BG_CARD, button_color=BG_CARD,
                button_hover_color=BG_CARD_HOVER,
                text_color=ACCENT,
                dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
                dropdown_text_color=WHITE,
                dynamic_resizing=False)
            self._dropdown.pack(padx=4, pady=3)
        else:
            for s in self.sites:
                btn = ctk.CTkButton(
                    self, text=s, width=64, height=30,
                    corner_radius=6,
                    font=(ui_font(), 11, 'bold'),
                    command=lambda site=s: self.set_selected(site, trigger_command=True))
                btn.pack(side='left', padx=2, pady=3)
                self.buttons[s] = btn
            self.set_selected(selected, trigger_command=False)

    def _on_dropdown_change(self, value):
        self.selected = value
        if self.command:
            self.command(value)

    def set_selected(self, site, trigger_command=False):
        self.selected = site
        if self._dropdown:
            self._dropdown.set(site)
        else:
            for s, btn in self.buttons.items():
                if s == site:
                    btn.configure(
                        fg_color=('#FDE8EC', '#2B161B'),
                        hover_color=('#FAD2DB', '#3F1F26'),
                        text_color=ACCENT)
                else:
                    btn.configure(
                        fg_color='transparent',
                        hover_color=BG_CARD_HOVER,
                        text_color=TEXT_SEC)
        if trigger_command and self.command:
            self.command(site)

    def get(self):
        return self.selected

    def set(self, site):
        self.set_selected(site, trigger_command=False)


class ToolTip:
    """Lightweight, themed floating tooltip that displays full text on hover."""
    def __init__(self, widget, text_func, delay_ms: int = 250, max_width: int = 400, only_if_truncated: bool = True):
        self.widget = widget
        self.text_func = text_func if callable(text_func) else (lambda: text_func)
        self.delay_ms = delay_ms
        self.max_width = max_width
        self.only_if_truncated = only_if_truncated
        self._tip_window = None
        self._after_id = None

        try:
            self.widget.bind('<Enter>', self._on_enter, add='+')
            self.widget.bind('<Leave>', self._on_leave, add='+')
            self.widget.bind('<ButtonPress>', self._on_leave, add='+')
            self.widget.bind('<Destroy>', self._on_destroy, add='+')
        except Exception:
            pass

    def _on_enter(self, event=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay_ms, self._show)
        except Exception:
            pass

    def _on_leave(self, event=None):
        self._cancel()
        self._hide()

    def _on_destroy(self, event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        try:
            if not self.widget.winfo_exists():
                return
        except Exception:
            return

        text = self.text_func()
        if not text:
            return

        if self.only_if_truncated:
            try:
                widget_text = ''
                if hasattr(self.widget, 'cget'):
                    try:
                        widget_text = self.widget.cget('text')
                    except Exception:
                        pass
                if not widget_text and hasattr(self.widget, '_text'):
                    widget_text = getattr(self.widget, '_text', '')

                widget_text = str(widget_text or '').strip()
                full_text = str(text or '').strip()

                # If the widget already shows the entire text completely without truncation, skip tooltip
                if widget_text and widget_text == full_text and not widget_text.endswith('…') and not widget_text.endswith('...'):
                    return
            except Exception:
                pass

        self._hide()

        try:
            x = self.widget.winfo_pointerx() + 12
            y = self.widget.winfo_pointery() + 18
            screen_w = self.widget.winfo_screenwidth()
            screen_h = self.widget.winfo_screenheight()

            mode = 'dark'
            try:
                mode = ctk.get_appearance_mode().lower()
            except Exception:
                pass
            is_dark = (mode != 'light')

            bg_color = '#181820' if is_dark else '#FFFFFF'
            fg_color = '#F5F2EF' if is_dark else '#1B1817'
            border_color = '#363644' if is_dark else '#CEC8C0'

            tip = tk.Toplevel(self.widget)
            self._tip_window = tip
            tip.wm_overrideredirect(True)
            try:
                tip.wm_attributes('-topmost', True)
            except Exception:
                pass

            border_frame = tk.Frame(tip, bg=border_color, padx=1, pady=1)
            border_frame.pack(fill='both', expand=True)

            inner_frame = tk.Frame(border_frame, bg=bg_color, padx=9, pady=6)
            inner_frame.pack(fill='both', expand=True)

            lbl = tk.Label(
                inner_frame,
                text=text,
                justify='left',
                bg=bg_color,
                fg=fg_color,
                font=(ui_font(), 10),
                wraplength=self.max_width
            )
            lbl.pack()

            tip.update_idletasks()
            tip_w = tip.winfo_reqwidth()
            tip_h = tip.winfo_reqheight()

            if x + tip_w > screen_w - 12:
                x = screen_w - tip_w - 12
            if x < 12:
                x = 12
            if y + tip_h > screen_h - 12:
                y = max(12, self.widget.winfo_pointery() - tip_h - 10)
            if y < 12:
                y = 12

            tip.wm_geometry(f"+{x}+{y}")
        except Exception:
            self._hide()

    def _hide(self):
        tip = self._tip_window
        self._tip_window = None
        if tip:
            try:
                tip.destroy()
            except Exception:
                pass


# ── Main App ─────────────────────────────────────────────────────────
class ModernApp(ctk.CTk):
    def __init__(self, url: str = '', dest: str = 'download', lang: str = 'en'):
        super().__init__()

        get_shared_ssl_context()
        config.load_cf_overrides()
        self._lang_code_by_name = {name: code for code, name in LANGUAGES}
        self._lang_name_by_code = {code: name for code, name in LANGUAGES}
        self._theme_mode = config.get_theme()
        ctk.set_appearance_mode(self._theme_mode)
        ctk.set_default_color_theme('blue')

        stored = config.get_ui_lang()
        set_lang(stored or 'en')
        self._needs_lang_prompt = (stored is None)

        self.title('FetchJAV')
        self.geometry('1280x820')
        self._base_window_width = 1280
        self.minsize(980, 680)
        self.configure(fg_color=BG_DARK)

        # Frameless window: the in-app header provides the window controls.
        try:
            self.overrideredirect(True)
        except Exception:
            pass
        self._ensure_window_taskbar()

        # Set software window icon & AppUserModelID for Windows taskbar
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('FetchJAV.App')
            except Exception:
                pass

        _ico_candidates = [
            _resolve_resource_path(os.path.join('img', 'logo21', 'logo21_multi.ico')),
            _resolve_resource_path(os.path.join('img', 'logo21', 'logo21_256x256.ico')),
            _resolve_resource_path('logo.ico'),
            _resolve_resource_path(os.path.join('img', 'favicon.ico')),
        ]
        _ico_path = next((p for p in _ico_candidates if os.path.isfile(p)), _resolve_resource_path(os.path.join('img', 'favicon.ico')))
        self._ico_path = _ico_path

        _png_candidates = [
            _resolve_resource_path('logo.png'),
            _resolve_resource_path(os.path.join('img', 'logo.png')),
            _resolve_resource_path(os.path.join('img', 'favicon-256x256.png')),
            _resolve_resource_path(os.path.join('img', 'apple-touch-icon.png')),
        ]
        _png_path = next((p for p in _png_candidates if os.path.isfile(p)), '')

        if _ico_path and os.path.exists(_ico_path):
            try:
                self.iconbitmap(_ico_path)
            except Exception:
                pass
        if _png_path and os.path.exists(_png_path):
            try:
                _app_icon = ImageTk.PhotoImage(Image.open(_png_path))
                self.iconphoto(True, _app_icon)
                self._app_icon = _app_icon
            except Exception:
                pass

        self._dest = dest
        self._url_input = url
        self._is_closing = False
        self._rebuilding = False

        # Browse state
        self._inactive_sites = set(config.get_inactive_sites())
        _active_sites_init = [k for k in SITES.keys() if k not in self._inactive_sites]
        self._site_key = _active_sites_init[0] if _active_sites_init else 'JableTV'
        self._categories: list[dict] = []
        self._current_base_url = ''
        self._page = 1
        self._has_next = True
        self._videos: list[dict] = []
        self._selected_urls: set = set()
        self._selected_source_subtitle_evidence: dict[str, tuple[str, ...]] = {}
        self._sidebar_expanded: dict[str, bool] = {}
        self._grid_gen: int = 0  # bumps on each page refresh so stale thumbs are dropped
        self._grid_columns = browse_columns_for_width(1280)
        self._resize_after_id = None
        self._page_req: int = 0
        self._build_gen: int = 0
        self._active_tab_idx: int = 0
        self._last_loaded_page: int = 1
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._search_all_mode = False       # compass toggle: search every site at once
        self._search_all_active = False     # current grid is a multi-site search result
        self._search_all_query = ''
        self._compass_lbl = None
        self._compass_icon = None
        self._compass_icon_active = None
        self._last_estimated_cw: int = 260
        self._card_widgets: dict = {}  # url -> {card, sel_btn, preview_btn}
        self._preview_gen: int = 0
        self._preview_video: Optional[dict] = None
        self._preview_source = None
        self._preview_player = None
        self._preview_thumb_refs: list = []
        self._browse_mode: str = 'grid'
        self._dl_rows: dict = {}   # url -> {row, state_lbl, name_lbl, pb, pct, spd, remove}
        self._dl_empty_lbl = None
        self._dl_footer_lbl = None
        self._dl_drain_id = None
        self._dl_gen = 0
        self._thumb_executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)
        self._dur_executor = concurrent.futures.ThreadPoolExecutor(max_workers=6)
        self._speed_mbps = 0.0
        self._download_autosave_ticks = 0
        self._last_download_save_sig = None
        self._update_info = None
        self._update_checking = False
        self._update_installing = False
        self._update_prompt_shown = False
        self._update_status_text = ''
        self._update_status_color = TEXT_DIM
        self._update_badge = None
        self._update_status_lbl = None
        self._update_note_lbl = None
        self._update_check_btn = None
        self._update_now_btn = None

        # Background (close-to-tray) support
        self._tray_icon = None
        self._tray_available = False
        self._tray_cmds = None
        self._tray_cmd_drain_id = None
        self._background_poll_id = None
        self._window_hidden = False
        self._close_dlg = None

        # Download manager
        self._dlmgr = DownloadManager(
            max_concurrent=config.get_download_concurrency())
        if not os.path.exists(CSV_PATH):
            old_csv = os.path.join(os.getcwd(), 'JableTV.csv')
            if (os.path.exists(old_csv) and
                    os.path.abspath(old_csv) != os.path.abspath(CSV_PATH)):
                try:
                    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
                    shutil.copy2(old_csv, CSV_PATH)
                except Exception:
                    pass
        self._dlmgr.load_csv(CSV_PATH)
        # Auto-resume tasks that were running when the app was last closed.
        try:
            self._dlmgr.auto_resume_pending()
        except Exception as exc:
            try:
                print(f'[auto resume failed] {exc}', flush=True)
            except Exception:
                pass
        try:
            self._dlmgr.save_csv(CSV_PATH)
        except Exception:
            pass

        # Report anonymous launch event to Firebase / GA4
        try:
            analytics.track_app_open(version=APP_VERSION, lang=get_lang())
        except Exception:
            pass

        # Load destination field icons (browse & open) and tag icon
        self._browse_icon = None
        self._open_icon = None
        self._tag_icon = None
        img_dir_dest = _resolve_resource_path('img')
        try:
            b_light_p = os.path.join(img_dir_dest, 'icon_browse_light.png')
            b_dark_p = os.path.join(img_dir_dest, 'icon_browse_dark.png')
            if os.path.exists(b_light_p) and os.path.exists(b_dark_p):
                self._browse_icon = ctk.CTkImage(
                    light_image=Image.open(b_light_p),
                    dark_image=Image.open(b_dark_p),
                    size=(18, 18)
                )
            o_light_p = os.path.join(img_dir_dest, 'icon_open_light.png')
            o_dark_p = os.path.join(img_dir_dest, 'icon_open_dark.png')
            if os.path.exists(o_light_p) and os.path.exists(o_dark_p):
                self._open_icon = ctk.CTkImage(
                    light_image=Image.open(o_light_p),
                    dark_image=Image.open(o_dark_p),
                    size=(18, 18)
                )
            t_light_p = os.path.join(img_dir_dest, 'icon_tag_accent_light.png')
            t_dark_p = os.path.join(img_dir_dest, 'icon_tag_accent_dark.png')
            if os.path.exists(t_light_p) and os.path.exists(t_dark_p):
                self._tag_icon = ctk.CTkImage(
                    light_image=Image.open(t_light_p),
                    dark_image=Image.open(t_dark_p),
                    size=(18, 18)
                )

            h_p = os.path.join(img_dir_dest, 'icon_heart_white.png')
            if os.path.exists(h_p):
                self._heart_icon = ctk.CTkImage(
                    light_image=Image.open(h_p), dark_image=Image.open(h_p),
                    size=(16, 16)
                )
            h_fl_p = os.path.join(img_dir_dest, 'icon_heart_filled_light.png')
            h_fd_p = os.path.join(img_dir_dest, 'icon_heart_filled_dark.png')
            if os.path.exists(h_fl_p) and os.path.exists(h_fd_p):
                self._heart_active_icon = ctk.CTkImage(
                    light_image=Image.open(h_fl_p), dark_image=Image.open(h_fd_p),
                    size=(16, 16)
                )
            else:
                h_pri_p = os.path.join(img_dir_dest, 'icon_heart_pri.png')
                if os.path.exists(h_pri_p):
                    self._heart_active_icon = ctk.CTkImage(
                        light_image=Image.open(h_pri_p), dark_image=Image.open(h_pri_p),
                        size=(16, 16)
                    )
                else:
                    self._heart_active_icon = getattr(self, '_heart_icon', None)
            p_p = os.path.join(img_dir_dest, 'icon_plus_white.png')
            if os.path.exists(p_p):
                self._plus_icon = ctk.CTkImage(
                    light_image=Image.open(p_p), dark_image=Image.open(p_p),
                    size=(14, 14)
                )
            d_p = os.path.join(img_dir_dest, 'icon_dl_white.png')
            if os.path.exists(d_p):
                self._dl_icon = ctk.CTkImage(
                    light_image=Image.open(d_p), dark_image=Image.open(d_p),
                    size=(14, 14)
                )
            sub_loc_light = os.path.join(img_dir_dest, 'icon_sub_local_light.png')
            sub_loc_dark = os.path.join(img_dir_dest, 'icon_sub_local_dark.png')
            if os.path.exists(sub_loc_light) and os.path.exists(sub_loc_dark):
                self._sub_local_icon = ctk.CTkImage(
                    light_image=Image.open(sub_loc_light),
                    dark_image=Image.open(sub_loc_dark),
                    size=(16, 16)
                )
            sub_srch_light = os.path.join(img_dir_dest, 'icon_sub_search_light.png')
            sub_srch_dark = os.path.join(img_dir_dest, 'icon_sub_search_dark.png')
            if os.path.exists(sub_srch_light) and os.path.exists(sub_srch_dark):
                self._sub_search_icon = ctk.CTkImage(
                    light_image=Image.open(sub_srch_light),
                    dark_image=Image.open(sub_srch_dark),
                    size=(16, 16)
                )
        except Exception:
            pass

        self._build_ui()
        self.bind('<Configure>', self._on_root_resize, add='+')
        self.bind_all('<Key>', self._on_global_player_key, add='+')
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        # Start periodic refresh for downloads
        self._refresh_downloads()
        # Start clipboard monitor (main-thread safe)
        self._clp_text = ''
        self._clipboard_poll()

        # Tk rejects worker-thread ``after`` calls before mainloop starts.  Defer
        # every worker that can complete quickly until the event loop is active.
        self.after_idle(self._start_initial_background_tasks)
        if self._needs_lang_prompt:
            self.after(250, self._first_run_language_prompt)

    def _ensure_window_taskbar(self):
        """Give the frameless window a taskbar button (Windows only)."""
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if not (style & WS_EX_APPWINDOW):
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE, style | WS_EX_APPWINDOW)
        except Exception:
            pass

    def _win_minimize(self):
        if self._is_closing:
            return
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                # SW_MINIMIZE (wm iconify fails on override-redirect windows)
                ctypes.windll.user32.ShowWindow(hwnd, 6)
                return
            except Exception:
                pass
        try:
            self.iconify()
        except Exception:
            pass

    def _win_toggle_maximize(self):
        if self._is_closing:
            return
        try:
            if self.state() == 'zoomed':
                self.state('normal')
            else:
                self.state('zoomed')
        except Exception:
            pass
        self._update_win_max_icon()

    def _win_close(self):
        self._on_close()

    def _update_win_max_icon(self):
        is_zoomed = (self.state() == 'zoomed')
        btn = getattr(self, '_win_btn_max', None)
        if btn is not None:
            try:
                btn.configure(text='❐' if is_zoomed else '□')
            except Exception:
                pass
        shell = getattr(self, '_window_shell', None)
        if shell is not None:
            try:
                if is_zoomed:
                    shell.configure(border_width=0, corner_radius=0)
                else:
                    shell.configure(border_width=1, corner_radius=8, border_color=('#c4c4cc', '#585868'))
            except Exception:
                pass

    def _start_initial_background_tasks(self):
        if self._is_closing:
            return
        self._start_update_check(manual=False)
        self._load_categories()

    def _ask_language_first_run(self):
        popup = None
        try:
            idx = 0 if ctk.get_appearance_mode() == 'Light' else 1
            def C(tok):                      # resolve a (light,dark) token to a single hex string
                return tok[idx] if isinstance(tok, (tuple, list)) else tok
            bg, card, fg, border, accent, cardh = (
                C(BG_DARK), C(BG_CARD), C(TEXT_PRI), C(BORDER_HOVER), C(ACCENT), C(BG_CARD_HOVER))

            popup = tk.Toplevel(self)
            popup.title(T('lang_picker_title'))
            popup.configure(bg=bg)
            popup.resizable(False, False)
            popup.transient(self)
            if getattr(self, '_ico_path') and os.path.exists(self._ico_path):
                try:
                    popup.iconbitmap(self._ico_path)
                except Exception:
                    pass

            picker_font = 'Microsoft JhengHei'   # renders all 4 native scripts
            tk.Label(popup, text=T('lang_picker_title'), bg=bg, fg=fg,
                     font=(picker_font, 15, 'bold')).pack(padx=32, pady=(24, 14))

            def _choose(code='en'):
                config.set_ui_lang(code)
                if code != get_lang():
                    self._apply_language(code)
                try:
                    popup.destroy()
                except tk.TclError:
                    pass

            for code, name in LANGUAGES:
                tk.Button(popup, text=name, width=22,
                          bg=card, fg=fg, activebackground=accent, activeforeground='#ffffff',
                          relief='flat', bd=1, highlightbackground=border, highlightthickness=1,
                          padx=12, pady=9, font=(picker_font, 12), cursor='hand2',
                          command=lambda c=code: _choose(c)).pack(padx=32, pady=5)

            popup.protocol('WM_DELETE_WINDOW', lambda: _choose(get_lang() or 'en'))
            popup.update_idletasks()
            w = max(popup.winfo_reqwidth(), 320)
            h = max(popup.winfo_reqheight(), 280)
            x = max((self.winfo_screenwidth() - w) // 2, 0)
            y = max((self.winfo_screenheight() - h) // 3, 0)
            popup.geometry(f'{w}x{h}+{x}+{y}')
            # Force the picker visible (plain tk.Toplevel shows reliably in frozen builds)
            popup.deiconify()
            popup.lift()
            try:
                popup.attributes('-topmost', True)
                popup.after(300, lambda: popup.winfo_exists() and popup.attributes('-topmost', False))
            except tk.TclError:
                pass
            popup.update_idletasks()
            popup.focus_force()
        except Exception:
            if popup is not None:
                try:
                    popup.destroy()
                except tk.TclError:
                    pass
            try:
                config.set_ui_lang('en')
            except Exception:
                pass

    def _first_run_language_prompt(self):
        if self._is_closing:
            return
        try:
            self.deiconify()
            self.update_idletasks()
        except tk.TclError:
            pass
        self._ask_language_first_run()

    def _ui(self, fn, gen: int | None = None):
        if self._is_closing:
            return
        if gen is not None and gen != self._build_gen:
            return

        def _run():
            if self._is_closing:
                return
            if gen is not None and gen != self._build_gen:
                return
            try:
                fn()
            except tk.TclError:
                pass

        try:
            self.after(0, _run)
        except (tk.TclError, RuntimeError, Exception):
            pass

    def _short_update_note(self, info):
        notes = (info or {}).get('notes') or ''
        for line in notes.splitlines():
            line = line.strip()
            if line:
                return line[:180]
        return ''

    def _show_update_prompt(self, info):
        if self._is_closing or self._update_prompt_shown:
            return
        self._update_prompt_shown = True
        prompt = None
        try:
            prompt = ctk.CTkToplevel(self)
            prompt.title(T('update_prompt_title'))
            prompt.configure(fg_color=BG_CARD)
            prompt.resizable(False, False)
            prompt.transient(self)
            if getattr(self, '_ico_path') and os.path.exists(self._ico_path):
                try:
                    prompt.iconbitmap(self._ico_path)
                except Exception:
                    pass

            pos_width, pos_height = 420, 220
            self.update_idletasks()
            x = self.winfo_rootx() + max((self.winfo_width() - pos_width) // 2, 0)
            y = self.winfo_rooty() + 80
            x = max(min(x, self.winfo_screenwidth() - pos_width), 0)
            y = max(min(y, self.winfo_screenheight() - pos_height), 0)

            body = ctk.CTkFrame(prompt, fg_color=BG_CARD, corner_radius=0)
            body.pack(fill='both', expand=True, padx=22, pady=20)

            ctk.CTkLabel(
                body, text=T('update_prompt_title'),
                font=(ui_font(), 16, 'bold'), text_color=TEXT_PRI
            ).pack(anchor='w')

            tag = (info or {}).get('tag') or (info or {}).get('version')
            ctk.CTkLabel(
                body, text=T('update_available', version=tag),
                font=(ui_font(), 12), text_color=TEXT_SEC,
                wraplength=360, justify='left'
            ).pack(anchor='w', pady=(12, 0))

            note = self._short_update_note(info)
            if note:
                ctk.CTkLabel(
                    body, text=note, font=(ui_font(), 10),
                    text_color=TEXT_DIM, wraplength=360, justify='left'
                ).pack(anchor='w', pady=(8, 0))

            row = ctk.CTkFrame(body, fg_color='transparent')
            row.pack(fill='x', pady=(18, 0))

            def _close():
                try:
                    prompt.destroy()
                except tk.TclError:
                    pass

            def _install():
                _close()
                self._start_update_install()

            later_btn = ctk.CTkButton(
                row, text=T('update_prompt_later'), width=118, height=34,
                corner_radius=8, fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, command=_close)

            update_btn = ctk.CTkButton(
                row, text=T('update_now_btn'), width=118, height=34,
                corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                text_color=('#FFFFFF', '#FFFFFF'), command=_install
            )
            update_btn.pack(side='right')
            later_btn.pack(side='right', padx=(0, 8))

            prompt.protocol('WM_DELETE_WINDOW', _close)
            prompt.bind('<Escape>', lambda _event: _close())
            prompt.update_idletasks()
            prompt.geometry(f'+{x}+{y}')
            prompt.deiconify()
            prompt.lift()
            prompt.focus_force()
            later_btn.focus_force()
        except Exception:
            if prompt is not None:
                try:
                    prompt.destroy()
                except tk.TclError:
                    pass

    def _set_update_status(self, text, color=None):
        self._update_status_text = text
        self._update_status_color = color or TEXT_DIM
        self._refresh_update_ui()

    def _refresh_update_ui(self):
        available = bool(self._update_info)
        status = self._update_status_text or T('update_idle')
        if self._update_status_lbl is not None:
            try:
                self._update_status_lbl.configure(
                    text=status, text_color=self._update_status_color)
            except tk.TclError:
                pass
        if self._update_note_lbl is not None:
            try:
                if available:
                    note = self._short_update_note(self._update_info)
                    tag = self._update_info.get('tag') or self._update_info.get('version')
                    text = T('update_available', version=tag)
                    if note:
                        text = f'{text}  {note}'
                    self._update_note_lbl.configure(text=text)
                else:
                    self._update_note_lbl.configure(text='')
            except tk.TclError:
                pass
        if self._update_check_btn is not None:
            try:
                self._update_check_btn.configure(
                    state='disabled' if self._update_checking else 'normal')
            except tk.TclError:
                pass
        if self._update_now_btn is not None:
            try:
                if available:
                    if not self._update_now_btn.winfo_manager():
                        self._update_now_btn.pack(side='left', padx=(8, 0))
                    self._update_now_btn.configure(
                        state='disabled' if self._update_installing else 'normal')
                else:
                    self._update_now_btn.configure(state='disabled')
                    self._update_now_btn.pack_forget()
            except tk.TclError:
                pass
        if self._update_badge is not None:
            try:
                if available:
                    if not self._update_badge.winfo_manager():
                        self._update_badge.pack(side='left', padx=(8, 0))
                else:
                    self._update_badge.pack_forget()
            except tk.TclError:
                pass

    def _start_update_check(self, manual=False):
        if self._is_closing or self._update_checking:
            return
        self._update_checking = True
        if manual:
            self._set_update_status(T('update_checking'), TEXT_SEC)
        else:
            self._refresh_update_ui()

        def _worker():
            info = None
            newer = False
            try:
                info = updater.check_latest()
                newer = bool(info and updater.is_newer(
                    info.get('version', ''), APP_VERSION))
            except Exception:
                info = None
                newer = False

            def _apply():
                self._update_checking = False
                if newer:
                    self._update_info = info
                    tag = info.get('tag') or info.get('version')
                    self._set_update_status(
                        T('update_available', version=tag), SUCCESS)
                    if not manual and not self._update_prompt_shown:
                        self._show_update_prompt(info)
                elif manual:
                    self._update_info = None
                    self._set_update_status(T('update_uptodate'), TEXT_SEC)
                elif info is not None:
                    self._update_info = None
                    self._refresh_update_ui()
                else:
                    if manual:
                        self._set_update_status(T('update_failed'), ERROR_C)
                    else:
                        self._refresh_update_ui()

            self._ui(_apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _start_update_install(self):
        info = self._update_info
        if self._is_closing or self._update_installing or not info:
            return
        if not updater.is_frozen():
            try:
                webbrowser.open(info.get('html_url') or updater.API_LATEST)
            except Exception:
                pass
            self._set_update_status(T('update_from_source'), WARNING)
            return

        name = updater.current_exe_name()
        url = (info.get('assets') or {}).get(name)
        if not url:
            self._set_update_status(T('update_failed'), ERROR_C)
            return

        self._update_installing = True
        self._set_update_status(T('update_downloading', pct=0), TEXT_SEC)

        def _worker():
            exe_dir = os.path.dirname(sys.executable)
            new_path = os.path.join(exe_dir, name + '.new')

            def _progress(downloaded, total):
                pct = int(downloaded * 100 / total) if total else 0
                self._ui(lambda p=pct: self._set_update_status(
                    T('update_downloading', pct=p), TEXT_SEC))

            ok = updater.download_asset(url, new_path, progress_cb=_progress)
            if ok and updater.apply_update_and_restart(new_path):
                self._ui(lambda: self._set_update_status(
                    T('update_restarting'), SUCCESS))
                self._ui(self._on_close)
                return

            def _failed():
                self._update_installing = False
                self._set_update_status(T('update_failed'), ERROR_C)

            self._ui(_failed)

        threading.Thread(target=_worker, daemon=True).start()

    def _show_update_settings(self, event=None):
        self._select_tab('settings')

    def _theme_display_name(self, mode: str) -> str:
        mode_s = (mode or '').strip().lower()
        if mode_s == 'system':
            return 'System Theme'
        elif mode_s == 'light':
            return 'Light Theme'
        return 'Dark Theme'

    def _on_theme_select(self, choice: str):
        choice_s = (choice or '').strip().lower()
        if 'system' in choice_s:
            mode = 'system'
        elif 'light' in choice_s:
            mode = 'light'
        else:
            mode = 'dark'
        self._theme_mode = mode
        ctk.set_appearance_mode(mode)
        config.set_theme(mode)
        if hasattr(self, '_theme_var') and self._theme_var:
            self._theme_var.set(self._theme_display_name(mode))

    def _theme_glyph(self):
        return {'system': '◐', 'light': '☀', 'dark': '☾'}.get(self._theme_mode, '☾')

    def _get_theme_icon(self):
        return getattr(self, '_theme_icon', None)

    def _cycle_theme(self):
        modes = ('system', 'light', 'dark')
        try:
            idx = modes.index(self._theme_mode)
        except ValueError:
            idx = 0
        self._theme_mode = modes[(idx + 1) % len(modes)]
        ctk.set_appearance_mode(self._theme_mode)
        config.set_theme(self._theme_mode)
        if hasattr(self, '_theme_var') and self._theme_var:
            self._theme_var.set(self._theme_display_name(self._theme_mode))
        icon_obj = self._get_theme_icon()
        if hasattr(self, '_theme_btn') and self._theme_btn:
            if icon_obj:
                self._theme_btn.configure(text="", image=icon_obj)
            else:
                self._theme_btn.configure(text=self._theme_glyph())

    def _on_refresh_page(self):
        active_tab_idx = getattr(self, '_active_tab_idx', 0)
        tab_keys = getattr(self, '_tab_keys', ['browse'])
        current_tab = tab_keys[active_tab_idx] if active_tab_idx < len(tab_keys) else 'browse'

        if current_tab == 'browse':
            if getattr(self, '_browse_mode', 'grid') == 'preview':
                preview_vid = getattr(self, '_preview_video', None)
                if preview_vid:
                    self._open_preview(preview_vid, is_back_nav=True)
            else:
                self._load_page()
        elif current_tab == 'queue':
            self._render_queue_page()
        elif current_tab == 'settings':
            active_cat = getattr(self, '_active_settings_cat', 'update')
            self._switch_settings_cat(active_cat)

        status_lbl = getattr(self, '_status_lbl', None)
        if status_lbl:
            status_lbl.configure(text=T('page_refreshed_toast') if 'page_refreshed_toast' in T.__code__.co_varnames else '🔄 Page refreshed')

    def _update_responsive_nav(self, width: int = None):
        if getattr(self, '_is_closing', False):
            return
        if width is None:
            try:
                width = self.winfo_width() / max(self._get_window_scaling(), 1.0)
            except Exception:
                width = self.winfo_width()

        if width <= 1:
            width = 1280

        # 10% width reduction threshold from base initial window width (1280px * 0.9 = 1152px)
        base_w = getattr(self, '_base_window_width', 1280)
        compact_threshold = base_w * 0.90
        is_compact_header = width <= compact_threshold
        is_compact_sidebar = width < 880

        # Runtime position check: if right_info left edge is near the centered tab_nav right edge with text
        try:
            tab_nav = getattr(self, '_tab_nav_frame', None)
            right_info = getattr(self, '_right_info_frame', None)
            if tab_nav and right_info and tab_nav.winfo_exists() and right_info.winfo_exists():
                rx = right_info.winfo_x()
                if rx > 300:
                    if rx <= (width / 2) + 190:
                        is_compact_header = True
        except Exception:
            pass

        tab_labels = {'browse': T('tab_browse'), 'download': T('tab_download'), 'settings': T('tab_settings')}

        for key in getattr(self, '_tab_keys', []):
            info = getattr(self, '_tab_buttons', {}).get(key)
            if not info or 'btn' not in info:
                continue
            btn = info['btn']
            try:
                if is_compact_header:
                    btn.configure(text="", width=40, compound='center')
                    btn.pack_configure(padx=2)
                else:
                    btn.configure(text=f" {tab_labels[key]}", width=120, compound='left')
                    btn.pack_configure(padx=0)
            except Exception:
                pass

        if hasattr(self, '_settings_nav_btns') and self._settings_nav_btns:
            left_nav = getattr(self, '_settings_left_nav', None)
            if left_nav:
                try:
                    left_nav.configure(width=56 if is_compact_sidebar else 210)
                except Exception:
                    pass

            for cat_item in getattr(self, '_settings_categories', []):
                if len(cat_item) == 3:
                    cat_key, cat_icon, cat_label = cat_item
                else:
                    cat_key, cat_label = cat_item[:2]
                    cat_icon = '⚙'
                btn = self._settings_nav_btns.get(cat_key)
                if btn:
                    try:
                        if is_compact_sidebar:
                            btn.configure(text=cat_icon, anchor='center')
                        else:
                            btn.configure(text=f"{cat_icon}  {cat_label}", anchor='w')
                    except Exception:
                        pass

        # Dynamic browse toolbar row rearrangement for narrow window sizes
        toolbar_shell = getattr(self, '_top_toolbar_shell', None)
        row1 = getattr(self, '_top_toolbar_row1', None)
        row2 = getattr(self, '_top_toolbar_row2', None)
        actions = getattr(self, '_toolbar_actions', None)
        current_mode = getattr(self, '_toolbar_layout_mode', 'wide')

        if toolbar_shell and row1 and row2 and actions:
            is_narrow = width < 960
            target_mode = 'narrow' if is_narrow else 'wide'
            if target_mode != current_mode:
                self._toolbar_layout_mode = target_mode
                try:
                    if target_mode == 'narrow':
                        actions.pack_forget()
                        row2.pack(fill='x', padx=12, pady=(0, 6))
                        actions.pack(in_=row2, side='right')
                    else:
                        actions.pack_forget()
                        row2.pack_forget()
                        actions.pack(in_=row1, side='right')
                except Exception:
                    pass

    def _on_root_resize(self, event):
        if event.widget is not self or self._is_closing:
            return
        try:
            logical_width = event.width / max(self._get_window_scaling(), 1.0)
        except Exception:
            logical_width = event.width

        self._update_responsive_nav(logical_width)
        self._update_win_max_icon()

        if getattr(self, '_browse_mode', '') == 'preview':
            self._update_preview_layout(logical_width)

        columns = browse_columns_for_width(logical_width)
        if columns == self._grid_columns:
            return
        self._grid_columns = columns
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        try:
            self._resize_after_id = self.after(180, self._apply_responsive_grid)
        except tk.TclError:
            self._resize_after_id = None

    def _apply_responsive_grid(self):
        self._resize_after_id = None
        if (self._is_closing or not self._videos or
                getattr(self, '_grid_scroll', None) is None):
            return
        self._refresh_grid()

    def _current_tab_index(self):
        return self._active_tab_idx

    def _set_tab_index(self, idx: int):
        idx = max(0, min(int(idx), len(self._tab_keys) - 1))
        self._select_tab(self._tab_keys[idx])

    def _select_tab(self, key):
        if key not in getattr(self, '_tab_frames', {}):
            return
        for f in self._tab_frames.values():
            f.pack_forget()
        self._tab_frames[key].pack(fill='both', expand=True)
        for k, w in self._tab_buttons.items():
            active = (k == key)
            try:
                icon_obj = getattr(self, '_nav_icons', {}).get(k, {}).get('active' if active else 'inactive')
                if 'btn' in w:
                    w['btn'].configure(
                        text_color=(ACCENT if active else TEXT_SEC),
                        image=icon_obj if icon_obj else getattr(w['btn'], 'cget', lambda x: None)('image')
                    )
                elif 'lbl' in w:
                    w['lbl'].configure(
                        text_color=(TEXT_PRI if active else TEXT_SEC),
                        font=(ui_font(), 14, 'bold') if active else (ui_font(), 14))
                if 'underline' in w:
                    w['underline'].configure(fg_color=(ACCENT if active else 'transparent'))
            except Exception:
                pass
        self._active_tab_idx = self._tab_keys.index(key)

        # Disable & hide page navigation bar when on Settings or Download page
        is_browse = (key == 'browse')
        page_nav = getattr(self, '_page_nav_box', None)
        if page_nav:
            if is_browse:
                page_nav.pack(side='right', padx=12)
            else:
                page_nav.pack_forget()

        # Ensure status bar is always visible at the bottom on all tabs (unless in preview mode)
        status_bar = getattr(self, '_status_bar', None)
        status_sep = getattr(self, '_status_bar_sep', None)
        is_preview = (key == 'browse' and getattr(self, '_browse_mode', 'grid') == 'preview')
        if status_bar and not is_preview:
            try:
                status_bar.pack(side='bottom', fill='x')
                if status_sep:
                    status_sep.pack(side='bottom', fill='x')
            except Exception:
                pass

        for btn_attr in ('_b_first', '_b_prev', '_b_next', '_b_go', '_jump_entry'):
            widget = getattr(self, btn_attr, None)
            if widget:
                try:
                    widget.configure(state='normal' if is_browse else 'disabled')
                except Exception:
                    pass

    def _speed_values(self):
        return [T('unlimited'), '1 MB/s', '2 MB/s', '5 MB/s',
                '10 MB/s', '15 MB/s']

    def _speed_label(self):
        return T('unlimited') if self._speed_mbps == 0 else f'{int(self._speed_mbps)} MB/s'

    def _resolution_values(self):
        return [T('resolution_highest'), '1080p', '720p', '480p', '360p',
                T('resolution_lowest')]

    def _resolution_pref_from_label(self, label):
        label = str(label or '').strip()
        if label == T('resolution_lowest'):
            return 'lowest'
        if label in {'1080p', '720p', '480p', '360p'}:
            return label[:-1]
        return 'highest'

    def _resolution_label(self):
        from M3U8Sites.M3U8Crawler import get_resolution_pref
        pref = get_resolution_pref()
        if pref == 'lowest':
            return T('resolution_lowest')
        if pref in {'1080', '720', '480', '360'}:
            return f'{pref}p'
        return T('resolution_highest')

    def _subtitle_values(self):
        return [
            T('subtitle_none'), T('subtitle_ja'), T('subtitle_en'),
            T('subtitle_zh'), T('subtitle_all'),
        ]

    def _subtitle_pref_from_label(self, label):
        return {
            T('subtitle_none'): 'none',
            T('subtitle_ja'): 'ja',
            T('subtitle_en'): 'en',
            T('subtitle_zh'): 'zh',
            T('subtitle_all'): 'all',
        }.get(str(label or ''), 'none')

    def _subtitle_label(self):
        return {
            'none': T('subtitle_none'),
            'ja': T('subtitle_ja'),
            'en': T('subtitle_en'),
            'zh': T('subtitle_zh'),
            'all': T('subtitle_all'),
        }.get(config.get_subtitle_pref(), T('subtitle_none'))

    def _recognition_quality_values(self):
        return [
            T('recognition_quality_auto'),
            T('recognition_quality_quality'),
            T('recognition_quality_balanced'),
            T('recognition_quality_fast'),
        ]

    def _recognition_quality_from_label(self, label):
        return normalize_recognition_quality({
            T('recognition_quality_auto'): 'auto',
            T('recognition_quality_quality'): 'quality',
            T('recognition_quality_balanced'): 'balanced',
            T('recognition_quality_fast'): 'fast',
        }.get(str(label or ''), 'auto'))

    def _recognition_quality_label(self, quality=None):
        quality = (
            config.get_recognition_quality()
            if quality is None else quality)
        return {
            'auto': T('recognition_quality_auto'),
            'quality': T('recognition_quality_quality'),
            'balanced': T('recognition_quality_balanced'),
            'fast': T('recognition_quality_fast'),
        }[normalize_recognition_quality(quality)]

    def _open_translation_settings(self):
        open_translation_settings_dialog(
            self, on_saved=self._refresh_translation_provider_status)

    def _refresh_translation_provider_status(self):
        label = getattr(self, '_translation_provider_status_lbl', None)
        if label is None:
            return
        try:
            label.configure(text=translation_provider_summary())
        except tk.TclError:
            pass

    def _on_lang_change(self, display_name):
        code = self._lang_code_by_name.get(display_name)
        if not code or code == get_lang():
            return
        self._apply_language(code)

    def _var_get(self, name, default=''):
        var = getattr(self, name, None)
        if var is None:
            return default
        try:
            return var.get()
        except (AttributeError, tk.TclError):
            return default

    def _apply_language(self, code):
        self._rebuilding = True
        from M3U8Sites.M3U8Crawler import get_resolution_pref, set_resolution_pref

        try:
            snapshot = {
                'tab_idx': self._current_tab_index(),
                'settings_cat': getattr(self, '_active_settings_cat', 'general'),
                'dest': self._var_get('_dest_var', self._dest),
                'dl_url': self._var_get('_dl_url_var', self._url_input),
                'cf_host': self._var_get('_cf_host_var'),
                'cf_cookie': self._var_get('_cf_cookie_var'),
                'cf_ua': self._var_get('_cf_ua_var'),
                'page_jump': self._var_get('_page_jump_var'),
                'concurrency': self._dlmgr.max_concurrent,
                'max_workers_per_video': self._commit_workers_preference(),
                'speed_mbps': self._speed_mbps,
                'resolution_pref': get_resolution_pref(),
                'site_key': self._site_key,
            }

            set_lang(code)
            config.set_ui_lang(code)
            self._build_gen += 1
            self._page_req += 1
            self._grid_gen += 1

            for child in self.winfo_children():
                try:
                    child.destroy()
                except tk.TclError:
                    pass

            self._card_widgets = {}
            self._dl_rows = {}
            self._dl_footer_lbl = None
            self._dl_drain_id = None
            self._dl_gen += 1
            self._categories = []
            self._selected_urls.clear()
            self._dl_empty_lbl = None
            self._videos = []
            self._browse_blocked = False
            self._browse_empty_message = ''
            self._cf_status_lbl = None
            self._site_menu = None
            self._cat_menu = None
            self._grid_scroll = None
            self._dl_scroll = None
            self._sidebar = None
            self._status_lbl = None

            self._dest = snapshot['dest']
            self._url_input = snapshot['dl_url']
            self._site_key = snapshot['site_key']
            self._speed_mbps = snapshot['speed_mbps']
            set_resolution_pref(snapshot['resolution_pref'])

            self._build_ui()

            if hasattr(self, '_site_var') and self._site_var:
                self._site_var.set(snapshot['site_key'])
            if hasattr(self, '_dest_var') and self._dest_var:
                self._dest_var.set(snapshot['dest'])
            if hasattr(self, '_dl_url_var') and self._dl_url_var:
                self._dl_url_var.set(snapshot['dl_url'])
            if hasattr(self, '_page_jump_var') and self._page_jump_var:
                self._page_jump_var.set(snapshot['page_jump'])
            if hasattr(self, '_conc_var') and self._conc_var:
                self._conc_var.set(str(snapshot['concurrency']))
            if hasattr(self, '_workers_var') and self._workers_var:
                self._workers_var.set(str(snapshot['max_workers_per_video']))
            if hasattr(self, '_speed_var') and self._speed_var:
                self._speed_var.set(self._speed_label())
            if hasattr(self, '_res_var') and self._res_var:
                self._res_var.set(self._resolution_label())
            if hasattr(self, '_cf_host_var') and self._cf_host_var and snapshot.get('cf_host'):
                self._cf_host_var.set(snapshot['cf_host'])
            if hasattr(self, '_cf_cookie_var') and self._cf_cookie_var:
                self._cf_cookie_var.set(snapshot.get('cf_cookie', ''))
            if hasattr(self, '_cf_ua_var') and self._cf_ua_var:
                self._cf_ua_var.set(snapshot.get('cf_ua', ''))
            self._refresh_cf_status()
            self._set_tab_index(snapshot['tab_idx'])
            if snapshot['tab_idx'] < len(self._tab_keys) and self._tab_keys[snapshot['tab_idx']] == 'settings':
                self._switch_settings_cat(snapshot.get('settings_cat', 'general'))
            self._update_selection_count()
            self._rebuild_sidebar()
            self._load_categories()
        finally:
            self._rebuilding = False
        self._refresh_downloads(schedule=False)

    def _build_ui(self):
        # ── Outer window shell with subtle light-grey boundary outline ───────────
        is_zoomed = (self.state() == 'zoomed')
        self._window_shell = ctk.CTkFrame(
            self, fg_color=BG_DARK,
            corner_radius=0 if is_zoomed else 8,
            border_width=0 if is_zoomed else 1,
            border_color=('#c4c4cc', '#585868')
        )
        self._window_shell.pack(fill='both', expand=True)

        # ── Header bar ──────────────────────────────────────────────
        header = ctk.CTkFrame(self._window_shell, height=50, fg_color=BG_HEADER, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)

        # Brand Logo (Software Logo Icon + Fetch + JAV Brand Color Gradient)
        brand = ctk.CTkFrame(header, fg_color='transparent')
        brand.pack(side='left', padx=16, fill='y')

        self._brand_logo_lbl = None
        logo_png_p = _resolve_resource_path(os.path.join('img', 'logo_only.png'))
        if not os.path.exists(logo_png_p):
            logo_png_p = _resolve_resource_path('logo.png')
        if not os.path.exists(logo_png_p):
            logo_png_p = _resolve_resource_path(os.path.join('img', 'logo.png'))
        if not os.path.exists(logo_png_p):
            logo_png_p = _resolve_resource_path(os.path.join('img', 'favicon-256x256.png'))

        if os.path.exists(logo_png_p):
            try:
                logo_pil = Image.open(logo_png_p).rotate(90, expand=True)
                self._brand_logo_img = ctk.CTkImage(
                    light_image=logo_pil,
                    dark_image=logo_pil,
                    size=(22, 22)
                )
                self._brand_logo_lbl = ctk.CTkLabel(brand, image=self._brand_logo_img, text='')
                self._brand_logo_lbl.pack(side='left', padx=(0, 6))
            except Exception:
                pass

        self._brand_lbl_fetch = ctk.CTkLabel(brand, text='Fetch',
                                             font=(ui_font(), 17, 'bold'),
                                             text_color=TEXT_PRI)
        self._brand_lbl_fetch.pack(side='left')

        # Gradient JAV Brand Logo Label
        img_dir_j = _resolve_resource_path('img')
        jav_light_p = os.path.join(img_dir_j, 'jav_gradient_light.png')
        jav_dark_p = os.path.join(img_dir_j, 'jav_gradient_dark.png')

        if os.path.exists(jav_light_p) and os.path.exists(jav_dark_p):
            jav_light_img = Image.open(jav_light_p)
            jav_dark_img = Image.open(jav_dark_p)
            self._jav_ctk_img = ctk.CTkImage(
                light_image=jav_light_img,
                dark_image=jav_dark_img,
                size=(32, 17)
            )
            self._brand_lbl_jav = ctk.CTkLabel(brand, image=self._jav_ctk_img, text='')
        else:
            self._brand_lbl_jav = ctk.CTkLabel(brand, text='JAV',
                                               font=(ui_font(), 17, 'bold'),
                                               text_color=ACCENT)
        self._brand_lbl_jav.pack(side='left', padx=(1, 0))

        self._brand_lbl = ctk.CTkLabel(brand, text='',
                                       font=(ui_font(), 14, 'bold'),
                                       text_color=ACCENT)
        self._brand_lbl.pack(side='left', padx=(4, 0))

        # Clicking any part of the logo navigates to the Browse (home) tab.
        # If already on browse but in preview mode, switch back to grid view.
        def _go_home(e=None):
            self._select_tab('browse')
            if getattr(self, '_browse_mode', 'grid') != 'grid':
                self._set_browse_mode('grid')
        for _logo_widget in filter(None, (brand, self._brand_logo_lbl, self._brand_lbl_fetch, self._brand_lbl_jav, self._brand_lbl)):
            _logo_widget.bind('<Button-1>', _go_home)
            _logo_widget.configure(cursor='hand2')

        # Center Navigation Tabs (Explore, Download, Settings)
        self._tab_keys = ['browse', 'download', 'settings']
        tab_labels = {'browse': T('tab_browse'), 'download': T('tab_download'), 'settings': T('tab_settings')}

        # Load list select icon
        self._list_select_icon = None
        img_dir_ls = _resolve_resource_path('img')
        ls_p = os.path.join(img_dir_ls, 'icon_list_select.png')
        try:
            if os.path.exists(ls_p):
                ls_img = Image.open(ls_p)
                self._list_select_icon = ctk.CTkImage(light_image=ls_img, dark_image=ls_img, size=(22, 22))
        except Exception:
            pass

        # Load search icon
        self._search_icon = None
        img_dir_s = _resolve_resource_path('img')
        search_light_p = os.path.join(img_dir_s, 'icon_sub_search_light.png')
        search_dark_p = os.path.join(img_dir_s, 'icon_sub_search_dark.png')
        search_p = os.path.join(img_dir_s, 'icon_search.png')
        try:
            if os.path.exists(search_light_p) and os.path.exists(search_dark_p):
                self._search_icon = ctk.CTkImage(
                    light_image=Image.open(search_light_p),
                    dark_image=Image.open(search_dark_p),
                    size=(18, 18)
                )
            elif os.path.exists(search_p):
                search_img = Image.open(search_p)
                self._search_icon = ctk.CTkImage(light_image=search_img, dark_image=search_img, size=(18, 18))
        except Exception:
            pass

        # Load compass icon (Search From All toggle; light/dark + off/on + idle/hover variants)
        self._compass_icon = None
        self._compass_icon_hover = None
        self._compass_icon_active = None
        self._compass_icon_active_hover = None
        img_dir_c = _resolve_resource_path('img')
        comp_light_p = os.path.join(img_dir_c, 'icon_compass_light.png')
        comp_dark_p = os.path.join(img_dir_c, 'icon_compass_dark.png')
        comp_hover_light_p = os.path.join(img_dir_c, 'icon_compass_hover_light.png')
        comp_hover_dark_p = os.path.join(img_dir_c, 'icon_compass_hover_dark.png')
        comp_on_light_p = os.path.join(img_dir_c, 'icon_compass_on_light.png')
        comp_on_dark_p = os.path.join(img_dir_c, 'icon_compass_on_dark.png')
        comp_on_hov_light_p = os.path.join(img_dir_c, 'icon_compass_on_hover_light.png')
        comp_on_hov_dark_p = os.path.join(img_dir_c, 'icon_compass_on_hover_dark.png')
        try:
            if os.path.exists(comp_light_p) and os.path.exists(comp_dark_p):
                self._compass_icon = ctk.CTkImage(
                    light_image=Image.open(comp_light_p),
                    dark_image=Image.open(comp_dark_p),
                    size=(20, 20))
            if os.path.exists(comp_hover_light_p) and os.path.exists(comp_hover_dark_p):
                self._compass_icon_hover = ctk.CTkImage(
                    light_image=Image.open(comp_hover_light_p),
                    dark_image=Image.open(comp_hover_dark_p),
                    size=(20, 20))
            elif self._compass_icon:
                self._compass_icon_hover = self._compass_icon

            if os.path.exists(comp_on_light_p) and os.path.exists(comp_on_dark_p):
                self._compass_icon_active = ctk.CTkImage(
                    light_image=Image.open(comp_on_light_p),
                    dark_image=Image.open(comp_on_dark_p),
                    size=(20, 20))
            if os.path.exists(comp_on_hov_light_p) and os.path.exists(comp_on_hov_dark_p):
                self._compass_icon_active_hover = ctk.CTkImage(
                    light_image=Image.open(comp_on_hov_light_p),
                    dark_image=Image.open(comp_on_hov_dark_p),
                    size=(20, 20))
            elif self._compass_icon_active:
                self._compass_icon_active_hover = self._compass_icon_active
        except Exception:
            pass

        # Load theme bulb icon (OFF for Dark Mode, ON for Light Mode)
        self._theme_icon = None
        img_dir_t = _resolve_resource_path('img')
        bulb_on_p = os.path.join(img_dir_t, 'icon_bulb_on.png')
        bulb_off_p = os.path.join(img_dir_t, 'icon_bulb_off.png')
        try:
            if os.path.exists(bulb_on_p) and os.path.exists(bulb_off_p):
                b_on_img = Image.open(bulb_on_p)
                b_off_img = Image.open(bulb_off_p)
                self._theme_icon = ctk.CTkImage(light_image=b_on_img, dark_image=b_off_img, size=(16, 16))
        except Exception:
            pass

        # Load refresh icon (light & dark variants: dull default and bright hover)
        self._refresh_icon = None
        self._refresh_icon_hover = None
        ref_light_p = os.path.join(img_dir_t, 'icon_refresh_light.png')
        ref_dark_p = os.path.join(img_dir_t, 'icon_refresh_dark.png')
        ref_hover_light_p = os.path.join(img_dir_t, 'icon_refresh_hover_light.png')
        ref_hover_dark_p = os.path.join(img_dir_t, 'icon_refresh_hover_dark.png')
        try:
            if os.path.exists(ref_light_p) and os.path.exists(ref_dark_p):
                r_light = Image.open(ref_light_p)
                r_dark = Image.open(ref_dark_p)
                self._refresh_icon = ctk.CTkImage(light_image=r_light, dark_image=r_dark, size=(16, 16))
            if os.path.exists(ref_hover_light_p) and os.path.exists(ref_hover_dark_p):
                rh_light = Image.open(ref_hover_light_p)
                rh_dark = Image.open(ref_hover_dark_p)
                self._refresh_icon_hover = ctk.CTkImage(light_image=rh_light, dark_image=rh_dark, size=(16, 16))
            elif self._refresh_icon:
                self._refresh_icon_hover = self._refresh_icon
        except Exception:
            pass

        # Load tab icons (Sleek, refined size for Explore, Download, Settings)
        self._nav_icons = {}
        img_dir = _resolve_resource_path('img')
        for key in self._tab_keys:
            fname = 'explore' if key == 'browse' else key
            act_p = os.path.join(img_dir, f'icon_{fname}_active.png')
            inact_p = os.path.join(img_dir, f'icon_{fname}_inactive.png')
            try:
                if os.path.exists(act_p) and os.path.exists(inact_p):
                    act_img = Image.open(act_p)
                    inact_img = Image.open(inact_p)
                    self._nav_icons[key] = {
                        'active': ctk.CTkImage(light_image=act_img, dark_image=act_img, size=(18, 18)),
                        'inactive': ctk.CTkImage(light_image=inact_img, dark_image=inact_img, size=(18, 18))
                    }
            except Exception:
                pass

        tab_nav = ctk.CTkFrame(header, fg_color='transparent')
        tab_nav.place(relx=0.5, rely=0.5, anchor='center')
        self._tab_nav_frame = tab_nav

        self._tab_buttons = {}
        for idx, key in enumerate(self._tab_keys):
            icon_obj = self._nav_icons.get(key, {}).get('inactive') if getattr(self, '_nav_icons', None) else None

            btn = ctk.CTkButton(
                tab_nav, text=f" {tab_labels[key]}",
                image=icon_obj, compound='left',
                fg_color='transparent', hover=False,
                text_color=TEXT_SEC, font=(ui_font(), 13, 'bold'),
                cursor='hand2', height=36, corner_radius=0,
                command=lambda k=key: (self._select_tab(k), self._set_browse_mode('grid')) if k == 'browse' else self._select_tab(k)
            )
            btn.pack(side='left', padx=0, fill='y')

            def _make_hover(b, k):
                def _on_enter(e):
                    if self._tab_keys[self._active_tab_idx] != k:
                        try:
                            b.configure(text_color=TEXT_PRI)
                        except Exception:
                            pass
                def _on_leave(e):
                    if self._tab_keys[self._active_tab_idx] != k:
                        try:
                            b.configure(text_color=TEXT_SEC)
                        except Exception:
                            pass
                b.bind('<Enter>', _on_enter)
                b.bind('<Leave>', _on_leave)

            _make_hover(btn, key)
            self._tab_buttons[key] = {'btn': btn}

        # Right info container flush on the right side of header line
        right_info = ctk.CTkFrame(header, fg_color='transparent')
        right_info.pack(side='right', padx=16, fill='y')
        self._right_info_frame = right_info

        # ── Frameless window controls (minimize / maximize / close) ─────────
        # Packed first with side='right' so they land at the far right edge
        # (close first => rightmost, matching the standard Windows order).
        self._win_btn_close = ctk.CTkButton(
            right_info, text='✕', width=36, height=36,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=0,
            hover_color=ERROR_DIM, text_color=TEXT_SEC,
            font=(ui_font(), 13, 'bold'), cursor='hand2',
            command=self._win_close)
        self._win_btn_close.pack(side='right', padx=(8, 0), pady=7)
        self._win_btn_close.bind('<Enter>', lambda e: self._win_btn_close.configure(text_color=ERROR_C), add='+')
        self._win_btn_close.bind('<Leave>', lambda e: self._win_btn_close.configure(text_color=TEXT_SEC), add='+')

        self._win_btn_max = ctk.CTkButton(
            right_info, text='□', width=36, height=36,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=0,
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=(ui_font(), 13, 'bold'), cursor='hand2',
            command=self._win_toggle_maximize)
        self._win_btn_max.pack(side='right', padx=(8, 0), pady=7)
        self._win_btn_max.bind('<Enter>', lambda e: self._win_btn_max.configure(text_color=WHITE), add='+')
        self._win_btn_max.bind('<Leave>', lambda e: self._win_btn_max.configure(text_color=TEXT_SEC), add='+')

        self._win_btn_min = ctk.CTkButton(
            right_info, text='─', width=36, height=36,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=0,
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=(ui_font(), 13, 'bold'), cursor='hand2',
            command=self._win_minimize)
        self._win_btn_min.pack(side='right', padx=(8, 0), pady=7)
        self._win_btn_min.bind('<Enter>', lambda e: self._win_btn_min.configure(text_color=WHITE), add='+')
        self._win_btn_min.bind('<Leave>', lambda e: self._win_btn_min.configure(text_color=TEXT_SEC), add='+')

        # Drag-to-move + double-click-to-maximize on the empty header areas.
        def _start_win_drag(event):
            if self.state() == 'zoomed':
                return
            try:
                self._win_drag_x = event.x_root - self.winfo_x()
                self._win_drag_y = event.y_root - self.winfo_y()
            except Exception:
                pass

        def _do_win_drag(event):
            if self.state() == 'zoomed':
                return
            try:
                self.geometry(
                    f'+{event.x_root - self._win_drag_x}'
                    f'+{event.y_root - self._win_drag_y}')
            except Exception:
                pass

        for _drag_host in (header, right_info):
            _drag_host.bind('<Button-1>', _start_win_drag, add='+')
            _drag_host.bind('<B1-Motion>', _do_win_drag, add='+')
            _drag_host.bind('<Double-Button-1>',
                            lambda e: self._win_toggle_maximize(), add='+')

        ref_icon_obj = getattr(self, '_refresh_icon', None)
        ref_hover_icon_obj = getattr(self, '_refresh_icon_hover', None)
        self._refresh_btn = ctk.CTkButton(
            right_info, text="" if ref_icon_obj else "↻",
            image=ref_icon_obj,
            width=36, height=36,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=0,
            hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 13, 'bold'),
            cursor='hand2',
            command=self._on_refresh_page)
        self._refresh_btn.pack(side='right', padx=(8, 0), pady=7)

        def _on_ref_enter(e=None):
            try:
                if ref_hover_icon_obj:
                    self._refresh_btn.configure(image=ref_hover_icon_obj)
                self._refresh_btn.configure(text_color=TEXT_PRI)
            except Exception:
                pass

        def _on_ref_leave(e=None):
            try:
                if ref_icon_obj:
                    self._refresh_btn.configure(image=ref_icon_obj)
                self._refresh_btn.configure(text_color=TEXT_SEC)
            except Exception:
                pass

        self._refresh_btn.bind('<Enter>', _on_ref_enter, add='+')
        self._refresh_btn.bind('<Leave>', _on_ref_leave, add='+')

        version_box = ctk.CTkFrame(
            right_info, fg_color='transparent')
        version_box.pack(side='right', padx=(0, 8), pady=7)
        self._update_badge = ctk.CTkLabel(
            version_box, text=T('update_new_badge'),
            font=(ui_font(), 10, 'bold'), text_color=ACCENT)
        try:
            self._update_badge.configure(cursor='hand2')
        except Exception:
            pass
        self._update_badge.bind('<Button-1>', self._show_update_settings)

        # Header separator
        ctk.CTkFrame(self._window_shell, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')



        # ── Inline Compact Status & Navigation Bar (Docked to bottom) ──────────────────
        self._status_bar = ctk.CTkFrame(self._window_shell, height=32, fg_color=BG_HEADER, corner_radius=0)
        self._status_bar.pack(side='bottom', fill='x')
        self._status_bar.pack_propagate(False)
        self._status_bar_sep = ctk.CTkFrame(self._window_shell, height=1, fg_color=BORDER, corner_radius=0)
        self._status_bar_sep.pack(side='bottom', fill='x')

        self._status_lbl = ctk.CTkLabel(self._status_bar, text=T('status_ready'),
                                         font=('Consolas', 10),
                                         text_color=TEXT_SEC)
        self._status_lbl.pack(side='left', padx=16)

        # Inline page navigation container (packed on right side of status bar)
        self._page_nav_box = ctk.CTkFrame(self._status_bar, fg_color='transparent')
        self._page_nav_box.pack(side='right', padx=12)

        self._b_first = ctk.CTkButton(self._page_nav_box, text=T('first_page'), width=44, height=24,
                                fg_color='transparent', border_width=0, hover=False,
                                text_color=TEXT_SEC, font=(ui_font(), 10),
                                command=lambda: self._goto_page(1))
        self._b_first.pack(side='left', padx=1)
        b_first = self._b_first

        self._b_prev = ctk.CTkButton(self._page_nav_box, text=T('prev_page'), width=50, height=24,
                               fg_color='transparent', border_width=0, hover=False,
                               text_color=TEXT_SEC, font=(ui_font(), 10),
                               command=lambda: self._goto_page(self._page - 1))
        self._b_prev.pack(side='left', padx=1)
        b_prev = self._b_prev

        self._page_lbl = ctk.CTkLabel(self._page_nav_box, text=T('page_n', n=1), text_color=TEXT_PRI,
                                       font=(ui_font(), 10, 'bold'),
                                       width=54)
        self._page_lbl.pack(side='left', padx=4)

        self._b_next = ctk.CTkButton(self._page_nav_box, text=T('next_page'), width=50, height=24,
                               fg_color='transparent', border_width=0, hover=False,
                               text_color=ACCENT, font=(ui_font(), 10, 'bold'),
                               command=lambda: self._goto_page(self._page + 1))
        self._b_next.pack(side='left', padx=1)
        b_next = self._b_next

        # Hover text highlights for clean text-only navigation buttons
        for btn, default_col in [(b_first, TEXT_SEC), (b_prev, TEXT_SEC), (b_next, ACCENT)]:
            def _bind_btn_hover(b, dc):
                b.bind('<Enter>', lambda e: b.configure(text_color=WHITE))
                b.bind('<Leave>', lambda e: b.configure(text_color=dc))
            _bind_btn_hover(btn, default_col)

        # Underlined page jump input line
        ctk.CTkFrame(self._page_nav_box, width=1, fg_color=BORDER).pack(
            side='left', fill='y', pady=5, padx=6)

        jump_box = ctk.CTkFrame(
            self._page_nav_box, fg_color='transparent',
            border_width=1, border_color=BORDER,
            corner_radius=4, height=24)
        jump_box.pack(side='left', padx=3)

        self._page_jump_var = ctk.StringVar(value='')
        page_entry = ctk.CTkEntry(jump_box, textvariable=self._page_jump_var,
                                   width=32, height=18, corner_radius=0,
                                   fg_color='transparent', border_width=0,
                                   text_color=TEXT_PRI, font=(ui_font(), 10, 'bold'),
                                   placeholder_text='#', justify='center')
        page_entry.pack(side='top', pady=(2, 0), padx=2)
        page_entry.bind('<Return>', lambda e: self._jump_to_page())

        underline = ctk.CTkFrame(jump_box, height=2, width=32, corner_radius=0, fg_color=ACCENT)
        underline.pack(fill='x', side='bottom', pady=(0, 1))

        b_go = ctk.CTkButton(self._page_nav_box, text=T('go_btn'), width=30, height=24,
                             fg_color='transparent', border_width=0, hover=False,
                             text_color=TEXT_SEC, font=(ui_font(), 10, 'bold'),
                             command=self._jump_to_page)
        b_go.pack(side='left', padx=1)
        b_go.bind('<Enter>', lambda e: b_go.configure(text_color=WHITE))
        b_go.bind('<Leave>', lambda e: b_go.configure(text_color=TEXT_SEC))

        # Content container holding the 3 tab frames (expands between header and status bar)
        self._tab_container = ctk.CTkFrame(self._window_shell, fg_color=BG_DARK, corner_radius=0)
        self._tab_container.pack(fill='both', expand=True)
        self._tab_frames = {}
        for key in self._tab_keys:
            self._tab_frames[key] = ctk.CTkFrame(
                self._tab_container, fg_color=BG_DARK, corner_radius=0)

        self._build_browse_tab()
        self._build_download_tab()
        self._build_settings_tab()

        self._select_tab(self._tab_keys[self._active_tab_idx])

    # ── Browse Tab ───────────────────────────────────────────────────
    def _build_browse_tab(self):
        tab = self._tab_frames['browse']

        # ── Workspace toolbar (adaptive 1-row / 2-row layout) ───────────────
        self._top_toolbar_shell = ctk.CTkFrame(tab, fg_color=BG_SECTION, corner_radius=0)
        self._top_toolbar_shell.pack(fill='x')

        self._top_toolbar_row1 = ctk.CTkFrame(self._top_toolbar_shell, fg_color='transparent')
        self._top_toolbar_row1.pack(fill='x', padx=12, pady=(6, 6))

        self._top_toolbar_row2 = ctk.CTkFrame(self._top_toolbar_shell, fg_color='transparent')

        active_sites = [k for k in SITES.keys() if k not in getattr(self, '_inactive_sites', set())]
        if not active_sites:
            active_sites = list(SITES.keys())
        if self._site_key not in active_sites:
            self._site_key = active_sites[0]
        self._site_var = ctk.StringVar(value=self._site_key)
        self._site_menu = SiteSelectorBar(
            self._top_toolbar_row1, sites=active_sites, selected=self._site_key,
            command=self._on_site_change)
        self._site_menu.pack(side='left')

        self._cat_var = ctk.StringVar(value=T('loading_browse'))
        self._cat_menu = ctk.CTkOptionMenu(
            self._top_toolbar_row1, values=[T('loading_browse')], variable=self._cat_var,
            command=self._on_cat_change, width=165, height=36,
            fg_color=BG_CARD, button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE, corner_radius=CONTROL_RADIUS,
            dynamic_resizing=False,
            font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11))
        self._cat_menu.pack(side='left', padx=(8, 0))

        search_box = ctk.CTkFrame(
            self._top_toolbar_row1, fg_color=BG_INPUT, border_color=BORDER,
            border_width=1, corner_radius=CONTROL_RADIUS, height=36)
        search_box.pack(side='left', fill='x', expand=True, padx=(8, 8))
        search_box.pack_propagate(False)

        icon_search_obj = getattr(self, '_search_icon', None)
        if icon_search_obj:
            icon_lbl = ctk.CTkLabel(search_box, text="", image=icon_search_obj, width=28)
            icon_lbl.pack(side='right', padx=(2, 8))
            icon_lbl.bind('<Button-1>', lambda e: self._on_search())
            try:
                icon_lbl.configure(cursor='hand2')
            except Exception:
                pass
        else:
            icon_lbl = ctk.CTkLabel(search_box, text="🔍", text_color=TEXT_SEC)
            icon_lbl.pack(side='right', padx=(2, 8))

        # Compass toggle — Search From All (dull by default, brightened on hover)
        compass_obj = getattr(self, '_compass_icon', None)
        self._compass_lbl = None
        self._compass_hovered = False
        if compass_obj is not None:
            compass_lbl = ctk.CTkLabel(search_box, text="", image=compass_obj,
                                       width=28, height=28)
            compass_lbl.pack(side='right', padx=(0, 2))
            compass_lbl.bind('<Button-1>', lambda e: self._toggle_search_all())
            try:
                compass_lbl.configure(cursor='hand2')
            except Exception:
                pass
            self._compass_lbl = compass_lbl

            def _on_comp_enter(e):
                self._compass_hovered = True
                self._update_search_all_indicator()

            def _on_comp_leave(e):
                self._compass_hovered = False
                self._update_search_all_indicator()

            compass_lbl.bind('<Enter>', _on_comp_enter)
            compass_lbl.bind('<Leave>', _on_comp_leave)

            ToolTip(compass_lbl, lambda: (
                T('search_all_tip_on') if self._search_all_mode else T('search_all_tip_off')))
        self._update_search_all_indicator()

        self._search_entry = ctk.CTkEntry(
            search_box,
            placeholder_text=T('search_placeholder'),
            placeholder_text_color=('#B0AAA5', '#585350'),
            height=34, fg_color='transparent', border_width=0,
            text_color=TEXT_PRI, font=(ui_font(), 11))
        self._search_entry.pack(side='left', fill='both', expand=True, padx=(10, 4))
        self._search_entry.bind('<Return>', lambda e: self._on_search())

        # Container for right-side action buttons
        self._toolbar_actions = ctk.CTkFrame(self._top_toolbar_row1, fg_color='transparent')
        self._toolbar_actions.pack(side='right')

        def _on_select_option_change(choice):
            if choice == T('select_all_btn') or 'Select' in choice or '全' in choice:
                self._select_all_on_page()
            elif choice in {T('unselect_all_btn'), 'Unselect All', '取消全選', '取消全选', '全選択解除'}:
                self._clear_selection_in_place()

        self._select_menu_var = ctk.StringVar(value=T('select_all_btn'))
        self._select_menu = ctk.CTkOptionMenu(
            self._toolbar_actions,
            values=[T('select_all_btn'), T('unselect_all_btn')],
            variable=self._select_menu_var,
            command=_on_select_option_change,
            width=115, height=36, corner_radius=CONTROL_RADIUS,
            fg_color=BG_CARD, button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE, dynamic_resizing=False,
            font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11))
        self._select_menu.pack(side='left', padx=(0, 6))

        self._add_q_btn = ctk.CTkButton(
            self._toolbar_actions, text=T('add_to_queue'), command=self._add_selected_to_queue,
            width=104, height=36, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, font=(ui_font(), 11))
        self._add_q_btn.pack(side='left', padx=(0, 6))

        self._dl_selected_btn = ctk.CTkButton(
            self._toolbar_actions, text=T('download_selected'), command=self._download_selected,
            width=138, height=36, corner_radius=CONTROL_RADIUS,
            fg_color=('#FDE8EC', '#2B161B'),
            border_width=1, border_color=ACCENT,
            hover_color=('#FAD2DB', '#3F1F26'),
            text_color=ACCENT, font=(ui_font(), 11, 'bold'))
        self._dl_selected_btn.pack(side='left')

        self._toolbar_layout_mode = 'wide'

        # ── Content area: sidebar + grid ────────────────────────────
        content = ctk.CTkFrame(tab, fg_color=BG_DARK, corner_radius=0)
        content.pack(fill='both', expand=True)

        # Sidebar
        self._sidebar = ctk.CTkScrollableFrame(
            content, width=190, fg_color=BG_SIDEBAR,
            corner_radius=0, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        self._sidebar.pack(side='left', fill='y')

        # Main workspace: browse grid and preview detail screen swap in-place.
        self._browse_workspace = ctk.CTkFrame(
            content, fg_color=BG_DARK, corner_radius=0)
        self._browse_workspace.pack(side='left', fill='both', expand=True)

        self._browse_grid_area = ctk.CTkFrame(
            self._browse_workspace, fg_color=BG_DARK, corner_radius=0)
        self._browse_grid_area.pack(fill='both', expand=True)

        # Entity page heading banner (actress / director / studio / tag).
        # Shown only while browsing a filtered entity page (all of someone's work).
        self._page_heading = ctk.CTkFrame(
            self._browse_grid_area, fg_color=BG_CARD, corner_radius=0,
            border_width=0)
        self._page_heading_lbl = ctk.CTkLabel(
            self._page_heading, text='', text_color=ACCENT,
            font=(ui_font(), 13, 'bold'), anchor='e')
        self._page_heading_lbl.pack(side='right', padx=16, pady=8)
        self._page_heading_close = ctk.CTkButton(
            self._page_heading, text=T('entity_close'), width=64, height=24,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            font=(ui_font(), 10), corner_radius=CONTROL_RADIUS,
            command=self._close_entity_page)
        self._page_heading_close.pack(side='left', padx=12, pady=6)

        self._grid_scroll = ctk.CTkScrollableFrame(
            self._browse_grid_area, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        self._grid_scroll.pack(fill='both', expand=True)

        self._preview_area = ctk.CTkFrame(
            self._browse_workspace, fg_color=BG_DARK, corner_radius=0)

        self._rebuild_sidebar()

    def _sync_page_nav_visibility(self):
        page_nav = getattr(self, '_page_nav_box', None)
        if not page_nav:
            return
        try:
            active_key = self._tab_keys[self._active_tab_idx]
        except Exception:
            active_key = ''
        show = active_key == 'browse' and getattr(self, '_browse_mode', 'grid') == 'grid'
        try:
            if show:
                page_nav.pack(side='right', padx=12)
            else:
                page_nav.pack_forget()
        except tk.TclError:
            pass

    def _set_browse_mode(self, mode: str):
        mode = 'preview' if mode == 'preview' else 'grid'
        self._browse_mode = mode
        grid_area = getattr(self, '_browse_grid_area', None)
        preview_area = getattr(self, '_preview_area', None)
        sidebar = getattr(self, '_sidebar', None)
        workspace = getattr(self, '_browse_workspace', None)
        status_bar = getattr(self, '_status_bar', None)
        status_sep = getattr(self, '_status_bar_sep', None)
        if not grid_area or not preview_area:
            return
        try:
            if mode == 'preview':
                if sidebar:
                    sidebar.pack_forget()
                if status_sep:
                    status_sep.pack_forget()
                if status_bar:
                    status_bar.pack_forget()
                grid_area.pack_forget()
                preview_area.pack(fill='both', expand=True)
            else:
                self._preview_stack = []
                self._stop_preview_player()
                preview_area.pack_forget()
                if sidebar and workspace:
                    sidebar.pack(side='left', fill='y', before=workspace)
                if status_bar:
                    status_bar.pack(side='bottom', fill='x')
                if status_sep:
                    status_sep.pack(side='bottom', fill='x')
                grid_area.pack(fill='both', expand=True)
        except tk.TclError:
            return
        self._sync_page_nav_visibility()

    def _stop_preview_player(self):
        fs_win = getattr(self, '_fs_win', None)
        if fs_win:
            try:
                fs_win.destroy()
            except Exception:
                pass
            self._fs_win = None
            self._fs_canvas = None
            self._fs_prev_controls = None

        timer = getattr(self, '_player_timer_id', None)
        if timer:
            try:
                self.after_cancel(timer)
            except Exception:
                pass
            self._player_timer_id = None

        player = getattr(self, '_preview_player', None)
        if player:
            try:
                player.stop()
                player.release()
            except Exception:
                pass
            self._preview_player = None

        vlc_inst = getattr(self, '_vlc_instance', None)
        if vlc_inst:
            try:
                vlc_inst.release()
            except Exception:
                pass
            self._vlc_instance = None

        proxy = getattr(self, '_preview_proxy', None)
        if proxy:
            try:
                proxy.stop()
            except Exception:
                pass
            self._preview_proxy = None

        sub_mgr = getattr(self, '_subtitle_mgr', None)
        if sub_mgr:
            try:
                sub_mgr.set_active_track(None, None)
            except Exception:
                pass
            self._subtitle_mgr = None

    @staticmethod
    def _format_duration_ms(ms: int) -> str:
        if not ms or ms < 0:
            return '00:00'
        total_sec = int(ms / 1000)
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        if h > 0:
            return f'{h}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'

    def _create_vlc_player_on_canvas(self, canvas, proxied_url: str):
        """Create a fresh VLC player bound to `canvas`. Returns the player or None."""
        try:
            _setup_vlc_environment()
            import vlc
        except Exception:
            return None
        vlc_args = [
            '--quiet',
            '--no-xlib',
            '--avcodec-hw=any',
            '--network-caching=500',
            '--live-caching=500',
            '--file-caching=400',
            '--http-reconnect',
            '--clock-jitter=0',
            '--clock-synchro=0',
            '--avcodec-fast',
            '--avcodec-threads=4',
            '--avcodec-skiploopfilter=1',
            '--drop-late-frames',
            '--skip-frames',
            '--no-video-title-show',
        ]
        instance = vlc.Instance(*vlc_args)
        player = instance.media_player_new()
        media = instance.media_new(proxied_url)
        media.add_option(':http-reconnect=true')
        media.add_option(':network-caching=500')
        media.add_option(':live-caching=500')
        media.add_option(':file-caching=400')
        media.add_option(':clock-jitter=0')
        media.add_option(':clock-synchro=0')
        player.set_media(media)

        canvas.update()
        if sys.platform == 'win32':
            player.set_hwnd(canvas.winfo_id())
        elif sys.platform == 'darwin':
            player.set_nsobject(canvas.winfo_id())
        else:
            player.set_xwindow(canvas.winfo_id())

        self._vlc_instance = instance
        self._preview_player = player
        return player

    def _show_preview_player_fallback(self, canvas, player_container, source):
        """Render a clean fallback card when embedded VLC is unavailable on the system."""
        try:
            for child in canvas.winfo_children():
                child.destroy()
        except Exception:
            pass

        card = ctk.CTkFrame(
            canvas, fg_color=BG_CARD, corner_radius=12,
            border_width=1, border_color=BORDER_CARD, width=440, height=260)
        card.place(relx=0.5, rely=0.5, anchor='center')
        card.pack_propagate(False)

        icon_lbl = ctk.CTkLabel(
            card, text="🎬", font=(ui_font(), 30), text_color=ACCENT)
        icon_lbl.pack(pady=(16, 4))

        title_lbl = ctk.CTkLabel(
            card, text=T('preview_vlc_missing_title'),
            font=(ui_font(), 13, 'bold'), text_color=TEXT_PRI)
        title_lbl.pack(pady=(0, 4))

        desc_lbl = ctk.CTkLabel(
            card,
            text=T('preview_vlc_missing_desc'),
            font=(ui_font(), 10), text_color=TEXT_SEC, justify='center', wraplength=380)
        desc_lbl.pack(pady=(0, 14))

        btn_row = ctk.CTkFrame(card, fg_color='transparent')
        btn_row.pack()

        target_url = getattr(source, 'page_url', '') or getattr(self, '_preview_proxied_url', '') or getattr(source, 'media_url', '')
        if target_url:
            open_btn = ctk.CTkButton(
                btn_row, text=T('preview_open_in_browser'),
                font=(ui_font(), 11, 'bold'), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                text_color=WHITE, corner_radius=6, height=32,
                command=lambda u=target_url: webbrowser.open(u))
            open_btn.pack(side='left', padx=6)

        dl_vlc_btn = ctk.CTkButton(
            btn_row, text=T('preview_download_vlc'),
            font=(ui_font(), 11, 'bold'), fg_color=BG_HEADER, hover_color=BG_CARD_HOVER,
            border_width=1, border_color=BORDER, text_color=TEXT_PRI, corner_radius=6, height=32,
            command=lambda: webbrowser.open('https://www.videolan.org/vlc/download-windows.html'))
        dl_vlc_btn.pack(side='left', padx=6)

    def _init_vlc_player(self, media_url: str, headers: dict, canvas: tk.Canvas):
        try:
            import vlc

            # Stop and release any existing preview player first
            old = getattr(self, '_preview_player', None)
            if old is not None:
                try:
                    old.stop()
                    old.release()
                except Exception:
                    pass
                self._preview_player = None

            if not hasattr(self, '_preview_proxy') or self._preview_proxy is None:
                self._preview_proxy = PreviewProxyServer()
            self._preview_proxy.start()
            token = self._preview_proxy.register(headers)
            proxied = self._preview_proxy.proxied_url(token, media_url)
            self._preview_proxied_url = proxied

            player = self._create_vlc_player_on_canvas(canvas, proxied)
            if player is None:
                return False

            player.play()
            self._start_player_update_loop()
            self._update_cc_button_state()

            # Initialize Subtitle Subsystem asynchronously so it never blocks or delays video startup
            def _init_subtitles_async():
                try:
                    sub_mgr = SubtitleManager()
                    preview_vid = getattr(self, '_preview_video', {}) or {}
                    sub_mgr.load_tracks_for_video(preview_vid, media_path=media_url)
                    self._subtitle_mgr = sub_mgr

                    def _apply_initial_sub():
                        if getattr(self, '_preview_player', None) == player and getattr(self, '_subtitle_mgr', None):
                            if sub_mgr.active_track_id:
                                sub_mgr.set_active_track(sub_mgr.active_track_id, player)
                            self._update_cc_button_state()

                    self.after(0, _apply_initial_sub)
                except Exception:
                    pass

            threading.Thread(target=_init_subtitles_async, daemon=True).start()
            return True
        except Exception as exc:
            return False

    def _rebuild_preview_player(self, canvas, position_ms=None, volume=None, active_track_id=None):
        """Stop the current VLC player and recreate it on `canvas`, restoring playback state."""
        old = getattr(self, '_preview_player', None)
        if old is not None:
            try:
                if position_ms is None:
                    pos = old.get_time()
                    position_ms = pos if pos >= 0 else None
                if volume is None:
                    vol = old.audio_get_volume()
                    volume = vol if vol >= 0 else None
                old.stop()
                old.release()
            except Exception:
                pass
            self._preview_player = None

        proxied = getattr(self, '_preview_proxied_url', None)
        if not proxied:
            return False
        try:
            player = self._create_vlc_player_on_canvas(canvas, proxied)
        except Exception:
            return False
        if player is None:
            return False

        if volume is not None and volume >= 0:
            try:
                player.audio_set_volume(volume)
            except Exception:
                pass

        player.play()
        self._start_player_update_loop()
        self._update_cc_button_state()

        def _after_load():
            if getattr(self, '_preview_player', None) != player:
                return
            try:
                if position_ms and position_ms > 0:
                    length = player.get_length()
                    if length > 0:
                        player.set_time(max(0, min(int(position_ms), length - 1000)))
                    else:
                        self.after(300, _after_load)
                        return
            except Exception:
                pass
            if active_track_id:
                sub_mgr = getattr(self, '_subtitle_mgr', None)
                if sub_mgr:
                    try:
                        sub_mgr.set_active_track(active_track_id, player)
                    except Exception:
                        pass
                self._update_cc_button_state()

        self.after(400, _after_load)
        return True

    def _start_player_update_loop(self):
        if getattr(self, '_player_timer_id', None):
            try:
                self.after_cancel(self._player_timer_id)
            except Exception:
                pass
        self._update_player_ui()

    def _update_player_ui(self):
        player = getattr(self, '_preview_player', None)
        if not player or getattr(self, '_is_closing', False) or getattr(self, '_browse_mode', '') != 'preview':
            return

        try:
            length_ms = player.get_length()
            time_ms = player.get_time()
            is_playing = player.is_playing()

            btn = getattr(self, '_player_play_btn', None)
            if btn:
                btn.configure(text='❚❚' if is_playing else '▶')

            time_lbl = getattr(self, '_player_time_lbl', None)
            if time_lbl:
                t_str = self._format_duration_ms(time_ms)
                d_str = self._format_duration_ms(length_ms) if length_ms > 0 else (self._preview_source.duration if getattr(self, '_preview_source', None) else '00:00')
                time_lbl.configure(text=f'{t_str} / {d_str}')

            slider = getattr(self, '_player_slider', None)
            if slider and length_ms > 0 and not getattr(self, '_is_seeking', False):
                pos = max(0.0, min(1.0, time_ms / length_ms))
                slider.set(pos)
        except Exception:
            pass

        if getattr(self, '_browse_mode', '') == 'preview':
            self._player_timer_id = self.after(500, self._update_player_ui)

    def _toggle_player_play(self):
        player = getattr(self, '_preview_player', None)
        if player:
            if player.is_playing():
                player.pause()
            else:
                player.play()

    def _on_player_slider_press(self, event=None):
        self._is_seeking = True

    def _on_player_slider_drag(self, value):
        self._is_seeking = True
        player = getattr(self, '_preview_player', None)
        if player:
            length_ms = player.get_length()
            if length_ms > 0:
                target_ms = int(float(value) * length_ms)
                time_lbl = getattr(self, '_player_time_lbl', None)
                if time_lbl:
                    t_str = self._format_duration_ms(target_ms)
                    d_str = self._format_duration_ms(length_ms)
                    time_lbl.configure(text=f'{t_str} / {d_str}')

    def _on_player_slider_release(self, event=None):
        slider = getattr(self, '_player_slider', None)
        if slider:
            try:
                self._on_player_seek(slider.get())
            except Exception:
                pass
        self.after(350, lambda: setattr(self, '_is_seeking', False))

    def _on_player_seek(self, value):
        player = getattr(self, '_preview_player', None)
        if player:
            length_ms = player.get_length()
            if length_ms > 0:
                target_ms = int(float(value) * length_ms)
                target_ms = max(0, min(target_ms, max(0, length_ms - 500)))
                player.set_time(target_ms)

    def _on_global_player_key(self, event):
        if getattr(self, '_browse_mode', '') != 'preview':
            return

        # Do not steal key events if focus is inside an entry field or text box
        try:
            focus_w = self.focus_get()
            if focus_w:
                w_type = str(type(focus_w)).lower()
                if 'entry' in w_type or 'text' in w_type or 'spinbox' in w_type:
                    return
        except Exception:
            pass

        keysym = str(getattr(event, 'keysym', '') or '').lower()
        if keysym in ('space', 'k'):
            self._on_player_space()
            return 'break'
        elif keysym in ('right', 'l'):
            self._on_player_right()
            return 'break'
        elif keysym in ('left', 'j'):
            self._on_player_left()
            return 'break'
        elif keysym in ('up', 'volumeup'):
            self._on_player_up()
            return 'break'
        elif keysym in ('down', 'volumedown'):
            self._on_player_down()
            return 'break'
        elif keysym in ('f', 'f11'):
            self._toggle_fullscreen_player()
            return 'break'
        elif keysym == 'escape':
            self._exit_fullscreen_player()
            return 'break'

    def _on_player_space(self, event=None):
        player = getattr(self, '_preview_player', None)
        if player:
            if player.is_playing():
                player.pause()
            else:
                player.play()
            return
        web_frame = getattr(getattr(self, '_player_container_ref', None), '_web_frame', None)
        if web_frame:
            try:
                web_frame.run_js("var v=document.getElementById('player');if(v){v.paused?v.play():v.pause();}")
            except Exception:
                pass

    def _on_player_right(self, event=None):
        player = getattr(self, '_preview_player', None)
        if player:
            length_ms = player.get_length()
            time_ms = player.get_time()
            if time_ms >= 0:
                target_ms = time_ms + 10000
                if length_ms > 0:
                    target_ms = min(target_ms, max(0, length_ms - 500))
                player.set_time(target_ms)
                slider = getattr(self, '_player_slider', None)
                if slider and length_ms > 0:
                    slider.set(max(0.0, min(1.0, target_ms / length_ms)))
            return
        web_frame = getattr(getattr(self, '_player_container_ref', None), '_web_frame', None)
        if web_frame:
            try:
                web_frame.run_js("var v=document.getElementById('player');if(v){v.currentTime+=10;}")
            except Exception:
                pass

    def _on_player_left(self, event=None):
        player = getattr(self, '_preview_player', None)
        if player:
            length_ms = player.get_length()
            time_ms = player.get_time()
            if time_ms >= 0:
                target_ms = max(0, time_ms - 10000)
                player.set_time(target_ms)
                slider = getattr(self, '_player_slider', None)
                if slider and length_ms > 0:
                    slider.set(max(0.0, min(1.0, target_ms / length_ms)))
            return
        web_frame = getattr(getattr(self, '_player_container_ref', None), '_web_frame', None)
        if web_frame:
            try:
                web_frame.run_js("var v=document.getElementById('player');if(v){v.currentTime=Math.max(0,v.currentTime-10);}")
            except Exception:
                pass

    def _on_player_up(self, event=None):
        player = getattr(self, '_preview_player', None)
        if player:
            vol = player.audio_get_volume()
            new_vol = min(100, (vol if vol >= 0 else 50) + 10)
            player.audio_set_volume(new_vol)
            slider = getattr(self, '_player_vol_slider', None)
            if slider:
                slider.set(new_vol / 100.0)
            return
        web_frame = getattr(getattr(self, '_player_container_ref', None), '_web_frame', None)
        if web_frame:
            try:
                web_frame.run_js("var v=document.getElementById('player');if(v){v.volume=Math.min(1.0,v.volume+0.1);}")
            except Exception:
                pass

    def _on_player_down(self, event=None):
        player = getattr(self, '_preview_player', None)
        if player:
            vol = player.audio_get_volume()
            new_vol = max(0, (vol if vol >= 0 else 50) - 10)
            player.audio_set_volume(new_vol)
            slider = getattr(self, '_player_vol_slider', None)
            if slider:
                slider.set(new_vol / 100.0)
            return
        web_frame = getattr(getattr(self, '_player_container_ref', None), '_web_frame', None)
        if web_frame:
            try:
                web_frame.run_js("var v=document.getElementById('player');if(v){v.volume=Math.max(0.0,v.volume-0.1);}")
            except Exception:
                pass

    def _bind_player_keyboard_controls(self, widget):
        def _on_enter(e):
            self._is_mouse_over_player = True

        def _on_leave(e):
            self._is_mouse_over_player = False

        def _on_click(e):
            try:
                widget.focus_set()
            except Exception:
                pass

        try:
            widget.bind('<Enter>', _on_enter, add='+')
            widget.bind('<Leave>', _on_leave, add='+')
            widget.bind('<Button-1>', _on_click, add='+')
            for child in widget.winfo_children():
                try:
                    child.bind('<Enter>', _on_enter, add='+')
                    child.bind('<Leave>', _on_leave, add='+')
                    child.bind('<Button-1>', _on_click, add='+')
                except Exception:
                    pass
        except Exception:
            pass

    def _on_player_volume(self, value):
        player = getattr(self, '_preview_player', None)
        if player:
            vol = int(float(value) * 100)
            player.audio_set_volume(vol)

    # ── FULLSCREEN VIDEO PLAYER ──────────────────────────────────────────────

    def _build_player_controls(self, parent, fullscreen=False):
        controls = ctk.CTkFrame(parent, fg_color='#111115', height=40, corner_radius=0)
        controls.pack(fill='x', side='bottom')

        self._player_play_btn = ctk.CTkButton(
            controls, text='▶', width=36, height=28,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=WHITE, font=(ui_font(), 12, 'bold'),
            command=self._toggle_player_play)
        self._player_play_btn.pack(side='left', padx=(6, 2), pady=4)

        self._player_time_lbl = ctk.CTkLabel(
            controls, text='00:00 / 00:00', text_color=TEXT_DIM,
            font=('Consolas', 11))
        self._player_time_lbl.pack(side='left', padx=6)

        self._player_slider = ctk.CTkSlider(
            controls, from_=0.0, to=1.0, height=14,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            progress_color=ACCENT, fg_color=BORDER,
            command=self._on_player_slider_drag)
        self._player_slider.pack(side='left', fill='x', expand=True, padx=8)
        self._player_slider.bind('<Button-1>', self._on_player_slider_press, add='+')
        self._player_slider.bind('<ButtonRelease-1>', self._on_player_slider_release, add='+')

        ctk.CTkLabel(controls, text='🔊', text_color=TEXT_DIM, font=(ui_font(), 11)).pack(side='left', padx=(4, 0))
        self._player_vol_slider = ctk.CTkSlider(
            controls, from_=0.0, to=1.0, width=70, height=12,
            button_color=TEXT_PRI, progress_color=ACCENT, fg_color=BORDER,
            command=self._on_player_volume)
        self._player_vol_slider.set(0.8)
        self._player_vol_slider.pack(side='left', padx=(4, 6))

        # CC / Subtitle button
        self._player_cc_btn = ctk.CTkButton(
            controls, text='CC', width=42, height=26,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_DIM, border_width=1, border_color=BORDER,
            corner_radius=4, font=(ui_font(), 10, 'bold'),
            command=self._open_subtitle_menu_modal)
        self._player_cc_btn.pack(side='left', padx=(2, 8), pady=4)

        # Fullscreen toggle button
        self._player_fs_btn = ctk.CTkButton(
            controls, text='Exit' if fullscreen else 'Full', width=48, height=26,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, border_width=1, border_color=BORDER,
            corner_radius=4, font=(ui_font(), 10, 'bold'),
            command=self._toggle_fullscreen_player)
        self._player_fs_btn.pack(side='left', padx=(2, 8), pady=4)

        self._sync_player_volume_slider()

    def _sync_player_volume_slider(self):
        player = getattr(self, '_preview_player', None)
        slider = getattr(self, '_player_vol_slider', None)
        if player and slider:
            try:
                vol = player.audio_get_volume()
                if vol >= 0:
                    slider.set(vol / 100.0)
            except Exception:
                pass

    def _toggle_fullscreen_player(self, event=None):
        win = getattr(self, '_fs_win', None)
        if win is not None:
            try:
                if win.winfo_exists():
                    self._exit_fullscreen_player()
                    return
            except tk.TclError:
                pass
            self._fs_win = None
        self._enter_fullscreen_player()

    def _enter_fullscreen_player(self):
        player = getattr(self, '_preview_player', None)
        orig_canvas = getattr(self, '_preview_canvas', None)
        if player is None or orig_canvas is None:
            return
        try:
            if not orig_canvas.winfo_exists():
                return
        except tk.TclError:
            return

        win = None
        try:
            win = ctk.CTkToplevel(self)
            win.title('')
            win.configure(fg_color='#000000')
            win.attributes('-fullscreen', True)
            if getattr(self, '_ico_path') and os.path.exists(self._ico_path):
                try:
                    win.iconbitmap(self._ico_path)
                except Exception:
                    pass
            win.bind('<Escape>', self._exit_fullscreen_player, add='+')
            win.bind('<Double-Button-1>', self._toggle_fullscreen_player, add='+')
            win.protocol('WM_DELETE_WINDOW', self._exit_fullscreen_player)

            canvas = tk.Canvas(win, bg='#000000', highlightthickness=0)
            canvas.pack(fill='both', expand=True)

            self._fs_win = win
            self._fs_canvas = canvas
            self._fs_prev_controls = {
                'play': getattr(self, '_player_play_btn', None),
                'time': getattr(self, '_player_time_lbl', None),
                'slider': getattr(self, '_player_slider', None),
                'vol': getattr(self, '_player_vol_slider', None),
                'cc': getattr(self, '_player_cc_btn', None),
                'fs': getattr(self, '_player_fs_btn', None),
            }
            self._build_player_controls(win, fullscreen=True)

            # Realize the fullscreen window so canvas.winfo_id() is a valid hwnd
            win.update_idletasks()
            win.update()

            sub_mgr = getattr(self, '_subtitle_mgr', None)
            active_track_id = sub_mgr.active_track_id if sub_mgr else None

            # Recreate the player on the fullscreen canvas. A fresh player bound
            # to the new hwnd reliably moves the video output, unlike set_hwnd
            # on an already-running player.
            ok = self._rebuild_preview_player(canvas, active_track_id=active_track_id)
            if not ok:
                try:
                    win.destroy()
                except Exception:
                    pass
                self._fs_win = None
                self._fs_canvas = None
                self._fs_prev_controls = None
                try:
                    orig_canvas.update()
                    self._rebuild_preview_player(orig_canvas, active_track_id=active_track_id)
                except Exception:
                    pass
                return

            self._bind_player_keyboard_controls(win)
            self._bind_player_keyboard_controls(canvas)
            self._update_cc_button_state()
            try:
                canvas.focus_set()
                win.focus_force()
            except Exception:
                pass
        except Exception:
            try:
                if win is not None:
                    win.destroy()
            except Exception:
                pass
            self._fs_win = None
            self._fs_canvas = None
            self._fs_prev_controls = None

    def _exit_fullscreen_player(self, event=None):
        win = getattr(self, '_fs_win', None)
        if win is None:
            return
        try:
            if win.winfo_exists():
                saved = getattr(self, '_fs_prev_controls', None) or {}
                if saved.get('play'):
                    self._player_play_btn = saved['play']
                if saved.get('time'):
                    self._player_time_lbl = saved['time']
                if saved.get('slider'):
                    self._player_slider = saved['slider']
                if saved.get('vol'):
                    self._player_vol_slider = saved['vol']
                if saved.get('cc'):
                    self._player_cc_btn = saved['cc']
                if saved.get('fs'):
                    self._player_fs_btn = saved['fs']
                win.destroy()
        except tk.TclError:
            pass
        except Exception:
            pass
        self._fs_win = None
        self._fs_canvas = None
        self._fs_prev_controls = None

        # Recreate the player on the original embedded canvas
        orig_canvas = getattr(self, '_preview_canvas', None)
        if orig_canvas is not None:
            try:
                if orig_canvas.winfo_exists():
                    orig_canvas.update()
                    sub_mgr = getattr(self, '_subtitle_mgr', None)
                    active_track_id = sub_mgr.active_track_id if sub_mgr else None
                    self._rebuild_preview_player(orig_canvas, active_track_id=active_track_id)
            except tk.TclError:
                pass
            except Exception:
                pass
        self._update_cc_button_state()
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    # ── SUBTITLE SYSTEM INTEGRATION ──────────────────────────────────────────

    def _update_cc_button_state(self):
        btn = getattr(self, '_player_cc_btn', None)
        if not btn:
            return
        sub_mgr = getattr(self, '_subtitle_mgr', None)
        active_track = sub_mgr.get_active_track() if sub_mgr else None
        if active_track:
            lang_tag = active_track.language_code.upper() if active_track.language_code != 'user' else 'FILE'
            btn.configure(
                text=f"CC ({lang_tag})",
                text_color=ACCENT,
                border_color=ACCENT,
                fg_color=BG_CARD_HOVER
            )
        else:
            btn.configure(
                text="CC",
                text_color=TEXT_DIM,
                border_color=BORDER,
                fg_color='transparent'
            )

    def _open_subtitle_menu_modal(self):
        sub_mgr = getattr(self, '_subtitle_mgr', None)
        if not sub_mgr:
            status_lbl = getattr(self, '_status_lbl', None)
            if status_lbl:
                status_lbl.configure(text=T('subtitle_error_unavailable'))
            return

        overlay = ModalOverlay(self, max_width=580, max_height=660)
        # Clicking the backdrop smoothly closes the modal
        if getattr(overlay, '_backdrop', None):
            overlay._backdrop.bind("<Button-1>", lambda e: overlay.close(), add="+")

        def _close_modal():
            try:
                overlay.close()
            except Exception:
                pass

        container = overlay.modal

        # ── In-Popup Header Bar with Title, CC Badge & Close Button ────────
        header_bar = ctk.CTkFrame(
            container, fg_color=BG_CARD, height=48, corner_radius=0
        )
        header_bar.pack(fill='x')
        header_bar.pack_propagate(False)

        # Close button packed on the right FIRST so it is NEVER pushed off by long titles
        close_btn = ctk.CTkButton(
            header_bar, text='✕', width=32, height=32,
            corner_radius=16, fg_color='transparent',
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=(ui_font(), 13, 'bold'),
            command=_close_modal
        )
        close_btn.pack(side='right', padx=10, pady=8)

        header_left = ctk.CTkFrame(header_bar, fg_color='transparent')
        header_left.pack(side='left', fill='both', expand=True, padx=14, pady=8)

        cc_badge = ctk.CTkLabel(
            header_left, text='CC', text_color=WHITE, fg_color=ACCENT,
            corner_radius=4, height=22, width=28,
            font=(ui_font(), 10, 'bold')
        )
        cc_badge.pack(side='left', padx=(0, 8))

        title_lbl = ctk.CTkLabel(
            header_left, text=T('subtitle_title'),
            text_color=TEXT_PRI, font=(ui_font(), 13, 'bold'),
            anchor='w'
        )
        title_lbl.pack(side='left', fill='x', expand=True)

        main_body = ctk.CTkFrame(container, fg_color=BG_DARK, corner_radius=0)
        main_body.pack(fill='both', expand=True, padx=16, pady=(12, 16))

        # ── Inline Tab Bar: Available Subtitles | Search Online | Sync with Audio ──
        tab_bar = ctk.CTkFrame(main_body, fg_color='transparent')
        tab_bar.pack(fill='x', pady=(0, 10))

        tab_btn_row = ctk.CTkFrame(tab_bar, fg_color='transparent')
        tab_btn_row.pack(fill='x')

        active_pane = tk.StringVar(value='tracks')

        def _update_tab_states():
            current = active_pane.get()
            tracks_btn.configure(
                fg_color=BG_CARD_HOVER if current == 'tracks' else 'transparent',
                text_color=TEXT_PRI if current == 'tracks' else TEXT_SEC,
                font=(ui_font(), 11, 'bold' if current == 'tracks' else 'normal')
            )
            search_btn.configure(
                fg_color=BG_CARD_HOVER if current == 'search' else 'transparent',
                text_color=TEXT_PRI if current == 'search' else TEXT_SEC,
                font=(ui_font(), 11, 'bold' if current == 'search' else 'normal')
            )
            sync_btn.configure(
                fg_color=BG_CARD_HOVER if current == 'sync' else 'transparent',
                text_color=TEXT_PRI if current == 'sync' else TEXT_SEC,
                font=(ui_font(), 11, 'bold' if current == 'sync' else 'normal')
            )

        def _show_tracks():
            active_pane.set('tracks')
            _update_tab_states()
            tracks_content.pack(fill='both', expand=True)
            search_content.pack_forget()
            sync_content.pack_forget()

        def _show_search():
            active_pane.set('search')
            _update_tab_states()
            search_content.pack(fill='both', expand=True)
            tracks_content.pack_forget()
            sync_content.pack_forget()

        def _show_sync():
            active_pane.set('sync')
            _update_tab_states()
            try:
                cur_active = sub_mgr.get_active_track()
                if cur_active:
                    sync_track_val_lbl.configure(
                        text=f"✓  {cur_active.name}",
                        text_color=TEXT_PRI
                    )
                else:
                    sync_track_val_lbl.configure(
                        text="⚠  No active track (select one in Available Subtitles)",
                        text_color=WARNING
                    )
                cur_offset = sub_mgr.get_sync_offset_ms()
                offset_var.set(_offset_label_text(cur_offset))
            except Exception:
                pass
            sync_content.pack(fill='both', expand=True)
            tracks_content.pack_forget()
            search_content.pack_forget()

        tracks_btn = ctk.CTkButton(
            tab_btn_row, text='Available Subtitles', height=32,
            corner_radius=CONTROL_RADIUS,
            fg_color=BG_CARD_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, font=(ui_font(), 11, 'bold'),
            command=_show_tracks)
        tracks_btn.pack(side='left', fill='x', expand=True, padx=(0, 2))

        search_btn = ctk.CTkButton(
            tab_btn_row, text='Search Online', height=32,
            corner_radius=CONTROL_RADIUS,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 11),
            command=_show_search)
        search_btn.pack(side='left', fill='x', expand=True, padx=2)

        sync_btn = ctk.CTkButton(
            tab_btn_row, text='Sync with Audio', height=32,
            corner_radius=CONTROL_RADIUS,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 11),
            command=_show_sync)
        sync_btn.pack(side='left', fill='x', expand=True, padx=(2, 0))

        ctk.CTkFrame(tab_bar, height=1, fg_color=BORDER).pack(fill='x', pady=(10, 0))

        # ── Content Panes ──
        tracks_content = ctk.CTkFrame(main_body, fg_color='transparent')
        search_content = ctk.CTkFrame(main_body, fg_color='transparent')
        sync_content = ctk.CTkFrame(main_body, fg_color='transparent')

        # ── 1. AVAILABLE SUBTITLES PANE ──
        tracks_col = ctk.CTkFrame(
            tracks_content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD
        )
        tracks_col.pack(fill='both', expand=True)

        tracks_scroll = ctk.CTkScrollableFrame(
            tracks_col, fg_color='transparent', corner_radius=CARD_RADIUS,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=BORDER_HOVER
        )
        tracks_scroll.pack(fill='both', expand=True, padx=8, pady=8)

        def _refresh_track_list():
            for child in tracks_scroll.winfo_children():
                child.destroy()

            current_tracks = sub_mgr.get_tracks()
            active_id = sub_mgr.active_track_id

            # Off option
            is_off = (active_id is None)
            off_frame = ctk.CTkFrame(
                tracks_scroll,
                fg_color=BG_CARD_HOVER if is_off else 'transparent',
                border_width=1.5 if is_off else 1,
                border_color=ACCENT if is_off else BORDER,
                corner_radius=6, height=42
            )
            off_frame.pack(fill='x', pady=3, padx=4)
            off_frame.pack_propagate(False)

            def _select_off():
                sub_mgr.set_active_track(None, getattr(self, '_preview_player', None))
                self._update_cc_button_state()
                _refresh_track_list()

            if is_off:
                active_badge = ctk.CTkLabel(
                    off_frame, text="✓ ACTIVE",
                    text_color=WHITE, fg_color=ACCENT,
                    corner_radius=4, height=20, padx=8,
                    font=(ui_font(), 9, 'bold')
                )
                active_badge.pack(side='right', padx=(4, 10), pady=8)

            off_btn = ctk.CTkRadioButton(
                off_frame, text=T('subtitle_off'),
                text_color=WHITE if is_off else TEXT_SEC,
                fg_color=ACCENT, hover_color=ACCENT_HOVER,
                font=(ui_font(), 11, 'bold' if is_off else 'normal'),
                command=_select_off
            )
            if is_off:
                off_btn.select()
            else:
                off_btn.deselect()
            off_btn.pack(side='left', fill='both', expand=True, padx=10, pady=8)
            off_frame.bind('<Button-1>', lambda e: _select_off())

            for track in current_tracks:
                is_active = (track.id == active_id)
                t_frame = ctk.CTkFrame(
                    tracks_scroll,
                    fg_color=BG_CARD_HOVER if is_active else 'transparent',
                    border_width=1.5 if is_active else 1,
                    border_color=ACCENT if is_active else BORDER,
                    corner_radius=6, height=44
                )
                t_frame.pack(fill='x', pady=3, padx=4)
                t_frame.pack_propagate(False)

                def _make_select_cmd(tid=track.id):
                    def _cmd():
                        sub_mgr.set_active_track(tid, getattr(self, '_preview_player', None))
                        self._update_cc_button_state()
                        _refresh_track_list()
                    return _cmd

                sel_cmd = _make_select_cmd()

                # Right badges (packed FIRST so right-side info is always aligned)
                right_badge_box = ctk.CTkFrame(t_frame, fg_color='transparent')
                right_badge_box.pack(side='right', padx=(4, 10), pady=8)

                if is_active:
                    ctk.CTkLabel(
                        right_badge_box, text="✓ ACTIVE",
                        text_color=WHITE, fg_color=ACCENT,
                        corner_radius=4, height=20, padx=8,
                        font=(ui_font(), 9, 'bold')
                    ).pack(side='right', padx=(6, 0))

                badge_text = track.source.value.upper() if hasattr(track.source, 'value') else str(track.source).upper()
                ctk.CTkLabel(
                    right_badge_box, text=badge_text,
                    text_color=ACCENT if is_active else TEXT_DIM,
                    fg_color=BG_DARK, corner_radius=3, height=20, padx=6,
                    font=(ui_font(), 9, 'bold')
                ).pack(side='right')

                # Left side: Radio Button + Track Name with flexible expansion
                r_btn = ctk.CTkRadioButton(
                    t_frame, text=track.name,
                    text_color=WHITE if is_active else TEXT_PRI,
                    fg_color=ACCENT, hover_color=ACCENT_HOVER,
                    font=(ui_font(), 11, 'bold' if is_active else 'normal'),
                    command=sel_cmd
                )
                if is_active:
                    r_btn.select()
                else:
                    r_btn.deselect()
                r_btn.pack(side='left', fill='both', expand=True, padx=(10, 4), pady=8)

                t_frame.bind('<Button-1>', lambda e, c=sel_cmd: c())

        _refresh_track_list()

        def _on_load_local_file():
            file_path = filedialog.askopenfilename(
                parent=self,
                title=T('subtitle_load_file'),
                filetypes=[
                    ("Subtitle Files", "*.srt *.vtt *.ass *.ssa"),
                    ("SubRip (*.srt)", "*.srt"),
                    ("WebVTT (*.vtt)", "*.vtt"),
                    ("Advanced SubStation Alpha (*.ass *.ssa)", "*.ass *.ssa"),
                    ("All Files", "*.*")
                ]
            )
            if file_path:
                try:
                    track = sub_mgr.add_local_track(file_path)
                    sub_mgr.set_active_track(track.id, getattr(self, '_preview_player', None))
                    self._update_cc_button_state()
                    _refresh_track_list()
                    _show_tracks()
                except Exception as exc:
                    messagebox.showerror("Subtitle Error", f"{T('subtitle_error_load')}\n{exc}", parent=self)

        local_icon = getattr(self, '_sub_local_icon', None)
        load_bar = ctk.CTkFrame(tracks_content, fg_color='transparent')
        load_bar.pack(fill='x', pady=(10, 0))
        ctk.CTkButton(
            load_bar, text="  " + T('subtitle_load_file'), height=36,
            image=local_icon, compound='left',
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, border_width=1, border_color=BORDER_HOVER,
            corner_radius=CONTROL_RADIUS, font=(ui_font(), 11, 'bold'),
            command=_on_load_local_file
        ).pack(fill='x')

        # ── 2. SYNC CONTENT (shown when the Sync tab is active) ──
        sync_scroll = ctk.CTkScrollableFrame(
            sync_content, fg_color='transparent', corner_radius=CARD_RADIUS,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=BORDER_HOVER
        )
        sync_scroll.pack(fill='both', expand=True)

        # ── Target Track Info Card ──
        sync_track_card = ctk.CTkFrame(
            sync_scroll, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD
        )
        sync_track_card.pack(fill='x', pady=(0, 10))

        sync_track_inner = ctk.CTkFrame(sync_track_card, fg_color='transparent')
        sync_track_inner.pack(fill='x', padx=14, pady=10)

        ctk.CTkLabel(
            sync_track_inner, text='TARGET SUBTITLE TRACK',
            text_color=TEXT_DIM, font=(ui_font(), 9, 'bold'), anchor='w'
        ).pack(fill='x')

        sync_track_val_lbl = ctk.CTkLabel(
            sync_track_inner, text='',
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'), anchor='w', justify='left'
        )
        sync_track_val_lbl.pack(fill='x', pady=(2, 0))

        # ── Manual Timing Offset Card ──
        manual_card = ctk.CTkFrame(
            sync_scroll, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD
        )
        manual_card.pack(fill='x', pady=(0, 10))

        manual_inner = ctk.CTkFrame(manual_card, fg_color='transparent')
        manual_inner.pack(fill='both', expand=True, padx=14, pady=12)

        ctk.CTkLabel(
            manual_inner, text='Manual Timing Adjustment',
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'), anchor='w'
        ).pack(fill='x')

        ctk.CTkLabel(
            manual_inner,
            text='Nudge subtitles earlier or later to match speech timing exactly.',
            text_color=TEXT_SEC, font=(ui_font(), 10), anchor='w'
        ).pack(fill='x', pady=(2, 8))

        def _offset_label_text(ms):
            if ms == 0:
                return '0.0s (In Sync)'
            sign = '+' if ms > 0 else '-'
            return f"{sign}{abs(ms)/1000.0:.2f}s"

        offset_var = tk.StringVar(value=_offset_label_text(sub_mgr.get_sync_offset_ms()))
        offset_display = ctk.CTkLabel(
            manual_inner, textvariable=offset_var,
            font=('Consolas', 18, 'bold'), text_color=ACCENT
        )
        offset_display.pack(pady=(4, 10))

        def _apply_sync(delta_ms):
            active = sub_mgr.get_active_track()
            if not active:
                return
            applied = sub_mgr.adjust_sync_offset_ms(
                delta_ms, getattr(self, '_preview_player', None))
            offset_var.set(_offset_label_text(applied))

        def _apply_reset():
            applied = sub_mgr.set_sync_offset_ms(
                0, getattr(self, '_preview_player', None))
            offset_var.set(_offset_label_text(applied))

        # Quick step buttons in a responsive grid
        step_btn_row = ctk.CTkFrame(manual_inner, fg_color='transparent')
        step_btn_row.pack(fill='x', pady=(0, 8))
        for col_idx in range(4):
            step_btn_row.grid_columnconfigure(col_idx, weight=1)

        def _make_regular_step_btn(parent, text, step_ms, col):
            btn = ctk.CTkButton(
                parent, text=text, height=34,
                fg_color='transparent', hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, border_width=1, border_color=BORDER_HOVER,
                corner_radius=CONTROL_RADIUS, font=(ui_font(), 11, 'bold'),
                command=lambda s=step_ms: _apply_sync(s)
            )
            btn.grid(row=0, column=col, sticky='ew', padx=2)
            return btn

        for idx, (text, step) in enumerate((('-1s', -1000), ('-0.5s', -500), ('+0.5s', 500), ('+1s', 1000))):
            _make_regular_step_btn(step_btn_row, text, step, idx)

        # Reset button (Regular outline)
        reset_btn = ctk.CTkButton(
            manual_inner, text='Reset Offset (0.0s)', height=32,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, border_width=1, border_color=BORDER_HOVER,
            corner_radius=CONTROL_RADIUS, font=(ui_font(), 10, 'bold'),
            command=_apply_reset
        )
        reset_btn.pack(fill='x', pady=(2, 0))

        # ── AI Speech Alignment Card ──
        auto_card = ctk.CTkFrame(
            sync_scroll, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD
        )
        auto_card.pack(fill='x', pady=(0, 10))

        auto_inner = ctk.CTkFrame(auto_card, fg_color='transparent')
        auto_inner.pack(fill='both', expand=True, padx=14, pady=12)

        ctk.CTkLabel(
            auto_inner, text='AI Speech Alignment',
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'), anchor='w'
        ).pack(fill='x')

        ctk.CTkLabel(
            auto_inner,
            text='Detects voice patterns in audio stream and automatically aligns subtitle timestamps.',
            text_color=TEXT_SEC, font=(ui_font(), 10), wraplength=440, justify='left', anchor='w'
        ).pack(fill='x', pady=(2, 10))

        auto_btn = ctk.CTkButton(
            auto_inner, text='⚡ Auto Sync with Audio', height=38,
            fg_color='transparent', hover_color=ACCENT_DIM,
            text_color=ACCENT, border_width=1, border_color=ACCENT,
            corner_radius=CONTROL_RADIUS, font=(ui_font(), 12, 'bold'),
            command=lambda: _do_auto_sync()
        )
        auto_btn.pack(fill='x', pady=(0, 6))

        sync_status_lbl = ctk.CTkLabel(
            auto_inner, text="", text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=440, justify='center'
        )
        sync_status_lbl.pack(fill='x', pady=(2, 0))

        def _do_auto_sync():
            active = sub_mgr.get_active_track()
            if active is None:
                sync_status_lbl.configure(
                    text='Please select a subtitle track in Available Subtitles first',
                    text_color=ERROR_C)
                return
            source = getattr(self, '_preview_source', None)
            media_url = getattr(source, 'media_url', '') or ''
            headers = dict(getattr(source, 'headers', {}) or {})
            auto_btn.configure(
                state='disabled', text='Analyzing audio…',
                border_color=BORDER_HOVER, text_color=TEXT_DIM)
            sync_status_lbl.configure(text='Detecting speech timestamps…', text_color=ACCENT)

            def _on_auto_done(offset_ms, err):
                def _ui():
                    try:
                        auto_btn.configure(
                            state='normal', text='⚡ Auto Sync with Audio',
                            border_color=ACCENT, text_color=ACCENT)
                        if err:
                            sync_status_lbl.configure(
                                text=f'Auto sync failed: {err}', text_color=ERROR_C)
                            return
                        applied = sub_mgr.set_sync_offset_ms(
                            offset_ms, getattr(self, '_preview_player', None))
                        offset_var.set(_offset_label_text(applied))
                        if applied:
                            sync_status_lbl.configure(
                                text=f'Auto sync applied: {_offset_label_text(applied)}',
                                text_color=SUCCESS)
                        else:
                            sync_status_lbl.configure(
                                text='Subtitles are already in sync', text_color=SUCCESS)
                    except Exception:
                        pass
                try:
                    self.after(0, _ui)
                except Exception:
                    pass

            sub_mgr.auto_sync_track(active, media_url, headers, on_done=_on_auto_done)

        # ── 3. SEARCH CONTENT (shown when the Search tab is active) ──
        search_col = ctk.CTkFrame(
            search_content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD
        )
        search_col.pack(fill='both', expand=True)

        search_inner = ctk.CTkFrame(search_col, fg_color='transparent')
        search_inner.pack(fill='both', expand=True, padx=12, pady=12)

        default_query = video_code(self._preview_video) if getattr(self, '_preview_video', None) else ""
        if not default_query and getattr(self, '_preview_video', None):
            default_query = str(self._preview_video.get('title') or '')[:30]

        query_entry = ctk.CTkEntry(
            search_inner, placeholder_text=T('subtitle_search_placeholder'),
            placeholder_text_color=('#B0AAA5', '#585350'),
            fg_color=BG_INPUT, text_color=TEXT_PRI, border_color=BORDER,
            border_width=1, corner_radius=CONTROL_RADIUS, height=34,
            font=(ui_font(), 11)
        )
        query_entry.pack(fill='x', pady=(0, 8))
        if default_query:
            query_entry.insert(0, default_query)

        filter_row = ctk.CTkFrame(search_inner, fg_color='transparent')
        filter_row.pack(fill='x', pady=(0, 8))
        filter_row.grid_columnconfigure(0, weight=4)
        filter_row.grid_columnconfigure(1, weight=4)
        filter_row.grid_columnconfigure(2, weight=3)

        lang_options = [
            T('subtitle_all_langs'), 'English', 'Japanese', 'Traditional Chinese', 'Simplified Chinese',
            'Korean', 'Spanish', 'French', 'German', 'Vietnamese', 'Thai', 'Indonesian'
        ]
        lang_var = ctk.StringVar(value=T('subtitle_all_langs'))

        lang_menu = ctk.CTkOptionMenu(
            filter_row, variable=lang_var, values=lang_options,
            height=34,
            fg_color=BG_CARD, button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE, dynamic_resizing=False,
            corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)
        )
        lang_menu.grid(row=0, column=0, sticky='ew', padx=(0, 4))

        prov_options = [T('subtitle_all_providers'), 'SubtitleCat', 'YTS Subtitles', 'OpenSubtitles', 'SubDL', 'Podnapisi']
        prov_var = ctk.StringVar(value=T('subtitle_all_providers'))

        prov_menu = ctk.CTkOptionMenu(
            filter_row, variable=prov_var, values=prov_options,
            height=34,
            fg_color=BG_CARD, button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE, dynamic_resizing=False,
            corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)
        )
        prov_menu.grid(row=0, column=1, sticky='ew', padx=(0, 4))

        search_icon = getattr(self, '_sub_search_icon', None)
        search_btn = ctk.CTkButton(
            filter_row, text="  " + T('subtitle_search_btn'), height=34,
            image=search_icon, compound='left',
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, border_width=1, border_color=BORDER_HOVER,
            corner_radius=CONTROL_RADIUS, font=(ui_font(), 11, 'bold'),
            command=lambda: _do_search()
        )
        search_btn.grid(row=0, column=2, sticky='ew')

        status_lbl = ctk.CTkLabel(
            search_inner, text="", text_color=TEXT_DIM,
            font=(ui_font(), 10)
        )
        status_lbl.pack(anchor='w', pady=(0, 6))

        results_scroll = ctk.CTkScrollableFrame(
            search_inner, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color=BORDER_HOVER
        )
        results_scroll.pack(fill='both', expand=True)

        _result_seen: set = set()

        def _append_result_card(res):
            card = ctk.CTkFrame(
                results_scroll, fg_color=BG_DARK,
                corner_radius=6, border_width=1, border_color=BORDER
            )
            card.pack(fill='x', pady=4, padx=4)

            # Pack button on the right FIRST so it is NEVER pushed off or hidden by long titles
            dl_btn = ctk.CTkButton(
                card, text='Download & Use', width=120, height=32,
                fg_color='transparent', hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, border_width=1, border_color=BORDER_HOVER,
                corner_radius=CONTROL_RADIUS,
                font=(ui_font(), 10, 'bold'),
                command=lambda: _dl_action(res, dl_btn)
            )
            dl_btn.pack(side='right', padx=(6, 10), pady=8)

            # Then pack info box on the left with wrapping support
            info_box = ctk.CTkFrame(card, fg_color='transparent')
            info_box.pack(side='left', fill='both', expand=True, padx=(10, 6), pady=8)

            ctk.CTkLabel(
                info_box, text=res.title, text_color=TEXT_PRI,
                font=(ui_font(), 11, 'bold'), anchor='w', justify='left',
                wraplength=340
            ).pack(fill='x', anchor='w')

            meta_sub = ctk.CTkLabel(
                info_box, text=f"Language: {res.language} • Provider: {res.provider}",
                text_color=TEXT_DIM, font=(ui_font(), 9), anchor='w'
            )
            meta_sub.pack(fill='x', anchor='w', pady=(2, 0))

        def _dl_action(res, btn_widget):
            status_lbl.configure(text=T('subtitle_downloading'), text_color=ACCENT)
            try:
                btn_widget.configure(state='disabled', text='Downloading…')
            except Exception:
                pass

            def _on_dl_done(track, dl_err):
                def _dl_ui():
                    try:
                        btn_widget.configure(state='normal', text='Download & Use')
                    except Exception:
                        pass
                    if dl_err or not track:
                        status_lbl.configure(
                            text=str(dl_err or T('subtitle_error_load')), text_color=ERROR_C)
                    else:
                        status_lbl.configure(
                            text=f"✓ Downloaded & Activated: {track.name}", text_color=SUCCESS)
                        self._update_cc_button_state()
                        _refresh_track_list()
                        _show_tracks()
                try:
                    self.after(0, _dl_ui)
                except Exception:
                    pass

            sub_mgr.download_online_track_async(res, on_complete=_on_dl_done)

        def _do_search():
            q = query_entry.get().strip()
            if not q:
                return

            status_lbl.configure(text=T('subtitle_searching'), text_color=ACCENT)
            for child in results_scroll.winfo_children():
                child.destroy()
            _result_seen.clear()

            selected_lang = lang_var.get()
            lang_filter = None if selected_lang == T('subtitle_all_langs') else selected_lang

            selected_prov = prov_var.get()
            prov_filter = None if selected_prov in (T('subtitle_all_providers'), 'All Providers') else selected_prov

            def _on_search_progress(partial):
                def _ui():
                    if getattr(self, '_is_closing', False):
                        return
                    added = 0
                    for res in partial:
                        key = (res.provider, res.download_url, res.title)
                        if key in _result_seen:
                            continue
                        _result_seen.add(key)
                        _append_result_card(res)
                        added += 1
                    if added:
                        status_lbl.configure(
                            text=f"Found {len(_result_seen)} subtitle(s)...",
                            text_color=TEXT_DIM)
                try:
                    self.after(0, _ui)
                except Exception:
                    pass

            def _on_search_done(results, error_msg):
                def _ui_update():
                    if getattr(self, '_is_closing', False):
                        return
                    if error_msg:
                        status_lbl.configure(text=error_msg, text_color=ERROR_C)
                        return
                    for res in results:
                        key = (res.provider, res.download_url, res.title)
                        if key in _result_seen:
                            continue
                        _result_seen.add(key)
                        _append_result_card(res)

                    if not _result_seen:
                        for child in results_scroll.winfo_children():
                            child.destroy()

                        empty_box = ctk.CTkFrame(
                            results_scroll, fg_color=BG_DARK, corner_radius=CARD_RADIUS,
                            border_width=1, border_color=BORDER_CARD
                        )
                        empty_box.pack(fill='both', expand=True, padx=8, pady=24)

                        ctk.CTkLabel(
                            empty_box, text="🔍", font=(ui_font(), 32), text_color=TEXT_DIM
                        ).pack(pady=(20, 6))

                        ctk.CTkLabel(
                            empty_box, text=T('subtitle_no_results'),
                            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold')
                        ).pack(pady=(0, 6))

                        ctk.CTkLabel(
                            empty_box,
                            text=T('subtitle_no_results_desc', query=q),
                            text_color=TEXT_SEC, font=(ui_font(), 10),
                            wraplength=380, justify='center'
                        ).pack(padx=20, pady=(0, 16))

                        # Quick action buttons inside empty state
                        empty_btns = ctk.CTkFrame(empty_box, fg_color='transparent')
                        empty_btns.pack(pady=(0, 20))

                        ctk.CTkButton(
                            empty_btns, text="📁 " + T('subtitle_load_file'), height=32,
                            fg_color=BG_CARD_HOVER, hover_color=BG_CARD,
                            text_color=TEXT_PRI, border_width=1, border_color=BORDER_HOVER,
                            corner_radius=CONTROL_RADIUS, font=(ui_font(), 10, 'bold'),
                            command=_on_load_local_file
                        ).pack(side='left', padx=6)

                        v_code = video_code(self._preview_video) if getattr(self, '_preview_video', None) else ""
                        if v_code and v_code.lower() != q.lower():
                            def _search_code_only():
                                query_entry.delete(0, 'end')
                                query_entry.insert(0, v_code)
                                _do_search()

                            ctk.CTkButton(
                                empty_btns, text=f"🔍 Search '{v_code}'", height=32,
                                fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                text_color=WHITE, corner_radius=CONTROL_RADIUS,
                                font=(ui_font(), 10, 'bold'),
                                command=_search_code_only
                            ).pack(side='left', padx=6)

                        status_lbl.configure(
                            text=f"No subtitles found for '{q}'",
                            text_color=TEXT_DIM)
                    else:
                        status_lbl.configure(
                            text=f"Found {len(_result_seen)} subtitle(s)",
                            text_color=TEXT_DIM)
                try:
                    self.after(0, _ui_update)
                except Exception:
                    pass

            sub_mgr.search_online_async(
                q, language=lang_filter, provider_name=prov_filter,
                on_progress=_on_search_progress, on_complete=_on_search_done)

        query_entry.bind('<Return>', lambda e: _do_search())

        # Show the Available Subtitles tab by default
        _show_tracks()

    def _find_video_by_url(self, url: str) -> dict:
        for video in getattr(self, '_videos', []):
            if video.get('url') == url:
                return dict(video)
        return {'url': url, 'title': url}

    def _open_preview_for_url(self, url: str):
        self._open_preview(self._find_video_by_url(url))

    def _open_preview(self, video: dict, is_back_nav: bool = False):
        url = str((video or {}).get('url') or '').strip()
        if not url:
            return

        if not hasattr(self, '_preview_stack'):
            self._preview_stack = []

        if not is_back_nav:
            if not self._preview_stack or (self._preview_stack[-1].get('url') != video.get('url')):
                self._preview_stack.append(dict(video or {}))

        if not hasattr(self, '_preview_gen'):
            self._preview_gen = 0
        self._preview_gen += 1
        gen = self._preview_gen
        self._preview_video = dict(video or {})
        self._preview_source = None
        self._set_browse_mode('preview')
        self._render_preview_loading(self._preview_video)

        def _resolve():
            source = resolve_preview_source(url, self._preview_video)
            try:
                self.after(0, lambda: self._apply_preview_source(gen, source))
            except Exception:
                pass
            self._enrich_preview_metadata(self._preview_video, source, gen)

        threading.Thread(target=_resolve, daemon=True).start()

    def _preview_navigate_back(self):
        stack = getattr(self, '_preview_stack', [])
        if len(stack) > 1:
            stack.pop()
            prev_video = stack[-1]
            self._open_preview(prev_video, is_back_nav=True)
        else:
            self._preview_stack = []
            self._set_browse_mode('grid')

    def _enrich_preview_metadata(self, video: dict, source: PreviewSource, gen: int):
        """Scrape accurate metadata for the preview info pane: the video's own detail
        page (JableTV / MissAV / SupJav) plus cross-site lookup for missing fields and
        an actress photo. Then refresh the info card in place on the main thread."""
        try:
            enriched = fetch_video_metadata(video)
        except Exception:
            enriched = {}

        if isinstance(enriched, dict) and enriched:
            for k, v in enriched.items():
                if v and not self._preview_video.get(k):
                    self._preview_video[k] = v
            if gen == getattr(self, '_preview_gen', 0):
                try:
                    self.after(0, self._refresh_preview_info)
                except Exception:
                    pass

        # Related-video cross-search (MissAV / SupJav) to feed the recommendation rows
        title_or_url = f"{video.get('title', '')} {video.get('url', '')} {source.page_url}"
        m = re.search(r'([a-zA-Z]{2,6}-\d{3,5})', title_or_url, re.IGNORECASE)
        code = m.group(1).upper() if m else ''
        if code:
            related = []
            seen = set()
            try:
                from M3U8Sites.SiteSupJav import SupJavBrowser
                for rv in SupJavBrowser.search(code) or []:
                    if not isinstance(rv, dict):
                        continue
                    u = rv.get('url', '')
                    if u and u not in seen:
                        seen.add(u)
                        related.append(rv)
            except Exception:
                pass
            if related:
                self._preview_video['related_vids'] = related

    def _preview_list(self, *keys):
        """Collect unique, non-empty values across several metadata keys."""
        v_dict = getattr(self, '_preview_video', {}) or {}
        vals = []
        for k in keys:
            raw = v_dict.get(k)
            if isinstance(raw, (list, tuple, set)):
                for x in raw:
                    s = str(x).strip()
                    if s and s not in vals:
                        vals.append(s)
            else:
                s = str(raw or '').strip()
                if s and s not in vals:
                    vals.append(s)
        return vals

    def _preview_info_payload(self) -> dict:
        """Current values for the preview info card (shared by render + refresh)."""
        v_dict = getattr(self, '_preview_video', {}) or {}
        source = getattr(self, '_preview_source', None)
        page_url = getattr(source, 'page_url', '') if source is not None else ''
        url = str(v_dict.get('url') or page_url or '')

        def _join(*keys):
            vals = self._preview_list(*keys)
            return ', '.join(vals) or 'N/A'

        actor_val = _join('actor', 'stars', 'star')
        actress_val = _join('actress', 'actresses', 'model', 'models', 'cast')
        director_val = _join('director', 'directors')
        studio_val = _join('studio', 'maker', 'publisher', 'production')
        if studio_val == 'N/A':
            studio_val = str(getattr(source, 'site_name', '') if source is not None else '') or 'N/A'

        tags_val = _join('tags', 'categories', 'keywords')

        duration_val = 'N/A'
        if source is not None and getattr(source, 'duration', ''):
            duration_val = str(source.duration)
        elif v_dict.get('duration'):
            duration_val = str(v_dict.get('duration'))
        fmt_val = str((getattr(source, 'media_kind', '') if source is not None else '') or v_dict.get('media_kind') or 'HLS').upper()
        stream_val = str(getattr(source, 'media_url', '') if source is not None else '') or 'N/A'

        return {
            'actor': actor_val,
            'actress': actress_val,
            'director': director_val,
            'studio': studio_val,
            'tags': tags_val,
            'duration': duration_val,
            'format': fmt_val,
            'url': url,
            'stream': stream_val,
        }

    def _render_preview_chips(self, kind: str, items, urls=None):
        """Render plain hoverable text links (actress / director / studio / tag)
        in the info card. Hovering turns the text into the prime color; clicking
        runs a quick search for everything the entity is part of."""
        flow = (self._preview_chip_rows or {}).get(kind)
        if flow is None or not flow.winfo_exists():
            return
        try:
            for w in flow.winfo_children():
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        except tk.TclError:
            return
        if not items:
            ctk.CTkLabel(
                flow, text='N/A', text_color=TEXT_PRI,
                font=(ui_font(), 11)).pack(side='left')
            return
        for idx, name in enumerate(items):
            name = str(name).strip()
            if not name:
                continue
            url = ''
            if urls and idx < len(urls):
                url = str(urls[idx] or '').strip()
            link = ctk.CTkLabel(
                flow, text=name, text_color=TEXT_PRI,
                font=(ui_font(), 11))
            link.pack(side='left', padx=(0, 10), pady=2)
            try:
                link.configure(cursor='hand2')
            except Exception:
                pass
            link.bind('<Button-1>',
                      lambda e, k=kind, n=name, u=url: self._open_entity_page(k, n, u))
            link.bind('<Enter>',
                      lambda e, w=link: w.configure(text_color=ACCENT))
            link.bind('<Leave>',
                      lambda e, w=link: w.configure(text_color=TEXT_PRI))

    def _refresh_preview_info(self):
        """Update the info card value labels and actress photo after enrichment."""
        if getattr(self, '_is_closing', False):
            return
        if getattr(self, '_browse_mode', '') != 'preview':
            return
        labels = getattr(self, '_preview_info_labels', None)
        if not labels:
            return
        payload = self._preview_info_payload()
        for key in ('actor', 'duration', 'format', 'url', 'stream'):
            lbl = labels.get(key)
            if lbl is None:
                continue
            try:
                if not lbl.winfo_exists():
                    continue
                lbl.configure(text=payload[key])
            except tk.TclError:
                return

        # Rebuild the clickable chips for actress / director / studio / tags.
        self._render_preview_chips('actress',
                                   self._preview_list('actress', 'actresses', 'model', 'models', 'cast'),
                                   (self._preview_video or {}).get('actress_urls') or [])
        self._render_preview_chips('director',
                                   self._preview_list('director', 'directors'))
        self._render_preview_chips('studio',
                                   self._preview_list('studio', 'maker', 'publisher', 'production'))
        self._render_preview_chips('tags',
                                   self._preview_list('tags', 'categories', 'keywords'))

        photo_urls = (self._preview_video or {}).get('actress_photos') or []
        if not photo_urls:
            single = (self._preview_video or {}).get('actress_photo') or ''
            if single:
                photo_urls = [single]
        if photo_urls:
            self._load_actress_photos(photo_urls)

        # Now that the current video's tags are known, re-rank the category row.
        self._refresh_category_cards()

    def _load_actress_photos(self, photo_urls):
        """Fetch actress portraits in the background and show them as circular
        avatars in an inline, horizontally scrollable row in the info card."""
        if getattr(self, '_is_closing', False):
            return
        urls = []
        for u in (photo_urls or []):
            s = str(u or '').strip()
            if s and s not in urls:
                urls.append(s)
        if not urls:
            return
        gen = getattr(self, '_preview_gen', 0)
        scroll = getattr(self, '_preview_photos_scroll', None)
        if scroll is None or not scroll.winfo_exists():
            return
        already = set(getattr(scroll, '_added_urls', []))
        urls = [u for u in urls if u not in already]
        if not urls:
            return
        names = [str(x).strip() for x in
                 ((self._preview_video or {}).get('actress') or []) if str(x).strip()]
        actress_urls = [str(x).strip() for x in
                        ((self._preview_video or {}).get('actress_urls') or []) if str(x).strip()]

        def _worker():
            if self._is_closing or gen != getattr(self, '_preview_gen', 0):
                return
            results = []
            for i, u in enumerate(urls):
                if self._is_closing or gen != getattr(self, '_preview_gen', 0):
                    return
                img = _fetch_actress_portrait(u)
                if img is not None:
                    name = names[i] if i < len(names) else ''
                    page_url = actress_urls[i] if i < len(actress_urls) else ''
                    results.append((u, name, page_url))
            if not results:
                return

            def _open(n, pu):
                self._open_entity_page('actress', n, pu)

            def _apply():
                if self._is_closing or gen != getattr(self, '_preview_gen', 0):
                    return
                scroll = getattr(self, '_preview_photos_scroll', None)
                if scroll is None or not scroll.winfo_exists():
                    return
                try:
                    if not getattr(self, '_preview_photos_shown', False):
                        try:
                            scroll.grid(row=1, column=0, sticky='ew', pady=(12, 0))
                        except tk.TclError:
                            return
                        self._preview_photos_shown = True
                    diameter = 88
                    for u, name, page_url in results:
                        if not scroll.winfo_exists():
                            return
                        img = _fetch_actress_portrait(u)
                        if img is None:
                            continue
                        ctk_img = _make_circular_avatar(img, diameter)
                        holder = ctk.CTkFrame(scroll, fg_color='transparent')
                        holder.pack(side='left', padx=(0, 10), pady=6)
                        lbl = ctk.CTkLabel(holder, text='', width=diameter, height=diameter)
                        lbl.pack()
                        lbl.configure(image=ctk_img)
                        lbl._ctk_img_ref = ctk_img
                        added = getattr(scroll, '_added_urls', None)
                        if added is None:
                            added = []
                            scroll._added_urls = added
                        added.append(u)
                        if name:
                            try:
                                lbl.configure(cursor='hand2')
                            except Exception:
                                pass
                            lbl.bind('<Button-1>', lambda e, n=name, pu=page_url: _open(n, pu))
                            name_lbl = ctk.CTkLabel(
                                holder, text=name, text_color=TEXT_PRI,
                                font=(ui_font(), 9), wraplength=diameter, justify='center')
                            name_lbl.pack(anchor='center', pady=(4, 0))
                            try:
                                name_lbl.configure(cursor='hand2')
                            except Exception:
                                pass
                            name_lbl.bind('<Button-1>', lambda e, n=name, pu=page_url: _open(n, pu))
                            name_lbl.bind('<Enter>',
                                          lambda e, w=name_lbl: w.configure(text_color=ACCENT))
                            name_lbl.bind('<Leave>',
                                          lambda e, w=name_lbl: w.configure(text_color=TEXT_PRI))
                except Exception:
                    pass

            self._ui(_apply)

        try:
            self._thumb_executor.submit(_worker)
        except RuntimeError:
            pass

    def _video_tag_set(self, v) -> set:
        """Normalized lowercase tag set for a video dict (any of the tag keys)."""
        out = set()
        if not isinstance(v, dict):
            return out
        for k in ('tags', 'categories', 'keywords'):
            raw = v.get(k)
            if isinstance(raw, (list, tuple, set)):
                for x in raw:
                    s = str(x).strip().lower()
                    if s:
                        out.add(s)
            elif raw:
                for part in str(raw).split(','):
                    s = part.strip().lower()
                    if s:
                        out.add(s)
        return out

    def _rank_category_pool(self, pool):
        """Sort candidate videos by how many tags they share with the current
        video, tie-broken by the original rotation order."""
        cur_tags = self._video_tag_set(getattr(self, '_preview_video', {}))

        def _score(c):
            return (-len((c.get('_tag_set') or set()) & cur_tags), c.get('_tag_order', 0))

        return sorted(pool, key=_score)

    def _render_more_category_cards(self, cat_grid, display_vids, gen):
        """Render (or re-render) the 3 'More from this category' cards."""
        if self._is_closing or gen != getattr(self, '_preview_gen', 0):
            return
        if cat_grid is None or not cat_grid.winfo_exists():
            return
        try:
            for child in cat_grid.winfo_children():
                try:
                    child.destroy()
                except tk.TclError:
                    pass
            for c in range(3):
                cat_grid.grid_columnconfigure(c, weight=1, uniform='cat_cols')
        except tk.TclError:
            return

        for v_idx, v_item in enumerate(display_vids[:3]):
            v_url = v_item.get('url', '')
            v_title = v_item.get('title', '')
            v_dur = v_item.get('duration', '')
            v_thumb = v_item.get('thumbnail') or v_item.get('img') or v_item.get('poster_url') or v_item.get('cover_url') or ''

            v_card = ctk.CTkFrame(
                cat_grid, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                border_width=1, border_color=BORDER_CARD)
            v_card.grid(row=0, column=v_idx, padx=4, sticky='nsew')
            v_thumb_holder = ctk.CTkFrame(v_card, fg_color=BG_SIDEBAR, height=180, corner_radius=6)
            v_thumb_holder.pack(fill='x', padx=4, pady=(4, 0))
            v_thumb_holder.pack_propagate(False)

            v_cover_url = v_item.get('cover_url') or ''
            has_v_cover = bool(v_cover_url and v_cover_url != v_thumb)

            v_lbl = ctk.CTkLabel(v_thumb_holder, text='', text_color=TEXT_DIM, font=(ui_font(), 9))
            v_lbl.pack(fill='both', expand=True)
            if v_thumb:
                self._load_thumb_async(
                    v_thumb, v_lbl, self._preview_gen, self._build_gen,
                    getattr(self, '_site_key', ''), enable_blur=has_v_cover)

            v_dur_lbl = ctk.CTkLabel(
                v_thumb_holder, text=f' {v_dur} ' if v_dur else '', text_color=WHITE, fg_color='#000000',
                corner_radius=3, font=('Consolas', 8, 'bold'))
            if v_dur:
                v_dur_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-4, y=-4)
            elif v_url and ('hanime.tv' in v_url.lower() or 'tnaflix.com' in v_url.lower()):
                def _fetch_cat_dur_bg(card_url=v_url, card_lbl=v_dur_lbl, card_dict=v_item, my_pgen=getattr(self, '_preview_gen', 0)):
                    try:
                        resolved_dur = self._resolve_video_duration_fast(card_url)
                        if resolved_dur and my_pgen == getattr(self, '_preview_gen', 0):
                            card_dict['duration'] = resolved_dur
                            def _apply():
                                try:
                                    if card_lbl.winfo_exists():
                                        card_lbl.configure(text=f' {resolved_dur} ')
                                        card_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-4, y=-4)
                                        card_lbl.lift()
                                except Exception:
                                    pass
                            self.after(0, _apply)
                    except Exception:
                        pass
                if hasattr(self, '_dur_executor') and self._dur_executor:
                    self._dur_executor.submit(_fetch_cat_dur_bg)
                else:
                    threading.Thread(target=_fetch_cat_dur_bg, daemon=True).start()

            v_cover_widgets = []
            if has_v_cover:
                vcov_w, vcov_h = 114, 166
                vcov_frame = ctk.CTkFrame(
                    v_thumb_holder, fg_color='#0a0a0f',
                    corner_radius=4,
                    border_width=1,
                    border_color='#404055',
                    width=vcov_w, height=vcov_h)
                vcov_frame.place(relx=0.0, rely=0.5, anchor='w', x=6)
                vcov_frame.pack_propagate(False)

                vcov_lbl = ctk.CTkLabel(vcov_frame, text='', fg_color='transparent')
                vcov_lbl.pack(fill='both', expand=True)

                self._load_cover_overlay_async(
                    v_cover_url, vcov_lbl, vcov_w, vcov_h,
                    self._preview_gen, self._build_gen, getattr(self, '_site_key', '')
                )
                v_cover_widgets = [vcov_frame, vcov_lbl]

            # Subtitle and Dub outline badges — bottom-left of thumbnail
            try:
                _sub_cache = SubtitleCache()
            except Exception:
                _sub_cache = None
            _sub_dest_var = getattr(self, '_dest_var', None)
            _sub_dest = _sub_dest_var.get() if _sub_dest_var is not None else getattr(self, '_dest', '')
            _sub_listing_url = getattr(self, '_current_base_url', '')
            try:
                card_badges = _detect_video_card_badges(
                    v_item, dest=_sub_dest, cache=_sub_cache,
                    listing_url=_sub_listing_url)
            except Exception:
                card_badges = []
            sub_badge_widgets = []
            if card_badges:
                _bx = 126 if has_v_cover else 5
                for b in card_badges:
                    _text = b['text']
                    _color = b['color']
                    _w = max(26, len(_text) * 7 + 10)
                    _badge = ctk.CTkLabel(
                        v_thumb_holder, text=_text,
                        width=_w, height=16, corner_radius=2,
                        border_width=1, border_color=_color,
                        fg_color=('#101018', '#101018'), text_color=_color,
                        font=('Consolas', 8, 'bold'))
                    _badge.place(relx=0, rely=1.0, anchor='sw', x=_bx, y=-4)
                    _badge.lift()
                    sub_badge_widgets.append(_badge)
                    _bx += _w + 4

            v_info = ctk.CTkFrame(v_card, fg_color='transparent')
            v_info.pack(fill='x', padx=8, pady=(6, 8))

            v_title_lbl = ctk.CTkLabel(
                v_info, text=v_title, text_color=TEXT_PRI,
                font=(ui_font(), 10, 'bold'), wraplength=220, justify='left', anchor='w')
            v_title_lbl.pack(anchor='w', fill='x', pady=(0, 4))
            ToolTip(v_title_lbl, v_title)

            v_badges = ctk.CTkFrame(v_info, fg_color='transparent')
            v_badges.pack(anchor='w', fill='x')

            ctk.CTkLabel(
                v_badges, text=getattr(self, '_site_key', 'JAVXY'), text_color=TEXT_DIM,
                fg_color=BG_SIDEBAR, corner_radius=4, height=18, padx=6,
                font=(ui_font(), 9, 'bold')).pack(side='left')

            v_is_saved = config.is_video_saved(v_url)
            v_heart_img = getattr(self, '_heart_active_icon', None) if v_is_saved else getattr(self, '_heart_icon', None)
            v_heart_text = '' if v_heart_img else ('♥' if v_is_saved else '♡')

            v_heart_btn = ctk.CTkButton(
                v_badges, text=v_heart_text, image=v_heart_img,
                width=24, height=22, corner_radius=4,
                fg_color='transparent',
                border_width=1, border_color=ACCENT if v_is_saved else BORDER_HOVER,
                hover_color=BG_CARD_HOVER, text_color=ACCENT if v_is_saved else TEXT_PRI,
            )
            v_heart_btn.configure(
                command=lambda item=v_item, u=v_url, b=v_heart_btn: self._on_card_heart_click(item, u, b)
            )
            v_heart_btn.pack(side='right')

            def _bind_v(widget, item=v_item):
                widget.bind('<Button-1>', lambda e: self._open_preview(item))
                widget.configure(cursor='hand2')

            _bind_v(v_card)
            _bind_v(v_thumb_holder)
            _bind_v(v_lbl)
            for _cw in v_cover_widgets:
                _bind_v(_cw)
            _bind_v(v_info)
            for _bw in sub_badge_widgets:
                _bind_v(_bw)

            if has_v_cover:
                v_lbl._enable_blur = True
                def _on_cat_enter(_e=None, lbl=v_lbl):
                    if getattr(lbl, '_hovered', False):
                        return
                    lbl._hovered = True
                    sharp = getattr(lbl, '_ctk_sharp_img', None)
                    if sharp:
                        try:
                            lbl.configure(image=sharp)
                            lbl._ctk_img_ref = sharp
                        except Exception:
                            pass

                def _on_cat_leave(_e=None, c=v_card, lbl=v_lbl):
                    def _check_leave():
                        try:
                            if not c.winfo_exists():
                                return
                            x, y = c.winfo_pointerxy()
                            w = c.winfo_containing(x, y)
                            is_inside = False
                            while w:
                                if w == c:
                                    is_inside = True
                                    break
                                w = getattr(w, 'master', None)
                            if not is_inside:
                                lbl._hovered = False
                                blurred = getattr(lbl, '_ctk_blurred_img', None)
                                if blurred:
                                    lbl.configure(image=blurred)
                                    lbl._ctk_img_ref = blurred
                        except Exception:
                            pass
                    c.after(40, _check_leave)

                for _w in (v_card, v_thumb_holder, v_lbl, v_info, v_title_lbl, v_heart_btn, *v_cover_widgets, *sub_badge_widgets):
                    try:
                        _w.bind('<Enter>', _on_cat_enter, add='+')
                        _w.bind('<Leave>', _on_cat_leave, add='+')
                    except Exception:
                        pass

    def _render_more_series_cards(self, series_frame, series_grid, series_count_lbl, series_vids, gen):
        """Render the 'More from this series' cards sorted by part / episode number."""
        if self._is_closing or gen != getattr(self, '_preview_gen', 0):
            return
        if series_frame is None or not series_frame.winfo_exists():
            return
        if not series_vids or len(series_vids) <= 0:
            try:
                series_frame.pack_forget()
            except Exception:
                pass
            return

        cur_url = (getattr(self, '_preview_video', {}) or {}).get('url', '')

        # Sort series videos by their part number ascending (1, 2, 3...)
        def _series_sort_key(v):
            part = v.get('_series_part', 0)
            if not part:
                _, part, _ = extract_series_info(v)
            return (part if part > 0 else 999999, str(v.get('title', '')))

        sorted_vids = sorted(series_vids, key=_series_sort_key)

        try:
            for child in series_grid.winfo_children():
                try:
                    child.destroy()
                except tk.TclError:
                    pass

            columns = 3
            for c in range(columns):
                series_grid.grid_columnconfigure(c, weight=1, uniform='series_cols')
        except tk.TclError:
            return

        if series_count_lbl and series_count_lbl.winfo_exists():
            parts_txt = f'({len(sorted_vids)} {"parts" if len(sorted_vids) > 1 else "part"})'
            series_count_lbl.configure(text=parts_txt)

        try:
            series_frame.pack(fill='x', pady=(4, 16))
        except Exception:
            pass

        for v_idx, v_item in enumerate(sorted_vids):
            row_idx = v_idx // columns
            col_idx = v_idx % columns

            v_url = v_item.get('url', '')
            v_title = v_item.get('title', '')
            v_dur = v_item.get('duration', '')
            v_thumb = v_item.get('thumbnail') or v_item.get('img') or v_item.get('poster_url') or v_item.get('cover_url') or ''
            part_label = v_item.get('_series_label') or ''
            if not part_label:
                _, _, part_label = extract_series_info(v_item)

            is_current = bool(v_url and v_url == cur_url)

            v_card = ctk.CTkFrame(
                series_grid, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                border_width=2 if is_current else 1,
                border_color=ACCENT if is_current else BORDER_CARD)
            v_card.grid(row=row_idx, column=col_idx, padx=4, pady=4, sticky='nsew')

            v_thumb_holder = ctk.CTkFrame(v_card, fg_color=BG_SIDEBAR, height=180, corner_radius=6)
            v_thumb_holder.pack(fill='x', padx=4, pady=(4, 0))
            v_thumb_holder.pack_propagate(False)

            s_cover_url = v_item.get('cover_url') or ''
            has_s_cover = bool(s_cover_url and s_cover_url != v_thumb)

            v_lbl = ctk.CTkLabel(v_thumb_holder, text='', text_color=TEXT_DIM, font=(ui_font(), 9))
            v_lbl.pack(fill='both', expand=True)
            if v_thumb:
                self._load_thumb_async(
                    v_thumb, v_lbl, self._preview_gen, self._build_gen,
                    v_item.get('site_name') or getattr(self, '_site_key', ''),
                    enable_blur=has_s_cover
                )

            # Part / Episode badge at top-left
            if part_label:
                badge_bg = ACCENT if is_current else '#2563EB'
                ctk.CTkLabel(
                    v_thumb_holder, text=f' {part_label} ', text_color=WHITE,
                    fg_color=badge_bg, corner_radius=3,
                    font=('Consolas', 9, 'bold')).place(relx=0.0, rely=0.0, anchor='nw', x=4, y=4)

            if is_current:
                ctk.CTkLabel(
                    v_thumb_holder, text=' NOW PLAYING ', text_color=WHITE,
                    fg_color=ACCENT, corner_radius=3,
                    font=('Consolas', 8, 'bold')).place(relx=1.0, rely=0.0, anchor='ne', x=-4, y=4)

            v_dur_lbl = ctk.CTkLabel(
                v_thumb_holder, text=f' {v_dur} ' if v_dur else '', text_color=WHITE, fg_color='#000000',
                corner_radius=3, font=('Consolas', 8, 'bold'))
            if v_dur:
                v_dur_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-4, y=-4)
            elif v_url and ('hanime.tv' in v_url.lower() or 'tnaflix.com' in v_url.lower()):
                def _fetch_ser_dur_bg(card_url=v_url, card_lbl=v_dur_lbl, card_dict=v_item, my_pgen=getattr(self, '_preview_gen', 0)):
                    try:
                        resolved_dur = self._resolve_video_duration_fast(card_url)
                        if resolved_dur and my_pgen == getattr(self, '_preview_gen', 0):
                            card_dict['duration'] = resolved_dur
                            def _apply():
                                try:
                                    if card_lbl.winfo_exists():
                                        card_lbl.configure(text=f' {resolved_dur} ')
                                        card_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-4, y=-4)
                                        card_lbl.lift()
                                except Exception:
                                    pass
                            self.after(0, _apply)
                    except Exception:
                        pass
                if hasattr(self, '_dur_executor') and self._dur_executor:
                    self._dur_executor.submit(_fetch_ser_dur_bg)
                else:
                    threading.Thread(target=_fetch_ser_dur_bg, daemon=True).start()

            s_cover_widgets = []
            if has_s_cover:
                scov_w, scov_h = 114, 166
                scov_frame = ctk.CTkFrame(
                    v_thumb_holder, fg_color='#0a0a0f',
                    corner_radius=4,
                    border_width=1,
                    border_color='#404055',
                    width=scov_w, height=scov_h)
                scov_frame.place(relx=0.0, rely=0.5, anchor='w', x=6)
                scov_frame.pack_propagate(False)

                scov_lbl = ctk.CTkLabel(scov_frame, text='', fg_color='transparent')
                scov_lbl.pack(fill='both', expand=True)

                self._load_cover_overlay_async(
                    s_cover_url, scov_lbl, scov_w, scov_h,
                    self._preview_gen, self._build_gen,
                    v_item.get('site_name') or getattr(self, '_site_key', '')
                )
                s_cover_widgets = [scov_frame, scov_lbl]

            # Subtitle and Dub badges
            try:
                _sub_cache = SubtitleCache()
            except Exception:
                _sub_cache = None
            _sub_dest_var = getattr(self, '_dest_var', None)
            _sub_dest = _sub_dest_var.get() if _sub_dest_var is not None else getattr(self, '_dest', '')
            _sub_listing_url = getattr(self, '_current_base_url', '')
            try:
                card_badges = _detect_video_card_badges(
                    v_item, dest=_sub_dest, cache=_sub_cache,
                    listing_url=_sub_listing_url)
            except Exception:
                card_badges = []
            sub_badge_widgets = []
            if card_badges:
                _bx = 126 if has_s_cover else 5
                for b in card_badges:
                    _text = b['text']
                    _color = b['color']
                    _w = max(26, len(_text) * 7 + 10)
                    _badge = ctk.CTkLabel(
                        v_thumb_holder, text=_text,
                        width=_w, height=16, corner_radius=2,
                        border_width=1, border_color=_color,
                        fg_color=('#101018', '#101018'), text_color=_color,
                        font=('Consolas', 8, 'bold'))
                    _badge.place(relx=0, rely=1.0, anchor='sw', x=_bx, y=-4)
                    _badge.lift()
                    sub_badge_widgets.append(_badge)
                    _bx += _w + 4

            v_info = ctk.CTkFrame(v_card, fg_color='transparent')
            v_info.pack(fill='x', padx=8, pady=(6, 8))

            v_title_lbl = ctk.CTkLabel(
                v_info, text=v_title, text_color=TEXT_PRI,
                font=(ui_font(), 10, 'bold'), wraplength=220, justify='left', anchor='w')
            v_title_lbl.pack(anchor='w', fill='x', pady=(0, 4))
            ToolTip(v_title_lbl, v_title)

            v_badges = ctk.CTkFrame(v_info, fg_color='transparent')
            v_badges.pack(anchor='w', fill='x')

            card_site = v_item.get('site_name') or config.site_name_from_url(v_url) or getattr(self, '_site_key', 'JAVXY')
            ctk.CTkLabel(
                v_badges, text=card_site, text_color=TEXT_DIM,
                fg_color=BG_SIDEBAR, corner_radius=4, height=18, padx=6,
                font=(ui_font(), 9, 'bold')).pack(side='left')

            v_is_saved = config.is_video_saved(v_url)
            v_heart_img = getattr(self, '_heart_active_icon', None) if v_is_saved else getattr(self, '_heart_icon', None)
            v_heart_text = '' if v_heart_img else ('♥' if v_is_saved else '♡')

            v_heart_btn = ctk.CTkButton(
                v_badges, text=v_heart_text, image=v_heart_img,
                width=24, height=22, corner_radius=4,
                fg_color='transparent',
                border_width=1, border_color=ACCENT if v_is_saved else BORDER_HOVER,
                hover_color=BG_CARD_HOVER, text_color=ACCENT if v_is_saved else TEXT_PRI,
            )
            v_heart_btn.configure(
                command=lambda item=v_item, u=v_url, b=v_heart_btn: self._on_card_heart_click(item, u, b)
            )
            v_heart_btn.pack(side='right')

            def _bind_v(widget, item=v_item):
                widget.bind('<Button-1>', lambda e: self._open_preview(item))
                widget.configure(cursor='hand2')

            _bind_v(v_card)
            _bind_v(v_thumb_holder)
            _bind_v(v_lbl)
            for _cw in s_cover_widgets:
                _bind_v(_cw)
            _bind_v(v_info)
            _bind_v(v_title_lbl)
            for _bw in sub_badge_widgets:
                _bind_v(_bw)

            if has_s_cover:
                v_lbl._enable_blur = True
                def _on_ser_enter(_e=None, lbl=v_lbl):
                    if getattr(lbl, '_hovered', False):
                        return
                    lbl._hovered = True
                    sharp = getattr(lbl, '_ctk_sharp_img', None)
                    if sharp:
                        try:
                            lbl.configure(image=sharp)
                            lbl._ctk_img_ref = sharp
                        except Exception:
                            pass

                def _on_ser_leave(_e=None, c=v_card, lbl=v_lbl):
                    def _check_leave():
                        try:
                            if not c.winfo_exists():
                                return
                            x, y = c.winfo_pointerxy()
                            w = c.winfo_containing(x, y)
                            is_inside = False
                            while w:
                                if w == c:
                                    is_inside = True
                                    break
                                w = getattr(w, 'master', None)
                            if not is_inside:
                                lbl._hovered = False
                                blurred = getattr(lbl, '_ctk_blurred_img', None)
                                if blurred:
                                    lbl.configure(image=blurred)
                                    lbl._ctk_img_ref = blurred
                        except Exception:
                            pass
                    c.after(40, _check_leave)

                for _w in (v_card, v_thumb_holder, v_lbl, v_info, v_title_lbl, v_heart_btn, *s_cover_widgets, *sub_badge_widgets):
                    try:
                        _w.bind('<Enter>', _on_ser_enter, add='+')
                        _w.bind('<Leave>', _on_ser_leave, add='+')
                    except Exception:
                        pass

    def _discover_series_videos_bg(self, series_base, series_frame, series_grid, series_count_lbl,
                                   existing_vids, seen_urls, gen):
        """Perform background search across site to discover all episodes in the series."""
        def _worker():
            site_key = getattr(self, '_site_key', 'MissAV')
            cur_vid = getattr(self, '_preview_video', {}) or {}
            is_search_all = bool(getattr(self, '_search_all_mode', False) or getattr(self, '_search_all_active', False))
            target_sites = list(SITES.keys()) if is_search_all else [site_key]
            new_found = []

            # 1. If HanimeTV in target_sites or (is_search_all and current video is HanimeTV)
            if 'HanimeTV' in target_sites or (not is_search_all and (site_key == 'HanimeTV' or 'hanime.tv' in str(cur_vid.get('url', '')).lower())):
                try:
                    from M3U8Sites.SiteHanimeTV import _load_catalog, _load_duration_cache
                    cat = _load_catalog()
                    dur_cache = _load_duration_cache()
                    for item in cat:
                        slug = str(item.get('slug') or '')
                        name = item.get('name') or slug
                        cand_url = f'https://hanime.tv/videos/hentai/{slug}'
                        if cand_url in seen_urls:
                            continue
                        cand = {
                            'title': name,
                            'url': cand_url,
                            'thumbnail': item.get('poster_url') or item.get('cover_url') or '',
                            'img': item.get('poster_url') or item.get('cover_url') or '',
                            'duration': dur_cache.get(slug) or '',
                            'site_name': 'HanimeTV',
                        }
                        if is_same_series(cand, cur_vid):
                            _, p_num, p_lbl = extract_series_info(cand)
                            cand['_series_part'] = p_num
                            cand['_series_label'] = p_lbl
                            seen_urls.add(cand_url)
                            new_found.append(cand)
                except Exception:
                    pass

            # 2. General site search across target sites
            for s_key in target_sites:
                if s_key == 'HanimeTV':
                    continue  # Already handled via in-memory catalog
                browser_cls = SITES.get(s_key, {}).get('browser')
                if browser_cls and hasattr(browser_cls, 'search'):
                    search_terms = [series_base]
                    words = series_base.split()
                    if len(words) >= 3:
                        search_terms.append(' '.join(words[:2]))
                    for term in search_terms:
                        try:
                            extra_vids = browser_cls.search(term)
                        except Exception:
                            extra_vids = []
                        if isinstance(extra_vids, list):
                            for ev in extra_vids:
                                if not isinstance(ev, dict):
                                    continue
                                ev_url = (ev.get('url') or ev.get('page_url') or '').strip()
                                if ev_url and ev_url not in seen_urls and is_same_series(ev, cur_vid):
                                    _, p_num, p_lbl = extract_series_info(ev)
                                    ev['_series_part'] = p_num
                                    ev['_series_label'] = p_lbl
                                    ev['site_name'] = ev.get('site_name') or s_key
                                    seen_urls.add(ev_url)
                                    new_found.append(ev)

            if not new_found:
                return

            all_series = list(existing_vids) + new_found

            def _apply():
                if self._is_closing or gen != getattr(self, '_preview_gen', 0):
                    return
                self._render_more_series_cards(series_frame, series_grid, series_count_lbl, all_series, gen)

            try:
                self._ui(_apply, gen=gen)
            except Exception:
                pass

        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            pass

    def _enrich_category_tags(self, cat_grid, gen):
        """Fetch tags for a bounded set of category candidates in the background,
        then re-rank the row once tag data arrives."""
        pool = getattr(self, '_preview_category_pool', None)
        if not pool or getattr(self, '_preview_category_enriching', False):
            return
        self._preview_category_enriching = True
        to_fetch = []
        for v in pool:
            if v.get('_tag_set'):
                continue
            code = video_code(v)
            if not code:
                continue
            to_fetch.append((v, code))
        if not to_fetch:
            return
        to_fetch = to_fetch[:8]

        def _fetch_one(item):
            v, code = item
            try:
                from metadata_fetcher import fetch_tags_for_code
                return v, fetch_tags_for_code(code)
            except Exception:
                return v, []

        def _worker():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            results = {}
            try:
                with ThreadPoolExecutor(max_workers=4) as ex:
                    futs = [ex.submit(_fetch_one, it) for it in to_fetch]
                    try:
                        for f in as_completed(futs, timeout=15):
                            v, tags = f.result()
                            results[id(v)] = tags
                    except Exception:
                        pass
            except Exception:
                pass

            def _apply():
                if self._is_closing or gen != getattr(self, '_preview_gen', 0):
                    return
                for v, _code in to_fetch:
                    tags = results.get(id(v)) or []
                    v['tags'] = list(tags)
                    v['_tag_set'] = {str(t).strip().lower() for t in tags if str(t).strip()}
                try:
                    self._refresh_category_cards(cat_grid)
                except Exception:
                    pass
            try:
                self._ui(_apply)
            except Exception:
                pass

        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            self._preview_category_enriching = False

    def _refresh_category_cards(self, cat_grid=None):
        """Re-rank the category pool with the latest tag data and re-render it."""
        if self._is_closing or getattr(self, '_browse_mode', '') != 'preview':
            return
        gen = getattr(self, '_preview_gen', 0)
        if getattr(self, '_preview_category_gen', -1) != gen:
            return
        cat_grid = cat_grid or getattr(self, '_preview_category_grid', None)
        if cat_grid is None or not cat_grid.winfo_exists():
            return
        pool = getattr(self, '_preview_category_pool', None) or []
        ranked = self._rank_category_pool(pool)
        if not ranked:
            return
        self._render_more_category_cards(cat_grid, ranked[:3], gen)

    def _clear_preview_area(self):
        self._stop_preview_player()
        self._preview_canvas = None
        area = getattr(self, '_preview_area', None)
        if not area:
            return
        for child in area.winfo_children():
            try:
                child.destroy()
            except tk.TclError:
                pass
        self._preview_thumb_refs = []

    def _render_preview_loading(self, video: dict):
        self._clear_preview_area()
        area = self._preview_area

        shell = ctk.CTkFrame(area, fg_color=BG_DARK, corner_radius=0)
        shell.pack(fill='both', expand=True, padx=16, pady=16)

        top_bar = ctk.CTkFrame(shell, fg_color='transparent')
        top_bar.pack(fill='x', pady=(0, 8))
        ctk.CTkButton(
            top_bar, text='←  ' + T('preview_back'), width=140, height=32,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, border_width=1, border_color=BORDER_HOVER,
            corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 11, 'bold'),
            command=lambda: self._set_browse_mode('grid')).pack(side='left')

        box = ctk.CTkFrame(
            shell, fg_color=BG_CARD, border_width=1,
            border_color=BORDER_CARD, corner_radius=CARD_RADIUS)
        box.pack(fill='both', expand=True, pady=(8, 0))

        title = str((video or {}).get('title') or '')
        ctk.CTkLabel(
            box, text=T('preview_loading'), text_color=ACCENT,
            font=(ui_font(), 16, 'bold')).pack(expand=True, pady=(60, 10))

        if title:
            ctk.CTkLabel(
                box, text=title, text_color=TEXT_PRI,
                font=(ui_font(), 14), wraplength=680,
                justify='center').pack(pady=(0, 60), padx=24)

    def _apply_preview_source(self, gen: int, source: PreviewSource):
        if getattr(self, '_is_closing', False) or gen != getattr(self, '_preview_gen', 0):
            return
        self._preview_source = source
        try:
            analytics.track_preview_open(source.site_name or getattr(self, '_site_key', 'Video'), source.media_kind or 'HLS')
        except Exception:
            pass
        self._render_preview_detail(source)

    def _render_preview_detail(self, source: PreviewSource):
        self._clear_preview_area()
        area = self._preview_area

        shell = ctk.CTkFrame(area, fg_color=BG_DARK, corner_radius=0)
        shell.pack(fill='both', expand=True, padx=(12, 0), pady=0)

        # Single Scroll Container: video player & related videos scroll together using one scroll bar
        main_scroll = ctk.CTkScrollableFrame(
            shell, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        main_scroll.pack(fill='both', expand=True)

        split = ctk.CTkFrame(main_scroll, fg_color='transparent')
        split.pack(fill='both', expand=True)

        # Right Sidebar Pane (Related Videos) - packed FIRST with width=340
        right_sidebar = ctk.CTkFrame(split, width=340, fg_color='transparent')
        right_sidebar.pack_propagate(False)
        right_sidebar.pack(side='right', fill='y', padx=(0, 24))

        # Left Main Pane (Video Player + Info + Bottom Category Cards) - packed SECOND with expand=True
        left_main = ctk.CTkFrame(split, fg_color='transparent')
        left_main.pack(side='left', fill='both', expand=True, padx=(0, 16))

        # ── 1. EMBEDDED VIDEO PLAYER FRAME ─────────────────────────────────
        player_container = ctk.CTkFrame(
            left_main, fg_color='#000000', corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD, height=560)
        player_container.pack(fill='x', pady=(0, 12))
        player_container.pack_propagate(False)
        self._player_container_ref = player_container
        self._bind_player_keyboard_controls(player_container)

        # Canvas for VLC embedding
        canvas = tk.Canvas(player_container, bg='#000000', highlightthickness=0)
        canvas.pack(fill='both', expand=True)
        canvas.bind('<Double-Button-1>', self._toggle_fullscreen_player, add='+')
        self._preview_canvas = canvas

        # Control overlay bar below canvas
        self._build_player_controls(player_container, fullscreen=False)

        # Start in-app VLC player if stream is playable
        if source.is_playable:
            vlc_ok = self._init_vlc_player(source.media_url, source.headers, canvas)
            if vlc_ok:
                self._bind_player_keyboard_controls(player_container)
                self._bind_player_keyboard_controls(canvas)
            else:
                self._show_preview_player_fallback(canvas, player_container, source)
        else:
            ctk.CTkLabel(
                canvas, text=source.error or T('preview_no_source'),
                text_color=ERROR_C, font=(ui_font(), 14, 'bold')).place(relx=0.5, rely=0.5, anchor='center')

        # ── 2. VIDEO TITLE & ACTION ROW ─────────────────────────────────────
        title_box = ctk.CTkFrame(left_main, fg_color='transparent')
        title_box.pack(fill='x', pady=(0, 8))

        title_text = source.title or (self._preview_video or {}).get('title', '') or source.page_url

        # Selectable Title (User can select text with cursor and copy via Ctrl+C)
        t_len = len(title_text)
        tb_height = 32 if t_len <= 50 else (54 if t_len <= 100 else (76 if t_len <= 160 else 98))
        title_tb = ctk.CTkTextbox(
            title_box,
            fg_color='transparent',
            border_width=0,
            wrap='word',
            activate_scrollbars=False,
            font=(ui_font(), 16, 'bold'),
            text_color=TEXT_PRI,
            height=tb_height
        )
        try:
            title_tb._textbox.configure(padx=0, pady=0)
        except Exception:
            pass
        title_tb.insert('1.0', title_text)
        title_tb.configure(state='disabled')
        title_tb.pack(fill='x', pady=(0, 6), anchor='w')

        meta_row = ctk.CTkFrame(title_box, fg_color='transparent')
        meta_row.pack(fill='x')

        badges = ctk.CTkFrame(meta_row, fg_color='transparent')
        badges.pack(side='left')

        if source.site_name:
            ctk.CTkLabel(
                badges, text=source.site_name, text_color=WHITE,
                fg_color=ACCENT, corner_radius=4, height=22, padx=8,
                font=(ui_font(), 10, 'bold')).pack(side='left', padx=(0, 6))

        format_str = (source.media_kind or 'HLS').upper()
        ctk.CTkLabel(
            badges, text=format_str, text_color=TEXT_PRI,
            fg_color=BG_CARD, border_width=1, border_color=BORDER_CARD,
            corner_radius=4, height=22, padx=8,
            font=(ui_font(), 10)).pack(side='left', padx=(0, 6))

        dur_str = source.duration or (self._preview_video or {}).get('duration', '') or ''
        if dur_str:
            ctk.CTkLabel(
                badges, text=dur_str, text_color=TEXT_PRI,
                fg_color=BG_CARD, border_width=1, border_color=BORDER_CARD,
                corner_radius=4, height=22, padx=8,
                font=(ui_font(), 10)).pack(side='left')

        try:
            preview_vid = dict(getattr(self, '_preview_video', None) or {})
            preview_vid['url'] = preview_vid.get('url') or source.page_url
            preview_vid['title'] = preview_vid.get('title') or source.title
            _sub_dest_var = getattr(self, '_dest_var', None)
            _sub_dest = _sub_dest_var.get() if _sub_dest_var is not None else getattr(self, '_dest', '')
            card_badges = _detect_video_card_badges(preview_vid, dest=_sub_dest)
            for b in card_badges:
                _text = b['text']
                _color = b['color']
                ctk.CTkLabel(
                    badges, text=_text, text_color=_color,
                    fg_color=('#101018', '#101018'), border_width=1, border_color=_color,
                    corner_radius=4, height=22, padx=8,
                    font=('Consolas', 10, 'bold')).pack(side='left', padx=(6, 0))
        except Exception:
            pass

        url = source.page_url or (self._preview_video or {}).get('url', '')

        # Automatically record view history
        config.add_view_history({
            'url': url,
            'title': title_text,
            'thumbnail': source.thumbnail or (self._preview_video or {}).get('thumbnail', '') or (self._preview_video or {}).get('img', ''),
            'duration': dur_str,
            'site_name': source.site_name or (self._preview_video or {}).get('site_name', ''),
        })

        actions_right = ctk.CTkFrame(meta_row, fg_color='transparent')
        actions_right.pack(side='right')

        def _add_to_queue_direct():
            dest = getattr(self, '_dest_var', None)
            dest_val = dest.get() if dest else 'download'
            evidence = self._source_subtitle_evidence_for_video(self._preview_video) if hasattr(self, '_source_subtitle_evidence_for_video') else ()

            items_now = getattr(self, '_dlmgr').get_items() if hasattr(self, '_dlmgr') else []
            curr_item = next((i for i in items_now if i.url == url), None)

            status_lbl = getattr(self, '_status_lbl', None)
            if curr_item is not None:
                self._dlmgr.remove_item(url)
                if status_lbl:
                    status_lbl.configure(text=f"🗑 Removed from queue: {title_text[:40]}")
            else:
                if url and M3U8Sites.VaildateUrl(url):
                    self._dlmgr.add_item(
                        url, state='等待中', dest=dest_val,
                        source_subtitle_evidence=evidence
                    )
                if status_lbl:
                    status_lbl.configure(text=f"📋 {T('add_to_queue')}: {title_text[:40]}")

            self._update_preview_action_buttons()

        def _direct_download():
            dest = getattr(self, '_dest_var', None)
            dest_val = dest.get() if dest else 'download'
            evidence = self._source_subtitle_evidence_for_video(self._preview_video) if hasattr(self, '_source_subtitle_evidence_for_video') else ()

            items_now = getattr(self, '_dlmgr').get_items() if hasattr(self, '_dlmgr') else []
            curr_item = next((i for i in items_now if i.url == url), None)

            is_enqueued = False
            if curr_item is not None:
                is_active = (hasattr(self._dlmgr, '_active') and url in self._dlmgr._active)
                is_pending = (hasattr(self._dlmgr, '_pending') and any(t.url == url for t in self._dlmgr._pending))
                is_downloading_state = (curr_item.state in ('下載中', '準備中', '字幕準備中', '字幕辨識中', '字幕翻譯中'))
                is_enqueued = is_active or is_pending or is_downloading_state

            status_lbl = getattr(self, '_status_lbl', None)
            if curr_item is not None and curr_item.state == '已下載':
                # Download is completed: redirect user to the download page
                self._select_tab('download')
                return
            elif is_enqueued:
                self._dlmgr.remove_item(url)
                if status_lbl:
                    status_lbl.configure(text=f"🛑 Download cancelled: {title_text[:40]}")
            else:
                if url and M3U8Sites.VaildateUrl(url):
                    self._dlmgr.add_item(
                        url, state='等待中', dest=dest_val,
                        source_subtitle_evidence=evidence
                    )
                    self._dlmgr.enqueue(url, dest_val)
                if status_lbl:
                    status_lbl.configure(text=f"🚀 {T('preview_downloading')}: {title_text[:40]}")

            self._update_preview_action_buttons()

        is_saved = config.is_video_saved(url)

        def _toggle_save():
            v_info = {
                'url': url,
                'title': title_text,
                'thumbnail': source.thumbnail or (self._preview_video or {}).get('thumbnail', '') or (self._preview_video or {}).get('img', ''),
                'duration': dur_str,
                'site_name': source.site_name or (self._preview_video or {}).get('site_name', ''),
            }
            new_saved = config.toggle_saved_video(v_info)
            status_lbl = getattr(self, '_status_lbl', None)
            if status_lbl:
                status_lbl.configure(text=T('video_saved_toast') if new_saved else T('video_removed_toast'))
            p_btn = getattr(self, '_preview_heart_btn', None)
            if p_btn:
                self._animate_heart_btn(p_btn, new_saved)
            self._update_card_heart_btn(url, animate=False)
            if getattr(self, '_active_settings_cat', '') == 'saved':
                self._switch_settings_cat('saved')

        # Heart button with SVG heart icon
        heart_img = getattr(self, '_heart_active_icon', None) if is_saved else getattr(self, '_heart_icon', None)
        heart_text = '' if heart_img else ('♥' if is_saved else '♡')
        self._preview_heart_btn = ctk.CTkButton(
            actions_right, text=heart_text,
            image=heart_img,
            width=34, height=32,
            corner_radius=CONTROL_RADIUS,
            fg_color='transparent',
            border_width=1,
            border_color=ACCENT if is_saved else BORDER_HOVER,
            hover_color=BG_CARD_HOVER,
            text_color=ACCENT if is_saved else TEXT_PRI,
            command=_toggle_save
        )
        self._preview_heart_btn.pack(side='left', padx=(0, 6))

        # Add to Queue button (Separate queue functionality, solid green when active)
        self._preview_q_btn = ctk.CTkButton(
            actions_right, text=' ' + T('add_to_queue'), height=32, width=110,
            image=getattr(self, '_plus_icon', None),
            corner_radius=CONTROL_RADIUS,
            fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            font=(ui_font(), 10),
            command=_add_to_queue_direct
        )
        self._preview_q_btn.pack(side='left', padx=(0, 6))

        # Download button (Ghost button style)
        self._preview_dl_btn = ctk.CTkButton(
            actions_right, text=' ' + T('download_btn'), height=32, width=110,
            image=getattr(self, '_dl_icon', None),
            corner_radius=CONTROL_RADIUS,
            fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            font=(ui_font(), 10, 'bold'),
            command=_direct_download
        )
        self._preview_dl_btn.pack(side='left')

        # Synchronize action button visuals with download manager state
        self._update_preview_action_buttons()

        # ── 3. INFO & DESCRIPTION PANE ──────────────────────────────────────
        info_card = ctk.CTkFrame(
            left_main, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD)
        info_card.pack(fill='x', pady=(0, 16))

        info_hdr = ctk.CTkFrame(info_card, fg_color='transparent')
        info_hdr.pack(fill='x', padx=16, pady=(12, 8))
        ctk.CTkLabel(
            info_hdr, text='Info', text_color=ACCENT,
            font=(ui_font(), 13, 'bold')).pack(side='left')

        ctk.CTkFrame(info_card, height=1, fg_color=BORDER).pack(fill='x', padx=16)

        info_body = ctk.CTkFrame(info_card, fg_color='transparent')
        info_body.pack(fill='x', padx=16, pady=12)
        info_body.grid_columnconfigure(0, weight=1)

        desc_box = ctk.CTkFrame(info_body, fg_color='transparent')
        desc_box.grid(row=0, column=0, sticky='nsew')

        self._preview_info_labels = {}
        self._preview_chip_rows = {}

        def _chips_row(label, kind, items, urls=None):
            r = ctk.CTkFrame(desc_box, fg_color='transparent')
            r.pack(fill='x', pady=4)
            ctk.CTkLabel(
                r, text=label, text_color=TEXT_DIM,
                font=(ui_font(), 11, 'bold'), width=120, anchor='w').pack(side='left')
            flow = ctk.CTkFrame(r, fg_color='transparent')
            flow.pack(side='left', fill='x', expand=True)
            self._preview_chip_rows[kind] = flow
            self._render_preview_chips(kind, items, urls)

        def _desc_row(label, val, can_copy=False, key=''):
            r = ctk.CTkFrame(desc_box, fg_color='transparent')
            r.pack(fill='x', pady=4)
            ctk.CTkLabel(
                r, text=label, text_color=TEXT_DIM,
                font=(ui_font(), 11, 'bold'), width=120, anchor='w').pack(side='left')
            val_lbl = ctk.CTkLabel(
                r, text=val, text_color=TEXT_PRI,
                font=(ui_font(), 11), anchor='w', wraplength=400, justify='left')
            val_lbl.pack(side='left', fill='x', expand=True)
            if key:
                self._preview_info_labels[key] = val_lbl

            if can_copy:
                def _copy():
                    try:
                        self.clipboard_clear()
                        self.clipboard_append(val)
                    except Exception:
                        pass
                ctk.CTkButton(
                    r, text='Copy', width=48, height=22,
                    corner_radius=4, fg_color='transparent',
                    border_width=1, border_color=BORDER_HOVER,
                    hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                    font=(ui_font(), 9), command=_copy).pack(side='right', padx=(6, 0))

        # Metadata fields: Actor, Actress, Director, Studio, Tags, Duration, Format, URL
        payload = self._preview_info_payload()
        _desc_row('Actor:', payload['actor'], key='actor')
        _chips_row('Actress:', 'actress',
                   self._preview_list('actress', 'actresses', 'model', 'models', 'cast'),
                   (self._preview_video or {}).get('actress_urls') or [])
        _chips_row('Director:', 'director',
                   self._preview_list('director', 'directors'))
        _chips_row('Studio:', 'studio',
                   self._preview_list('studio', 'maker', 'publisher', 'production'))
        _chips_row('Tags:', 'tags',
                   self._preview_list('tags', 'categories', 'keywords'))
        _desc_row('Duration:', payload['duration'], key='duration')
        _desc_row('Media Format:', payload['format'], key='format')
        _desc_row('Page URL:', payload['url'], can_copy=True, key='url')
        _desc_row('Media Stream:', payload['stream'], can_copy=True, key='stream')

        # Actress portraits — inline, horizontally scrollable row below the
        # Media Stream link, arranged in the order of the actresses.
        photos_scroll = ctk.CTkScrollableFrame(
            info_body, fg_color='transparent',
            orientation='horizontal', height=138,
            corner_radius=6,
            scrollbar_button_color=BG_SIDEBAR,
            scrollbar_button_hover_color=BG_CARD_HOVER)
        self._preview_photos_scroll = photos_scroll
        self._preview_photos_shown = False

        photos = (self._preview_video or {}).get('actress_photos') or []
        single = (self._preview_video or {}).get('actress_photo') or ''
        if photos or single:
            self._load_actress_photos(photos or [single])

        # ── 4. "MORE FROM THIS CATEGORY" BOTTOM SECTION ─────────────────────
        cat_hdr = ctk.CTkFrame(left_main, fg_color='transparent')
        cat_hdr.pack(fill='x', pady=(4, 6))
        ctk.CTkLabel(
            cat_hdr, text=T('preview_more_from_category', fallback='More from this category'),
            text_color=TEXT_PRI,
            font=(ui_font(), 13, 'bold')).pack(side='left')

        cat_grid = ctk.CTkFrame(left_main, fg_color='transparent')
        cat_grid.pack(fill='x', pady=(0, 16))
        for c in range(3):
            cat_grid.grid_columnconfigure(c, weight=1, uniform='cat_cols')

        # ── 4b. "MORE FROM THIS SERIES" BOTTOM SECTION ──────────────────────
        series_frame = ctk.CTkFrame(left_main, fg_color='transparent')
        series_hdr = ctk.CTkFrame(series_frame, fg_color='transparent')
        series_hdr.pack(fill='x', pady=(4, 6))
        ctk.CTkLabel(
            series_hdr, text=T('preview_more_from_series', fallback='More from this series'),
            text_color=TEXT_PRI,
            font=(ui_font(), 13, 'bold')).pack(side='left')
        series_count_lbl = ctk.CTkLabel(
            series_hdr, text='', text_color=TEXT_DIM,
            font=(ui_font(), 10, 'bold'))
        series_count_lbl.pack(side='left', padx=(8, 0))

        series_grid = ctk.CTkFrame(series_frame, fg_color='transparent')
        series_grid.pack(fill='x', pady=(0, 16))

        # Collect candidate pool for recommendations (direct related + browse grid + saved + view history)
        current_url = url
        all_candidates = []
        seen_cand_urls = set()
        is_search_all = bool(getattr(self, '_search_all_mode', False) or getattr(self, '_search_all_active', False))
        selected_site = getattr(self, '_site_key', '') or config.site_name_from_url(current_url) or (self._preview_video or {}).get('site_name', '')
        norm_sel_site = (selected_site or '').lower()

        def _add_cand(v):
            if not isinstance(v, dict):
                return
            u = (v.get('url') or v.get('page_url') or '').strip()
            if not u or u == current_url or u in seen_cand_urls:
                return
            cand_site = (v.get('site_name') or v.get('site') or config.site_name_from_url(u) or '').lower()
            if not is_search_all and norm_sel_site and cand_site and cand_site != norm_sel_site:
                return
            seen_cand_urls.add(u)
            cand_tags = []
            for k in ('tags', 'categories', 'keywords'):
                raw = v.get(k)
                if isinstance(raw, (list, tuple, set)):
                    for x in raw:
                        s = str(x).strip()
                        if s and s not in cand_tags:
                            cand_tags.append(s)
                elif raw:
                    for part in str(raw).split(','):
                        s = part.strip()
                        if s and s not in cand_tags:
                            cand_tags.append(s)
            all_candidates.append({
                'url': u,
                'title': v.get('title') or u,
                'thumbnail': v.get('thumbnail') or v.get('img') or '',
                'duration': v.get('duration') or '',
                'site_name': v.get('site_name') or config.site_name_from_url(u),
                'tags': cand_tags,
                'cover_url': v.get('cover_url') or '',
            })

        for v in (self._preview_video or {}).get('related_vids', []):
            _add_cand(v)

        for v in getattr(self, '_videos', []):
            _add_cand(v)

        for v in config.get_saved_videos():
            _add_cand(v)

        for v in config.get_view_history():
            _add_cand(v)

        # HanimeTV instant in-memory catalog candidate backfill
        if (selected_site == 'HanimeTV' or 'hanime.tv' in current_url.lower()) and len(all_candidates) < 25:
            try:
                from M3U8Sites.SiteHanimeTV import _load_catalog, _load_duration_cache
                cat = _load_catalog()
                dur_cache = _load_duration_cache()
                for item in cat:
                    slug = str(item.get('slug') or '')
                    cand_url = f'https://hanime.tv/videos/hentai/{slug}'
                    _add_cand({
                        'title': item.get('name') or slug,
                        'url': cand_url,
                        'thumbnail': item.get('poster_url') or item.get('cover_url') or '',
                        'img': item.get('poster_url') or item.get('cover_url') or '',
                        'duration': dur_cache.get(slug) or '',
                        'site_name': 'HanimeTV',
                        'cover_url': item.get('poster_url') or item.get('cover_url') or '',
                        'tags': item.get('tags') or item.get('genres') or [],
                    })
                    if len(all_candidates) >= 30:
                        break
            except Exception:
                pass

        # Fallback series search if candidate pool is small (< 16 items)
        if len(all_candidates) < 16:
            import re
            code_m = re.search(r'([a-zA-Z]{2,6})[\-_ ]*\d{3,5}', title_text or url, re.IGNORECASE)
            search_term = code_m.group(1).upper() if code_m else ''
            if search_term:
                try:
                    target_sites = list(SITES.keys()) if is_search_all else [selected_site or getattr(self, '_site_key', 'MissAV')]
                    for s_k in target_sites:
                        browser_cls = SITES.get(s_k, {}).get('browser')
                        if browser_cls and hasattr(browser_cls, 'search'):
                            extra_vids = browser_cls.search(search_term)
                            if isinstance(extra_vids, list):
                                for ev in extra_vids:
                                    _add_cand(ev)
                except Exception:
                    pass

        # If still < 16, search using tags from the preview video
        if len(all_candidates) < 16:
            v_tags = (self._preview_video or {}).get('tags') or []
            tag_terms = [t for t in v_tags if isinstance(t, str) and len(t) >= 2]
            target_sites = list(SITES.keys()) if is_search_all else [selected_site or getattr(self, '_site_key', 'MissAV')]
            for term in tag_terms[:2]:
                for s_k in target_sites:
                    try:
                        browser_cls = SITES.get(s_k, {}).get('browser')
                        if browser_cls and hasattr(browser_cls, 'search'):
                            extra_vids = browser_cls.search(term)
                            if isinstance(extra_vids, list):
                                for ev in extra_vids:
                                    _add_cand(ev)
                    except Exception:
                        pass
                if len(all_candidates) >= 20:
                    break

        # Dynamic rotation per preview session so every session shows fresh related videos
        shift = (getattr(self, '_preview_gen', 0) * 3) % max(len(all_candidates), 1)
        rotated_pool = all_candidates[shift:] + all_candidates[:shift]

        # "More from this category": prefer the videos sharing the most tags with
        # the currently played video. Same-code cross-site copies are excluded.
        current_code = video_code(self._preview_video or {})
        tag_pool = []
        for i, v in enumerate(rotated_pool):
            if current_code and video_code(v) == current_code:
                continue
            v['_tag_set'] = self._video_tag_set(v)
            v['_tag_order'] = i
            tag_pool.append(v)
        self._preview_category_pool = tag_pool
        self._preview_category_grid = cat_grid
        self._preview_category_gen = getattr(self, '_preview_gen', 0)
        self._preview_category_enriching = False

        ranked = self._rank_category_pool(tag_pool)
        display_vids = ranked[:3] or rotated_pool[:3]
        used_category_urls = {v['url'] for v in display_vids}

        self._render_more_category_cards(cat_grid, display_vids, self._preview_gen)
        self._enrich_category_tags(cat_grid, self._preview_gen)

        # Series Detection & Discovery
        cur_series_base, cur_series_part, cur_series_label = extract_series_info(self._preview_video or {})
        initial_series_vids = []
        seen_series_urls = set()

        if cur_series_base:
            cur_item = dict(self._preview_video or {})
            cur_item['_series_part'] = cur_series_part
            cur_item['_series_label'] = cur_series_label
            if current_url:
                cur_item['url'] = current_url
                seen_series_urls.add(current_url)
                initial_series_vids.append(cur_item)

            for cand in all_candidates:
                cand_u = (cand.get('url') or cand.get('page_url') or '').strip()
                if cand_u and cand_u not in seen_series_urls and is_same_series(cand, self._preview_video):
                    _, cand_p, cand_l = extract_series_info(cand)
                    cand['_series_part'] = cand_p
                    cand['_series_label'] = cand_l
                    seen_series_urls.add(cand_u)
                    initial_series_vids.append(cand)

        if len(initial_series_vids) >= 1:
            self._render_more_series_cards(series_frame, series_grid, series_count_lbl, initial_series_vids, self._preview_gen)
        else:
            series_frame.pack_forget()

        if cur_series_base:
            self._discover_series_videos_bg(
                cur_series_base, series_frame, series_grid, series_count_lbl,
                initial_series_vids, seen_series_urls, self._preview_gen
            )

        # ── 5. RELATED VIDEOS (DYNAMIC RESPONSIVE CONTAINER) ─────────────────
        bottom_related = ctk.CTkFrame(left_main, fg_color='transparent')
        bottom_related.pack(fill='x', pady=(8, 16))

        related_candidates = [v for v in rotated_pool if v['url'] not in used_category_urls]
        related_vids = list(related_candidates[:10])
        if len(related_vids) < 10:
            for v in rotated_pool:
                if v not in related_vids and v.get('url') != current_url:
                    related_vids.append(v)
                    if len(related_vids) >= 10:
                        break
        if not related_vids:
            related_vids = list(rotated_pool[:10])

        self._preview_left_main = left_main
        self._preview_right_sidebar = right_sidebar
        self._preview_bottom_related = bottom_related
        self._preview_related_vids = related_vids
        self._preview_related_pool = rotated_pool
        self._preview_shown_related_urls = {v.get('url') for v in related_vids if v.get('url')}
        self._preview_layout_mode = None
        self._preview_layout_cols = None

        try:
            w = self.winfo_width() / max(self._get_window_scaling(), 1.0)
            if w <= 1:
                w = 1200
        except Exception:
            w = 1200

        self._update_preview_layout(w)

    # ── Download Tab ─────────────────────────────────────────────────
    def _build_download_tab(self):
        tab = self._tab_frames['download']

        # ── Input section ───────────────────────────────────────────
        input_frame = ctk.CTkFrame(tab, fg_color=BG_SECTION, corner_radius=0)
        input_frame.pack(fill='x')

        # Save location (Save to field with embedded browse & open icons + speed dropdown inline)
        row1 = ctk.CTkFrame(input_frame, fg_color='transparent')
        row1.pack(fill='x', padx=20, pady=(16, 12))

        ctk.CTkLabel(row1, text=T('save_location'), text_color=TEXT_SEC, width=86,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')

        # Container for Save To entry with integrated browse & open icons inside
        browse_save_to = ctk.CTkFrame(
            row1, fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            corner_radius=CONTROL_RADIUS, height=36
        )
        browse_save_to.pack(side='left', fill='x', expand=True, padx=(0, 10))
        browse_save_to.pack_propagate(False)

        self._dest_var = ctk.StringVar(value=self._dest)
        dest_entry = ctk.CTkEntry(
            browse_save_to, textvariable=self._dest_var,
            height=34, corner_radius=0,
            fg_color='transparent', border_width=0,
            text_color=TEXT_PRI, font=(ui_font(), 11)
        )
        dest_entry.pack(side='left', fill='x', expand=True, padx=(8, 4))

        # Integrated Browse & Open icons inside entry container
        if getattr(self, '_browse_icon', None):
            btn_browse = ctk.CTkButton(
                browse_save_to, text='', image=self._browse_icon, width=28, height=28,
                fg_color='transparent', hover_color=BG_CARD_HOVER, corner_radius=4,
                command=self._pick_dest
            )
            btn_browse.pack(side='right', padx=(0, 4))
        else:
            btn_browse = ctk.CTkButton(
                browse_save_to, text=T('browse_folder'), width=60, height=28,
                fg_color='transparent', hover_color=BG_CARD_HOVER, corner_radius=4,
                text_color=TEXT_PRI, font=(ui_font(), 10),
                command=self._pick_dest
            )
            btn_browse.pack(side='right', padx=(0, 4))

        if getattr(self, '_open_icon', None):
            btn_open = ctk.CTkButton(
                browse_save_to, text='', image=self._open_icon, width=28, height=28,
                fg_color='transparent', hover_color=BG_CARD_HOVER, corner_radius=4,
                command=self._open_dest_folder
            )
            btn_open.pack(side='right', padx=(0, 2))
        else:
            btn_open = ctk.CTkButton(
                browse_save_to, text=T('open_btn'), width=50, height=28,
                fg_color='transparent', hover_color=BG_CARD_HOVER, corner_radius=4,
                text_color=TEXT_PRI, font=(ui_font(), 10),
                command=self._open_dest_folder
            )
            btn_open.pack(side='right', padx=(0, 2))

        # Speed limit dropdown inline in Row 1 on right
        speed = ctk.CTkFrame(row1, fg_color='transparent')
        speed.pack(side='right')
        ctk.CTkLabel(speed, text=T('speed_limit'), text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(side='left', padx=(0, 8))
        self._speed_var = ctk.StringVar(value=self._speed_label())
        ctk.CTkOptionMenu(
            speed, values=self._speed_values(), variable=self._speed_var,
            command=self._on_speed_change, width=118, height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color=BG_CARD, button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE, dynamic_resizing=False,
            font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)
        ).pack(side='left')

        # Download URL row with inline action controls (Download dropdown, Cancel All, Clear)
        row2 = ctk.CTkFrame(input_frame, fg_color='transparent')
        row2.pack(fill='x', padx=20, pady=(0, 16))

        ctk.CTkLabel(row2, text=T('url_label'), text_color=TEXT_SEC, width=86,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')

        self._dl_url_var = ctk.StringVar(value=self._url_input)
        ctk.CTkEntry(
            row2, textvariable=self._dl_url_var,
            height=36, corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            text_color=TEXT_PRI, font=('Consolas', 10)
        ).pack(side='left', fill='x', expand=True, padx=(0, 10))

        # Inline actions right side of Row 2
        # Download dropdown (Download & Download All) - styled identically to Home page select dropdown
        dl_opt_single = T('download_btn')
        dl_opt_all = T('download_all_btn')
        self._dl_action_var = ctk.StringVar(value=dl_opt_single)

        def _on_dl_action(choice: str):
            self._dl_action_var.set(choice)
            if choice == dl_opt_all or T('download_all_btn') in choice:
                self._download_all()
            else:
                self._download_url()

        ctk.CTkOptionMenu(
            row2, values=[dl_opt_single, dl_opt_all],
            variable=self._dl_action_var,
            command=_on_dl_action, width=130, height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color=BG_CARD, button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE, dynamic_resizing=False,
            font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)
        ).pack(side='left', padx=(0, 6))

        ctk.CTkButton(
            row2, text=T('cancel_all'), width=88, height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=ERROR_C,
            command=self._cancel_all
        ).pack(side='left', padx=(0, 6))

        ctk.CTkButton(
            row2, text=T('clear_list'), width=70, height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            command=self._clear_queue
        ).pack(side='left')

        # Separator under input section
        ctk.CTkFrame(tab, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')

        # ── Download list ───────────────────────────────────────────
        self._dl_scroll = ctk.CTkScrollableFrame(
            tab, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        self._dl_scroll.pack(fill='both', expand=True)

    def _build_update_card(self, content):
        upd = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                           border_width=1, border_color=BORDER_CARD)
        upd.pack(fill='x', pady=(0, 16), padx=(0, 18))

        upd_hdr = ctk.CTkFrame(upd, fg_color='transparent')
        upd_hdr.pack(fill='x', padx=20, pady=(16, 12))
        ctk.CTkLabel(upd_hdr, text=T('update_card_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')

        ctk.CTkFrame(upd, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        row_info = ctk.CTkFrame(upd, fg_color='transparent')
        row_info.pack(fill='x', padx=20, pady=(12, 10))

        row_actions = ctk.CTkFrame(row_info, fg_color='transparent')
        row_actions.pack(side='right', anchor='e')

        left_info = ctk.CTkFrame(row_info, fg_color='transparent')
        left_info.pack(side='left', fill='x', expand=True, padx=(0, 16))
        ctk.CTkLabel(left_info, text=T('update_current', version=APP_VERSION),
                     font=(ui_font(), 12, 'bold'),
                     text_color=TEXT_PRI).pack(anchor='w')

        self._update_status_lbl = ctk.CTkLabel(
            left_info, text='', text_color=TEXT_DIM, font=(ui_font(), 11))
        self._update_status_lbl.pack(anchor='w', pady=(3, 0))

        self._update_note_lbl = ctk.CTkLabel(
            left_info, text='', text_color=TEXT_DIM, font=(ui_font(), 10),
            wraplength=620, justify='left')
        self._update_note_lbl.pack(anchor='w', pady=(1, 0))

        self._update_check_btn = ctk.CTkButton(
            row_actions, text=T('update_check_btn'), width=138, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=lambda: self._start_update_check(manual=True))
        self._update_check_btn.pack(side='left')
        self._update_now_btn = ctk.CTkButton(
            row_actions, text=T('update_now_btn'), width=118, height=38,
            corner_radius=CONTROL_RADIUS, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE,
            command=self._start_update_install)
        self._refresh_update_ui()

        # ── Community Announcement & Directory Compilation Note ──────────
        ctk.CTkFrame(upd, height=1, fg_color=BORDER).pack(fill='x', padx=20, pady=(4, 10))

        msg_frame = ctk.CTkFrame(upd, fg_color=BG_SIDEBAR, corner_radius=6, border_width=1, border_color=BORDER_CARD)
        msg_frame.pack(fill='x', padx=20, pady=(0, 14))

        announcement_text = (
            "Dear friends & fellow cinephiles,\n\n"
            "Building FetchJAV has been a true labor of love. What started as a small personal project has blossomed into the world's most extensive, unified video compilation directory — bringing together over 2,200,000+ (2.2 Million+) videos across your favorite sources, with fresh discoveries added every single day.\n\n"
            "We built this for you. FetchJAV is completely free, open, and will always stay 100% free with no paywalls, subscriptions, or compromises. We pour our hearts into refining every pixel, player optimization, and translation feature to give you the smoothest, most enjoyable experience possible.\n\n"
            "Your voice truly shapes this application. Whether you have an idea for a new feature, discovered an issue, or simply want to say hello, we are always here listening. Come chat with us, share your thoughts, and be a part of our warm community on Telegram (https://t.me/FetchJAV) or GitHub.\n\n"
            "We have so many exciting new projects and innovations in the pipeline — thank you from the bottom of our hearts for being on this journey with us.\n\n"
            "With all our love and gratitude,\n"
            "— The FetchJAV Team ❤️"
        )

        ctk.CTkLabel(
            msg_frame,
            text=announcement_text,
            text_color=TEXT_PRI,
            font=(ui_font(), 11),
            justify='left',
            wraplength=600
        ).pack(anchor='w', padx=14, pady=(10, 6))

        import webbrowser
        def _open_telegram():
            try:
                webbrowser.open('https://t.me/FetchJAV')
            except Exception:
                pass

        def _open_github():
            try:
                webbrowser.open('https://github.com/FetchJAV/FetchJAV_Public')
            except Exception:
                pass

        tg_icon_img = None
        try:
            tg_icon_path = os.path.join(_resolve_resource_path('img'), 'telegram_outline.png')
            if os.path.exists(tg_icon_path):
                pil_tg = Image.open(tg_icon_path)
                tg_icon_img = ctk.CTkImage(light_image=pil_tg, dark_image=pil_tg, size=(18, 18))
        except Exception:
            pass

        btn_row = ctk.CTkFrame(msg_frame, fg_color='transparent')
        btn_row.pack(anchor='w', padx=14, pady=(0, 10))

        tg_btn = ctk.CTkButton(
            btn_row,
            text='  Join Telegram Community',
            image=tg_icon_img,
            compound='left',
            fg_color='transparent',
            border_width=1,
            border_color='#2AABEE',
            hover_color=('#e8f4fc', '#172738'),
            text_color='#2AABEE',
            height=30,
            corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 10, 'bold'),
            command=_open_telegram
        )
        tg_btn.pack(side='left', padx=(0, 8))

        gh_btn = ctk.CTkButton(
            btn_row,
            text='  GitHub Repository',
            compound='left',
            fg_color='transparent',
            border_width=1,
            border_color='#8b949e',
            hover_color=('#f0f0f0', '#1c2128'),
            text_color='#8b949e',
            height=30,
            corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 10, 'bold'),
            command=_open_github
        )
        gh_btn.pack(side='left')

    # ── Settings Tab ─────────────────────────────────────────────────
        # ── Settings Tab (Group 75 2-Column Sidebar Layout) ──────────────
    def _build_settings_tab(self):
        tab = self._tab_frames['settings']

        outer = ctk.CTkScrollableFrame(
            tab, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        outer.pack(fill='both', expand=True)

        content = ctk.CTkFrame(outer, fg_color='transparent')
        content.pack(fill='both', expand=True, padx=40, pady=24)



        # Main 2-Column Settings Card
        main_card = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                                 border_width=1, border_color=BORDER_CARD, height=608)
        main_card.pack(fill='x', expand=False)
        main_card.pack_propagate(False)

        # Left Sidebar Navigation (Fully visible auto-expanding width & height)
        left_nav = ctk.CTkFrame(main_card, width=230, fg_color='transparent')
        left_nav.pack(side='left', fill='y', padx=12, pady=16)

        # Vertical Divider Line
        ctk.CTkFrame(main_card, width=1, fg_color=BORDER).pack(
            side='left', fill='y', pady=12)

        # Right Detail Pane (Scrollable so all options fit cleanly)
        self._settings_detail_pane = ctk.CTkScrollableFrame(
            main_card, fg_color='transparent',
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        self._settings_detail_pane.pack(side='left', fill='both', expand=True, padx=12, pady=12)

        # Inner page rendering methods inside _build_settings_tab for source inspection parity
        def render_update_page(container):
            self._build_update_card(container)

        def render_general_page(container):
            grp = ctk.CTkFrame(container, fg_color='transparent')
            grp.pack(fill='both', expand=True, padx=(0, 18))

            grp_hdr = ctk.CTkFrame(grp, fg_color='transparent')
            grp_hdr.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(grp_hdr, text=T('general_settings_title'),
                         font=(ui_font(), 15, 'bold'),
                         text_color=TEXT_PRI).pack(side='left')

            ctk.CTkFrame(grp, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 14))

            # Theme Selection (System Theme, Dark Theme, Light Theme)
            row_theme = ctk.CTkFrame(grp, fg_color='transparent')
            row_theme.pack(fill='x', pady=(2, 1))
            ctk.CTkLabel(row_theme, text=T('theme_setting_title'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=130,
                         anchor='w').pack(side='left')

            self._theme_var = ctk.StringVar(value=self._theme_display_name(self._theme_mode))
            self._theme_menu = ctk.CTkOptionMenu(
                row_theme,
                values=['System Theme', 'Dark Theme', 'Light Theme'],
                variable=self._theme_var,
                command=self._on_theme_select,
                width=160, height=36,
                corner_radius=CONTROL_RADIUS,
                fg_color=BG_CARD, button_color=BG_CARD,
                button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
                dropdown_text_color=WHITE, dynamic_resizing=False,
                font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11))
            self._theme_menu.pack(side='left', padx=10)

            ctk.CTkLabel(grp, text=T('theme_setting_desc'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(anchor='w', padx=(140, 0), pady=(0, 14))

            # Language Selection
            row_lang = ctk.CTkFrame(grp, fg_color='transparent')
            row_lang.pack(fill='x', pady=(2, 1))
            ctk.CTkLabel(row_lang, text=T('language_setting_title'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=130,
                         anchor='w').pack(side='left')

            self._lang_var = ctk.StringVar(value=self._lang_name_by_code.get(get_lang(), 'English'))
            self._lang_menu = ctk.CTkOptionMenu(
                row_lang,
                values=[name for _, name in LANGUAGES],
                variable=self._lang_var,
                command=self._on_lang_change,
                width=160, height=36,
                corner_radius=CONTROL_RADIUS,
                fg_color=BG_CARD, button_color=BG_CARD,
                button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
                dropdown_text_color=WHITE, dynamic_resizing=False,
                font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11))
            self._lang_menu.pack(side='left', padx=10)

            ctk.CTkLabel(grp, text=T('language_setting_desc'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(anchor='w', padx=(140, 0), pady=(0, 14))

        def render_download_page(container):
            grp = ctk.CTkFrame(container, fg_color='transparent')
            grp.pack(fill='both', expand=True, padx=(0, 18))

            grp_hdr = ctk.CTkFrame(grp, fg_color='transparent')
            grp_hdr.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(grp_hdr, text=T('download_settings'),
                         font=(ui_font(), 15, 'bold'),
                         text_color=TEXT_PRI).pack(side='left')

            ctk.CTkFrame(grp, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 14))

            # Save location
            row_dest = ctk.CTkFrame(grp, fg_color='transparent')
            row_dest.pack(fill='x', pady=(2, 1))
            ctk.CTkLabel(row_dest, text=T('save_location_setting'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=130,
                         anchor='w').pack(side='left')
            ctk.CTkEntry(row_dest, textvariable=self._dest_var,
                         height=34, corner_radius=CONTROL_RADIUS,
                         fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                         text_color=TEXT_PRI).pack(side='left', fill='x', expand=True, padx=10)
            ctk.CTkButton(row_dest, text=T('browse_folder'), width=60, height=32, corner_radius=8,
                          fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                          hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                          command=self._pick_dest).pack(side='left')
            ctk.CTkLabel(grp, text=T('save_location_desc'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(anchor='w', padx=(140, 0), pady=(0, 4))

            # Speed limit
            row_speed = ctk.CTkFrame(grp, fg_color='transparent')
            row_speed.pack(fill='x', pady=(3, 1))
            ctk.CTkLabel(row_speed, text=T('speed_limit_setting'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=130,
                         anchor='w').pack(side='left')
            ctk.CTkOptionMenu(row_speed, values=self._speed_values(),
                              variable=self._speed_var,
                              command=self._on_speed_change, width=140, height=36,
                              corner_radius=CONTROL_RADIUS,
                              fg_color=BG_CARD, button_color=BG_CARD,
                              button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                              dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
                              dropdown_text_color=WHITE, dynamic_resizing=False,
                              font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)).pack(side='left', padx=10)
            ctk.CTkLabel(grp, text=T('speed_limit_desc'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(anchor='w', padx=(140, 0), pady=(0, 4))

            # Concurrent downloads
            row_conc = ctk.CTkFrame(grp, fg_color='transparent')
            row_conc.pack(fill='x', pady=(3, 1))
            ctk.CTkLabel(row_conc, text=T('concurrent_setting'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=130,
                         anchor='w').pack(side='left')
            self._conc_var = ctk.StringVar(value=str(self._dlmgr.max_concurrent))
            self._conc_entry = ctk.CTkEntry(
                row_conc, textvariable=self._conc_var, width=80, height=32,
                corner_radius=8, fg_color=BG_INPUT,
                border_color=BORDER, border_width=1,
                text_color=TEXT_PRI, justify='center')
            self._conc_entry.pack(side='left', padx=10)
            self._conc_entry.bind('<Return>', self._on_conc_change)
            self._conc_entry.bind('<FocusOut>', self._on_conc_change)
            ctk.CTkLabel(row_conc, text=T('max_n', n=MAX_CONCURRENT),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(side='left')
            ctk.CTkLabel(grp, text=T('concurrent_desc'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(anchor='w', padx=(140, 0), pady=(0, 4))

            # Segment workers
            row_workers = ctk.CTkFrame(grp, fg_color='transparent')
            row_workers.pack(fill='x', pady=(3, 1))
            ctk.CTkLabel(
                row_workers, text=T('max_workers_per_video_setting'),
                text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
                width=130, anchor='w').pack(side='left')
            self._workers_var = ctk.StringVar(
                value=str(config.get_max_workers_per_video()))
            self._workers_entry = ctk.CTkEntry(
                row_workers, textvariable=self._workers_var, width=80, height=32,
                corner_radius=8, fg_color=BG_INPUT,
                border_color=BORDER, border_width=1,
                text_color=TEXT_PRI, justify='center')
            self._workers_entry.pack(side='left', padx=10)
            self._workers_entry.bind('<Return>', self._on_workers_change)
            self._workers_entry.bind('<FocusOut>', self._on_workers_change)
            ctk.CTkLabel(
                row_workers,
                text=T('max_n', n=config.MAX_WORKERS_PER_VIDEO),
                text_color=TEXT_DIM, font=(ui_font(), 10)).pack(side='left')
            ctk.CTkLabel(
                grp,
                text=T('max_workers_per_video_desc', n=config.MAX_WORKERS_PER_VIDEO),
                text_color=TEXT_DIM, font=(ui_font(), 10),
                wraplength=SETTINGS_INLINE_HELP_WRAP,
                justify='left', anchor='w').pack(
                    anchor='w', padx=(140, 20), pady=(0, 4))

            # Resolution preference
            row_res = ctk.CTkFrame(grp, fg_color='transparent')
            row_res.pack(fill='x', pady=(3, 1))
            ctk.CTkLabel(row_res, text=T('resolution_setting'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=130,
                         anchor='w').pack(side='left')
            self._res_var = ctk.StringVar(value=self._resolution_label())
            ctk.CTkOptionMenu(row_res,
                              values=self._resolution_values(),
                              variable=self._res_var,
                              command=self._on_res_change, width=180, height=36,
                              corner_radius=CONTROL_RADIUS,
                              fg_color=BG_CARD, button_color=BG_CARD,
                              button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                              dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
                              dropdown_text_color=WHITE, dynamic_resizing=False,
                              font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)).pack(side='left', padx=10)

        def render_proxy_page(container):
            proxy = ctk.CTkFrame(container, fg_color='transparent')
            proxy.pack(fill='both', expand=True, padx=(0, 18))

            proxy_hdr = ctk.CTkFrame(proxy, fg_color='transparent')
            proxy_hdr.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(proxy_hdr, text=T('proxy_card_title'),
                         font=(ui_font(), 15, 'bold'),
                         text_color=TEXT_PRI).pack(side='left')
            ctk.CTkLabel(proxy, text=T('proxy_card_desc'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(anchor='w', pady=(0, 8))

            ctk.CTkFrame(proxy, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 14))

            self._proxy_var = ctk.StringVar(value=config.get_proxy_url())
            row_proxy = ctk.CTkFrame(proxy, fg_color='transparent')
            row_proxy.pack(fill='x', pady=(6, 2))
            ctk.CTkLabel(row_proxy, text=T('proxy_url_label'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=116,
                         anchor='w').pack(side='left')
            ctk.CTkEntry(
                row_proxy, textvariable=self._proxy_var,
                placeholder_text=T('proxy_url_placeholder'),
                height=34, corner_radius=8,
                fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                text_color=TEXT_PRI).pack(side='left', fill='x', expand=True, padx=10)

            proxy_actions = ctk.CTkFrame(proxy, fg_color='transparent')
            proxy_actions.pack(fill='x', pady=(10, 2))
            ctk.CTkButton(
                proxy_actions, text=T('proxy_save'), width=70, height=34,
                corner_radius=CONTROL_RADIUS, fg_color='transparent',
                border_width=1, border_color=ACCENT,
                hover_color=BG_CARD_HOVER, text_color=ACCENT,
                font=(ui_font(), 10, 'bold'),
                command=self._on_proxy_save).pack(
                    side='left', padx=(126, 6))
            ctk.CTkButton(
                proxy_actions, text=T('proxy_windows'), width=86, height=34,
                corner_radius=8, fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI,
                command=self._on_proxy_windows).pack(side='left', padx=(0, 6))
            ctk.CTkButton(
                proxy_actions, text=T('proxy_clear'), width=70, height=34,
                corner_radius=8, fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, command=self._on_proxy_clear).pack(side='left')
            self._proxy_status_lbl = ctk.CTkLabel(
                proxy_actions, text='', text_color=TEXT_SEC, font=(ui_font(), 10))
            self._proxy_status_lbl.pack(side='left', padx=12)
            self._refresh_proxy_status()

        def render_subtitle_page(container):
            grp = ctk.CTkFrame(container, fg_color='transparent')
            grp.pack(fill='both', expand=True, padx=(0, 18))

            grp_hdr = ctk.CTkFrame(grp, fg_color='transparent')
            grp_hdr.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(grp_hdr, text=T('subtitle_settings_title') if 'subtitle_settings_title' in T.__code__.co_varnames else 'Subtitles & AI',
                         font=(ui_font(), 15, 'bold'),
                         text_color=TEXT_PRI).pack(side='left')

            ctk.CTkFrame(grp, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 14))

            # Subtitles
            row_subtitle = ctk.CTkFrame(grp, fg_color='transparent')
            row_subtitle.pack(fill='x', pady=(3, 1))
            ctk.CTkLabel(row_subtitle, text=T('subtitle_setting'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=130,
                         anchor='w').pack(side='left')
            self._subtitle_var = ctk.StringVar(value=self._subtitle_label())
            ctk.CTkOptionMenu(
                row_subtitle, values=self._subtitle_values(),
                variable=self._subtitle_var, command=self._on_subtitle_change,
                width=230, height=36, corner_radius=CONTROL_RADIUS,
                fg_color=BG_CARD, button_color=BG_CARD,
                button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
                dropdown_text_color=WHITE, dynamic_resizing=False,
                font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)).pack(side='left', padx=10)
            ctk.CTkLabel(
                grp, text=T('subtitle_desc'), text_color=TEXT_DIM,
                font=(ui_font(), 10),
                wraplength=SETTINGS_INLINE_HELP_WRAP,
                justify='left', anchor='w').pack(
                    anchor='w', padx=(140, 20), pady=(0, 4))

            # Recognition quality
            row_recognition = ctk.CTkFrame(grp, fg_color='transparent')
            row_recognition.pack(fill='x', pady=(3, 1))
            ctk.CTkLabel(
                row_recognition, text=T('recognition_quality_setting'),
                text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
                width=130, anchor='w').pack(side='left')
            self._recognition_quality_var = ctk.StringVar(
                value=self._recognition_quality_label())
            ctk.CTkOptionMenu(
                row_recognition, values=self._recognition_quality_values(),
                variable=self._recognition_quality_var,
                command=self._on_recognition_quality_change,
                width=230, height=36, corner_radius=CONTROL_RADIUS,
                fg_color=BG_CARD, button_color=BG_CARD,
                button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
                dropdown_text_color=WHITE, dynamic_resizing=False,
                font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)).pack(side='left', padx=10)
            ctk.CTkLabel(
                grp, text=T('recognition_quality_desc'), text_color=TEXT_DIM,
                font=(ui_font(), 10),
                wraplength=SETTINGS_INLINE_HELP_WRAP,
                justify='left', anchor='w').pack(
                    anchor='w', padx=(140, 20), pady=(0, 4))

            # Subtitle translation provider
            row_translation = ctk.CTkFrame(grp, fg_color='transparent')
            row_translation.pack(fill='x', pady=(3, 1))
            ctk.CTkLabel(
                row_translation, text=T('translation_provider_setting'),
                text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
                width=130, anchor='w').pack(side='left')
            self._translation_provider_status_lbl = ctk.CTkLabel(
                row_translation,
                text=translation_provider_summary(),
                text_color=TEXT_SEC, font=(ui_font(), 10),
                anchor='w')
            self._translation_provider_status_lbl.pack(
                side='left', fill='x', expand=True, padx=10)
            ctk.CTkButton(
                row_translation, text=T('translation_provider_configure'),
                width=86, height=32, corner_radius=8,
                fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, font=(ui_font(), 10, 'bold'),
                command=self._open_translation_settings).pack(side='right')
            ctk.CTkLabel(
                grp, text=T('translation_provider_desc'),
                text_color=TEXT_DIM,
                font=(ui_font(), 10),
                wraplength=SETTINGS_INLINE_HELP_WRAP,
                justify='left', anchor='w').pack(
                    anchor='w', padx=(140, 20), pady=(0, 4))

            # Pre-download local models
            row_prefetch = ctk.CTkFrame(grp, fg_color='transparent')
            row_prefetch.pack(fill='x', pady=(10, 1))
            self._subtitle_prefetch_btn = ctk.CTkButton(
                row_prefetch, text=T('subtitle_prefetch_button'),
                width=86, height=32, corner_radius=8,
                fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, font=(ui_font(), 10, 'bold'),
                command=self._prefetch_subtitle_models)
            self._subtitle_prefetch_btn.pack(side='left', padx=(140, 10))
            self._subtitle_prefetch_status = ctk.CTkLabel(
                row_prefetch, text='', text_color=TEXT_SEC,
                font=(ui_font(), 10), anchor='w')
            self._subtitle_prefetch_status.pack(
                side='left', fill='x', expand=True)
            if getattr(self, '_subtitle_prefetching', False):
                self._subtitle_prefetch_btn.configure(state='disabled')
            self._subtitle_prefetch_status.configure(
                text=getattr(self, '_subtitle_prefetch_status_text', ''))
            ctk.CTkLabel(
                grp, text=T('subtitle_prefetch_desc'),
                text_color=TEXT_DIM,
                font=(ui_font(), 10),
                wraplength=SETTINGS_INLINE_HELP_WRAP,
                justify='left', anchor='w').pack(
                    anchor='w', padx=(140, 20), pady=(0, 4))

            # Remove all downloaded subtitles
            row_clear_subs = ctk.CTkFrame(grp, fg_color='transparent')
            row_clear_subs.pack(fill='x', pady=(10, 1))
            self._subtitle_clear_btn = ctk.CTkButton(
                row_clear_subs, text=T('clear_downloaded_subtitles_button'),
                width=110, height=32, corner_radius=8,
                fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=ACCENT, font=(ui_font(), 10, 'bold'),
                command=self._remove_all_downloaded_subtitles)
            self._subtitle_clear_btn.pack(side='left', padx=(140, 10))
            self._subtitle_clear_status = ctk.CTkLabel(
                row_clear_subs, text='', text_color=TEXT_SEC,
                font=(ui_font(), 10), anchor='w')
            self._subtitle_clear_status.pack(
                side='left', fill='x', expand=True)
            self._update_subtitle_cache_status()
            ctk.CTkLabel(
                grp, text=T('clear_downloaded_subtitles_desc'),
                text_color=TEXT_DIM,
                font=(ui_font(), 10),
                wraplength=SETTINGS_INLINE_HELP_WRAP,
                justify='left', anchor='w').pack(
                    anchor='w', padx=(140, 20), pady=(0, 4))

            # Notice / Important Guidance Card
            notice_card = ctk.CTkFrame(
                grp, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                border_width=1, border_color=BORDER_CARD
            )
            notice_card.pack(fill='x', pady=(14, 6))

            notice_inner = ctk.CTkFrame(notice_card, fg_color='transparent')
            notice_inner.pack(fill='x', padx=16, pady=12)

            ctk.CTkLabel(
                notice_inner, text=T('subtitle_notice_title'),
                font=(ui_font(), 11, 'bold'), text_color=TEXT_PRI, anchor='w'
            ).pack(anchor='w', pady=(0, 6))

            ctk.CTkLabel(
                notice_inner, text=T('subtitle_notice_desc'),
                text_color=TEXT_SEC, font=(ui_font(), 10),
                wraplength=SETTINGS_INLINE_HELP_WRAP - 30,
                justify='left', anchor='w'
            ).pack(anchor='w')

        def render_cf_page(container):
            cf = ctk.CTkFrame(container, fg_color='transparent')
            cf.pack(fill='both', expand=True, padx=(0, 18))

            cf_hdr = ctk.CTkFrame(cf, fg_color='transparent')
            cf_hdr.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(cf_hdr, text=T('cf_card_title'),
                         font=(ui_font(), 15, 'bold'),
                         text_color=TEXT_PRI).pack(side='left')
            ctk.CTkLabel(cf, text=T('cf_card_desc'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(anchor='w', pady=(0, 8))

            ctk.CTkFrame(cf, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 14))

            hosts = sorted({h for mirrors in config.MIRRORS.values() for h in mirrors})
            default_host = hosts[0] if hosts else ''
            self._cf_host_var = ctk.StringVar(value=default_host)
            self._cf_cookie_var = ctk.StringVar()
            self._cf_ua_var = ctk.StringVar()

            row_host = ctk.CTkFrame(cf, fg_color='transparent')
            row_host.pack(fill='x', pady=(6, 2))
            ctk.CTkLabel(row_host, text=T('cf_host_label'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=116,
                         anchor='w').pack(side='left')
            ctk.CTkOptionMenu(row_host, values=hosts,
                              variable=self._cf_host_var,
                              command=self._on_cf_host_change, width=220, height=36,
                              corner_radius=CONTROL_RADIUS,
                              fg_color=BG_CARD, button_color=BG_CARD,
                              button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                              dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
                              dropdown_text_color=WHITE, dynamic_resizing=False,
                              font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11)).pack(side='left', padx=10)

            row_cookie = ctk.CTkFrame(cf, fg_color='transparent')
            row_cookie.pack(fill='x', pady=(8, 2))
            ctk.CTkLabel(row_cookie, text=T('cf_cookie_label'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=116,
                         anchor='w').pack(side='left')
            ctk.CTkEntry(row_cookie, textvariable=self._cf_cookie_var,
                         height=34, corner_radius=8,
                         fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                         text_color=TEXT_PRI).pack(side='left', fill='x', expand=True, padx=10)

            row_ua = ctk.CTkFrame(cf, fg_color='transparent')
            row_ua.pack(fill='x', pady=(8, 2))
            ctk.CTkLabel(row_ua, text=T('cf_ua_label'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=116,
                         anchor='w').pack(side='left')
            ctk.CTkEntry(row_ua, textvariable=self._cf_ua_var,
                         height=34, corner_radius=8,
                         fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                         text_color=TEXT_PRI).pack(side='left', fill='x', expand=True, padx=10)

            cf_actions = ctk.CTkFrame(cf, fg_color='transparent')
            cf_actions.pack(fill='x', pady=(10, 2))
            ctk.CTkButton(cf_actions, text=T('cf_save'), width=70, height=34,
                          corner_radius=CONTROL_RADIUS, fg_color='transparent',
                          border_width=1, border_color=ACCENT,
                          hover_color=BG_CARD_HOVER, text_color=ACCENT,
                          font=(ui_font(), 10, 'bold'),
                          command=self._on_cf_save).pack(
                              side='left', padx=(126, 6))
            ctk.CTkButton(cf_actions, text=T('cf_clear'), width=70, height=34,
                          corner_radius=8, fg_color='transparent', border_width=1,
                          border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                          text_color=TEXT_PRI, command=self._on_cf_clear).pack(
                              side='left')
            self._cf_status_lbl = ctk.CTkLabel(cf_actions, text='', text_color=TEXT_SEC,
                                               font=(ui_font(), 10))
            self._cf_status_lbl.pack(side='left', padx=12)

            ctk.CTkLabel(cf, text=T('cf_card_desc_long'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10),
                         wraplength=SETTINGS_INLINE_HELP_WRAP,
                         justify='left', anchor='w').pack(anchor='w', pady=(12, 0))

        def render_queue_page(container):
            box = ctk.CTkFrame(container, fg_color='transparent')
            box.pack(fill='both', expand=True, padx=(0, 18))

            ctk.CTkLabel(box, text=T('queue_settings_title') if 'queue_settings_title' in T.__code__.co_varnames else 'Save Download Queue',
                         font=(ui_font(), 15, 'bold'), text_color=TEXT_PRI).pack(anchor='w')
            ctk.CTkFrame(box, height=1, fg_color=BORDER).pack(fill='x', pady=(8, 14))
            ctk.CTkLabel(box, text=T('queue_card_desc'),
                         text_color=TEXT_SEC, font=(ui_font(), 11)).pack(anchor='w', pady=(0, 12))

            path_row = ctk.CTkFrame(box, fg_color='transparent')
            path_row.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(path_row, text=T('queue_path_label'), text_color=TEXT_PRI,
                         font=(ui_font(), 12, 'bold'), width=100, anchor='w').pack(side='left')
            self._queue_path_var = ctk.StringVar(value=CSV_PATH)
            entry = ctk.CTkEntry(path_row, textvariable=self._queue_path_var,
                         height=34, corner_radius=8,
                         fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                         text_color=TEXT_PRI)
            entry.pack(side='left', fill='x', expand=True, padx=10)
            entry.configure(state='readonly')

            actions = ctk.CTkFrame(box, fg_color='transparent')
            actions.pack(fill='x', pady=(10, 2))
            ctk.CTkButton(
                actions, text=T('open_queue_folder'), width=110, height=34,
                corner_radius=8, fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, command=self._open_queue_folder
            ).pack(side='left', padx=(100, 6))
            ctk.CTkButton(
                actions, text=T('clear_saved_queue'), width=110, height=34,
                corner_radius=8, fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=ACCENT, command=self._clear_saved_queue
            ).pack(side='left')

        def render_about_page(container):
            box = ctk.CTkFrame(container, fg_color='transparent')
            box.pack(fill='both', expand=True, padx=(0, 18))

            hdr_row = ctk.CTkFrame(box, fg_color='transparent')
            hdr_row.pack(anchor='w', fill='x', pady=(0, 4))

            logo_p = _resolve_resource_path('logo.png')
            if not os.path.exists(logo_p):
                logo_p = _resolve_resource_path(os.path.join('img', 'logo.png'))
            if os.path.exists(logo_p):
                try:
                    about_logo_pil = Image.open(logo_p)
                    about_logo_img = ctk.CTkImage(
                        light_image=about_logo_pil, dark_image=about_logo_pil, size=(44, 44))
                    ctk.CTkLabel(hdr_row, image=about_logo_img, text='').pack(side='left', padx=(0, 12))
                except Exception:
                    pass

            text_col = ctk.CTkFrame(hdr_row, fg_color='transparent')
            text_col.pack(side='left', fill='y')
            ctk.CTkLabel(text_col, text="FetchJAV", font=(ui_font(), 18, 'bold'), text_color=ACCENT).pack(anchor='w')
            ctk.CTkLabel(text_col, text="Modern High-Speed JAV Downloader", text_color=TEXT_SEC, font=(ui_font(), 11)).pack(anchor='w', pady=(2, 0))

            ctk.CTkFrame(box, height=1, fg_color=BORDER).pack(fill='x', pady=(12, 14))
            ctk.CTkLabel(box, text="• Supports JableTV, MissAV & SupJav", text_color=TEXT_PRI, font=(ui_font(), 11)).pack(anchor='w', pady=2)
            ctk.CTkLabel(box, text="• Multi-threaded chunk downloading & Whisper auto-subtitles", text_color=TEXT_PRI, font=(ui_font(), 11)).pack(anchor='w', pady=2)

        def render_saved_page(container):
            for w in container.winfo_children():
                w.destroy()

            grp = ctk.CTkFrame(container, fg_color='transparent')
            grp.pack(fill='both', expand=True, padx=(0, 18))

            grp_hdr = ctk.CTkFrame(grp, fg_color='transparent')
            grp_hdr.pack(fill='x', pady=(0, 8))

            ctk.CTkLabel(
                grp_hdr, text=T('saved_settings_title'),
                font=(ui_font(), 15, 'bold'),
                text_color=TEXT_PRI
            ).pack(side='left')

            saved_items = config.get_saved_videos()

            def _on_export():
                from tkinter import filedialog
                path = filedialog.asksaveasfilename(
                    parent=self,
                    title=T('saved_export_title'),
                    defaultextension='.json',
                    filetypes=[('JSON', '*.json'), ('All files', '*.*')],
                    initialfile='saved_videos.json',
                )
                if not path:
                    return
                count = config.export_saved_videos(path)
                if hasattr(self, '_status_lbl') and self._status_lbl:
                    self._status_lbl.configure(text=T('saved_export_done', n=count))

            def _on_import():
                from tkinter import filedialog
                path = filedialog.askopenfilename(
                    parent=self,
                    title=T('saved_import_title'),
                    filetypes=[('JSON', '*.json'), ('All files', '*.*')],
                )
                if not path:
                    return
                count = config.import_saved_videos(path)
                if count > 0:
                    if hasattr(self, '_status_lbl') and self._status_lbl:
                        self._status_lbl.configure(text=T('saved_import_done', n=count))
                else:
                    if hasattr(self, '_status_lbl') and self._status_lbl:
                        self._status_lbl.configure(text=T('saved_import_none'))
                render_saved_page(container)

            btn_style = dict(
                height=28, width=65,
                corner_radius=CONTROL_RADIUS, fg_color='transparent',
                border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                font=(ui_font(), 10),
            )

            ctk.CTkButton(
                grp_hdr, text='↓ ' + T('saved_export'), **btn_style,
                command=_on_export,
            ).pack(side='right', padx=(4, 0))

            ctk.CTkButton(
                grp_hdr, text='↑ ' + T('saved_import'), **btn_style,
                command=_on_import,
            ).pack(side='right', padx=(4, 0))

            if saved_items:
                def _on_clear_all():
                    config.clear_saved_videos()
                    render_saved_page(container)

                ctk.CTkButton(
                    grp_hdr, text=T('saved_clear_all'), height=28, width=70,
                    corner_radius=CONTROL_RADIUS, fg_color='transparent',
                    border_width=1, border_color=BORDER_HOVER,
                    hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                    font=(ui_font(), 10),
                    command=_on_clear_all
                ).pack(side='right')

            ctk.CTkFrame(grp, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 14))

            if not saved_items:
                empty_card = ctk.CTkFrame(grp, fg_color=BG_CARD, corner_radius=CARD_RADIUS, border_width=1, border_color=BORDER_CARD)
                empty_card.pack(fill='x', pady=20, padx=10)
                ctk.CTkLabel(
                    empty_card, text=T('saved_empty_msg'), font=(ui_font(), 11), text_color=TEXT_SEC, justify='center'
                ).pack(pady=(0, 20))
                return

            for item in saved_items:
                url = item.get('url', '')
                title = item.get('title') or url
                site_name = item.get('site_name') or ''
                duration = item.get('duration') or ''

                item_card = ctk.CTkFrame(
                    grp, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                    border_width=1, border_color=BORDER_CARD
                )
                item_card.pack(fill='x', pady=4)

                card_inner = ctk.CTkFrame(item_card, fg_color='transparent')
                card_inner.pack(fill='x', padx=12, pady=10)

                left_info = ctk.CTkFrame(card_inner, fg_color='transparent')
                left_info.pack(side='left', fill='both', expand=True)

                title_row = ctk.CTkFrame(left_info, fg_color='transparent')
                title_row.pack(anchor='w', fill='x')

                if site_name:
                    ctk.CTkLabel(
                        title_row, text=site_name, text_color=WHITE,
                        fg_color=ACCENT, corner_radius=4, height=20, padx=6,
                        font=(ui_font(), 9, 'bold')
                    ).pack(side='left', padx=(0, 6))

                saved_title_lbl = ctk.CTkLabel(
                    title_row, text=title, text_color=TEXT_PRI,
                    font=(ui_font(), 12, 'bold'), anchor='w', wraplength=350, justify='left'
                )
                saved_title_lbl.pack(side='left', fill='x', expand=True)
                ToolTip(saved_title_lbl, title)

                if duration or url:
                    sub_info = duration if duration else url
                    ctk.CTkLabel(
                        left_info, text=sub_info, text_color=TEXT_DIM,
                        font=(ui_font(), 10), anchor='w'
                    ).pack(anchor='w', pady=(2, 0))

                right_btns = ctk.CTkFrame(card_inner, fg_color='transparent')
                right_btns.pack(side='right', padx=(10, 0))

                def _open_item_preview(target_item=item):
                    self._select_tab('browse')
                    self._open_preview(target_item)

                def _remove_item(target_url=url):
                    config.remove_saved_video(target_url)
                    render_saved_page(container)

                def _queue_item(target_url=url):
                    if target_url not in getattr(self, '_selected_urls', set()):
                        self._toggle_select(target_url)
                    if hasattr(self, '_status_lbl') and self._status_lbl:
                        self._status_lbl.configure(text=T('added_to_queue'))

                ctk.CTkButton(
                    right_btns, text=T('open_preview'), height=28, width=65,
                    corner_radius=CONTROL_RADIUS, fg_color=ACCENT,
                    hover_color=ACCENT_HOVER, text_color=WHITE,
                    font=(ui_font(), 10, 'bold'),
                    command=_open_item_preview
                ).pack(side='left', padx=(0, 4))

                ctk.CTkButton(
                    right_btns, text='+ ' + T('add_to_queue'), height=28, width=80,
                    corner_radius=CONTROL_RADIUS, fg_color='transparent',
                    border_width=1, border_color=BORDER_HOVER,
                    hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                    font=(ui_font(), 10),
                    command=_queue_item
                ).pack(side='left', padx=(0, 4))

                ctk.CTkButton(
                    right_btns, text='Remove', height=28, width=60,
                    corner_radius=CONTROL_RADIUS, fg_color='transparent',
                    border_width=1, border_color=BORDER_HOVER,
                    hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                    font=(ui_font(), 10),
                    command=_remove_item
                ).pack(side='left')

        def render_history_page(container):
            for w in container.winfo_children():
                w.destroy()

            v_hist = config.get_view_history()
            dl_hist = config.get_download_history()

            scroll = ctk.CTkFrame(container, fg_color='transparent')
            scroll.pack(fill='both', expand=True, padx=(0, 18))

            trash_icon = None
            img_dir_dest = _resolve_resource_path('img')
            t_light_p = os.path.join(img_dir_dest, 'icon_trash_light.png')
            t_dark_p = os.path.join(img_dir_dest, 'icon_trash_dark.png')
            if os.path.exists(t_light_p) and os.path.exists(t_dark_p):
                trash_icon = ctk.CTkImage(
                    light_image=Image.open(t_light_p),
                    dark_image=Image.open(t_dark_p),
                    size=(14, 14)
                )

            tab_bar = ctk.CTkFrame(scroll, fg_color='transparent')
            tab_bar.pack(fill='x', pady=(0, 8))

            active_tab = tk.StringVar(value='view')

            def _show_view():
                active_tab.set('view')
                view_btn.configure(fg_color=BG_CARD_HOVER, text_color=TEXT_PRI)
                dl_btn.configure(fg_color='transparent', text_color=TEXT_SEC)
                view_content.pack(fill='both', expand=True)
                dl_content.pack_forget()

            def _show_download():
                active_tab.set('download')
                dl_btn.configure(fg_color=BG_CARD_HOVER, text_color=TEXT_PRI)
                view_btn.configure(fg_color='transparent', text_color=TEXT_SEC)
                dl_content.pack(fill='both', expand=True)
                view_content.pack_forget()

            view_btn = ctk.CTkButton(
                tab_bar, text=T('recent_view_history'), width=160, height=32,
                corner_radius=CONTROL_RADIUS,
                fg_color=BG_CARD_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
                command=_show_view)
            view_btn.pack(side='left', padx=(0, 4))

            def _clear_active():
                if active_tab.get() == 'view':
                    config.clear_view_history()
                else:
                    config.clear_download_history()
                render_history_page(container)

            clear_btn = ctk.CTkButton(
                tab_bar, text=T('clear_history'), height=26, width=90,
                corner_radius=CONTROL_RADIUS, fg_color='transparent',
                border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                font=(ui_font(), 10), command=_clear_active
            )
            clear_btn.pack(side='right', padx=(8, 6))

            dl_btn = ctk.CTkButton(
                tab_bar, text=T('recent_download_history'), width=180, height=32,
                corner_radius=CONTROL_RADIUS,
                fg_color='transparent', hover_color=BG_CARD_HOVER,
                text_color=TEXT_SEC, font=(ui_font(), 12),
                command=_show_download)
            dl_btn.pack(side='left', padx=(4, 0))

            ctk.CTkFrame(scroll, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 10))

            view_content = ctk.CTkFrame(scroll, fg_color='transparent')
            dl_content = ctk.CTkFrame(scroll, fg_color='transparent')

            # ── VIEW HISTORY CONTENT ─────────────────────────────────────────
            if not v_hist:
                empty1 = ctk.CTkFrame(view_content, fg_color=BG_CARD, corner_radius=CARD_RADIUS, border_width=1, border_color=BORDER_CARD)
                empty1.pack(fill='both', expand=True, pady=(0, 16))
                ctk.CTkLabel(empty1, text=T('no_history'), font=(ui_font(), 11), text_color=TEXT_SEC).pack(pady=16)
            else:
                card1 = ctk.CTkFrame(view_content, fg_color=BG_CARD, corner_radius=CARD_RADIUS, border_width=1, border_color=BORDER_CARD)
                card1.pack(fill='both', expand=True, pady=(0, 16))

                for idx, item in enumerate(v_hist[:30]):
                    url = item.get('url', '')
                    title = item.get('title') or url
                    site_name = item.get('site_name') or ''

                    row = ctk.CTkFrame(card1, fg_color='transparent')
                    row.pack(fill='x', expand=True, padx=(12, 16), pady=8)

                    left_f = ctk.CTkFrame(row, fg_color='transparent')
                    left_f.pack(side='left', fill='both', expand=True)

                    if site_name:
                        ctk.CTkLabel(
                            left_f, text=f"[{site_name}]", text_color=ACCENT,
                            font=(ui_font(), 10, 'bold')).pack(side='left', padx=(0, 8))

                    v_hist_lbl = ctk.CTkLabel(
                        left_f, text=title, text_color=TEXT_PRI,
                        font=(ui_font(), 11), anchor='w', wraplength=460, justify='left')
                    v_hist_lbl.pack(side='left', fill='x', expand=True)
                    ToolTip(v_hist_lbl, title)

                    right_f = ctk.CTkFrame(row, fg_color='transparent')
                    right_f.pack(side='right', fill='y', padx=(8, 0))

                    def _open_hist_item(target_item=item):
                        self._select_tab('browse')
                        self._open_preview(target_item)

                    def _remove_view_item(target_url=url):
                        config.remove_view_history(target_url)
                        render_history_page(container)

                    ctk.CTkButton(
                        right_f, text=T('open_preview'), height=26, width=65,
                        corner_radius=CONTROL_RADIUS, fg_color='transparent',
                        border_width=1, border_color=BORDER_HOVER,
                        hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                        font=(ui_font(), 10), command=_open_hist_item
                    ).pack(side='left', padx=(0, 6))

                    ctk.CTkButton(
                        right_f, text='', height=26, width=32,
                        corner_radius=CONTROL_RADIUS, fg_color='transparent',
                        border_width=1, border_color=BORDER_HOVER,
                        hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                        image=trash_icon, command=_remove_view_item
                    ).pack(side='left', padx=(0, 2))

                    if idx < len(v_hist[:30]) - 1:
                        ctk.CTkFrame(card1, height=1, fg_color=BORDER_CARD).pack(fill='x', padx=12)

            # ── DOWNLOAD HISTORY CONTENT ────────────────────────────────────
            if not dl_hist:
                empty2 = ctk.CTkFrame(dl_content, fg_color=BG_CARD, corner_radius=CARD_RADIUS, border_width=1, border_color=BORDER_CARD)
                empty2.pack(fill='both', expand=True, pady=(0, 16))
                ctk.CTkLabel(empty2, text=T('no_history'), font=(ui_font(), 11), text_color=TEXT_SEC).pack(pady=16)
            else:
                card2 = ctk.CTkFrame(dl_content, fg_color=BG_CARD, corner_radius=CARD_RADIUS, border_width=1, border_color=BORDER_CARD)
                card2.pack(fill='both', expand=True, pady=(0, 16))

                for idx, item in enumerate(dl_hist[:30]):
                    url = item.get('url', '')
                    name = item.get('name') or url
                    dest = item.get('dest') or ''
                    state = state_label(item.get('state') or 'DOWNLOADED')

                    row = ctk.CTkFrame(card2, fg_color='transparent')
                    row.pack(fill='x', expand=True, padx=(12, 16), pady=8)

                    left_f = ctk.CTkFrame(row, fg_color='transparent')
                    left_f.pack(side='left', fill='both', expand=True)

                    ctk.CTkLabel(
                        left_f, text=f"[{state}]", text_color=SUCCESS,
                        font=(ui_font(), 10, 'bold')).pack(side='left', padx=(0, 8))

                    dl_hist_lbl = ctk.CTkLabel(
                        left_f, text=name, text_color=TEXT_PRI,
                        font=(ui_font(), 11), anchor='w', wraplength=420, justify='left')
                    dl_hist_lbl.pack(side='left', fill='x', expand=True)
                    ToolTip(dl_hist_lbl, name)

                    right_f = ctk.CTkFrame(row, fg_color='transparent')
                    right_f.pack(side='right', fill='y', padx=(8, 0))

                    def _locate_dl_item(target_dest=dest, target_name=name):
                        if not target_dest:
                            messagebox.showinfo(T('locate_title'), T('locate_no_folder'))
                            return
                        folder = os.path.abspath(target_dest)
                        if not os.path.isdir(folder):
                            messagebox.showinfo(T('locate_title'), T('locate_folder_missing'))
                            return
                        expected = os.path.join(folder, target_name + '.mp4')
                        if os.path.exists(expected):
                            import subprocess, platform
                            system = platform.system()
                            try:
                                if system == 'Windows':
                                    subprocess.Popen(['explorer', '/select,', expected])
                                elif system == 'Darwin':
                                    subprocess.Popen(['open', '-R', expected])
                                else:
                                    subprocess.Popen(['xdg-open', folder])
                            except OSError as e:
                                messagebox.showerror(T('open_folder_failed_title'), str(e))
                        else:
                            messagebox.showinfo(T('locate_title'), T('locate_file_missing'))

                    def _remove_dl_item(target_url=url):
                        config.remove_download_history(target_url)
                        render_history_page(container)

                    ctk.CTkButton(
                        right_f, text=T('locate_title'), height=26, width=60,
                        corner_radius=CONTROL_RADIUS, fg_color='transparent',
                        border_width=1, border_color=BORDER_HOVER,
                        hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                        font=(ui_font(), 10), command=_locate_dl_item
                    ).pack(side='left', padx=(0, 6))

                    ctk.CTkButton(
                        right_f, text='', height=26, width=32,
                        corner_radius=CONTROL_RADIUS, fg_color='transparent',
                        border_width=1, border_color=BORDER_HOVER,
                        hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                        image=trash_icon, command=_remove_dl_item
                    ).pack(side='left', padx=(0, 2))

                    if idx < len(dl_hist[:30]) - 1:
                        ctk.CTkFrame(card2, height=1, fg_color=BORDER_CARD).pack(fill='x', padx=12)

            view_content.pack(fill='both', expand=True)
            dl_content.pack_forget()

        def render_sources_page(container):
            grp = ctk.CTkFrame(container, fg_color='transparent')
            grp.pack(fill='both', expand=True, padx=(0, 18))

            grp_hdr = ctk.CTkFrame(grp, fg_color='transparent')
            grp_hdr.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(grp_hdr, text='Sources',
                         font=(ui_font(), 15, 'bold'),
                         text_color=TEXT_PRI).pack(side='left')
            ctk.CTkFrame(grp, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 14))

            ctk.CTkLabel(grp, text='Activate or deactivate video sources. '
                         'Deactivated sources are removed from the site selector.',
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(anchor='w', pady=(0, 12))

            _all_site_names = list(SITES.keys())
            if not hasattr(self, '_inactive_sites'):
                self._inactive_sites = set()

            _BTN_INACTIVE_BORDER = BORDER_HOVER
            _BTN_ACTIVE_BORDER = ACCENT
            _BTN_ACTIVE_BG = ('#FDE8EC', '#2B161B')
            _BTN_INACTIVE_BG = 'transparent'
            _BTN_INACTIVE_TEXT = TEXT_DIM
            _BTN_ACTIVE_TEXT = ACCENT

            self._source_btns = {}
            self._source_status_lbls = {}

            for site_name in _all_site_names:
                row = ctk.CTkFrame(grp, fg_color='transparent')
                row.pack(fill='x', pady=4)

                is_active = site_name not in self._inactive_sites

                status_lbl = ctk.CTkLabel(
                    row, text='●' if is_active else '○',
                    text_color=ACCENT if is_active else TEXT_DIM,
                    font=(ui_font(), 10, 'bold'), width=20)
                status_lbl.pack(side='left', padx=(0, 8))
                self._source_status_lbls[site_name] = status_lbl

                def _make_toggle(name=site_name):
                    def _toggle():
                        if name in self._inactive_sites:
                            self._inactive_sites.discard(name)
                        else:
                            self._inactive_sites.add(name)
                        config.set_inactive_sites(self._inactive_sites)
                        self._rebuild_site_selector()
                        self._refresh_source_btn_styles()
                    return _toggle

                btn = ctk.CTkButton(
                    row, text=site_name, width=120, height=32,
                    corner_radius=CONTROL_RADIUS,
                    border_width=2,
                    border_color=_BTN_ACTIVE_BORDER if is_active else _BTN_INACTIVE_BORDER,
                    fg_color=_BTN_ACTIVE_BG if is_active else _BTN_INACTIVE_BG,
                    text_color=_BTN_ACTIVE_TEXT if is_active else _BTN_INACTIVE_TEXT,
                    hover_color=_BTN_ACTIVE_BG if is_active else BG_CARD_HOVER,
                    font=(ui_font(), 11, 'bold'),
                    command=_make_toggle())
                btn.pack(side='left')
                self._source_btns[site_name] = btn

            def _refresh_source_btn_styles(self_ref=self):
                for name, b in self_ref._source_btns.items():
                    is_active = name not in self_ref._inactive_sites
                    try:
                        b.configure(
                            border_color=_BTN_ACTIVE_BORDER if is_active else _BTN_INACTIVE_BORDER,
                            fg_color=_BTN_ACTIVE_BG if is_active else _BTN_INACTIVE_BG,
                            text_color=_BTN_ACTIVE_TEXT if is_active else _BTN_INACTIVE_TEXT,
                            hover_color=_BTN_ACTIVE_BG if is_active else BG_CARD_HOVER,
                        )
                    except Exception:
                        pass
                for name, lbl in self_ref._source_status_lbls.items():
                    is_active = name not in self_ref._inactive_sites
                    try:
                        lbl.configure(
                            text='●' if is_active else '○',
                            text_color=ACCENT if is_active else TEXT_DIM)
                    except Exception:
                        pass

            self._refresh_source_btn_styles = _refresh_source_btn_styles

            def _activate_all():
                self._inactive_sites.clear()
                config.set_inactive_sites(self._inactive_sites)
                self._rebuild_site_selector()
                self._refresh_source_btn_styles()

            ctk.CTkFrame(grp, height=1, fg_color=BORDER).pack(fill='x', pady=(14, 10))
            ctk.CTkButton(
                grp, text='Enable All Sources', width=180, height=32,
                corner_radius=CONTROL_RADIUS,
                border_width=2, border_color=ACCENT,
                fg_color=ACCENT_DIM, hover_color=BG_CARD_HOVER,
                text_color=ACCENT, font=(ui_font(), 11, 'bold'),
                command=_activate_all).pack(anchor='w')

        self._settings_page_renderers = {
            'update': render_update_page,
            'general': render_general_page,
            'sources': render_sources_page,
            'saved': render_saved_page,
            'history': render_history_page,
            'subtitle': render_subtitle_page,
            'download': render_download_page,
            'proxy': render_proxy_page,
            'cf': render_cf_page,
            'queue': render_queue_page,
            'about': render_about_page,
        }

        # Navigation Categories
        self._settings_categories = [
            ('update', '', T('update_settings_title') if 'update_settings_title' in T.__code__.co_varnames else 'Update'),
            ('general', '', T('general_settings_title') if 'general_settings_title' in T.__code__.co_varnames else 'General'),
            ('sources', '', 'Sources'),
            ('saved', '', T('saved_settings_title') if 'saved_settings_title' in T.__code__.co_varnames else 'Saved'),
            ('history', '', T('history_settings_title')),
            ('download', '', T('download_settings')),
            ('subtitle', '', T('subtitle_settings_title') if 'subtitle_settings_title' in T.__code__.co_varnames else 'Subtitles & AI'),
            ('proxy', '', T('proxy_card_title')),
            ('cf', '', T('cf_card_title')),
            ('queue', '', T('queue_settings_title') if 'queue_settings_title' in T.__code__.co_varnames else 'Save Download Queue'),
            ('about', '', 'About')
        ]

        self._settings_nav_btns = {}
        self._active_settings_cat = 'update'
        self._settings_left_nav = left_nav

        for cat_key, cat_icon, cat_label in self._settings_categories:
            nav_text = f"{cat_icon}  {cat_label}".strip() if cat_icon else f"  {cat_label}"
            btn = ctk.CTkButton(
                left_nav, text=nav_text,
                fg_color=BG_CARD_HOVER if cat_key == 'update' else 'transparent',
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI if cat_key == 'update' else TEXT_SEC,
                anchor='w',
                font=(ui_font(), 12, 'bold' if cat_key == 'update' else 'normal'),
                height=38, corner_radius=CONTROL_RADIUS,
                command=lambda k=cat_key: self._switch_settings_cat(k))
            btn.pack(fill='x', pady=3)
            self._settings_nav_btns[cat_key] = btn

        # Display initial category and align responsive layout
        self._switch_settings_cat('update')
        self._update_responsive_nav()

    def _switch_settings_cat(self, selected_cat: str):
        self._active_settings_cat = selected_cat
        nav_btns = getattr(self, '_settings_nav_btns', {})
        for k, b in nav_btns.items():
            is_act = (k == selected_cat)
            try:
                b.configure(
                    fg_color=BG_CARD_HOVER if is_act else 'transparent',
                    text_color=TEXT_PRI if is_act else TEXT_SEC,
                    font=(ui_font(), 12, 'bold' if is_act else 'normal')
                )
            except Exception:
                pass

        # Clear detail pane
        pane = getattr(self, '_settings_detail_pane', None)
        if not pane:
            return
        for w in pane.winfo_children():
            w.destroy()

        renderer = getattr(self, '_settings_page_renderers', {}).get(selected_cat)
        if renderer:
            renderer(pane)

        try:
            pane._parent_canvas.yview_moveto(0)
            pane.update_idletasks()
            pane._parent_canvas.configure(scrollregion=pane._parent_canvas.bbox("all"))
        except Exception:
            pass

    def _load_categories(self):
        if self._is_closing:
            return
        _crumb("load_categories: site=%s" % self._site_key)
        self._page_req += 1
        my_req = self._page_req
        my_gen = self._build_gen
        site_key = self._site_key
        browser = SITES[site_key]['browser']
        missav_lang = T('missav_lang')
        supjav_lang = T('supjav_lang')

        def _fetch():
            failed = False
            try:
                if site_key == 'MissAV':
                    cats = browser.fetch_categories(lang=missav_lang)
                elif site_key == 'SupJav':
                    cats = browser.fetch_categories(lang=supjav_lang)
                else:
                    cats = browser.fetch_categories()
            except Exception:
                failed = True
                cats = []
            if not cats and hasattr(browser, 'HOMEPAGE_SECTIONS'):
                cats = [{'name': site_i18n.loc(site_i18n.CATEGORY_I18N, url, name),
                         'url': url, 'count': 0, 'section': True}
                        for name, url in browser.HOMEPAGE_SECTIONS]

            def _apply():
                if self._is_closing or my_req != self._page_req or my_gen != self._build_gen:
                    return
                self._categories = cats
                if cats and not failed:
                    self._current_base_url = cats[0]['url']
                    self._page = 1
                    self._last_loaded_page = 1
                    self._has_next = True
                    self._browse_blocked = False
                    self._browse_empty_message = ''
                    self._update_cat_menu([c['name'] for c in cats])
                    self._load_page()
                    return
                if cats:
                    self._current_base_url = cats[0]['url']
                    self._update_cat_menu([c['name'] for c in cats])
                else:
                    self._current_base_url = ''
                    self._cat_menu.configure(values=[])
                    self._cat_var.set('')
                self._videos = []
                self._has_next = False
                self._browse_blocked = False
                self._browse_empty_message = T('category_load_failed')
                self._status_lbl.configure(text=T('category_load_failed'))
                self._refresh_grid()

            self._ui(_apply, gen=my_gen)

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_cat_menu(self, names: list[str]):
        self._cat_menu.configure(values=names)
        if names:
            self._cat_var.set(names[0])

    def _load_page(self):
        if getattr(self, '_search_all_active', False) and getattr(self, '_search_all_query', ''):
            self._load_page_all_sites()
            return
        if not self._current_base_url:
            return
        self._page_req += 1
        my_req = self._page_req
        my_gen = self._build_gen
        # Entity pages (all of an actress/director/studio/tag's work) may fall
        # back to a different site's search, so use that site's browser and
        # pagination while an entity page is active.
        site_key = getattr(self, '_entity_site_key', '') or self._site_key
        browser = SITES[site_key]['browser']
        base = self._current_base_url
        page_snapshot = self._page
        if hasattr(browser, 'page_url'):
            url = browser.page_url(base, page_snapshot)
        elif site_key == 'JableTV':
            if '?' in base:
                url = f'{base}&from={page_snapshot}'
            else:
                url = f'{base.rstrip("/")}/?from={page_snapshot}'
        elif site_key == 'SupJav':
            url = SupJavBrowser.page_url(base, page_snapshot)
        elif site_key == 'HanimeTV':
            url = HanimeTVBrowser.page_url(base, page_snapshot)
        elif site_key == 'Hanime1':
            url = Hanime1Browser.page_url(base, page_snapshot)
        else:
            url = MissAVBrowser.page_url(base, page_snapshot)

        def _fetch():
            blocked = False
            try:
                data = fetch_page_data(browser, url)
                videos = data.get('videos', [])
            except MirrorsBlockedError:
                blocked = True
                videos = []
            self._ui(
                lambda: self._apply_page(my_req, videos, page_snapshot, blocked, my_gen),
                gen=my_gen)

        threading.Thread(target=_fetch, daemon=True).start()

    def _search_all_page_url(self, site_key: str, query: str, page: int) -> str:
        """Build a paginated search URL for one site in Search From All mode."""
        from urllib.parse import quote
        if site_key == 'JableTV':
            base = f'https://jable.tv/search/{query}/'
            if page <= 1:
                return base
            return f'{base.rstrip("/")}/?from={page}'
        if site_key == 'SupJav':
            base = SupJavBrowser.search_url(query, lang=T('supjav_lang'))
            return SupJavBrowser.page_url(base, page)
        if site_key == 'HanimeTV':
            base = HanimeTVBrowser.search_url(query)
            return HanimeTVBrowser.page_url(base, page)
        if site_key == 'Hanime1':
            base = Hanime1Browser.search_url(query)
            return Hanime1Browser.page_url(base, page)
        lang = T('missav_lang')
        eq = quote(query, safe='')
        base = f'https://missav.ai/{lang}/search/{eq}' if lang else f'https://missav.ai/search/{eq}'
        return MissAVBrowser.page_url(base, page)

    def _load_page_all_sites(self):
        """Search From All: fetch the same query from every site in parallel and
        merge the results into one page, tagging each video with its source site."""
        query = self._search_all_query
        page_snapshot = self._page
        my_req = self._page_req
        my_gen = self._build_gen
        lock = threading.Lock()
        merged: list[dict] = []
        blocked = False

        def _fetch(site_key: str, url: str):
            nonlocal blocked
            try:
                data = fetch_page_data(SITES[site_key]['browser'], url)
                videos = data.get('videos', [])
            except MirrorsBlockedError:
                videos = []
                blocked = True
            for v in videos:
                v['site'] = site_key
            with lock:
                merged.extend(videos)

        threads = []
        target_search_all_sites = [k for k in _ALL_SITE_KEYS if k not in getattr(self, '_inactive_sites', set())] or list(_ALL_SITE_KEYS)
        for site_key in target_search_all_sites:
            try:
                url = self._search_all_page_url(site_key, query, page_snapshot)
            except Exception:
                continue
            if not url:
                continue
            t = threading.Thread(target=_fetch, args=(site_key, url), daemon=True)
            t.start()
            threads.append(t)

        def _wait():
            for t in threads:
                t.join()
            self._ui(
                lambda: self._apply_page(my_req, merged, page_snapshot, blocked, my_gen),
                gen=my_gen)

        threading.Thread(target=_wait, daemon=True).start()

    def _resolve_video_duration_fast(self, url: str) -> str:
        if not url:
            return ''
        try:
            if 'hanime.tv' in url:
                from M3U8Sites.SiteHanimeTV import HanimeTVBrowser
                return HanimeTVBrowser.get_video_duration(url)
            elif 'tnaflix.com' in url:
                from M3U8Sites.SiteTnaFlix import SiteTnaFlix
                job = SiteTnaFlix(url)
                job.get_url_infos()
                return str(getattr(job, '_duration', '') or '')
        except Exception:
            pass
        return ''

    def _rank_search_results(self, videos: list[dict], query: str) -> list[dict]:
        """Rank search results so exact video code / title matches appear first,
        while maintaining recency/original order for tag and keyword matches."""
        q = str(query or '').strip()
        if not videos or not q:
            return list(videos or [])
        from video_identity import canonical_code, video_code, url_slug
        target_code = canonical_code(q).strip().casefold()
        norm_query = re.sub(r'[^a-zA-Z0-9]', '', q.lower())

        def _score(item):
            v_title = str(item.get('title', '') or '').strip()
            v_url = str(item.get('url', '') or '').strip()
            v_slug = url_slug(v_url).casefold()
            v_c = (video_code(item) or canonical_code(v_title) or canonical_code(v_url) or '').casefold()

            # 0. URL slug exact match (e.g. /videos/ssis-001/)
            if target_code and (v_slug == target_code or v_slug.startswith(f'{target_code}-') or v_slug.startswith(f'{target_code}_')):
                return 0
            # 1. Title starts with exact code (e.g. 'SSIS-001 Beautiful Debut...')
            if target_code and v_title.lower().startswith(target_code):
                return 1
            # 2. Exact code match in video metadata
            if target_code and v_c == target_code:
                return 2
            # 3. Exact normalized title match
            norm_title = re.sub(r'[^a-zA-Z0-9]', '', v_title.lower())
            if norm_query and norm_title == norm_query:
                return 3
            # 4. Title starts with query
            if norm_query and norm_title.startswith(norm_query):
                return 4
            # 5. General match (preserve original recency order)
            return 5

        return sorted(videos, key=_score)

    def _apply_page(self, req: int, videos: list[dict], page_snapshot: int,
                    blocked: bool = False, gen: int | None = None):
        if self._is_closing or req != self._page_req:
            return
        if gen is not None and gen != self._build_gen:
            return
        if not videos and page_snapshot > 1 and not blocked:
            self._page = self._last_loaded_page
            self._has_next = False
            self._page_lbl.configure(text=T('page_n', n=self._page))
            return
        if (not videos and page_snapshot == 1 and not blocked
                and getattr(self, '_entity_search_pending', False)):
            # The current entity URL came back empty — retry with the next
            # candidate (a search by an alternate name spelling or on a
            # different site) so the user still sees every matching title.
            remaining = getattr(self, '_entity_candidates', [])[1:]
            self._entity_candidates = remaining
            if remaining:
                self._current_base_url = remaining[0][0]
                self._entity_site_key = remaining[0][1]
                self._refresh_entity_heading()
                self._load_page()
                return
            self._entity_search_pending = False

        # If active search, prioritize exact code / title matches at the top
        active_q = getattr(self, '_search_all_query', '') or (self._search_entry.get() if hasattr(self, '_search_entry') and self._search_entry else (self._search_var.get() if hasattr(self, '_search_var') else '')).strip()
        if active_q and ('search' in str(getattr(self, '_current_base_url', '')).lower() or getattr(self, '_search_all_active', False)):
            videos = self._rank_search_results(videos, active_q)

        self._videos = videos
        self._browse_blocked = blocked
        self._browse_empty_message = ''
        self._has_next = bool(videos)
        if videos:
            self._last_loaded_page = page_snapshot
            self._page = page_snapshot
        _crumb("apply_page: %d videos -> refresh_grid" % len(videos))
        self._refresh_grid()
        _crumb("apply_page: grid refreshed")
        self._page_lbl.configure(text=T('page_n', n=self._page))

    def _video_version_badge(self, url: str, title: str):
        url_l = (url or '').lower()
        title_l = (title or '').lower()
        path = url_l.split('?', 1)[0].rstrip('/')
        if ('uncensored-leak' in url_l or '無碼' in title_l or
                '无码' in title_l or 'uncensored' in title_l):
            return T('badge_uncensored'), '#C2410C'
        if ('chinese-subtitle' in url_l or path.endswith('-c') or
                '-c/' in url_l or '中文字幕' in title_l or '中字' in title_l):
            return T('badge_chinese_sub'), '#0E7490'
        return None

    def _refresh_grid(self):
        try:
            for w in self._grid_scroll.winfo_children():
                w.destroy()
        except (AttributeError, tk.TclError):
            return
        self._card_widgets = {}
        self._grid_gen += 1
        gen = self._grid_gen
        build_gen = self._build_gen

        if not self._videos:
            if self._browse_blocked:
                msg = T('mirrors_blocked')
                ctk.CTkLabel(self._grid_scroll, text=msg,
                             text_color=TEXT_DIM,
                             font=(ui_font(), 14)).pack(pady=40)
            elif not self._browse_empty_message:
                _home_logo_p = _resolve_resource_path(os.path.join('img', 'logo_only.png'))
                if not os.path.exists(_home_logo_p):
                    _home_logo_p = _resolve_resource_path('logo.png')
                if os.path.exists(_home_logo_p):
                    try:
                        _home_pil = Image.open(_home_logo_p)
                        _home_logo_img = ctk.CTkImage(
                            light_image=_home_pil, dark_image=_home_pil,
                            size=(80, 80))
                        ctk.CTkLabel(self._grid_scroll, image=_home_logo_img,
                                     text='').pack(pady=(60, 8))
                    except Exception:
                        pass
                ctk.CTkLabel(self._grid_scroll, text='FetchJAV',
                             text_color=ACCENT,
                             font=(ui_font(), 22, 'bold')).pack(pady=(0, 4))
                ctk.CTkLabel(self._grid_scroll,
                             text=T('no_results') if self._page > 1 else '',
                             text_color=TEXT_DIM,
                             font=(ui_font(), 13)).pack(pady=(0, 20))
            else:
                msg = self._browse_empty_message
                ctk.CTkLabel(self._grid_scroll, text=msg,
                             text_color=TEXT_DIM,
                             font=(ui_font(), 14)).pack(pady=40)
            return

        # Responsive card density: 1 narrow / 2 compact / 3 default / 4 wide.
        columns = max(1, self._grid_columns)
        try:
            logical_width = self.winfo_width() / max(self._get_window_scaling(), 1.0)
        except Exception:
            logical_width = self.winfo_width()
        estimated_card_width = max(
            200, int((max(logical_width, 750) - 240) / columns) - 24)
        self._last_estimated_cw = estimated_card_width
        title_wrap = max(160, min(330, estimated_card_width - 34))

        # Reuse one subtitle-cache handle and current dest folder for the
        # per-card language badge lookups in this render pass.
        try:
            _sub_cache = SubtitleCache()
        except Exception:
            _sub_cache = None
        _sub_dest_var = getattr(self, '_dest_var', None)
        _sub_dest = _sub_dest_var.get() if _sub_dest_var is not None else getattr(self, '_dest', '')
        _sub_listing_url = getattr(self, '_current_base_url', '')

        row_frame = None
        for i, v in enumerate(self._videos):
            col_idx = i % columns
            if col_idx == 0:
                row_frame = ctk.CTkFrame(self._grid_scroll, fg_color='transparent')
                row_frame.pack(fill='x', padx=8, pady=4)
                for c in range(columns):
                    row_frame.grid_columnconfigure(c, weight=1, uniform='browse_cols')

            url = v.get('url', '')
            title = v.get('title', '')
            dur = v.get('duration', '')
            thumb_url = v.get('thumbnail') or v.get('img') or v.get('poster_url') or v.get('cover_url') or ''
            is_sel = url in self._selected_urls

            card = ctk.CTkFrame(row_frame, fg_color=BG_CARD,
                                corner_radius=CARD_RADIUS,
                                border_width=2 if is_sel else 1,
                                border_color=ACCENT if is_sel else BORDER_CARD)
            card.grid(row=0, column=col_idx, padx=6, pady=6, sticky='nsew')

            # ── Full-bleed thumbnail ──
            thumb_holder = ctk.CTkFrame(card, fg_color=BG_SIDEBAR,
                                         corner_radius=CARD_RADIUS,
                                         border_width=1,
                                         border_color=BORDER_HOVER)
            thumb_holder.pack(fill='x', padx=6, pady=(6, 0))
            # 5% taller thumbnail placeholder before image loads
            thumb_lbl = ctk.CTkLabel(thumb_holder, text=T('loading_browse'),
                                      text_color=TEXT_DIM,
                                      fg_color='transparent',
                                      font=(ui_font(), 10),
                                      height=168)
            thumb_lbl.pack(fill='x')

            # Duration badge — bottom-right of thumbnail
            dur_lbl = ctk.CTkLabel(thumb_holder, text=f' {dur} ' if dur else '',
                                    text_color='#FFFFFF',
                                    fg_color='#000000',
                                    corner_radius=4,
                                    font=('Consolas', 8, 'bold'))
            if dur:
                dur_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-6, y=-6)
            elif url and ('hanime.tv' in url.lower() or 'tnaflix.com' in url.lower()):
                def _fetch_card_dur_bg(card_url=url, card_dur_lbl=dur_lbl, card_dict=v, my_gen=gen):
                    try:
                        resolved_dur = self._resolve_video_duration_fast(card_url)
                        if resolved_dur and my_gen == getattr(self, '_grid_gen', 0):
                            card_dict['duration'] = resolved_dur
                            def _apply():
                                try:
                                    if card_dur_lbl.winfo_exists():
                                        card_dur_lbl.configure(text=f' {resolved_dur} ')
                                        card_dur_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-6, y=-6)
                                        card_dur_lbl.lift()
                                except Exception:
                                    pass
                            self.after(0, _apply)
                    except Exception:
                        pass
                if hasattr(self, '_dur_executor') and self._dur_executor:
                    self._dur_executor.submit(_fetch_card_dur_bg)
                else:
                    threading.Thread(target=_fetch_card_dur_bg, daemon=True).start()

            cover_url = v.get('cover_url') or ''
            has_cover_overlay = bool(cover_url and cover_url != thumb_url)

            # Subtitle and Dub outline badges — bottom-left of thumbnail
            try:
                card_badges = _detect_video_card_badges(
                    v, dest=_sub_dest, cache=_sub_cache,
                    listing_url=_sub_listing_url)
            except Exception:
                card_badges = []
            sub_badge_widgets = []
            if card_badges:
                _bx = 118 if has_cover_overlay else 7
                for b in card_badges:
                    _text = b['text']
                    _color = b['color']
                    _w = max(26, len(_text) * 7 + 10)
                    _badge_lbl = ctk.CTkLabel(
                        thumb_holder, text=_text,
                        width=_w, height=16, corner_radius=2,
                        border_width=1, border_color=_color,
                        fg_color=('#101018', '#101018'), text_color=_color,
                        font=('Consolas', 8, 'bold'))
                    _badge_lbl.place(relx=0, rely=1.0, anchor='sw',
                                     x=_bx, y=-7)
                    _badge_lbl.lift()
                    sub_badge_widgets.append(_badge_lbl)
                    _bx += _w + 4

            # Source-site label — dull chip top-left of the thumbnail, shown on
            # Search From All results so each site's results are distinguishable.
            site_lbl = None
            src_site = (v.get('site') or '').strip()
            if src_site:
                site_lbl = ctk.CTkLabel(
                    thumb_holder, text=f' {src_site} ',
                    height=17, corner_radius=4,
                    fg_color=('#0C0C11', '#0C0C11'),
                    text_color=('#9A938D', '#8B847E'),
                    font=('Consolas', 8, 'bold'))
                site_lbl.place(relx=0, rely=0, anchor='nw', x=7, y=7)
                site_lbl.lift()

            # Portrait box-art cover overlay on the left
            cover_widgets = []
            if has_cover_overlay:
                cov_w, cov_h = 114, 166
                cov_frame = ctk.CTkFrame(
                    thumb_holder, fg_color='#0a0a0f',
                    corner_radius=4,
                    border_width=1,
                    border_color='#404055',
                    width=cov_w, height=cov_h)
                cov_frame.place(relx=0.0, rely=0.5, anchor='w', x=7)
                cov_frame.pack_propagate(False)

                cov_lbl = ctk.CTkLabel(cov_frame, text='', fg_color='transparent')
                cov_lbl.pack(fill='both', expand=True)

                self._load_cover_overlay_async(
                    cover_url, cov_lbl, cov_w, cov_h,
                    gen, build_gen, src_site or self._site_key
                )
                cover_widgets = [cov_frame, cov_lbl]
                if site_lbl is not None:
                    site_lbl.lift()

            # ── Title (clean 2-line max) ──
            title_text = title[:65] + '…' if len(title) > 65 else title
            title_lbl = ctk.CTkLabel(card, text=title_text, text_color=TEXT_PRI,
                         font=(ui_font(), 11),
                         wraplength=title_wrap, justify='left',
                         anchor='nw')
            title_lbl.pack(fill='x', padx=10, pady=(7, 5), anchor='w')
            ToolTip(title_lbl, title)

            # ── Action buttons: Save (heart) · Preview · Select (inline) ──
            bottom = ctk.CTkFrame(card, fg_color='transparent')
            bottom.pack(fill='x', padx=8, pady=(0, 9))
            bottom.grid_columnconfigure(0, weight=0, minsize=30)
            bottom.grid_columnconfigure(1, weight=1, uniform='card_actions')
            bottom.grid_columnconfigure(2, weight=1, uniform='card_actions')

            is_card_saved = config.is_video_saved(url)
            card_heart_img = getattr(self, '_heart_active_icon', None) if is_card_saved else getattr(self, '_heart_icon', None)
            card_heart_text = '' if card_heart_img else ('♥' if is_card_saved else '♡')

            card_heart_btn = ctk.CTkButton(
                bottom, text=card_heart_text, image=card_heart_img,
                width=30, height=30,
                corner_radius=15,
                fg_color='transparent',
                border_width=1,
                border_color=ACCENT if is_card_saved else BORDER_HOVER,
                hover_color=BG_CARD_HOVER,
                text_color=ACCENT if is_card_saved else TEXT_PRI,
                command=lambda video=v, u=url: self._on_card_heart_click(video, u)
            )
            card_heart_btn.grid(row=0, column=0, padx=(0, 4))

            preview_btn = ctk.CTkButton(
                bottom, text=T('preview'), height=30,
                corner_radius=15,
                fg_color='transparent',
                border_width=1,
                border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI,
                font=(ui_font(), 10),
                command=lambda video=v: self._open_preview(video)
            )
            preview_btn.grid(row=0, column=1, sticky='ew', padx=(0, 4))

            sel_text = ('✓ ' + T('selected')) if is_sel else T('select')
            sel_btn = ctk.CTkButton(
                bottom, text=sel_text, height=30,
                corner_radius=15,
                fg_color=ACCENT if is_sel else 'transparent',
                border_width=0 if is_sel else 1,
                border_color=BORDER_HOVER,
                hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                text_color=('#FFFFFF', '#FFFFFF') if is_sel else TEXT_PRI,
                font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10),
                command=lambda u=url: self._toggle_select(u)
            )
            sel_btn.grid(row=0, column=2, sticky='ew')

            # Keep all inline button labels readable at any card width.
            def _adapt_action_fonts(_event=None, card_url=url):
                try:
                    if not preview_btn.winfo_exists() or not sel_btn.winfo_exists():
                        return
                    is_now_sel = card_url in self._selected_urls
                    cur_sel_text = ('✓ ' + T('selected')) if is_now_sel else T('select')
                    preview_btn.configure(
                        font=_fit_card_button_font(T('preview'), preview_btn.winfo_width(), 10))
                    sel_btn.configure(
                        font=_fit_card_button_font(cur_sel_text, sel_btn.winfo_width(), 10, is_now_sel))
                except Exception:
                    pass
            bottom.bind('<Configure>', _adapt_action_fonts, add='+')

            self._card_widgets[url] = {'card': card, 'sel_btn': sel_btn, 'preview_btn': preview_btn, 'heart_btn': card_heart_btn, 'adapt_fonts': _adapt_action_fonts}

            # Clickable card
            def _bind_click(widget, video_url=url):
                widget.bind('<Button-1>', lambda e, u=video_url: self._toggle_select(u))
                widget.configure(cursor='hand2')
            _bind_click(card)
            _bind_click(thumb_holder)
            _bind_click(thumb_lbl)
            for _cw in cover_widgets:
                _bind_click(_cw)
            for _bw in sub_badge_widgets:
                _bind_click(_bw)
            if site_lbl is not None:
                _bind_click(site_lbl)

            # Card hover unblur effect when overlay cover is present
            if has_cover_overlay:
                thumb_lbl._enable_blur = True
                def _on_card_enter(_e=None, lbl=thumb_lbl):
                    if getattr(lbl, '_hovered', False):
                        return
                    lbl._hovered = True
                    sharp = getattr(lbl, '_ctk_sharp_img', None)
                    if sharp:
                        try:
                            lbl.configure(image=sharp)
                            lbl._ctk_img_ref = sharp
                        except Exception:
                            pass

                def _on_card_leave(_e=None, c=card, lbl=thumb_lbl):
                    def _check_leave():
                        try:
                            if not c.winfo_exists():
                                return
                            x, y = c.winfo_pointerxy()
                            w = c.winfo_containing(x, y)
                            is_inside = False
                            while w:
                                if w == c:
                                    is_inside = True
                                    break
                                w = getattr(w, 'master', None)
                            if not is_inside:
                                lbl._hovered = False
                                blurred = getattr(lbl, '_ctk_blurred_img', None)
                                if blurred:
                                    lbl.configure(image=blurred)
                                    lbl._ctk_img_ref = blurred
                        except Exception:
                            pass
                    c.after(40, _check_leave)

                for _w in (card, thumb_holder, thumb_lbl, title_lbl, bottom, *cover_widgets, *sub_badge_widgets, card_heart_btn, preview_btn, sel_btn):
                    try:
                        _w.bind('<Enter>', _on_card_enter, add='+')
                        _w.bind('<Leave>', _on_card_leave, add='+')
                    except Exception:
                        pass

            # Background thumbnail load
            if thumb_url:
                self._load_thumb_async(
                    thumb_url, thumb_lbl, gen, build_gen, src_site or self._site_key,
                    enable_blur=has_cover_overlay)
            else:
                thumb_lbl.configure(text=T('no_thumbnail'))

    def _load_thumb_async(self, thumb_url: str, label: ctk.CTkLabel,
                          gen: int, build_gen: int, site_key: str = '',
                          enable_blur: bool = False):
        """Fetch thumbnail in a background thread; marshal result back to the
        main thread via .after() so Tk widget updates stay thread-safe.
        The gen counter prevents stale thumbs from polluting a newer page."""
        def _worker():
            if self._is_closing or build_gen != self._build_gen:
                return
            if gen != self._grid_gen and gen != getattr(self, '_preview_gen', -1):
                return
            img = _fetch_thumbnail(thumb_url, site_key)
            if img is None:
                def _apply_missing():
                    if self._is_closing or build_gen != self._build_gen:
                        return
                    if gen != self._grid_gen and gen != getattr(self, '_preview_gen', -1):
                        return
                    try:
                        if label.winfo_exists():
                            label.configure(text=T('no_thumbnail'), image=None)
                    except Exception:
                        pass
                self._ui(_apply_missing, gen=build_gen)
                return
            # Only apply if this label is still part of the current page.
            def _apply():
                if self._is_closing or build_gen != self._build_gen:
                    return
                if gen != self._grid_gen and gen != getattr(self, '_preview_gen', -1):
                    return
                try:
                    if not label.winfo_exists():
                        return
                    holder = label.master
                    cw = holder.winfo_width() if (holder and holder.winfo_exists()) else 0
                    if cw <= 4:
                        cw = int(self.__dict__.get('_last_estimated_cw', 260))  # fallback before layout is realised
                    label._raw_img = img

                    target_ch = max(1, min(190, int(round(cw * 0.61))))
                    ctk_img = _create_height_fitted_hd_ctk_image(img, cw, target_ch)
                    label._ctk_sharp_img = ctk_img

                    should_blur = enable_blur or getattr(label, '_enable_blur', False)
                    if should_blur:
                        try:
                            from PIL import ImageFilter
                            blurred_raw = img.filter(ImageFilter.GaussianBlur(radius=7))
                            ctk_blur = _create_height_fitted_hd_ctk_image(blurred_raw, cw, target_ch)
                            label._ctk_blurred_img = ctk_blur
                        except Exception:
                            label._ctk_blurred_img = ctk_img
                    else:
                        label._ctk_blurred_img = None

                    active_img = label._ctk_sharp_img if getattr(label, '_hovered', False) else (label._ctk_blurred_img or ctk_img)
                    label.configure(image=active_img, text='', height=target_ch)
                    label._ctk_img_ref = active_img
                    label._last_w = cw

                    # Ensure any overlay children inside holder stay in front of the background thumbnail
                    if holder and hasattr(holder, 'winfo_children') and holder.winfo_exists():
                        try:
                            for child in holder.winfo_children():
                                if child != label:
                                    child.lift()
                        except Exception:
                            pass

                    # Re-scale on card width change keeping image height 100% matched to thumbnail viewer height
                    if not getattr(label, '_has_resize_bind', False) and holder and holder.winfo_exists():
                        label._has_resize_bind = True
                        def _on_resize(event):
                            if not label.winfo_exists():
                                return
                            w = event.width
                            if w > 4 and abs(getattr(label, '_last_w', 0) - w) >= 12:
                                label._last_w = w
                                raw = getattr(label, '_raw_img', None)
                                if raw:
                                    tch = max(1, min(190, int(round(w * 0.61))))
                                    ci = _create_height_fitted_hd_ctk_image(raw, w, tch)
                                    label._ctk_sharp_img = ci
                                    if getattr(label, '_enable_blur', False) or enable_blur:
                                        try:
                                            from PIL import ImageFilter
                                            b_raw = raw.filter(ImageFilter.GaussianBlur(radius=7))
                                            label._ctk_blurred_img = _create_height_fitted_hd_ctk_image(b_raw, w, tch)
                                        except Exception:
                                            label._ctk_blurred_img = ci
                                    cur = label._ctk_sharp_img if getattr(label, '_hovered', False) else (label._ctk_blurred_img or ci)
                                    try:
                                        label.configure(image=cur, height=tch)
                                        label._ctk_img_ref = cur
                                        for ch in holder.winfo_children():
                                            if ch != label:
                                                ch.lift()
                                    except Exception:
                                        pass
                        holder.bind('<Configure>', _on_resize, add='+')
                except Exception:
                    pass
            self._ui(_apply, gen=build_gen)
        try:
            self._thumb_executor.submit(_worker)
        except RuntimeError:
            pass

    def _load_cover_overlay_async(self, cover_url: str, label: ctk.CTkLabel,
                                  target_w: int, target_h: int,
                                  gen: int, build_gen: int, site_key: str = ''):
        """Fetch portrait box-art cover in a background thread and render it
        as a sharp High-DPI overlay badge on the left side of the thumbnail."""
        def _worker():
            if self._is_closing or build_gen != self._build_gen:
                return
            if gen != self._grid_gen and gen != getattr(self, '_preview_gen', -1):
                return
            img = _fetch_thumbnail(cover_url, site_key)
            if img is None:
                return
            def _apply():
                if self._is_closing or build_gen != self._build_gen:
                    return
                if gen != self._grid_gen and gen != getattr(self, '_preview_gen', -1):
                    return
                try:
                    if not label.winfo_exists():
                        return
                    tw2, th2 = max(1, target_w * 2), max(1, target_h * 2)
                    ratio = max(tw2 / max(1, img.width), th2 / max(1, img.height))
                    nw = int(img.width * ratio)
                    nh = int(img.height * ratio)
                    scaled = img.resize((max(1, nw), max(1, nh)), Image.LANCZOS)
                    left = max(0, (scaled.width - tw2) // 2)
                    top = max(0, (scaled.height - th2) // 2)
                    cropped = scaled.crop((left, top, min(scaled.width, left + tw2), min(scaled.height, top + th2)))
                    ctk_img = ctk.CTkImage(light_image=cropped, dark_image=cropped, size=(target_w, target_h))
                    label.configure(image=ctk_img, text='')
                    label._ctk_img_ref = ctk_img
                    try:
                        if label.master and label.master.winfo_exists():
                            label.master.lift()
                    except Exception:
                        pass
                except Exception:
                    pass
            self._ui(_apply, gen=build_gen)
        try:
            self._thumb_executor.submit(_worker)
        except RuntimeError:
            pass

    def _source_subtitle_evidence_for_video(self, video: dict):
        candidate = dict(video or {})
        candidate['_site'] = self._site_key
        candidate['_source_listing_url'] = self._current_base_url
        return trusted_chinese_subtitle_evidence(candidate)

    def _toggle_select(self, url: str):
        if url in self._selected_urls:
            self._selected_urls.discard(url)
            self._selected_source_subtitle_evidence.pop(url, None)
        else:
            self._selected_urls.add(url)
            video = next(
                (item for item in self._videos
                 if item.get('url', '') == url),
                {'url': url},
            )
            evidence = self._source_subtitle_evidence_for_video(video)
            if evidence:
                self._selected_source_subtitle_evidence[url] = evidence
        # Update the specific card in-place (no full grid rebuild)
        w = self._card_widgets.get(url)
        if w:
            is_sel = url in self._selected_urls
            try:
                w['card'].configure(
                    fg_color=BG_CARD,
                    border_width=2 if is_sel else 1,
                    border_color=ACCENT if is_sel else BORDER_CARD)
                w['sel_btn'].configure(
                    text=('✓ ' + T('selected')) if is_sel else T('select'),
                    fg_color=ACCENT if is_sel else 'transparent',
                    border_width=0 if is_sel else 1,
                    hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                    text_color=WHITE if is_sel else TEXT_PRI)
                adapt = w.get('adapt_fonts')
                if adapt:
                    adapt()
            except Exception:
                pass
        self._update_selection_count()

    def _animate_heart_btn(self, btn, is_saved: bool):
        if not btn:
            return
        try:
            if not btn.winfo_exists():
                return
        except Exception:
            return

        h_img = getattr(self, '_heart_active_icon', None) if is_saved else getattr(self, '_heart_icon', None)
        h_txt = '' if h_img else ('♥' if is_saved else '♡')

        if is_saved:
            try:
                btn.configure(
                    fg_color=ACCENT,
                    border_color=ACCENT,
                    text_color=WHITE,
                    text='' if h_img else '💖',
                    image=h_img
                )
            except Exception:
                pass

            def _step2():
                try:
                    if btn.winfo_exists():
                        btn.configure(
                            fg_color='transparent',
                            border_color=ACCENT,
                            text_color=ACCENT,
                            text=h_txt,
                            image=h_img
                        )
                except Exception:
                    pass

            self.after(150, _step2)
        else:
            try:
                btn.configure(
                    fg_color=BG_CARD_HOVER,
                    border_color=BORDER,
                    text_color=TEXT_DIM,
                    text=h_txt,
                    image=h_img
                )
            except Exception:
                pass

            def _step2_off():
                try:
                    if btn.winfo_exists():
                        btn.configure(
                            fg_color='transparent',
                            border_color=BORDER_HOVER,
                            text_color=TEXT_PRI,
                            text=h_txt,
                            image=h_img
                        )
                except Exception:
                    pass

            self.after(150, _step2_off)

    def _update_preview_action_buttons(self):
        if getattr(self, '_browse_mode', '') != 'preview':
            return
        preview_source = getattr(self, '_preview_source', None)
        url = (preview_source.page_url if preview_source else '') or (getattr(self, '_preview_video', {}) or {}).get('url', '')
        if not url:
            return

        items = getattr(self, '_dlmgr').get_items() if hasattr(self, '_dlmgr') else []
        dl_item = next((i for i in items if i.url == url), None)

        q_btn = getattr(self, '_preview_q_btn', None)
        dl_btn = getattr(self, '_preview_dl_btn', None)

        # Check if item is enqueued/actively downloading
        is_enqueued = False
        if dl_item is not None:
            is_active = (hasattr(self._dlmgr, '_active') and url in self._dlmgr._active)
            is_pending = (hasattr(self._dlmgr, '_pending') and any(t.url == url for t in self._dlmgr._pending))
            is_dl_state = (dl_item.state in ('下載中', '準備中', '字幕準備中', '字幕辨識中', '字幕翻譯中', '已下載'))
            is_enqueued = is_active or is_pending or is_dl_state

        # Green "Download Selected" style tokens for active/queued state
        GREEN_BG = SUCCESS_DIM
        GREEN_BORDER = SUCCESS
        GREEN_HOVER = ('#D4EAD9', '#254A36')
        GREEN_TEXT = SUCCESS

        # Accent "Download Selected" style tokens for idle download button
        _acc = ACCENT[0] if isinstance(ACCENT, (tuple, list)) else str(ACCENT or '')
        _acc_dark = ACCENT[1] if isinstance(ACCENT, (tuple, list)) else str(ACCENT or '')
        ACCENT_BG = (_dim_color(_acc, '#FFFFFF', 0.12), _dim_color(_acc_dark, '#16161B', 0.18))
        ACCENT_BORDER = ACCENT
        ACCENT_HOVER_COLOR = (_brighten(ACCENT_BG[0], 1.08), _brighten(ACCENT_BG[1], 1.08))
        ACCENT_TEXT = ACCENT

        # 1. Update Add to Queue Button: Green "Download Selected" style when queued, outline when not.
        if q_btn:
            try:
                if q_btn.winfo_exists():
                    if dl_item is not None:
                        q_btn.configure(
                            text=' ' + T('add_to_queue'),
                            image=getattr(self, '_plus_icon', None),
                            fg_color=GREEN_BG,
                            border_width=1,
                            border_color=GREEN_BORDER,
                            hover_color=GREEN_HOVER,
                            text_color=GREEN_TEXT,
                            width=110,
                            font=(ui_font(), 10, 'bold')
                        )
                    else:
                        q_btn.configure(
                            text=' ' + T('add_to_queue'),
                            image=getattr(self, '_plus_icon', None),
                            fg_color='transparent',
                            border_width=1,
                            border_color=BORDER_HOVER,
                            hover_color=BG_CARD_HOVER,
                            text_color=TEXT_PRI,
                            width=110,
                            font=(ui_font(), 10)
                        )
            except Exception:
                pass

        # 2. Update Download Button: Green "Download Selected" style with "Downloading (52%)" WITHOUT ICON when downloading/enqueued!
        if dl_btn:
            try:
                if dl_btn.winfo_exists():
                    if is_enqueued and dl_item is not None:
                        st = dl_item.progress
                        state = dl_item.state
                        if state == '已下載':
                            dl_btn.configure(
                                text=f"{T('download_btn')} (100%)",
                                image=None,
                                fg_color=GREEN_BG,
                                border_width=1,
                                border_color=GREEN_BORDER,
                                hover_color=GREEN_HOVER,
                                text_color=GREEN_TEXT,
                                width=130,
                                font=(ui_font(), 10, 'bold')
                            )
                        else:
                            pct = max(0, min(100, int(st)))
                            dl_text = f"{T('preview_downloading')} ({pct}%)"
                            dl_btn.configure(
                                text=dl_text,
                                image=None,  # No icon inside download button when downloading!
                                fg_color=GREEN_BG,
                                border_width=1,
                                border_color=GREEN_BORDER,
                                hover_color=GREEN_HOVER,
                                text_color=GREEN_TEXT,
                                width=140,
                                font=(ui_font(), 10, 'bold')
                            )
                    else:
                        dl_btn.configure(
                            text=' ' + T('download_btn'),
                            image=getattr(self, '_dl_icon', None),
                            fg_color='transparent',
                            border_width=1,
                            border_color=BORDER_HOVER,
                            hover_color=BG_CARD_HOVER,
                            text_color=TEXT_PRI,
                            width=110,
                            font=(ui_font(), 10, 'bold')
                        )
            except Exception:
                pass

    def _shuffle_preview_related(self):
        if getattr(self, '_browse_mode', '') != 'preview':
            return
        pool = list(getattr(self, '_preview_related_pool', []) or [])
        cur_url = (getattr(self, '_preview_video', {}) or {}).get('url', '')
        shown = set(getattr(self, '_preview_shown_related_urls', set()))

        pool = [v for v in pool if v.get('url') and v.get('url') != cur_url]
        if not pool:
            return

        import random
        unseen = [v for v in pool if v.get('url') not in shown]
        if len(unseen) >= 10:
            new_selection = random.sample(unseen, 10)
        elif unseen:
            filler = [v for v in pool if v.get('url') not in {u.get('url') for u in unseen}]
            new_selection = unseen + random.sample(filler, min(10 - len(unseen), len(filler)))
        else:
            shown.clear()
            new_selection = random.sample(pool, min(10, len(pool)))

        if len(new_selection) < 10:
            for v in pool:
                if v not in new_selection and v.get('url') != cur_url:
                    new_selection.append(v)
                    if len(new_selection) >= 10:
                        break

        for v in new_selection:
            shown.add(v.get('url'))
        self._preview_shown_related_urls = shown
        self._preview_related_vids = new_selection
        self._preview_layout_mode = None
        self._preview_layout_cols = None
        try:
            w = self.winfo_width() / max(self._get_window_scaling(), 1.0)
            if w <= 1:
                w = 1200
        except Exception:
            w = 1200
        self._update_preview_layout(w)

    def _update_preview_layout(self, logical_width: float):
        if getattr(self, '_browse_mode', '') != 'preview':
            return

        left_main = getattr(self, '_preview_left_main', None)
        right_sidebar = getattr(self, '_preview_right_sidebar', None)
        bottom_container = getattr(self, '_preview_bottom_related', None)
        related_vids = getattr(self, '_preview_related_vids', [])

        if not left_main or not right_sidebar or not bottom_container:
            return

        if logical_width >= 750:
            target_mode = 'side_by_side'
            target_cols = 1
        elif logical_width >= 560:
            target_mode = 'bottom_grid'
            target_cols = 2
        else:
            target_mode = 'bottom_grid'
            target_cols = 1

        curr_mode = getattr(self, '_preview_layout_mode', None)
        curr_cols = getattr(self, '_preview_layout_cols', None)

        if curr_mode == target_mode and curr_cols == target_cols:
            return

        self._preview_layout_mode = target_mode
        self._preview_layout_cols = target_cols

        # Clear existing children of right_sidebar and bottom_container
        for w in list(right_sidebar.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass

        for w in list(bottom_container.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass

        if target_mode == 'side_by_side':
            bottom_container.pack_forget()
            left_main.pack_forget()
            right_sidebar.pack_forget()
            right_sidebar.configure(width=340)
            right_sidebar.pack(side='right', fill='y', padx=(0, 24))
            left_main.pack(side='left', fill='both', expand=True, padx=(0, 16))

            hdr_frame = ctk.CTkFrame(right_sidebar, fg_color='transparent')
            hdr_frame.pack(fill='x', padx=10, pady=(12, 10))

            ctk.CTkButton(
                hdr_frame,
                text='←',
                width=24,
                height=24,
                corner_radius=4,
                fg_color='transparent',
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI,
                font=(ui_font(), 15, 'bold'),
                command=self._preview_navigate_back
            ).pack(side='left', padx=(0, 6))

            ctk.CTkLabel(
                hdr_frame, text='Related Videos', text_color=TEXT_PRI,
                font=(ui_font(), 14, 'bold')).pack(side='left', padx=(0, 8))

            shuffle_btn = ctk.CTkButton(
                hdr_frame,
                text='Shuffle',
                width=60,
                height=24,
                corner_radius=12,
                fg_color=BG_CARD,
                border_width=1,
                border_color=BORDER,
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_SEC,
                font=(ui_font(), 10, 'bold'),
                command=self._shuffle_preview_related
            )
            shuffle_btn.pack(side='right', padx=(8, 0))

            for rv in related_vids:
                self._render_single_related_card(right_sidebar, rv, is_grid=False)
        else:
            right_sidebar.pack_forget()
            left_main.pack_forget()
            left_main.pack(side='left', fill='both', expand=True, padx=(0, 16))
            bottom_container.pack(fill='x', pady=(8, 16))
            hdr_frame = ctk.CTkFrame(bottom_container, fg_color='transparent')
            hdr_frame.pack(fill='x', pady=(12, 8))

            ctk.CTkButton(
                hdr_frame,
                text='←',
                width=24,
                height=24,
                corner_radius=4,
                fg_color='transparent',
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI,
                font=(ui_font(), 15, 'bold'),
                command=self._preview_navigate_back
            ).pack(side='left', padx=(0, 6))

            ctk.CTkLabel(
                hdr_frame, text='Related Videos', text_color=TEXT_PRI,
                font=(ui_font(), 14, 'bold')).pack(side='left', padx=(0, 8))

            shuffle_btn = ctk.CTkButton(
                hdr_frame,
                text='Shuffle',
                width=60,
                height=24,
                corner_radius=12,
                fg_color=BG_CARD,
                border_width=1,
                border_color=BORDER,
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_SEC,
                font=(ui_font(), 10, 'bold'),
                command=self._shuffle_preview_related
            )
            shuffle_btn.pack(side='right', padx=(8, 0))

            grid_frame = ctk.CTkFrame(bottom_container, fg_color='transparent')
            grid_frame.pack(fill='x', pady=(0, 16))

            row_frame = None
            for idx, rv in enumerate(related_vids):
                col_idx = idx % target_cols
                if col_idx == 0:
                    row_frame = ctk.CTkFrame(grid_frame, fg_color='transparent')
                    row_frame.pack(fill='x', pady=4)
                    for c in range(target_cols):
                        row_frame.grid_columnconfigure(c, weight=1, uniform='rel_cols')
                self._render_single_related_card(row_frame, rv, is_grid=True, cols=target_cols, col_idx=col_idx)

    def _render_single_related_card(self, parent, rv: dict, is_grid: bool = False, cols: int = 1, col_idx: int = 0):
        r_url = rv.get('url', '')
        r_title = rv.get('title', '')
        r_dur = rv.get('duration', '')
        r_thumb = rv.get('thumbnail') or rv.get('img') or rv.get('poster_url') or rv.get('cover_url') or ''
        r_is_sel = r_url in getattr(self, '_selected_urls', set())

        rcard = ctk.CTkFrame(
            parent, fg_color=BG_CARD,
            corner_radius=CARD_RADIUS,
            border_width=2 if r_is_sel else 1,
            border_color=ACCENT if r_is_sel else BORDER_CARD)

        if is_grid:
            rcard.grid(row=0, column=col_idx, padx=4, pady=4, sticky='nsew')
            img_height = 115 if cols == 3 else (135 if cols == 2 else 155)
            wrap_w = 200 if cols == 3 else (310 if cols == 2 else 540)
        else:
            rcard.pack(fill='x', padx=2, pady=6)
            img_height = 180
            wrap_w = 320

        r_cover_url = rv.get('cover_url') or ''
        has_r_cover = bool(r_cover_url and r_cover_url != r_thumb)

        # Top Preview Image Container (framed preview holder)
        rthumb_holder = ctk.CTkFrame(rcard, fg_color='#0a0a0d', height=img_height, corner_radius=6)
        rthumb_holder.pack(fill='x', padx=6, pady=(6, 0))
        rthumb_holder.pack_propagate(False)

        rlbl = ctk.CTkLabel(rthumb_holder, text='', text_color=TEXT_DIM, font=(ui_font(), 9))
        rlbl.pack(fill='both', expand=True)
        if r_thumb:
            self._load_thumb_async(
                r_thumb, rlbl, self._preview_gen, self._build_gen,
                getattr(self, '_site_key', ''), enable_blur=has_r_cover)

        r_dur_lbl = ctk.CTkLabel(
            rthumb_holder, text=f' {r_dur} ' if r_dur else '', text_color=WHITE, fg_color='#000000',
            corner_radius=4, font=('Consolas', 8, 'bold'))
        if r_dur:
            r_dur_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-4, y=-4)
        elif r_url and ('hanime.tv' in r_url.lower() or 'tnaflix.com' in r_url.lower()):
            def _fetch_rel_dur_bg(card_url=r_url, card_lbl=r_dur_lbl, card_dict=rv, my_pgen=getattr(self, '_preview_gen', 0)):
                try:
                    resolved_dur = self._resolve_video_duration_fast(card_url)
                    if resolved_dur and my_pgen == getattr(self, '_preview_gen', 0):
                        card_dict['duration'] = resolved_dur
                        def _apply():
                            try:
                                if card_lbl.winfo_exists():
                                    card_lbl.configure(text=f' {resolved_dur} ')
                                    card_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-4, y=-4)
                                    card_lbl.lift()
                            except Exception:
                                pass
                        self.after(0, _apply)
                except Exception:
                    pass
            if hasattr(self, '_dur_executor') and self._dur_executor:
                self._dur_executor.submit(_fetch_rel_dur_bg)
            else:
                threading.Thread(target=_fetch_rel_dur_bg, daemon=True).start()

        r_cover_widgets = []
        if has_r_cover:
            if is_grid:
                rcov_h = 86 if cols == 3 else (102 if cols == 2 else 118)
                rcov_w = int(round(rcov_h * 0.68))
            else:
                rcov_h = 166
                rcov_w = 114
            rcov_frame = ctk.CTkFrame(
                rthumb_holder, fg_color='#0a0a0f',
                corner_radius=4,
                border_width=1,
                border_color='#404055',
                width=rcov_w, height=rcov_h)
            rcov_frame.place(relx=0.0, rely=0.5, anchor='w', x=6)
            rcov_frame.pack_propagate(False)

            rcov_lbl = ctk.CTkLabel(rcov_frame, text='', fg_color='transparent')
            rcov_lbl.pack(fill='both', expand=True)

            self._load_cover_overlay_async(
                r_cover_url, rcov_lbl, rcov_w, rcov_h,
                self._preview_gen, self._build_gen, getattr(self, '_site_key', '')
            )
            r_cover_widgets = [rcov_frame, rcov_lbl]

        # Subtitle and Dub outline badges — bottom-left of thumbnail
        try:
            _sub_cache = SubtitleCache()
        except Exception:
            _sub_cache = None
        _sub_dest_var = getattr(self, '_dest_var', None)
        _sub_dest = _sub_dest_var.get() if _sub_dest_var is not None else getattr(self, '_dest', '')
        _sub_listing_url = getattr(self, '_current_base_url', '')
        try:
            card_badges = _detect_video_card_badges(
                rv, dest=_sub_dest, cache=_sub_cache,
                listing_url=_sub_listing_url)
        except Exception:
            card_badges = []
        sub_badges = []
        if card_badges:
            _bx = (rcov_w + 10) if has_r_cover else 5
            for b in card_badges:
                _text = b['text']
                _color = b['color']
                _w = max(26, len(_text) * 7 + 10)
                _badge = ctk.CTkLabel(
                    rthumb_holder, text=_text,
                    width=_w, height=16, corner_radius=2,
                    border_width=1, border_color=_color,
                    fg_color=('#101018', '#101018'), text_color=_color,
                    font=('Consolas', 8, 'bold'))
                _badge.place(
                    relx=0, rely=1.0, anchor='sw', x=_bx, y=-4)
                _badge.lift()
                sub_badges.append(_badge)
                _bx += _w + 4

        # Details Section
        rinfo = ctk.CTkFrame(rcard, fg_color='transparent')
        rinfo.pack(fill='x', padx=8, pady=(6, 8))

        r_title_lbl = ctk.CTkLabel(
            rinfo, text=r_title, text_color=TEXT_PRI,
            font=(ui_font(), 10, 'bold'), wraplength=wrap_w, justify='left')
        r_title_lbl.pack(anchor='w', fill='x', pady=(0, 4))
        ToolTip(r_title_lbl, r_title)

        rbadges = ctk.CTkFrame(rinfo, fg_color='transparent')
        rbadges.pack(anchor='w', fill='x')

        ctk.CTkLabel(
            rbadges, text=getattr(self, '_site_key', 'JAVXY'), text_color=TEXT_DIM,
            fg_color=BG_SIDEBAR, corner_radius=4, height=18, padx=6,
            font=(ui_font(), 9, 'bold')).pack(side='left', padx=(0, 6))

        ctk.CTkLabel(
            rbadges, text='1080p', text_color=TEXT_DIM,
            fg_color=BG_SIDEBAR, corner_radius=4, height=18, padx=6,
            font=(ui_font(), 9)).pack(side='left')

        r_is_saved = config.is_video_saved(r_url)
        r_heart_img = getattr(self, '_heart_active_icon', None) if r_is_saved else getattr(self, '_heart_icon', None)
        r_heart_text = '' if r_heart_img else ('♥' if r_is_saved else '♡')

        r_heart_btn = ctk.CTkButton(
            rbadges, text=r_heart_text, image=r_heart_img,
            width=24, height=22, corner_radius=4,
            fg_color='transparent',
            border_width=1, border_color=ACCENT if r_is_saved else BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=ACCENT if r_is_saved else TEXT_PRI,
        )
        r_heart_btn.configure(
            command=lambda item=rv, u=r_url, b=r_heart_btn: self._on_card_heart_click(item, u, b)
        )
        r_heart_btn.pack(side='right')

        def _bind_rv(widget, item=rv, frame=rcard, sel=r_is_sel):
            widget.bind('<Button-1>', lambda e: self._open_preview(item))
            widget.configure(cursor='hand2')
            def _on_enter(e):
                if not sel:
                    frame.configure(border_color=BORDER_HOVER)
            def _on_leave(e):
                if not sel:
                    frame.configure(border_color=BORDER_CARD)
            try:
                widget.bind('<Enter>', _on_enter, add='+')
                widget.bind('<Leave>', _on_leave, add='+')
            except Exception:
                pass

        _bind_rv(rcard)
        _bind_rv(rthumb_holder)
        _bind_rv(rlbl)
        for _cw in r_cover_widgets:
            _bind_rv(_cw)
        _bind_rv(rinfo)
        for _bw in sub_badges:
            _bind_rv(_bw)

        if has_r_cover:
            rlbl._enable_blur = True
            def _on_rel_enter(_e=None, lbl=rlbl):
                if getattr(lbl, '_hovered', False):
                    return
                lbl._hovered = True
                sharp = getattr(lbl, '_ctk_sharp_img', None)
                if sharp:
                    try:
                        lbl.configure(image=sharp)
                        lbl._ctk_img_ref = sharp
                    except Exception:
                        pass

            def _on_rel_leave(_e=None, c=rcard, lbl=rlbl):
                def _check_leave():
                    try:
                        if not c.winfo_exists():
                            return
                        x, y = c.winfo_pointerxy()
                        w = c.winfo_containing(x, y)
                        is_inside = False
                        while w:
                            if w == c:
                                is_inside = True
                                break
                            w = getattr(w, 'master', None)
                        if not is_inside:
                            lbl._hovered = False
                            blurred = getattr(lbl, '_ctk_blurred_img', None)
                            if blurred:
                                lbl.configure(image=blurred)
                                lbl._ctk_img_ref = blurred
                    except Exception:
                        pass
                c.after(40, _check_leave)

            for _w in (rcard, rthumb_holder, rlbl, rinfo, r_title_lbl, r_heart_btn, *r_cover_widgets, *sub_badges):
                try:
                    _w.bind('<Enter>', _on_rel_enter, add='+')
                    _w.bind('<Leave>', _on_rel_leave, add='+')
                except Exception:
                    pass

    def _on_card_heart_click(self, video: dict, url: str, btn_widget=None):
        target_url = url or (video or {}).get('url') or (video or {}).get('page_url') or ''
        if not target_url:
            return
        v_info = {
            'url': target_url,
            'title': (video or {}).get('title', '') or target_url,
            'thumbnail': (video or {}).get('thumbnail', '') or (video or {}).get('img', ''),
            'duration': (video or {}).get('duration', ''),
            'site_name': (video or {}).get('site_name', '') or config.site_name_from_url(target_url),
        }
        new_saved = config.toggle_saved_video(v_info)
        if hasattr(self, '_status_lbl') and self._status_lbl:
            self._status_lbl.configure(text=T('video_saved_toast') if new_saved else T('video_removed_toast'))

        if btn_widget and hasattr(btn_widget, 'winfo_exists') and btn_widget.winfo_exists():
            self._animate_heart_btn(btn_widget, new_saved)

        self._update_card_heart_btn(target_url, animate=True)

        if getattr(self, '_browse_mode', '') == 'preview':
            if getattr(self, '_preview_source', None) and self._preview_source.page_url == target_url:
                p_btn = getattr(self, '_preview_heart_btn', None)
                if p_btn and p_btn != btn_widget:
                    self._animate_heart_btn(p_btn, new_saved)

        if getattr(self, '_active_settings_cat', '') == 'saved':
            self._switch_settings_cat('saved')

    def _update_card_heart_btn(self, url: str, animate: bool = True):
        w = getattr(self, '_card_widgets', {}).get(url)
        if not w or 'heart_btn' not in w:
            return
        btn = w['heart_btn']
        is_s = config.is_video_saved(url)
        if animate:
            self._animate_heart_btn(btn, is_s)
        else:
            try:
                h_img = getattr(self, '_heart_active_icon', None) if is_s else getattr(self, '_heart_icon', None)
                h_txt = '' if h_img else ('♥' if is_s else '♡')
                btn.configure(
                    image=h_img,
                    text=h_txt,
                    fg_color='transparent',
                    border_color=ACCENT if is_s else BORDER_HOVER,
                    text_color=ACCENT if is_s else TEXT_PRI
                )
            except Exception:
                pass

    def _update_selection_count(self):
        n = len(self._selected_urls)
        if getattr(self, '_brand_lbl', None):
            self._brand_lbl.configure(text=f'({n})' if n > 0 else '')
        if getattr(self, '_sel_lbl', None):
            try:
                self._sel_lbl.configure(
                    text=f'{n} {T("selected")}',
                    text_color=ACCENT if n else TEXT_SEC)
            except Exception:
                pass

    def _set_card_selected(self, url: str, is_sel: bool):
        w = self._card_widgets.get(url)
        if not w:
            return
        try:
            w['card'].configure(
                fg_color=BG_CARD,
                border_width=2 if is_sel else 1,
                border_color=ACCENT if is_sel else BORDER_CARD)
            w['sel_btn'].configure(
                text=('✓ ' + T('selected')) if is_sel else T('select'),
                fg_color=ACCENT if is_sel else 'transparent',
                border_width=0 if is_sel else 1,
                hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                text_color=WHITE if is_sel else TEXT_PRI)
            adapt = w.get('adapt_fonts')
            if adapt:
                adapt()
        except Exception:
            pass

    def _clear_selection_in_place(self):
        selected = list(self._selected_urls)
        self._selected_urls.clear()
        self._selected_source_subtitle_evidence.clear()
        for url in selected:
            self._set_card_selected(url, False)
        self._update_selection_count()

    def _goto_page(self, p: int):
        if p < 1:
            return
        if p > self._page and not self._has_next:
            return
        self._page = p
        self._load_page()

    def _jump_to_page(self):
        """Jump to page number entered in the page-jump field."""
        try:
            p = int(self._page_jump_var.get().strip())
            if p >= 1 and not (p > self._page and not self._has_next):
                self._goto_page(p)
        except (ValueError, TypeError):
            pass
        self._page_jump_var.set('')

    def _select_all_on_page(self):
        """Select all videos currently displayed on the page."""
        for v in self._videos:
            url = v.get('url', '')
            if url:
                self._selected_urls.add(url)
                evidence = self._source_subtitle_evidence_for_video(v)
                if evidence:
                    self._selected_source_subtitle_evidence[url] = evidence
                self._set_card_selected(url, True)
        self._update_selection_count()

    def _rebuild_site_selector(self):
        inactive = getattr(self, '_inactive_sites', set())
        active_sites = [k for k in SITES.keys() if k not in inactive]
        if not active_sites:
            active_sites = list(SITES.keys())
            self._inactive_sites.clear()
            config.set_inactive_sites(self._inactive_sites)

        old_menu = getattr(self, '_site_menu', None)
        if old_menu:
            try:
                old_menu.pack_forget()
                old_menu.destroy()
            except Exception:
                pass

        if self._site_key not in active_sites:
            self._site_key = active_sites[0]

        self._site_menu = SiteSelectorBar(
            self._top_toolbar_row1, sites=active_sites,
            selected=self._site_key,
            command=self._on_site_change)
        self._site_menu.pack(side='left', before=self._cat_menu)

    def _on_site_change(self, val):
        self._site_key = val
        try:
            analytics.track_site_switch(val)
        except Exception:
            pass
        if getattr(self, '_tab_keys', ['browse'])[getattr(self, '_active_tab_idx', 0)] != 'browse':
            self._select_tab('browse')
        if getattr(self, '_browse_mode', 'grid') != 'grid':
            self._set_browse_mode('grid')
        self._active_tag_slug = None
        self._active_tag_url = None
        self._entity_prev_base_url = ''
        self._entity_prev_cat = ''
        self._entity_prev_from_preview = False
        self._entity_prev_preview_video = None
        self._entity_search_pending = False
        self._entity_candidates = []
        self._entity_site_key = ''
        self._exit_search_all_view()
        self._hide_page_heading()
        self._categories.clear()
        self._cached_sidebar_cats = None
        self._selected_urls.clear()
        self._selected_source_subtitle_evidence.clear()
        self._update_selection_count()
        self._rebuild_sidebar()
        self._load_categories()

    def _on_cat_change(self, val):
        idx = next((i for i, c in enumerate(self._categories)
                    if c['name'] == val), -1)
        if idx < 0:
            return
        if getattr(self, '_tab_keys', ['browse'])[getattr(self, '_active_tab_idx', 0)] != 'browse':
            self._select_tab('browse')
        if getattr(self, '_browse_mode', 'grid') != 'grid':
            self._set_browse_mode('grid')
        self._active_tag_slug = None
        self._active_tag_url = None
        self._entity_prev_base_url = ''
        self._entity_prev_cat = ''
        self._entity_prev_from_preview = False
        self._entity_prev_preview_video = None
        self._entity_search_pending = False
        self._entity_candidates = []
        self._entity_site_key = ''
        self._exit_search_all_view()
        self._hide_page_heading()
        self._current_base_url = self._categories[idx]['url']
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_source_subtitle_evidence.clear()
        self._update_selection_count()
        self._rebuild_sidebar()
        self._load_page()

    def _exit_search_all_view(self):
        """Leave the multi-site search result view (used when the user navigates
        to a category / tag / entity page so it never lingers)."""
        self._search_all_active = False
        self._search_all_query = ''
        self._hide_page_heading()

    def _toggle_search_all(self):
        self._search_all_mode = not self._search_all_mode
        if not self._search_all_mode:
            self._exit_search_all_view()
        self._update_search_all_indicator()

    def _update_search_all_indicator(self):
        """Sync the compass icon color to the search-all state and hover status."""
        lbl = getattr(self, '_compass_lbl', None)
        if lbl is not None:
            try:
                is_hovered = getattr(self, '_compass_hovered', False)
                if self._search_all_mode:
                    icon = (getattr(self, '_compass_icon_active_hover', None) or getattr(self, '_compass_icon_active', None)
                            if is_hovered else getattr(self, '_compass_icon_active', None))
                else:
                    icon = (getattr(self, '_compass_icon_hover', None)
                            if is_hovered else getattr(self, '_compass_icon', None))
                if icon is not None:
                    lbl.configure(image=icon)
            except Exception:
                pass

    def _on_search(self):
        q = (self._search_entry.get() if hasattr(self, '_search_entry') and self._search_entry else (self._search_var.get() if hasattr(self, '_search_var') else '')).strip()
        if not q:
            return
        if getattr(self, '_tab_keys', ['browse'])[getattr(self, '_active_tab_idx', 0)] != 'browse':
            self._select_tab('browse')
        if getattr(self, '_browse_mode', 'grid') != 'grid':
            self._set_browse_mode('grid')
        from urllib.parse import quote
        self._entity_prev_base_url = ''
        self._entity_prev_cat = ''
        self._entity_prev_from_preview = False
        self._entity_prev_preview_video = None
        self._entity_search_pending = False
        self._entity_candidates = []
        self._entity_site_key = ''
        self._hide_page_heading()
        try:
            analytics.track_search(self._site_key, is_all_sites=bool(self._search_all_mode))
        except Exception:
            pass
        if self._search_all_mode:
            # Search From All: query every site at once and merge results.
            self._search_all_active = True
            self._search_all_query = q
            self._current_base_url = ''
            self._show_search_all_heading(q)
        else:
            self._search_all_active = False
            self._search_all_query = ''
            if self._site_key == 'JableTV':
                # JableTV only serves search results from the raw path form
                # (/search/<name>/); the ?q= form returns an empty grid.
                self._current_base_url = f'https://jable.tv/search/{q}/'
            elif self._site_key == 'SupJav':
                self._current_base_url = SupJavBrowser.search_url(q, lang=T('supjav_lang'))
            elif self._site_key == 'HanimeTV':
                self._current_base_url = HanimeTVBrowser.search_url(q)
            elif self._site_key == 'Hanime1':
                self._current_base_url = Hanime1Browser.search_url(q)
            elif self._site_key == 'TnaFlix':
                self._current_base_url = TnaFlixBrowser.search_url(q)
            else:
                lang = T('missav_lang')
                eq = quote(q, safe='')
                if lang:
                    self._current_base_url = f'https://missav.ai/{lang}/search/{eq}'
                else:
                    self._current_base_url = f'https://missav.ai/search/{eq}'
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_source_subtitle_evidence.clear()
        self._update_selection_count()
        self._load_page()

    # ── Entity pages (actress / director / studio / tag) ────────────────
    _ENTITY_LABELS = {
        'actress': 'Actress',
        'director': 'Director',
        'studio': 'Studio',
        'tag': 'Tag',
    }
    _ENTITY_NAME_KEYS = {
        'actress': ('actress', 'actresses', 'model', 'models', 'cast'),
        'director': ('director', 'directors'),
        'studio': ('studio', 'maker', 'publisher', 'production'),
        'tag': ('tags', 'categories', 'keywords'),
    }

    def _tag_slug_for_name(self, name):
        """Find the JableTV sidebar slug for a tag name, if it is a known tag."""
        name = (name or '').strip().lower()
        if not name:
            return ''
        try:
            from M3U8Sites.SiteJableTV import JableTVBrowser
            for _group, tags in JableTVBrowser.SIDEBAR_TAGS.items():
                for tag_name, slug in tags:
                    if tag_name.lower() == name or slug.lower() == name:
                        return slug
        except Exception:
            pass
        return ''

    def _site_search_url(self, query, site_key=None):
        """Build a search listing URL for a site (defaults to the current site)."""
        site_key = site_key or self._site_key
        query = (query or '').strip()
        if not query:
            return ''
        from urllib.parse import quote
        if site_key == 'JableTV':
            # jable.tv only serves search results for a raw (unencoded) path.
            return f'https://jable.tv/search/{query}/'
        if site_key == 'SupJav':
            return SupJavBrowser.search_url(query, lang=T('supjav_lang'))
        if site_key == 'HanimeTV':
            return HanimeTVBrowser.search_url(query)
        if site_key == 'Hanime1':
            return Hanime1Browser.search_url(query)
        if site_key == 'TnaFlix':
            return TnaFlixBrowser.search_url(query)
        lang = T('missav_lang')
        q = quote(query, safe='')
        return f'https://missav.ai/{lang}/search/{q}' if lang else f'https://missav.ai/search/{q}'

    def _entity_listing_url(self, kind, name):
        """Build a browse URL that lists everything for an actress / director /
        studio / tag. Dedicated listing pages are unreliable across sites, so we
        run a quick search over the database by name and show only those titles."""
        from urllib.parse import quote
        name = (name or '').strip()
        if not name:
            return ''
        q = quote(name, safe='')
        if self._site_key == 'JableTV':
            if kind == 'tag':
                slug = self._tag_slug_for_name(name)
                if slug:
                    return JableTVBrowser.tag_url(slug)
            return self._site_search_url(name)
        if self._site_key == 'MissAV':
            if kind == 'tag':
                return f'https://missav.ai/tags/{q}'
            return self._site_search_url(name)
        if self._site_key == 'TnaFlix':
            return TnaFlixBrowser.search_url(name)
        return self._site_search_url(name)

    def _show_page_heading(self, kind, name):
        hdr = getattr(self, '_page_heading', None)
        if hdr is None:
            return
        prefix = self._ENTITY_LABELS.get(kind, '')
        text = f'{prefix}: {name}' if prefix else name
        self._entity_heading_base_text = text
        self._refresh_entity_heading()
        try:
            self._page_heading_close.pack(side='left', padx=12, pady=6)
        except Exception:
            pass
        try:
            hdr.pack(fill='x', before=getattr(self, '_grid_scroll', None))
        except (tk.TclError, Exception):
            try:
                hdr.pack(fill='x')
            except Exception:
                pass

    def _show_search_all_heading(self, query):
        """Banner above the merged Search From All results."""
        hdr = getattr(self, '_page_heading', None)
        if hdr is None:
            return
        self._entity_heading_base_text = f'{T("search_all_title")}: {query}'
        self._refresh_entity_heading()
        try:
            self._page_heading_close.pack_forget()
        except Exception:
            pass
        try:
            hdr.pack(fill='x', before=getattr(self, '_grid_scroll', None))
        except (tk.TclError, Exception):
            try:
                hdr.pack(fill='x')
            except Exception:
                pass

    def _refresh_entity_heading(self):
        """Re-render the heading label, appending the source site when the
        entity's videos come from a site other than the one being browsed."""
        text = getattr(self, '_entity_heading_base_text', '') or ''
        site = getattr(self, '_entity_site_key', '') or self._site_key
        if site and site != self._site_key:
            text = f'{text}  ·  {site}'
        try:
            self._page_heading_lbl.configure(text=f'  {text}  ')
        except Exception:
            pass

    def _hide_page_heading(self):
        self._active_entity = None
        hdr = getattr(self, '_page_heading', None)
        if hdr is None:
            return
        try:
            hdr.pack_forget()
        except tk.TclError:
            pass

    def _open_entity_page(self, kind, name, url=''):
        """Open a 'second page' in the browse grid showing all videos related to
        an actress / director / studio / tag. The heading bar is titled with the
        entity name."""
        # Remember the video player page when the entity is opened from a preview,
        # so the back button returns the user to the exact player they came from.
        if getattr(self, '_browse_mode', 'grid') == 'preview':
            self._entity_prev_from_preview = True
            self._entity_prev_preview_video = dict(self._preview_video or {})
        else:
            self._entity_prev_from_preview = False
            self._entity_prev_preview_video = None
        if getattr(self, '_tab_keys', ['browse'])[getattr(self, '_active_tab_idx', 0)] != 'browse':
            self._select_tab('browse')
        if getattr(self, '_browse_mode', 'grid') != 'grid':
            self._set_browse_mode('grid')
        name = (name or '').strip()
        if not name and not url:
            return
        if not url:
            url = self._entity_listing_url(kind, name)
        if not url:
            return
        if not getattr(self, '_entity_prev_base_url', None):
            self._entity_prev_base_url = self._current_base_url
            try:
                self._entity_prev_cat = self._cat_var.get()
            except Exception:
                self._entity_prev_cat = ''
        if kind == 'tag':
            self._active_tag_slug = self._tag_slug_for_name(name) or None
            self._active_tag_url = url
        else:
            self._active_tag_slug = None
            self._active_tag_url = None
        self._active_entity = {'kind': kind, 'name': name, 'url': url}

        # If Search from All is active, search across all sites simultaneously
        if getattr(self, '_search_all_mode', False) and name:
            self._search_all_active = True
            self._search_all_query = name
            self._page = 1
            self._last_loaded_page = 1
            self._has_next = True
            self._browse_blocked = False
            self._browse_empty_message = ''
            self._selected_urls.clear()
            self._selected_source_subtitle_evidence.clear()
            self._update_selection_count()
            self._show_search_all_heading(name)
            self._rebuild_sidebar()
            self._load_page()
            return

        # Otherwise, restrict to the user's selected site
        order = [self._site_key]
        candidates = []

        def _add(url, site):
            if url and site and (url, site) not in candidates:
                candidates.append((url, site))

        if url:
            _add(url, self._site_key)
        if name:
            for site in order:
                _add(self._site_search_url(name, site), site)
            for alt in self._entity_alt_names(kind):
                alt = (alt or '').strip()
                if not alt or alt == name:
                    continue
                for site in order:
                    _add(self._site_search_url(alt, site), site)
        if not candidates:
            return
        self._exit_search_all_view()
        self._entity_candidates = candidates
        self._entity_search_pending = False
        self._current_base_url = candidates[0][0]
        self._entity_site_key = candidates[0][1]
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_source_subtitle_evidence.clear()
        self._update_selection_count()
        self._show_page_heading(kind, name)
        self._rebuild_sidebar()
        self._load_page()

    def _entity_alt_names(self, kind):
        """Other name spellings for the same entity, collected from the preview
        metadata (used to retry a search that otherwise comes back empty)."""
        keys = self._ENTITY_NAME_KEYS.get(kind, ('actress', 'actresses', 'model', 'models', 'cast'))
        return self._preview_list(*keys)

    def _close_entity_page(self):
        """Close the entity page and return to where the user came from: the
        previous category listing, or the video player if the entity page was
        opened from a preview."""
        prev = getattr(self, '_entity_prev_base_url', '')
        prev_cat = getattr(self, '_entity_prev_cat', '')
        came_from_preview = getattr(self, '_entity_prev_from_preview', False)
        prev_video = getattr(self, '_entity_prev_preview_video', None)
        self._entity_prev_from_preview = False
        self._entity_prev_preview_video = None
        self._entity_search_pending = False
        self._exit_search_all_view()

        # Return to the video player page the user was on before opening the entity page.
        if came_from_preview and isinstance(prev_video, dict) and prev_video.get('url'):
            self._preview_stack = [dict(prev_video)]
            self._open_preview(prev_video, is_back_nav=True)
            return

        self._entity_prev_base_url = ''
        self._entity_prev_cat = ''
        self._entity_candidates = []
        self._entity_site_key = ''
        self._active_tag_slug = None
        self._active_tag_url = None
        self._hide_page_heading()
        if prev and prev != self._current_base_url:
            self._current_base_url = prev
            self._page = 1
            self._last_loaded_page = 1
            self._has_next = True
            self._browse_blocked = False
            self._browse_empty_message = ''
            self._selected_urls.clear()
            self._selected_source_subtitle_evidence.clear()
            self._update_selection_count()
            if prev_cat:
                try:
                    self._cat_var.set(prev_cat)
                except Exception:
                    pass
            self._load_page()

    def _on_tag_click(self, url: str, name: str, slug: str = ''):
        self._open_entity_page('tag', name, url)

    # ── Sidebar ──────────────────────────────────────────────────────
    def _rebuild_sidebar(self):
        for w in self._sidebar.winfo_children():
            w.destroy()

        # Sidebar Title Header
        title_box = ctk.CTkFrame(self._sidebar, fg_color='transparent')
        title_box.pack(fill='x', padx=12, pady=(12, 8))
        if getattr(self, '_tag_icon', None):
            ctk.CTkLabel(title_box, text="", image=self._tag_icon, width=20, height=20).pack(side='left', padx=(0, 6))
            ctk.CTkLabel(title_box, text=T('sidebar_title'),
                         text_color=ACCENT,
                         font=(ui_font(), 13, 'bold')).pack(side='left')
        else:
            ctk.CTkLabel(title_box, text=f"🏷  {T('sidebar_title')}",
                         text_color=ACCENT,
                         font=(ui_font(), 13, 'bold')).pack(anchor='w')

        # Subtle divider
        ctk.CTkFrame(self._sidebar, height=1,
                     fg_color=BORDER).pack(fill='x', padx=8, pady=(0, 8))

        # JableTV has a rich tag taxonomy; MissAV / SupJav have none, so offer
        # their categories as sidebar filters instead of an empty panel.
        # Each entry is (display_name, url, slug_or_''); an empty slug means the
        # button navigates to a category/page, otherwise it opens a tag page.
        # All groups start collapsed; they only expand when the header is toggled.
        if self._site_key == 'JableTV':
            tags_by_group = {
                T('sidebar_popular_tags'): [
                    (en_name, JableTVBrowser.tag_url(slug), slug)
                    for en_name, slug in JABLE_EN_TAG_GROUPS
                ]
            }
            for group_name, tag_list in JableTVBrowser.SIDEBAR_TAGS.items():
                tags_by_group[group_name] = [
                    (site_i18n.loc(site_i18n.TAGS, slug, name),
                     JableTVBrowser.tag_url(slug),
                     slug)
                    for name, slug in tag_list
                ]
        elif self._site_key == 'TnaFlix':
            tags_by_group = {}
            for group_name, tag_list in getattr(TnaFlixBrowser, 'SIDEBAR_TAG_GROUPS', {}).items():
                tags_by_group[group_name] = [(name, url, '') for name, url in tag_list]
        elif self._site_key == 'MissAV':
            tags_by_group = {}
            for nav_label, nav_items in MISS_AV_HEADER_NAV:
                tags_by_group[nav_label] = [(name, url, '') for name, url in nav_items]
            cached = getattr(self, '_cached_sidebar_cats', None)
            if cached is not None:
                tags_by_group[T('sidebar_categories')] = [(c['name'], c['url'], '') for c in cached]
            else:
                tags_by_group[T('sidebar_categories')] = []
                _site_key_for_bg = self._site_key
                _lang_for_bg = T('missav_lang')
                _my_gen = self._build_gen
                def _fetch_sidebar_cats_bg(_sk=_site_key_for_bg, _lang=_lang_for_bg):
                    try:
                        cats = SITES[_sk]['browser'].fetch_categories(lang=_lang)
                    except Exception:
                        cats = []
                    def _apply():
                        if self._is_closing or _my_gen != self._build_gen:
                            return
                        self._cached_sidebar_cats = cats
                        self._rebuild_sidebar()
                    self._ui(_apply, gen=_my_gen)
                threading.Thread(target=_fetch_sidebar_cats_bg, daemon=True).start()
        else:
            tags_by_group = {}
            cached = getattr(self, '_cached_sidebar_cats', None)
            if cached is not None:
                tags_by_group[T('sidebar_categories')] = [(c['name'], c['url'], '') for c in cached]
            else:
                tags_by_group[T('sidebar_categories')] = []
                _site_key_for_bg = self._site_key
                _lang_for_bg = T('supjav_lang')
                _my_gen = self._build_gen
                def _fetch_sidebar_cats_bg(_sk=_site_key_for_bg, _lang=_lang_for_bg):
                    try:
                        cats = SITES[_sk]['browser'].fetch_categories(lang=_lang)
                    except TypeError:
                        try:
                            cats = SITES[_sk]['browser'].fetch_categories()
                        except Exception:
                            cats = []
                    except Exception:
                        cats = []
                    def _apply():
                        if self._is_closing or _my_gen != self._build_gen:
                            return
                        self._cached_sidebar_cats = cats
                        self._rebuild_sidebar()
                    self._ui(_apply, gen=_my_gen)
                threading.Thread(target=_fetch_sidebar_cats_bg, daemon=True).start()

        self._rebuild_sidebar_tags(tags_by_group)

    def _rebuild_sidebar_tags(self, tags_by_group):
        lookup_tag_groups = self._site_key == 'JableTV'
        for group_name, tag_list in tags_by_group.items():
            if not tag_list:
                continue
            expanded = self._sidebar_expanded.get(group_name, False)
            display_group_name = (site_i18n.loc(site_i18n.TAG_GROUPS, group_name, group_name)
                                  if lookup_tag_groups else group_name)

            # Sleek Group Header Card Button
            arrow = '▾' if expanded else '▸'
            hdr = ctk.CTkButton(
                self._sidebar,
                text=f'{arrow}  {display_group_name}  ({len(tag_list)})',
                fg_color=BG_CARD if expanded else 'transparent',
                hover_color=BG_CARD_HOVER,
                text_color=ACCENT if expanded else TEXT_PRI,
                anchor='w',
                font=(ui_font(), 11, 'bold' if expanded else 'normal'),
                height=32, corner_radius=CONTROL_RADIUS,
                border_width=1 if expanded else 0,
                border_color=BORDER if expanded else BORDER,
                command=lambda g=group_name: self._toggle_group(g))
            hdr.pack(fill='x', padx=6, pady=2)

            if expanded:
                for display_name, item_url, slug in tag_list:
                    if slug:
                        is_active = (
                            getattr(self, '_active_tag_slug', None) == slug or
                            getattr(self, '_active_tag_url', None) == item_url
                        )
                    else:
                        is_active = (
                            (self._current_base_url or '').rstrip('/') ==
                            item_url.rstrip('/')
                        )
                    btn = ctk.CTkButton(
                        self._sidebar, text=f"•  {display_name}",
                        fg_color='transparent',
                        hover_color=ACCENT_DIM,
                        text_color=ACCENT if is_active else TEXT_SEC,
                        anchor='w',
                        font=(ui_font(), 10, 'bold' if is_active else 'normal'),
                        height=26, corner_radius=6,
                        command=lambda u=item_url, n=display_name, s=slug: (
                            self._on_tag_click(u, n, s) if s
                            else self._on_sidebar_cat_click(u, n)))
                    btn.pack(fill='x', padx=(16, 6), pady=1)

    def _on_sidebar_cat_click(self, url: str, name: str):
        """Navigate to a category straight from the sidebar (used by sites that
        have categories but no tag taxonomy, e.g. MissAV / SupJav)."""
        if name:
            idx = next((i for i, c in enumerate(self._categories)
                        if c['name'] == name), -1)
            if idx >= 0:
                self._on_cat_change(name)
                return
        if getattr(self, '_tab_keys', ['browse'])[getattr(self, '_active_tab_idx', 0)] != 'browse':
            self._select_tab('browse')
        if getattr(self, '_browse_mode', 'grid') != 'grid':
            self._set_browse_mode('grid')
        self._active_tag_slug = None
        self._active_tag_url = None
        self._entity_prev_base_url = ''
        self._entity_prev_cat = ''
        self._entity_search_pending = False
        self._entity_candidates = []
        self._entity_site_key = ''
        self._exit_search_all_view()
        self._hide_page_heading()
        self._current_base_url = url
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_source_subtitle_evidence.clear()
        self._update_selection_count()
        try:
            if name and self._cat_menu.cget('values'):
                self._cat_var.set(name)
        except Exception:
            pass
        self._rebuild_sidebar()
        self._load_page()

    def _toggle_group(self, group: str):
        was_expanded = self._sidebar_expanded.get(group, False)
        if was_expanded:
            self._sidebar_expanded[group] = False
        else:
            self._sidebar_expanded.clear()
            self._sidebar_expanded[group] = True
        self._rebuild_sidebar()

    # ── Download actions ─────────────────────────────────────────────
    def _add_selected_to_queue(self):
        dest = self._dest_var.get() or 'download'
        for url in list(self._selected_urls):
            if M3U8Sites.VaildateUrl(url):
                self._dlmgr.add_item(
                    url, state='等待中', dest=dest,
                    source_subtitle_evidence=(
                        self._selected_source_subtitle_evidence.get(
                            url, ())))
        n = len(self._selected_urls)
        self._clear_selection_in_place()
        print(f'已加入 {n} 部到清單')

    def _download_selected(self):
        dest = self._dest_var.get() or 'download'
        for url in list(self._selected_urls):
            if M3U8Sites.VaildateUrl(url):
                self._dlmgr.add_item(
                    url, state='等待中', dest=dest,
                    source_subtitle_evidence=(
                        self._selected_source_subtitle_evidence.get(
                            url, ())))
                self._dlmgr.enqueue(url, dest)
        n = len(self._selected_urls)
        self._clear_selection_in_place()
        print(f'{n} 部開始下載')

    def _download_url(self):
        url = self._dl_url_var.get().strip()
        if not url:
            return
        # Direct video URL
        if M3U8Sites.VaildateUrl(url):
            dest = self._dest_var.get() or 'download'
            self._dlmgr.add_item(url, state='等待中', dest=dest)
            self._dlmgr.enqueue(url, dest)
            self._dl_url_var.set('')
            return
        # Listing / actress / category URL — crawl all videos
        if self._is_listing_url(url):
            self._dl_url_var.set('')
            self._status_lbl.configure(text=T('crawling_url'))
            dest = self._dest_var.get() or 'download'
            threading.Thread(target=self._crawl_listing, args=(url, dest),
                             daemon=True).start()
            return
        self._status_lbl.configure(text=T('url_not_supported'))
        print(T('url_not_supported') + f': {url}')

    def _is_listing_url(self, url: str) -> bool:
        """Check if URL is a JableTV, MissAV, or SupJav listing/category/actress page."""
        if re.match(r'https://(?:www\.)?supjav\.com/(?:(?:zh|ja)/)?\d+\.html$', url):
            return False
        return (bool(re.match(r'https://(?:www\.)?(?:jable\.tv|fs1\.app)/', url)) or
                bool(re.match(r'https://(?:www\.)?(?:missav\.(?:ai|ws|live)|missav123\.com)/', url)) or
                bool(re.match(r'https://(?:www\.)?supjav\.com/', url)))

    def _crawl_listing(self, url: str, dest: str):
        """Crawl a listing URL across all pages; add every video to the queue."""
        gen = self._build_gen
        seen: set[str] = set()
        is_jable = bool(re.match(r'https://(?:www\.)?(?:jable\.tv|fs1\.app)/', url))
        is_supjav = bool(re.match(r'https://(?:www\.)?supjav\.com/', url))
        max_pages = 50

        for page in range(1, max_pages + 1):
            if self._is_closing:
                return
            try:
                if is_jable:
                    if page == 1:
                        page_url = url
                    elif '?' in url:
                        page_url = f'{url}&from={page}'
                    else:
                        page_url = f'{url.rstrip("/")}/?from={page}'
                    videos = JableTVBrowser.fetch_page(page_url)
                elif is_supjav:
                    page_url = SupJavBrowser.page_url(url, page)
                    videos = SupJavBrowser.fetch_page(page_url)
                else:
                    page_url = MissAVBrowser.page_url(url, page)
                    videos = MissAVBrowser.fetch_page(page_url)
            except MirrorsBlockedError as e:
                print(f'[crawl] page {page} blocked: {e}')
                self._ui(lambda: self._status_lbl.configure(text=T('mirrors_blocked')),
                         gen=gen)
                return
            except Exception as e:
                print(f'[crawl] page {page} error: {e}')
                break

            if not videos:
                if page == 1:
                    print(f'[crawl] No videos found on first page: {url}')
                break

            new_count = 0
            for v in videos:
                video_url = v.get('url', '')
                if video_url and video_url not in seen and M3U8Sites.VaildateUrl(video_url):
                    seen.add(video_url)
                    new_count += 1
                    name = v.get('title', '')
                    candidate = dict(v)
                    candidate['_site'] = (
                        'JableTV' if is_jable
                        else 'SupJav' if is_supjav
                        else 'MissAV')
                    candidate['_source_listing_url'] = url
                    self._dlmgr.add_item(
                        video_url, name=name, state='等待中', dest=dest,
                        source_subtitle_evidence=(
                            trusted_chinese_subtitle_evidence(candidate)))
                    self._dlmgr.enqueue(video_url, dest)

            if new_count == 0:
                break  # No new videos on this page, stop

            self._ui(lambda n=len(seen): self._status_lbl.configure(
                text=T('crawling_url') + f' ({n})'), gen=gen)

        n = len(seen)
        self._ui(lambda: self._status_lbl.configure(
            text=T('crawl_added', n=n)), gen=gen)

    def _download_all(self):
        # If the URL field has a listing URL, crawl it first
        url = self._dl_url_var.get().strip()
        if url:
            if M3U8Sites.VaildateUrl(url):
                dest = self._dest_var.get() or 'download'
                self._dlmgr.add_item(url, state='等待中', dest=dest)
                self._dlmgr.enqueue(url, dest)
                self._dl_url_var.set('')
            elif self._is_listing_url(url):
                self._dl_url_var.set('')
                self._status_lbl.configure(text=T('crawling_url'))
                dest = self._dest_var.get() or 'download'
                threading.Thread(target=self._crawl_listing, args=(url, dest),
                                 daemon=True).start()
                return
        dest = self._dest_var.get() or 'download'
        count = 0
        for item in self._dlmgr.get_items():
            # Skip items that are already active or completed; queued ('等待中')
            # items still need enqueue() to (re)start them.
            if item.state in (
                    '已下載', '未偵測到日語語音', '下載中', '準備中'):
                continue
            self._dlmgr.enqueue(item.url, item.dest or dest)
            count += 1
        if count:
            print(f'已加入 {count} 個下載任務')

    def _retry_download(self, url: str):
        item = next((i for i in self._dlmgr.get_items() if i.url == url), None)
        if item is None:
            return
        item.progress = 0
        item.speed = ''
        item.error = ''
        self._dlmgr.enqueue(url, item.dest or self._dest_var.get() or 'download')

    def _cancel_all(self):
        self._dlmgr.cancel_all()

    def _clear_queue(self):
        self._dlmgr.clear_all()
        self._dl_gen += 1
        self._last_download_save_sig = None
        try:
            self._dlmgr.save_csv(CSV_PATH)
        except Exception as e:
            print(f'[clear queue save failed] {e}', flush=True)
        self._refresh_downloads(schedule=False)

    def _on_cf_host_change(self, host):
        ov = config.get_cf_override(host) or {}
        self._cf_cookie_var.set(ov.get('cookie', ''))
        self._cf_ua_var.set(ov.get('ua', ''))

    def _refresh_proxy_status(self, saved=False):
        lbl = getattr(self, '_proxy_status_lbl', None)
        if not lbl:
            return
        mode = config.get_proxy_mode()
        if mode == 'manual' and config.get_proxy_url():
            text, color = T('proxy_enabled'), SUCCESS
        elif mode == 'system':
            _display_url, status = config.refresh_system_proxy()
            if status == 'detected':
                text, color = T('proxy_windows_enabled'), SUCCESS
            elif status == 'pac':
                text, color = T('proxy_windows_pac'), WARNING
            elif status == 'invalid':
                text, color = T('proxy_windows_invalid'), ERROR_C
            else:
                text, color = T('proxy_windows_missing'), WARNING
        else:
            text, color = T('proxy_disabled'), TEXT_DIM
        if saved:
            text = f"{T('proxy_saved')} · {text}"
        try:
            lbl.configure(text=text, text_color=color)
        except Exception:
            pass

    def _on_proxy_save(self):
        try:
            value = config.set_proxy_url(self._proxy_var.get())
        except (OSError, ValueError):
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._proxy_var.set(value)
        self._refresh_proxy_status(saved=True)

    def _on_proxy_windows(self):
        try:
            config.set_proxy_mode('system')
        except OSError:
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._refresh_proxy_status(saved=True)

    def _on_proxy_clear(self):
        try:
            config.set_proxy_url('')
        except OSError:
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._proxy_var.set('')
        self._refresh_proxy_status()

    def _on_cf_save(self):
        host = self._cf_host_var.get()
        config.set_cf_override(host, self._cf_cookie_var.get(), self._cf_ua_var.get())
        self._refresh_cf_status()
        lbl = getattr(self, '_cf_status_lbl', None)
        if lbl:
            try:
                current = lbl.cget('text')
                lbl.configure(text=f"{T('cf_saved')} | {current}")
            except Exception:
                pass

    def _on_cf_clear(self):
        host = self._cf_host_var.get()
        config.clear_cf_override(host)
        self._cf_cookie_var.set('')
        self._cf_ua_var.set('')
        self._refresh_cf_status()

    def _refresh_cf_status(self):
        lbl = getattr(self, '_cf_status_lbl', None)
        if not lbl:
            return
        hosts = config.cf_override_hosts()
        try:
            if hosts:
                lbl.configure(text=T('cf_status', hosts=', '.join(hosts)))
            else:
                lbl.configure(text=T('cf_status_none'))
        except Exception:
            pass

    def _on_speed_change(self, val):
        from M3U8Sites.M3U8Crawler import speed_limiter
        val = str(val)
        if val == T('unlimited') or not val[:1].isdigit():
            self._speed_mbps = 0
            speed_limiter.set_limit(0)
            return
        try:
            mbps = float(val.split()[0])
        except (ValueError, IndexError):
            return
        self._speed_mbps = mbps
        speed_limiter.set_limit(mbps)

    def _on_res_change(self, val):
        from M3U8Sites.M3U8Crawler import set_resolution_pref
        pref = self._resolution_pref_from_label(val)
        set_resolution_pref(pref)
        config.set_resolution_pref(pref)

    def _on_subtitle_change(self, val):
        config.set_subtitle_pref(self._subtitle_pref_from_label(val))

    def _on_recognition_quality_change(self, val):
        quality = self._recognition_quality_from_label(val)
        quality = config.set_recognition_quality(quality)
        self._recognition_quality_var.set(
            self._recognition_quality_label(quality))

    def _prefetch_subtitle_models(self):
        if getattr(self, '_subtitle_prefetching', False):
            return
        if not messagebox.askyesno(
                T('subtitle_prefetch_confirm_title'),
                T('subtitle_prefetch_confirm_body')):
            return
        self._subtitle_prefetching = True
        self._subtitle_prefetch_status_text = T('subtitle_prefetch_started')
        self._subtitle_prefetch_btn.configure(state='disabled')
        self._subtitle_prefetch_status.configure(
            text=self._subtitle_prefetch_status_text)
        threading.Thread(
            target=self._prefetch_subtitle_models_worker,
            daemon=True).start()

    def _prefetch_subtitle_models_worker(self):
        stage_keys = {
            'runtime': 'subtitle_stage_runtime',
            'model': 'subtitle_stage_model',
            'translation_model': 'subtitle_stage_translation_model',
        }

        def _progress(stage, percent):
            text = T(stage_keys.get(stage, stage))
            if percent is not None:
                text = f'{text} · {percent}%'
            self.after(0, lambda: self._set_subtitle_prefetch_status(text))

        try:
            summary = prefetch_subtitle_models(
                progress_callback=_progress,
                cancel_check=lambda: self._is_closing)
            status = T('subtitle_prefetch_done')
            if not summary.get('translation'):
                status = (
                    f"{status} · {T('subtitle_prefetch_translation_skipped')}")
            self.after(
                0, lambda: self._set_subtitle_prefetch_status(status))
        except Exception as exc:
            message = str(exc or '').strip() or exc.__class__.__name__
            self.after(0, lambda: self._set_subtitle_prefetch_status(
                T('subtitle_prefetch_error', error=message)))
        finally:
            self._subtitle_prefetching = False
            self.after(
                0, lambda: self._set_subtitle_prefetch_button_enabled())

    def _set_subtitle_prefetch_status(self, text):
        self._subtitle_prefetch_status_text = text
        label = getattr(self, '_subtitle_prefetch_status', None)
        if label is not None:
            try:
                label.configure(text=text)
            except Exception:
                pass

    def _set_subtitle_prefetch_button_enabled(self):
        if getattr(self, '_subtitle_prefetching', False):
            return
        btn = getattr(self, '_subtitle_prefetch_btn', None)
        if btn is not None:
            try:
                btn.configure(state='normal')
            except Exception:
                pass

    def _update_subtitle_cache_status(self):
        lbl = getattr(self, '_subtitle_clear_status', None)
        if lbl is None:
            return
        try:
            cache = SubtitleCache()
            stats = cache.get_cache_stats()
            count = stats.get('file_count', 0)
            bytes_total = stats.get('total_bytes', 0)
            if count > 0:
                size_mb = bytes_total / (1024 * 1024)
                if size_mb >= 0.1:
                    size_str = f"{size_mb:.1f} MB"
                else:
                    size_kb = max(1, round(bytes_total / 1024))
                    size_str = f"{size_kb} KB"
                lbl.configure(text=T('clear_downloaded_subtitles_count', count=count, size=size_str))
            else:
                lbl.configure(text=T('clear_downloaded_subtitles_empty'))
        except Exception:
            pass

    def _remove_all_downloaded_subtitles(self):
        try:
            cache = SubtitleCache()
            stats = cache.get_cache_stats()
            count = stats.get('file_count', 0)
            if count == 0:
                messagebox.showinfo(
                    T('clear_downloaded_subtitles_title'),
                    T('clear_downloaded_subtitles_already_empty'))
                return
            if not messagebox.askyesno(
                T('clear_downloaded_subtitles_confirm_title'),
                T('clear_downloaded_subtitles_confirm_body')):
                return

            removed = cache.clear_all()
            self._update_subtitle_cache_status()
            if getattr(self, '_status_lbl', None) is not None:
                self._status_lbl.configure(text=T('clear_downloaded_subtitles_done', count=removed))
            messagebox.showinfo(
                T('clear_downloaded_subtitles_title'),
                T('clear_downloaded_subtitles_done', count=removed))
        except Exception as exc:
            messagebox.showerror(
                T('clear_downloaded_subtitles_title'),
                str(exc))

    def _on_conc_change(self, _event=None):
        try:
            requested = int(self._conc_var.get().strip())
        except (AttributeError, TypeError, ValueError):
            self._conc_var.set(str(self._dlmgr.max_concurrent))
            return
        value = config.set_download_concurrency(requested)
        self._dlmgr.max_concurrent = value
        self._conc_var.set(str(value))

    def _commit_workers_preference(self):
        current = config.get_max_workers_per_video()
        var = self.__dict__.get('_workers_var')
        if var is None:
            return current
        try:
            requested = int(var.get().strip())
        except (AttributeError, TypeError, ValueError):
            value = current
        else:
            value = config.set_max_workers_per_video(requested)
        var.set(str(value))
        return value

    def _on_workers_change(self, _event=None):
        self._commit_workers_preference()

    def _pick_dest(self):
        d = filedialog.askdirectory(parent=self)
        if d:
            self._dest_var.set(d)

    def _open_dest_folder(self):
        import subprocess, platform
        dest = self._dest_var.get() or 'download'
        folder = os.path.abspath(dest)
        if not os.path.isdir(folder):
            messagebox.showerror(T('open_folder_failed_title'), folder)
            return
        system = platform.system()
        try:
            if system == 'Windows':
                os.startfile(folder)
            elif system == 'Darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except OSError as e:
            messagebox.showerror(T('open_folder_failed_title'), str(e))

    def _open_queue_folder(self):
        import subprocess, platform
        folder = os.path.dirname(config.queue_csv_path())
        system = platform.system()
        try:
            os.makedirs(folder, exist_ok=True)
            if system == 'Windows':
                os.startfile(folder)
            elif system == 'Darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except OSError as e:
            messagebox.showerror(T('open_folder_failed_title'), str(e))

    def _clear_saved_queue(self):
        if not messagebox.askyesno(T('clear_saved_queue'),
                                   T('clear_saved_queue_confirm')):
            return
        self._dlmgr.clear_all()
        self._dl_gen += 1
        self._last_download_save_sig = None
        try:
            self._dlmgr.save_csv(CSV_PATH)
            if getattr(self, '_status_lbl', None) is not None:
                self._status_lbl.configure(text=T('clear_saved_queue_done'))
            messagebox.showinfo(T('clear_saved_queue'), T('clear_saved_queue_done'))
        except Exception as e:
            messagebox.showerror(T('clear_saved_queue_failed'), str(e))
        finally:
            self._refresh_downloads(schedule=False)

    # ── Download list refresh (incremental — no destroy/rebuild storm) ──
    _STATE_COLORS = {
        '下載中': ACCENT, '準備中': WARNING, '等待中': WARNING,
        '字幕準備中': ACCENT, '字幕辨識中': ACCENT,
        '字幕翻譯中': ACCENT,
        '已下載': SUCCESS, '未偵測到日語語音': TEXT_SEC,
        '未完成': WARNING, '已取消': TEXT_DIM,
        '網址錯誤': ERROR_C, '封鎖/解析失敗': ERROR_C,
    }
    _STATE_BACKGROUNDS = {
        '下載中': ACCENT_DIM, '準備中': WARNING_DIM, '等待中': WARNING_DIM,
        '字幕準備中': ACCENT_DIM, '字幕辨識中': ACCENT_DIM,
        '字幕翻譯中': ACCENT_DIM,
        '已下載': SUCCESS_DIM, '未偵測到日語語音': BG_BADGE,
        '未完成': WARNING_DIM, '已取消': BG_BADGE,
        '網址錯誤': ERROR_DIM, '封鎖/解析失敗': ERROR_DIM,
    }

    def _sync_dl_footer(self, hidden: int):
        if hidden > 0:
            text = T('dl_list_more_not_shown', n=hidden)
            if self._dl_footer_lbl is None:
                self._dl_footer_lbl = ctk.CTkLabel(
                    self._dl_scroll, text=text, text_color=TEXT_DIM,
                    font=(ui_font(), 11))
            else:
                self._dl_footer_lbl.configure(text=text)
            try:
                self._dl_footer_lbl.pack_forget()
            except Exception:
                pass
            self._dl_footer_lbl.pack(fill='x', padx=12, pady=(4, 16))
        elif self._dl_footer_lbl is not None:
            try:
                self._dl_footer_lbl.destroy()
            except Exception:
                pass
            self._dl_footer_lbl = None

    def _build_visible_rows(self, visible: list[DownloadItem]) -> bool:
        built = 0
        more_to_build = False
        for item in visible:
            widgets = self._dl_rows.get(item.url)
            if widgets is not None:
                self._update_dl_row(widgets, item)
                continue
            if built >= ROW_BUILD_BUDGET:
                more_to_build = True
                continue
            try:
                self._dl_rows[item.url] = self._build_dl_row(item)
                built += 1
            except Exception as e:
                print(f'[download row build failed] {item.url}: {e}', flush=True)

        desired_rows = [
            self._dl_rows[i.url]['row']
            for i in visible
            if i.url in self._dl_rows and 'row' in self._dl_rows[i.url]
        ]
        try:
            current_slaves = [
                s for s in self._dl_scroll.pack_slaves()
                if s is not getattr(self, '_dl_empty_lbl', None)
                and s is not getattr(self, '_dl_footer_lbl', None)
            ]
            if current_slaves != desired_rows:
                for r in desired_rows:
                    r.pack_forget()
                    r.pack(fill='x', padx=16, pady=7)
                if self._dl_footer_lbl is not None:
                    self._dl_footer_lbl.pack_forget()
                    self._dl_footer_lbl.pack(fill='x', padx=12, pady=(4, 16))
        except Exception:
            pass

        return more_to_build

    def _arm_dl_drain(self):
        if (self._dl_drain_id is not None or self._is_closing
                or self._rebuilding):
            return
        gen = self._dl_gen
        try:
            self._dl_drain_id = self.after(
                20, lambda g=gen: self._drain_dl_rows(g))
        except tk.TclError:
            self._dl_drain_id = None

    def _drain_dl_rows(self, gen: int):
        self._dl_drain_id = None
        if (self._is_closing or self._rebuilding or gen != self._dl_gen
                or getattr(self, '_dl_scroll', None) is None):
            return
        try:
            items = self._dlmgr.get_items()
            visible = _visible_window(items, MAX_VISIBLE_ROWS)
            visible_set = {i.url for i in visible}

            for url in list(self._dl_rows.keys()):
                if url not in visible_set:
                    widgets = self._dl_rows.pop(url)
                    try:
                        widgets['row'].destroy()
                    except Exception:
                        pass

            if not items:
                self._sync_dl_footer(0)
                return

            more_to_build = self._build_visible_rows(visible)
            self._sync_dl_footer(len(items) - len(visible))
            if more_to_build:
                self._arm_dl_drain()
        except tk.TclError:
            pass

    def _refresh_downloads(self, schedule: bool = True):
        if self._is_closing:
            return
        if (self._rebuilding or getattr(self, '_status_lbl', None) is None
                or getattr(self, '_dl_scroll', None) is None):
            if schedule:
                try:
                    self.after(1000, self._refresh_downloads)
                except tk.TclError:
                    pass
            return
        try:
            items = self._dlmgr.get_items()
            visible = _visible_window(items, MAX_VISIBLE_ROWS)
            visible_set = {i.url for i in visible}

            # Remove rows outside the bounded visible window.
            for url in list(self._dl_rows.keys()):
                if url not in visible_set:
                    widgets = self._dl_rows.pop(url)
                    try:
                        widgets['row'].destroy()
                    except Exception:
                        pass

            # Toggle empty placeholder
            if not items:
                if self._dl_empty_lbl is None:
                    self._dl_empty_lbl = ctk.CTkLabel(
                        self._dl_scroll, text=T('dl_list_empty'),
                        text_color=TEXT_DIM,
                        font=(ui_font(), 13))
                    self._dl_empty_lbl.pack(pady=40)
            else:
                if self._dl_empty_lbl is not None:
                    try:
                        self._dl_empty_lbl.destroy()
                    except Exception:
                        pass
                    self._dl_empty_lbl = None

                more_to_build = self._build_visible_rows(visible)
                self._sync_dl_footer(len(items) - len(visible))
                if more_to_build:
                    self._arm_dl_drain()
            if not items:
                self._sync_dl_footer(0)

            # Update status bar
            a = self._dlmgr.active_count
            p = self._dlmgr.pending_count
            parts = []
            if a:
                parts.append(f'{state_label("下載中")} {a}/{self._dlmgr.max_concurrent}')
            if p:
                parts.append(f'{state_label("等待中")} {p}')
            subtitle_active = self._dlmgr.subtitle_active_count
            subtitle_pending = self._dlmgr.subtitle_pending_count
            if subtitle_active or subtitle_pending:
                parts.append(T(
                    'subtitle_queue_status',
                    active=subtitle_active, pending=subtitle_pending))
            done = sum(
                1 for i in items
                if i.state in {'已下載', '未偵測到日語語音'})
            if done:
                parts.append(f'{state_label("已下載")} {done}')
            self._status_lbl.configure(text='  |  '.join(parts) if parts else T('status_ready'))
            self._autosave_downloads(items)
            self._update_preview_action_buttons()
        except Exception as e:
            print(f'[download refresh failed] {e}', flush=True)
        finally:
            if schedule and not self._is_closing:
                try:
                    self.after(1000, self._refresh_downloads)
                except tk.TclError:
                    pass

    def _autosave_downloads(self, items: list[DownloadItem]):
        self._download_autosave_ticks += 1
        if self._download_autosave_ticks < 10:
            return
        self._download_autosave_ticks = 0
        sig = tuple((
            i.url, i.name, i.state, i.progress, i.dest,
            i.source_subtitle_evidence,
        ) for i in items)
        if sig == self._last_download_save_sig:
            return
        try:
            self._dlmgr.save_csv(CSV_PATH)
            self._last_download_save_sig = sig
            for i in items:
                if i.state in ('已下載', '未偵測到日語語音'):
                    config.add_download_history({'url': i.url, 'name': i.name, 'state': i.state, 'dest': i.dest})
        except Exception:
            pass

    def _build_dl_row(self, item: DownloadItem) -> dict:
        """Build one download row once; return widget handles for in-place updates."""
        color = self._STATE_COLORS.get(item.state, TEXT_SEC)
        row = None
        try:
            row = ctk.CTkFrame(
                self._dl_scroll, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                border_width=1, border_color=BORDER_CARD, height=76)
            row.pack(fill='x', padx=16, pady=7)
            row.pack_propagate(False)

            state_holder = ctk.CTkFrame(
                row,
                width=210 if item.state == '未偵測到日語語音' else 92,
                height=32, corner_radius=6,
                fg_color=self._STATE_BACKGROUNDS.get(item.state, BG_BADGE))
            state_holder.pack(side='left', padx=(14, 10))
            state_holder.pack_propagate(False)
            state_lbl = ctk.CTkLabel(
                state_holder, text=state_label(item.state) if item.state else '—',
                text_color=color, font=(ui_font(), 10, 'bold'))
            state_lbl.pack(fill='both', expand=True, padx=6)

            actions = ctk.CTkFrame(row, fg_color='transparent')
            actions.pack(side='right', padx=(6, 14))

            remove_btn = ctk.CTkButton(
                actions, text='✕', width=32, height=32,
                corner_radius=CONTROL_RADIUS,
                fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_DIM, font=('Consolas', 12),
                command=lambda u=item.url: self._dlmgr.remove_item(u))
            remove_btn.pack(side='right')

            retry_btn = ctk.CTkButton(
                actions, text='↻', width=32, height=32,
                corner_radius=CONTROL_RADIUS,
                fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER,
                text_color=ACCENT, font=('Consolas', 14, 'bold'),
                command=lambda u=item.url: self._retry_download(u))

            metrics = ctk.CTkFrame(row, fg_color='transparent')
            metrics.pack(side='right', padx=(6, 2))

            # Progress widgets (created once, packed/unpacked dynamically)
            pb = ctk.CTkProgressBar(metrics, width=150, height=8,
                                    corner_radius=5,
                                    fg_color=BG_INPUT,
                                    progress_color=ACCENT)
            pb.set(max(0.0, min(1.0, item.progress / 100)))
            pct_lbl = ctk.CTkLabel(
                metrics, text='', text_color=TEXT_SEC,
                font=('Consolas', 10, 'bold'), width=46)
            spd_lbl = ctk.CTkLabel(
                metrics, text='', text_color=TEXT_SEC,
                font=('Consolas', 9), width=76)

            text_stack = ctk.CTkFrame(row, fg_color='transparent')
            text_stack.pack(side='left', fill='both', expand=True, padx=(0, 10), pady=10)
            name_lbl = ctk.CTkLabel(
                text_stack, text=item.name or item.url, text_color=TEXT_PRI,
                font=(ui_font(), 11, 'bold'), anchor='w')
            name_lbl.pack(fill='x', anchor='w')
            detail_lbl = ctk.CTkLabel(
                text_stack, text=item.url, text_color=TEXT_DIM,
                font=('Consolas', 9), anchor='w')
            detail_lbl.pack(fill='x', anchor='w', pady=(3, 0))

            widgets = {
                'row': row, 'state_holder': state_holder,
                'state_lbl': state_lbl, 'name_lbl': name_lbl,
                'detail_lbl': detail_lbl, 'metrics': metrics,
                'actions': actions, 'remove_btn': remove_btn,
                'pb': pb, 'pct_lbl': pct_lbl, 'spd_lbl': spd_lbl,
                'retry_btn': retry_btn, '_before_remove': remove_btn,
                'pb_visible': False, 'pct_visible': False, 'spd_visible': False,
                'retry_visible': False,
                'last_state': None, 'last_name': None, 'last_detail': None,
                'last_progress': -1, 'last_speed': None,
            }
            self._update_dl_row(widgets, item)
            return widgets
        except Exception:
            if row is not None:
                try:
                    row.destroy()
                except Exception:
                    pass
            raise

    def _update_dl_row(self, w: dict, item: DownloadItem):
        """Update an existing row's fields in place without rebuilding widgets."""
        # State text + color
        if w['last_state'] != item.state:
            color = self._STATE_COLORS.get(item.state, TEXT_SEC)
            try:
                w['state_holder'].configure(
                    fg_color=self._STATE_BACKGROUNDS.get(item.state, BG_BADGE),
                    width=(
                        210 if item.state == '未偵測到日語語音'
                        else 92))
                w['state_lbl'].configure(
                    text=state_label(item.state) if item.state else '—',
                    text_color=color)
            except Exception:
                return
            w['last_state'] = item.state

        # Name and supporting detail (error or source URL) are separate levels.
        display_name = item.name or item.url
        detail = item.url
        detail_color = TEXT_DIM
        if item.error and item.state in ('未完成', '封鎖/解析失敗', '已下載'):
            err_text = T('blocked_vpn_hint') if item.error == ERR_BLOCKED else item.error
            err = err_text.replace('\n', ' ').strip()
            if len(err) > 110:
                err = err[:107] + '...'
            detail = err
            detail_color = WARNING if item.state == '已下載' else ERROR_C
        if w['last_name'] != display_name:
            try:
                w['name_lbl'].configure(text=display_name)
            except Exception:
                return
            w['last_name'] = display_name
        if w['last_detail'] != detail:
            try:
                w['detail_lbl'].configure(text=detail, text_color=detail_color)
            except Exception:
                return
            w['last_detail'] = detail

        retryable = (item.state in ('未完成', '封鎖/解析失敗', '已取消')
                     or (item.state == '已下載' and bool(item.error)))
        if retryable and not w['retry_visible']:
            w['retry_btn'].pack(side='right', padx=(0, 6))
            w['retry_visible'] = True
        elif not retryable and w['retry_visible']:
            try:
                w['retry_btn'].pack_forget()
            except Exception:
                pass
            w['retry_visible'] = False

        # Progress bar: show only while downloading
        is_downloading = (item.state in {
            '下載中', '字幕準備中', '字幕辨識中', '字幕翻譯中'
        } and item.progress > 0)
        if is_downloading:
            if not w['pb_visible']:
                w['pb'].pack(side='left', padx=(0, 4))
                w['pb_visible'] = True
            if w['last_progress'] != item.progress:
                w['pb'].set(max(0.0, min(1.0, item.progress / 100)))
                w['last_progress'] = item.progress
            pct_text = f'{item.progress}%'
            if not w['pct_visible']:
                w['pct_lbl'].pack(side='left')
                w['pct_visible'] = True
            if w['pct_lbl'].cget('text') != pct_text:
                w['pct_lbl'].configure(text=pct_text)
        else:
            if w['pb_visible']:
                try: w['pb'].pack_forget()
                except Exception: pass
                w['pb_visible'] = False
            if w['pct_visible']:
                try: w['pct_lbl'].pack_forget()
                except Exception: pass
                w['pct_visible'] = False

        # Speed
        if is_downloading and item.speed:
            if not w['spd_visible']:
                w['spd_lbl'].pack(side='left', padx=4)
                w['spd_visible'] = True
            if w['last_speed'] != item.speed:
                w['spd_lbl'].configure(text=item.speed)
                w['last_speed'] = item.speed
        else:
            if w['spd_visible']:
                try: w['spd_lbl'].pack_forget()
                except Exception: pass
                w['spd_visible'] = False
                w['last_speed'] = None

    # ── Clipboard monitor (main-thread safe) ─────────────────────────
    def _clipboard_poll(self):
        if self._is_closing:
            return
        if self._rebuilding:
            try:
                self.after(800, self._clipboard_poll)
            except tk.TclError:
                pass
            return
        try:
            clp = self.clipboard_get()
            if clp != self._clp_text:
                self._clp_text = clp
                for m in re.finditer(r'https?://\S+', clp):
                    url = m.group(0).rstrip('.,;)\'"')
                    if len(url) > 2048:      # no real video URL is this long; bounds validation cost
                        continue
                    if M3U8Sites.VaildateUrl(url):
                        existing = {i.url for i in self._dlmgr.get_items()}
                        if url not in existing:
                            self._dlmgr.add_item(url)
                            print(f'[剪貼簿] {url}')
        except (tk.TclError, Exception):
            pass
        finally:
            if not self._is_closing:
                try:
                    self.after(800, self._clipboard_poll)
                except tk.TclError:
                    pass

    # ── Close ────────────────────────────────────────────────────────
    def _on_close(self):
        if self._is_closing:
            return
        if self._close_dlg is not None:
            try:
                self._close_dlg.lift()
                self._close_dlg.focus_force()
            except Exception:
                pass
            return
        if self._dlmgr.inflight_count > 0:
            self._show_close_dialog()
            return
        self._do_close_quit()

    def _show_close_dialog(self):
        if self._close_dlg is not None:
            return
        downloads = self._dlmgr.active_count + self._dlmgr.pending_count
        subtitles = (
            self._dlmgr.subtitle_active_count
            + self._dlmgr.subtitle_pending_count)
        try:
            tray_supported = (
                importlib.util.find_spec('pystray') is not None)
        except Exception:
            tray_supported = False

        dlg = ctk.CTkToplevel(self)
        try:
            dlg.overrideredirect(True)
            # Call the base-class resizable: CTkToplevel.resizable() re-runs
            # _windows_set_titlebar_color on Windows, which withdraws the
            # window again and can leave it stuck hidden.
            tk.Toplevel.resizable(dlg, False, False)
        except Exception:
            pass
        w, h = 540, 260
        try:
            self.update_idletasks()
            pw = self.winfo_width()
            ph = self.winfo_height()
            px = self.winfo_rootx()
            py = self.winfo_rooty()
            x = max(0, px + (pw - w) // 2)
            y = max(0, py + (ph - h) // 2)
            dlg.geometry(f'{w}x{h}+{x}+{y}')
        except Exception:
            dlg.geometry(f'{w}x{h}')
        dlg.transient(self)
        dlg.configure(fg_color=BG_DARK)

        def _stay():
            self._close_dialog_done()

        def _quit_resume():
            self._close_dialog_done()
            self._do_close_quit()

        def _background():
            self._close_dialog_done()
            self._go_background()

        dlg.bind('<Escape>', lambda e: _stay(), add='+')

        # Outer card container with clean boundary
        container = ctk.CTkFrame(
            dlg, fg_color=BG_DARK, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD
        )
        container.pack(fill='both', expand=True)

        # ── In-Popup Header Bar with Logo, Title & Close Button ────────
        header_bar = ctk.CTkFrame(
            container, fg_color=BG_CARD, height=46, corner_radius=0
        )
        header_bar.pack(fill='x')
        header_bar.pack_propagate(False)

        header_left = ctk.CTkFrame(header_bar, fg_color='transparent')
        header_left.pack(side='left', padx=14, pady=8)

        # Load Logo
        logo_img = getattr(self, '_brand_logo_img', None)
        if not logo_img:
            logo_png_p = _resolve_resource_path('logo.png')
            if not os.path.exists(logo_png_p):
                logo_png_p = _resolve_resource_path(os.path.join('img', 'logo.png'))
            if not os.path.exists(logo_png_p):
                logo_png_p = _resolve_resource_path(os.path.join('img', 'favicon-256x256.png'))
            if os.path.exists(logo_png_p):
                try:
                    logo_pil = Image.open(logo_png_p)
                    logo_img = ctk.CTkImage(light_image=logo_pil, dark_image=logo_pil, size=(24, 24))
                except Exception:
                    logo_img = None

        if logo_img:
            logo_lbl = ctk.CTkLabel(header_left, image=logo_img, text='')
            logo_lbl.pack(side='left', padx=(0, 8))
        else:
            logo_lbl = None

        title_lbl = ctk.CTkLabel(
            header_left, text=T('close_dlg_title'),
            text_color=TEXT_PRI, font=(ui_font(), 13, 'bold')
        )
        title_lbl.pack(side='left')

        close_btn = ctk.CTkButton(
            header_bar, text='✕', width=30, height=30,
            corner_radius=15, fg_color='transparent',
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=(ui_font(), 13, 'bold'),
            command=_stay
        )
        close_btn.pack(side='right', padx=10, pady=8)

        # Draggable header bar for frameless popup
        def _start_drag(event):
            dlg._drag_start_x = event.x_root - dlg.winfo_x()
            dlg._drag_start_y = event.y_root - dlg.winfo_y()

        def _do_drag(event):
            x = event.x_root - getattr(dlg, '_drag_start_x', 0)
            y = event.y_root - getattr(dlg, '_drag_start_y', 0)
            dlg.geometry(f"+{x}+{y}")

        drag_widgets = [header_bar, header_left, title_lbl]
        if logo_lbl:
            drag_widgets.append(logo_lbl)
        for w_item in drag_widgets:
            w_item.bind('<Button-1>', _start_drag, add='+')
            w_item.bind('<B1-Motion>', _do_drag, add='+')

        # Dialog body
        body = ctk.CTkFrame(container, fg_color='transparent')
        body.pack(fill='both', expand=True, padx=20, pady=(14, 16))

        ctk.CTkLabel(
            body, text=T(
                'close_dlg_body', downloads=downloads,
                subtitles=subtitles),
            font=(ui_font(), 12), text_color=TEXT_SEC, anchor='w',
            justify='left', wraplength=490
        ).pack(fill='x', pady=(0, 16))

        btns = ctk.CTkFrame(body, fg_color='transparent')
        btns.pack(fill='x')

        action_row = ctk.CTkFrame(btns, fg_color='transparent')
        action_row.pack(fill='x', pady=(0, 8))
        action_row.grid_columnconfigure(0, weight=1)
        action_row.grid_columnconfigure(1, weight=1)

        stay_btn = ctk.CTkButton(
            action_row, text=T('close_dlg_stay'), height=38,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=WHITE,
            corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 12, 'bold'), command=_stay
        )
        stay_btn.grid(row=0, column=0, sticky='ew', padx=(0, 5))

        quit_resume_btn = ctk.CTkButton(
            action_row, text=T('close_dlg_cancel_resume'), height=38,
            fg_color='transparent', border_width=1, border_color=ERROR_C,
            hover_color=ERROR_DIM, text_color=ERROR_C,
            corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 11, 'bold'), command=_quit_resume
        )
        quit_resume_btn.grid(row=0, column=1, sticky='ew', padx=(5, 0))

        bg_btn = ctk.CTkButton(
            btns, text=T('close_dlg_background'), height=36,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 12), command=_background)
        bg_btn.pack(fill='x', pady=(0, 4))
        if not tray_supported:
            bg_btn.configure(state='disabled')
            ctk.CTkLabel(
                body, text=T('close_dlg_background_unavailable'),
                font=(ui_font(), 11), text_color=TEXT_DIM, anchor='w',
                justify='left', wraplength=490
            ).pack(fill='x', pady=(4, 0))

        self._close_dlg = dlg
        try:
            # CTkToplevel hides itself while it applies the Windows titlebar
            # colour, so re-show it explicitly before grabbing input.
            dlg.deiconify()
            dlg.update_idletasks()
            dlg.attributes('-topmost', True)
            dlg.lift()
            dlg.focus_force()
            dlg.grab_set()
        except Exception:
            pass
        try:
            dlg.after(1500, lambda: (
                dlg.winfo_exists() and dlg.attributes('-topmost', False)))
        except Exception:
            pass

    def _close_dialog_done(self):
        dlg = self._close_dlg
        self._close_dlg = None
        if dlg is not None:
            try:
                dlg.grab_release()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

    def _do_close_quit(self):
        if self._is_closing:
            return
        self._is_closing = True
        self._close_dialog_done()
        if self._dl_drain_id:
            try:
                self.after_cancel(self._dl_drain_id)
            except Exception:
                pass
            self._dl_drain_id = None
        try:
            self._thumb_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            if hasattr(self, '_dur_executor') and self._dur_executor:
                self._dur_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self._dlmgr.mark_inflight_for_resume()
        except Exception:
            pass
        try:
            self._dlmgr.save_csv(CSV_PATH)
        except Exception:
            pass
        try:
            self._dlmgr.cancel_all(cleanup=False)
        except Exception:
            pass
        self._stop_tray()
        try:
            self.destroy()
        except Exception:
            pass

    def _go_background(self):
        if self._is_closing:
            return
        self._ensure_tray()
        self._window_hidden = True
        try:
            fs_win = getattr(self, '_fs_win', None)
            if fs_win is not None and getattr(self, '_exit_fullscreen_player', None):
                self._exit_fullscreen_player()
        except Exception:
            pass
        try:
            self.withdraw()
        except Exception:
            pass
        self._arm_background_poll()

    def _restore_from_tray(self):
        if self._is_closing:
            return
        self._window_hidden = False
        self._cancel_background_poll()
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _arm_background_poll(self):
        self._cancel_background_poll()
        try:
            self._background_poll_id = self.after(
                2000, self._poll_background)
        except tk.TclError:
            self._background_poll_id = None

    def _cancel_background_poll(self):
        pid = self._background_poll_id
        if pid:
            try:
                self.after_cancel(pid)
            except Exception:
                pass
            self._background_poll_id = None

    def _poll_background(self):
        self._background_poll_id = None
        if self._is_closing:
            return
        try:
            if self._dlmgr.inflight_count == 0:
                self._notify_background_done()
                if not self._tray_available:
                    self._restore_from_tray()
                return
        except Exception:
            pass
        self._arm_background_poll()

    def _notify_background_done(self):
        try:
            if self._tray_icon is not None:
                self._tray_icon.notify(
                    T('tray_done_body'), T('tray_done_title'))
        except Exception:
            pass

    def _ensure_tray(self):
        if self._tray_icon is not None:
            return
        try:
            import pystray
        except Exception:
            self._tray_available = False
            return
        icon_path = os.path.join(
            os.path.dirname(__file__), 'img', 'favicon-256x256.png')
        if not os.path.exists(icon_path):
            icon_path = os.path.join(
                os.path.dirname(__file__), 'img', 'favicon.ico')
        if not os.path.exists(icon_path):
            self._tray_available = False
            return
        try:
            image = Image.open(icon_path)
            if self._tray_cmds is None:
                self._tray_cmds = queue.Queue()
            menu = pystray.Menu(
                pystray.MenuItem(
                    T('tray_restore'),
                    lambda icon, item: self._tray_cmds.put('restore'),
                    default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    T('tray_exit_resume'),
                    lambda icon, item: self._tray_cmds.put('quit')),
            )
            icon = pystray.Icon('FetchJAV', image, T('tray_tooltip'), menu)
            icon.run_detached()
            self._tray_icon = icon
            self._tray_available = True
            self._arm_tray_cmd_drain()
        except Exception:
            self._tray_available = False
            self._tray_icon = None

    def _arm_tray_cmd_drain(self):
        self._cancel_tray_cmd_drain()
        try:
            self._tray_cmd_drain_id = self.after(
                400, self._drain_tray_cmds)
        except tk.TclError:
            self._tray_cmd_drain_id = None

    def _cancel_tray_cmd_drain(self):
        pid = self._tray_cmd_drain_id
        if pid:
            try:
                self.after_cancel(pid)
            except Exception:
                pass
            self._tray_cmd_drain_id = None

    def _drain_tray_cmds(self):
        self._tray_cmd_drain_id = None
        if self._is_closing:
            return
        q = self._tray_cmds
        if q is not None:
            try:
                while True:
                    cmd = q.get_nowait()
                    if cmd == 'restore':
                        self._restore_from_tray()
                    elif cmd == 'quit':
                        self._do_close_quit()
                        return
            except queue.Empty:
                pass
        if self._tray_icon is not None and not self._is_closing:
            self._arm_tray_cmd_drain()

    def _stop_tray(self):
        self._cancel_tray_cmd_drain()
        self._cancel_background_poll()
        icon = self._tray_icon
        self._tray_icon = None
        self._tray_available = False
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass


def gui_modern_main(url: str = '', dest: str = 'download', lang: str = 'en'):
    _crumb("gui_modern_main: constructing ModernApp")
    app = ModernApp(url=url, dest=dest, lang=lang)
    _crumb("gui_modern_main: app constructed, entering mainloop")
    app.mainloop()
    _crumb("gui_modern_main: mainloop returned (normal exit)")
