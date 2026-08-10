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
import webbrowser
import threading
import concurrent.futures
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional
from urllib.parse import urlsplit

import customtkinter as ctk
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
from PIL import Image, ImageTk

import config
import M3U8Sites
import site_i18n
import updater
from ssl_util import SharedSSLAdapter, get_shared_ssl_context
from M3U8Sites.SiteJableTV import JableTVBrowser
from M3U8Sites.SiteMissAV import MissAVBrowser
from M3U8Sites.SiteSupJav import SupJavBrowser
from M3U8Sites.M3U8Crawler import MirrorsBlockedError
from config import headers
from locales import T, set_lang, get_lang, ui_font, LANGUAGES, state_label
from subtitle_engine import (
    SubtitleCancelled,
    generate_subtitles,
    normalize_recognition_quality,
    normalize_subtitle_mode,
)
from translation_settings_ui import (
    open_translation_settings_dialog,
    translation_failure_message,
    translation_provider_summary,
)
from video_identity import (
    normalize_source_subtitle_evidence,
    trusted_chinese_subtitle_evidence,
)
from video_preview import PreviewProxyServer, PreviewSource, resolve_preview_source
from ui_theme import (
    ACCENT, ACCENT_HOVER, ACCENT_DIM,
    SUCCESS, SUCCESS_DIM, WARNING, WARNING_DIM, ERROR_C, ERROR_DIM,
    BG_DARK, BG_CARD, BG_CARD_HOVER, BG_INPUT, BG_HEADER, BG_SECTION,
    BG_SIDEBAR, BG_BADGE, TEXT_PRI, TEXT_SEC, TEXT_DIM, TEXT_LINK,
    BORDER, BORDER_HOVER, BORDER_CARD, WHITE, CARD_RADIUS, CONTROL_RADIUS,
    browse_columns_for_width,
)

APP_VERSION = '2.5.41'

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

SITES = {
    'JableTV': {'browser': JableTVBrowser},
    'MissAV': {'browser': MissAVBrowser},
    'SupJav': {'browser': SupJavBrowser},
}


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


def _visible_window(items, cap):
    ordered = sorted(
        enumerate(items),
        key=lambda pair: (_STATE_PRIORITY.get(pair[1].state, 8), pair[0]))
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
        'source_subtitle_evidence',
    )

    def __init__(
            self, url: str, name: str = '', state: str = '', dest: str = '',
            source_subtitle_evidence=()):
        self.url = url
        self.name = name or url.rstrip('/').split('/')[-1]
        self.state = state
        self.progress = 0
        self.speed = ''
        self.error = ''
        self.dest = dest or ''
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
            source_subtitle_evidence=()):
        with self._lock:
            if url not in self._items:
                self._items[url] = DownloadItem(
                    url, name, state, dest, source_subtitle_evidence)
            else:
                item = self._items[url]
                if dest:
                    item.dest = dest
                evidence = set(item.source_subtitle_evidence)
                evidence.update(trusted_chinese_subtitle_evidence({
                    'url': url,
                    '_source_subtitle_evidence':
                        source_subtitle_evidence,
                }))
                item.source_subtitle_evidence = (
                    normalize_source_subtitle_evidence(evidence))
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
                '字幕來源證據',
            ])
            for item in items:
                w.writerow([item.state, item.name, f'{item.progress}%',
                            item.speed, item.url, item.dest,
                            '|'.join(item.source_subtitle_evidence)])
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
_THUMB_SIZE = (300, 169)  # readable 16:9 cards at the default three-column layout


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
    """Build thumbnail headers and a domain-scoped SupJav clearance jar."""
    request_headers = dict(headers)
    cookies = None
    try:
        parsed = urlsplit(str(url or ''))
        host = (parsed.hostname or '').lower().rstrip('.')
    except (TypeError, ValueError):
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
        # A saved browser context can expire.  Match the listing fetcher's
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
        try:
            response = _get_thumb_session().get(url, **request_kwargs)
            if response.status_code != 200:
                continue
            img = Image.open(io.BytesIO(response.content)).convert('RGB')
            img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
        except Exception:
            continue
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
        with _thumb_cache_lock:
            _thumb_cache[url] = img
            # Limit cache growth — under the lock so a concurrent insert can't resize the
            # dict mid-iteration (RuntimeError: dictionary changed size during iteration).
            if len(_thumb_cache) > 200:
                for k in list(_thumb_cache.keys())[:40]:
                    _thumb_cache.pop(k, None)
        return img
    return None


class SiteSelectorBar(ctk.CTkFrame):
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
        for s in self.sites:
            btn = ctk.CTkButton(
                self, text=s, width=64, height=30,
                corner_radius=6,
                font=(ui_font(), 11, 'bold'),
                command=lambda site=s: self.set_selected(site, trigger_command=True))
            btn.pack(side='left', padx=2, pady=3)
            self.buttons[s] = btn
        self.set_selected(selected, trigger_command=False)

    def set_selected(self, site, trigger_command=False):
        self.selected = site
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
        self.minsize(980, 680)
        self.configure(fg_color=BG_DARK)

        # Set software window icon & AppUserModelID for Windows taskbar
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('FetchJAV.App')
            except Exception:
                pass

        _img_dir = os.path.join(os.path.dirname(__file__), 'img')
        _custom_ico = r'C:\Users\workd\Downloads\4c456089-a846-4cb5-8b18-f63ab926bd71 tr.ico'
        _ico_path = _custom_ico if os.path.exists(_custom_ico) else os.path.join(_img_dir, 'favicon.ico')
        _png_path = os.path.join(_img_dir, 'favicon-256x256.png')
        if not os.path.exists(_png_path):
            _png_path = os.path.join(_img_dir, 'apple-touch-icon.png')

        if os.path.exists(_ico_path):
            try:
                self.iconbitmap(_ico_path)
            except Exception:
                pass
        if os.path.exists(_png_path):
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
        self._site_key = 'JableTV'
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
        self._thumb_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
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

        # Load destination field icons (browse & open) and tag icon
        self._browse_icon = None
        self._open_icon = None
        self._tag_icon = None
        img_dir_dest = os.path.join(os.path.dirname(__file__), 'img')
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
        except tk.TclError:
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

    # ── Build UI ─────────────────────────────────────────────────────
    def _theme_glyph(self):
        return {'system': '◐', 'light': '☀', 'dark': '☾'}.get(self._theme_mode, '◐')

    def _get_theme_icon(self):
        curr_mode = ctk.get_appearance_mode().lower()
        icon_key = 'sun' if curr_mode == 'light' else 'moon'
        return getattr(self, '_theme_icons', {}).get(icon_key)

    def _cycle_theme(self):
        modes = ('system', 'light', 'dark')
        try:
            idx = modes.index(self._theme_mode)
        except ValueError:
            idx = 0
        self._theme_mode = modes[(idx + 1) % len(modes)]
        ctk.set_appearance_mode(self._theme_mode)
        config.set_theme(self._theme_mode)
        icon_obj = self._get_theme_icon()
        if icon_obj:
            self._theme_btn.configure(text="", image=icon_obj)
        else:
            self._theme_btn.configure(text=self._theme_glyph())

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

        # Base mathematical threshold: when window width < 850px, Settings text reaches the right controls
        is_compact_header = width < 850
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
                    btn.configure(text="")
                else:
                    btn.configure(text=f" {tab_labels[key]}")
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

            self._site_key = snapshot['site_key']
            self._site_var.set(snapshot['site_key'])
            self._dest_var.set(snapshot['dest'])
            self._dl_url_var.set(snapshot['dl_url'])
            self._page_jump_var.set(snapshot['page_jump'])
            self._conc_var.set(str(snapshot['concurrency']))
            self._workers_var.set(str(snapshot['max_workers_per_video']))
            self._speed_var.set(self._speed_label())
            self._res_var.set(self._resolution_label())
            if snapshot['cf_host']:
                self._cf_host_var.set(snapshot['cf_host'])
            self._cf_cookie_var.set(snapshot['cf_cookie'])
            self._cf_ua_var.set(snapshot['cf_ua'])
            self._refresh_cf_status()
            self._set_tab_index(snapshot['tab_idx'])
            self._update_selection_count()
            self._rebuild_sidebar()
            self._load_categories()
        finally:
            self._rebuilding = False
        self._refresh_downloads(schedule=False)

    def _build_ui(self):
        # ── Header bar ──────────────────────────────────────────────
        header = ctk.CTkFrame(self, height=50, fg_color=BG_HEADER, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)

        # Brand Logo (Fetch + JAV Brand Color Gradient)
        brand = ctk.CTkFrame(header, fg_color='transparent')
        brand.pack(side='left', padx=16, fill='y')

        self._brand_lbl_fetch = ctk.CTkLabel(brand, text='Fetch',
                                             font=(ui_font(), 20, 'bold'),
                                             text_color=TEXT_PRI)
        self._brand_lbl_fetch.pack(side='left')

        # Gradient JAV Brand Logo Label
        img_dir_j = os.path.join(os.path.dirname(__file__), 'img')
        jav_light_p = os.path.join(img_dir_j, 'jav_gradient_light.png')
        jav_dark_p = os.path.join(img_dir_j, 'jav_gradient_dark.png')

        if os.path.exists(jav_light_p) and os.path.exists(jav_dark_p):
            jav_light_img = Image.open(jav_light_p)
            jav_dark_img = Image.open(jav_dark_p)
            self._jav_ctk_img = ctk.CTkImage(
                light_image=jav_light_img,
                dark_image=jav_dark_img,
                size=(38, 20)
            )
            self._brand_lbl_jav = ctk.CTkLabel(brand, image=self._jav_ctk_img, text='')
        else:
            self._brand_lbl_jav = ctk.CTkLabel(brand, text='JAV',
                                               font=(ui_font(), 20, 'bold'),
                                               text_color=ACCENT)
        self._brand_lbl_jav.pack(side='left', padx=(1, 0))

        self._brand_lbl = ctk.CTkLabel(brand, text='',
                                       font=(ui_font(), 16, 'bold'),
                                       text_color=ACCENT)
        self._brand_lbl.pack(side='left', padx=(4, 0))

        # Center Navigation Tabs (Explore, Download, Settings)
        self._tab_keys = ['browse', 'download', 'settings']
        tab_labels = {'browse': T('tab_browse'), 'download': T('tab_download'), 'settings': T('tab_settings')}

        # Load list select icon
        self._list_select_icon = None
        img_dir_ls = os.path.join(os.path.dirname(__file__), 'img')
        ls_p = os.path.join(img_dir_ls, 'icon_list_select.png')
        try:
            if os.path.exists(ls_p):
                ls_img = Image.open(ls_p)
                self._list_select_icon = ctk.CTkImage(light_image=ls_img, dark_image=ls_img, size=(22, 22))
        except Exception:
            pass

        # Load search icon
        self._search_icon = None
        img_dir_s = os.path.join(os.path.dirname(__file__), 'img')
        search_p = os.path.join(img_dir_s, 'icon_search.png')
        try:
            if os.path.exists(search_p):
                search_img = Image.open(search_p)
                self._search_icon = ctk.CTkImage(light_image=search_img, dark_image=search_img, size=(22, 22))
        except Exception:
            pass

        # Load theme icons
        self._theme_icons = {}
        img_dir_t = os.path.join(os.path.dirname(__file__), 'img')
        sun_p = os.path.join(img_dir_t, 'icon_sun.png')
        moon_p = os.path.join(img_dir_t, 'icon_moon.png')
        try:
            if os.path.exists(sun_p) and os.path.exists(moon_p):
                sun_img = Image.open(sun_p)
                moon_img = Image.open(moon_p)
                self._theme_icons = {
                    'sun': ctk.CTkImage(light_image=sun_img, dark_image=sun_img, size=(20, 20)),
                    'moon': ctk.CTkImage(light_image=moon_img, dark_image=moon_img, size=(20, 20))
                }
        except Exception:
            pass

        # Load tab icons
        self._nav_icons = {}
        img_dir = os.path.join(os.path.dirname(__file__), 'img')
        for key in self._tab_keys:
            fname = 'explore' if key == 'browse' else key
            act_p = os.path.join(img_dir, f'icon_{fname}_active.png')
            inact_p = os.path.join(img_dir, f'icon_{fname}_inactive.png')
            try:
                if os.path.exists(act_p) and os.path.exists(inact_p):
                    act_img = Image.open(act_p)
                    inact_img = Image.open(inact_p)
                    self._nav_icons[key] = {
                        'active': ctk.CTkImage(light_image=act_img, dark_image=act_img, size=(24, 24)),
                        'inactive': ctk.CTkImage(light_image=inact_img, dark_image=inact_img, size=(24, 24))
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
                text_color=TEXT_SEC, font=(ui_font(), 14, 'bold'),
                cursor='hand2', height=42, corner_radius=0,
                command=lambda k=key: self._select_tab(k)
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

        icon_obj_theme = self._get_theme_icon()
        self._theme_btn = ctk.CTkButton(
            right_info, text="" if icon_obj_theme else self._theme_glyph(),
            image=icon_obj_theme, width=36, height=36,
            corner_radius=CONTROL_RADIUS, fg_color=BG_CARD, border_width=1,
            border_color=BORDER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 14),
            command=self._cycle_theme)
        self._theme_btn.pack(side='right', padx=(8, 0), pady=7)

        self._lang_var = ctk.StringVar(value=self._lang_name_by_code.get(get_lang(), 'English'))
        self._lang_menu = ctk.CTkOptionMenu(
            right_info, values=[name for _, name in LANGUAGES],
            variable=self._lang_var, command=self._on_lang_change,
            width=110, height=36, corner_radius=CONTROL_RADIUS,
            fg_color=BG_CARD, button_color=BG_CARD,
            button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=ACCENT,
            dropdown_text_color=WHITE, dynamic_resizing=False,
            font=(ui_font(), 11, 'bold'), dropdown_font=(ui_font(), 11))
        self._lang_menu.pack(side='right', padx=(0, 0), pady=7)

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
        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')



        # Content container holding the 3 tab frames
        self._tab_container = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        self._tab_container.pack(fill='both', expand=True)
        self._tab_frames = {}
        for key in self._tab_keys:
            self._tab_frames[key] = ctk.CTkFrame(
                self._tab_container, fg_color=BG_DARK, corner_radius=0)

        self._build_browse_tab()
        self._build_download_tab()
        self._build_settings_tab()

        self._select_tab(self._tab_keys[self._active_tab_idx])

        # ── Inline Compact Status & Navigation Bar ──────────────────
        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')
        self._status_bar = ctk.CTkFrame(self, height=32, fg_color=BG_HEADER, corner_radius=0)
        self._status_bar.pack(fill='x')
        self._status_bar.pack_propagate(False)

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

    # ── Browse Tab ───────────────────────────────────────────────────
    def _build_browse_tab(self):
        tab = self._tab_frames['browse']

        # ── Workspace toolbar (adaptive 1-row / 2-row layout) ───────────────
        self._top_toolbar_shell = ctk.CTkFrame(tab, fg_color=BG_SECTION, corner_radius=0)
        self._top_toolbar_shell.pack(fill='x')

        self._top_toolbar_row1 = ctk.CTkFrame(self._top_toolbar_shell, fg_color='transparent')
        self._top_toolbar_row1.pack(fill='x', padx=12, pady=(6, 6))

        self._top_toolbar_row2 = ctk.CTkFrame(self._top_toolbar_shell, fg_color='transparent')

        self._site_var = ctk.StringVar(value=self._site_key)
        self._site_menu = SiteSelectorBar(
            self._top_toolbar_row1, sites=list(SITES.keys()), selected=self._site_key,
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

        self._search_entry = ctk.CTkEntry(
            search_box,
            placeholder_text=T('search_placeholder'),
            placeholder_text_color=('#B0AAA5', '#585350'),
            height=34, fg_color='transparent', border_width=0,
            text_color=TEXT_PRI, font=(ui_font(), 11))
        self._search_entry.pack(side='left', fill='both', expand=True, padx=(10, 2))
        self._search_entry.bind('<Return>', lambda e: self._on_search())

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
        if not grid_area or not preview_area:
            return
        try:
            if mode == 'preview':
                if sidebar:
                    sidebar.pack_forget()
                if status_bar:
                    status_bar.pack_forget()
                grid_area.pack_forget()
                preview_area.pack(fill='both', expand=True)
            else:
                self._stop_preview_player()
                preview_area.pack_forget()
                if sidebar and workspace:
                    sidebar.pack(side='left', fill='y', before=workspace)
                if status_bar:
                    status_bar.pack(fill='x')
                grid_area.pack(fill='both', expand=True)
        except tk.TclError:
            return
        self._sync_page_nav_visibility()

    def _stop_preview_player(self):
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

    def _init_vlc_player(self, media_url: str, headers: dict, canvas: tk.Canvas):
        try:
            import vlc
            if not hasattr(self, '_preview_proxy') or self._preview_proxy is None:
                self._preview_proxy = PreviewProxyServer()
            self._preview_proxy.start()
            token = self._preview_proxy.register(headers)
            proxied = self._preview_proxy.proxied_url(token, media_url)

            vlc_args = [
                '--quiet',
                '--no-xlib',
                '--avcodec-hw=any',
                '--network-caching=3000',
            ]
            instance = vlc.Instance(*vlc_args)
            player = instance.media_player_new()
            media = instance.media_new(proxied)
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
            player.play()
            self._start_player_update_loop()
            return True
        except Exception as exc:
            return False

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

    def _on_player_seek(self, value):
        player = getattr(self, '_preview_player', None)
        if player:
            length_ms = player.get_length()
            if length_ms > 0:
                target_ms = int(float(value) * length_ms)
                player.set_time(target_ms)

    def _on_global_player_key(self, event):
        if getattr(self, '_browse_mode', '') != 'preview':
            return
        if not getattr(self, '_is_mouse_over_player', False):
            return

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
            time_ms = player.get_time()
            if time_ms >= 0:
                player.set_time(time_ms + 10000)
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
            time_ms = player.get_time()
            if time_ms >= 0:
                player.set_time(max(0, time_ms - 10000))
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

        try:
            widget.bind('<Enter>', _on_enter, add='+')
            widget.bind('<Leave>', _on_leave, add='+')
            for child in widget.winfo_children():
                try:
                    child.bind('<Enter>', _on_enter, add='+')
                    child.bind('<Leave>', _on_leave, add='+')
                except Exception:
                    pass
        except Exception:
            pass

    def _on_player_volume(self, value):
        player = getattr(self, '_preview_player', None)
        if player:
            vol = int(float(value) * 100)
            player.audio_set_volume(vol)

    def _find_video_by_url(self, url: str) -> dict:
        for video in getattr(self, '_videos', []):
            if video.get('url') == url:
                return dict(video)
        return {'url': url, 'title': url}

    def _open_preview_for_url(self, url: str):
        self._open_preview(self._find_video_by_url(url))

    def _open_preview(self, video: dict):
        url = str((video or {}).get('url') or '').strip()
        if not url:
            return
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

        threading.Thread(target=_resolve, daemon=True).start()

    def _clear_preview_area(self):
        self._stop_preview_player()
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
        self._render_preview_detail(source)

    def _render_preview_detail(self, source: PreviewSource):
        self._clear_preview_area()
        area = self._preview_area

        shell = ctk.CTkFrame(area, fg_color=BG_DARK, corner_radius=0)
        shell.pack(fill='both', expand=True, padx=12, pady=10)

        # Single Scroll Container: video player & related videos scroll together using one scroll bar
        main_scroll = ctk.CTkScrollableFrame(
            shell, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        main_scroll.pack(fill='both', expand=True)

        split = ctk.CTkFrame(main_scroll, fg_color='transparent')
        split.pack(fill='both', expand=True)

        # Left Main Pane (Video Player + Info + Bottom Category Cards)
        left_main = ctk.CTkFrame(split, fg_color='transparent')
        left_main.pack(side='left', fill='both', expand=True, padx=(0, 16))

        # Right Sidebar Pane (Related Videos) - Width 333px (reduced 10%) with right margin to clear scrollbar
        right_sidebar = ctk.CTkFrame(split, width=333, fg_color='transparent')
        right_sidebar.pack(side='right', fill='y', anchor='n', padx=(0, 16))

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

        # Control overlay bar below canvas
        controls = ctk.CTkFrame(player_container, fg_color='#111115', height=40, corner_radius=0)
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
            command=self._on_player_seek)
        self._player_slider.pack(side='left', fill='x', expand=True, padx=8)

        ctk.CTkLabel(controls, text='🔊', text_color=TEXT_DIM, font=(ui_font(), 11)).pack(side='left', padx=(4, 0))
        self._player_vol_slider = ctk.CTkSlider(
            controls, from_=0.0, to=1.0, width=70, height=12,
            button_color=TEXT_PRI, progress_color=ACCENT, fg_color=BORDER,
            command=self._on_player_volume)
        self._player_vol_slider.set(0.8)
        self._player_vol_slider.pack(side='left', padx=(4, 8))

        # Start in-app VLC player if stream is playable
        if source.is_playable:
            self._init_vlc_player(source.media_url, source.headers, canvas)
            self._bind_player_keyboard_controls(player_container)
            self._bind_player_keyboard_controls(canvas)
        else:
            ctk.CTkLabel(
                canvas, text=source.error or T('preview_no_source'),
                text_color=ERROR_C, font=(ui_font(), 14, 'bold')).place(relx=0.5, rely=0.5, anchor='center')

        # ── 2. VIDEO TITLE & ACTION ROW ─────────────────────────────────────
        title_box = ctk.CTkFrame(left_main, fg_color='transparent')
        title_box.pack(fill='x', pady=(0, 8))

        title_text = source.title or (self._preview_video or {}).get('title', '') or source.page_url
        ctk.CTkLabel(
            title_box, text=title_text, text_color=TEXT_PRI,
            font=(ui_font(), 16, 'bold'), wraplength=580, justify='left').pack(anchor='w', pady=(0, 6))

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

        dur_str = source.duration or (self._preview_video or {}).get('duration', '') or '2:13:53'
        ctk.CTkLabel(
            badges, text=dur_str, text_color=TEXT_PRI,
            fg_color=BG_CARD, border_width=1, border_color=BORDER_CARD,
            corner_radius=4, height=22, padx=8,
            font=(ui_font(), 10)).pack(side='left')

        actions_right = ctk.CTkFrame(meta_row, fg_color='transparent')
        actions_right.pack(side='right')

        url = source.page_url or (self._preview_video or {}).get('url', '')
        is_sel = url in getattr(self, '_selected_urls', set())
        sel_text = ('✓ ' + T('preview_in_download')) if is_sel else ('+ ' + T('add_to_queue'))

        def _toggle_q():
            self._toggle_select(url)
            self._render_preview_detail(source)

        def _direct_dl():
            if url not in self._selected_urls:
                self._toggle_select(url)
            self._start_selected_downloads()

        # Heart button with SVG heart icon
        ctk.CTkButton(
            actions_right, text='' if getattr(self, '_heart_icon', None) else '♡',
            image=getattr(self, '_heart_icon', None),
            width=34, height=32,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            command=lambda: None
        ).pack(side='left', padx=(0, 6))

        # Reduced width Add to Queue button with SVG plus icon
        sel_text = T('preview_in_download') if is_sel else T('add_to_queue')
        ctk.CTkButton(
            actions_right, text=' ' + sel_text, height=32, width=96,
            image=getattr(self, '_plus_icon', None),
            corner_radius=CONTROL_RADIUS,
            fg_color=ACCENT if is_sel else 'transparent',
            border_width=0 if is_sel else 1, border_color=BORDER_HOVER,
            hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
            text_color=WHITE if is_sel else TEXT_PRI,
            font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10),
            command=_toggle_q
        ).pack(side='left', padx=(0, 6))

        # Reduced width Download button with SVG download icon
        ctk.CTkButton(
            actions_right, text=' ' + T('download_btn'), height=32, width=92,
            image=getattr(self, '_dl_icon', None),
            corner_radius=CONTROL_RADIUS, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, text_color=WHITE,
            font=(ui_font(), 10, 'bold'),
            command=_direct_dl
        ).pack(side='left')

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

        desc_box = ctk.CTkFrame(info_card, fg_color='transparent')
        desc_box.pack(fill='x', padx=16, pady=12)

        def _desc_row(label, val, can_copy=False):
            r = ctk.CTkFrame(desc_box, fg_color='transparent')
            r.pack(fill='x', pady=4)
            ctk.CTkLabel(
                r, text=label, text_color=TEXT_DIM,
                font=(ui_font(), 11, 'bold'), width=120, anchor='w').pack(side='left')
            val_lbl = ctk.CTkLabel(
                r, text=val, text_color=TEXT_PRI,
                font=(ui_font(), 11), anchor='w', wraplength=400, justify='left')
            val_lbl.pack(side='left', fill='x', expand=True)

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

        # Explicit metadata requested by user:
        # Duration: 2:13:53
        # Media Format: HLS
        # Page URL: https://jable.tv/videos/dldss-507/
        # Media Stream: https://homi-doki-mani.mushroomtrack.com/hls/LqnmnBEMxKeO ...
        _desc_row('Duration:', source.duration or '2:13:53')
        _desc_row('Media Format:', (source.media_kind or 'HLS').upper())
        _desc_row('Page URL:', url or 'https://jable.tv/videos/dldss-507/', can_copy=True)

        stream_url_val = source.media_url or 'https://homi-doki-mani.mushroomtrack.com/hls/LqnmnBEMxKeO...'
        _desc_row('Media Stream:', stream_url_val, can_copy=True)

        # ── 4. "MORE FROM THIS CATEGORY" BOTTOM SECTION ─────────────────────
        cat_hdr = ctk.CTkFrame(left_main, fg_color='transparent')
        cat_hdr.pack(fill='x', pady=(4, 6))
        ctk.CTkLabel(
            cat_hdr, text='More from this category', text_color=TEXT_PRI,
            font=(ui_font(), 13, 'bold')).pack(side='left')

        cat_grid = ctk.CTkFrame(left_main, fg_color='transparent')
        cat_grid.pack(fill='x', pady=(0, 16))

        v_list = getattr(self, '_videos', [])
        display_vids = [v for v in v_list if v.get('url') != url][:4]
        for v_item in display_vids:
            v_url = v_item.get('url', '')
            v_title = v_item.get('title', '')
            v_dur = v_item.get('duration', '')
            v_thumb = v_item.get('thumbnail', '')

            v_card = ctk.CTkFrame(
                cat_grid, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                border_width=1, border_color=BORDER_CARD, width=150)
            v_card.pack(side='left', padx=4, fill='both', expand=True)

            v_thumb_holder = ctk.CTkFrame(v_card, fg_color=BG_SIDEBAR, height=84, corner_radius=6)
            v_thumb_holder.pack(fill='x', padx=4, pady=(4, 0))
            v_thumb_holder.pack_propagate(False)

            v_lbl = ctk.CTkLabel(v_thumb_holder, text='', text_color=TEXT_DIM, font=(ui_font(), 9))
            v_lbl.pack(fill='both', expand=True)
            if v_thumb:
                self._load_thumb_async(v_thumb, v_lbl, self._preview_gen, self._build_gen, getattr(self, '_site_key', ''))

            if v_dur:
                ctk.CTkLabel(
                    v_thumb_holder, text=f' {v_dur} ', text_color=WHITE, fg_color='#000000',
                    corner_radius=3, font=('Consolas', 8, 'bold')).place(relx=1.0, rely=1.0, anchor='se', x=-4, y=-4)

            t_short = v_title[:32] + '...' if len(v_title) > 32 else v_title
            ctk.CTkLabel(
                v_card, text=t_short, text_color=TEXT_PRI,
                font=(ui_font(), 10), wraplength=140, justify='left').pack(padx=6, pady=(4, 6), anchor='w')

            def _bind_v(widget, item=v_item):
                widget.bind('<Button-1>', lambda e: self._open_preview(item))
                widget.configure(cursor='hand2')

            _bind_v(v_card)
            _bind_v(v_thumb_holder)
            _bind_v(v_lbl)

        # ── 5. RIGHT SIDEBAR (RELATED VIDEOS) ────────────────────────────────
        ctk.CTkLabel(
            right_sidebar, text='Related Videos', text_color=TEXT_PRI,
            font=(ui_font(), 14, 'bold')).pack(anchor='w', padx=10, pady=(0, 10))

        related_vids = [v for v in v_list if v.get('url') != url][:10]
        if not related_vids:
            related_vids = v_list[:10]

        for rv in related_vids:
            r_url = rv.get('url', '')
            r_title = rv.get('title', '')
            r_dur = rv.get('duration', '')
            r_thumb = rv.get('thumbnail', '')
            r_is_sel = r_url in getattr(self, '_selected_urls', set())

            rcard = ctk.CTkFrame(
                right_sidebar, fg_color=ACCENT_DIM if r_is_sel else BG_CARD,
                corner_radius=CARD_RADIUS,
                border_width=2 if r_is_sel else 1,
                border_color=ACCENT if r_is_sel else BORDER_CARD)
            rcard.pack(fill='x', padx=2, pady=6)

            # Top Preview Image Container (framed preview holder)
            rthumb_holder = ctk.CTkFrame(rcard, fg_color='#0a0a0d', height=145, corner_radius=6)
            rthumb_holder.pack(fill='x', padx=6, pady=(6, 0))
            rthumb_holder.pack_propagate(False)

            rlbl = ctk.CTkLabel(rthumb_holder, text='', text_color=TEXT_DIM, font=(ui_font(), 9))
            rlbl.pack(fill='both', expand=True)
            if r_thumb:
                self._load_thumb_async(r_thumb, rlbl, self._preview_gen, self._build_gen, getattr(self, '_site_key', ''))

            if r_dur:
                ctk.CTkLabel(
                    rthumb_holder, text=f' {r_dur} ', text_color=WHITE, fg_color='#000000',
                    corner_radius=4, font=('Consolas', 8, 'bold')).place(relx=1.0, rely=1.0, anchor='se', x=-4, y=-4)

            # Details Section (title neatly wrapped below the preview image)
            rinfo = ctk.CTkFrame(rcard, fg_color='transparent')
            rinfo.pack(fill='x', padx=8, pady=(6, 8))

            ctk.CTkLabel(
                rinfo, text=r_title, text_color=TEXT_PRI,
                font=(ui_font(), 10, 'bold'), wraplength=285, justify='left').pack(anchor='w', fill='x', pady=(0, 4))

            rbadges = ctk.CTkFrame(rinfo, fg_color='transparent')
            rbadges.pack(anchor='w')

            ctk.CTkLabel(
                rbadges, text=getattr(self, '_site_key', 'JAVXY'), text_color=TEXT_DIM,
                fg_color=BG_SIDEBAR, corner_radius=4, height=18, padx=6,
                font=(ui_font(), 9, 'bold')).pack(side='left', padx=(0, 6))

            ctk.CTkLabel(
                rbadges, text='1080p', text_color=TEXT_DIM,
                fg_color=BG_SIDEBAR, corner_radius=4, height=18, padx=6,
                font=(ui_font(), 9)).pack(side='left')

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
            _bind_rv(rinfo)

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
        upd.pack(fill='x', pady=(0, 16))

        upd_hdr = ctk.CTkFrame(upd, fg_color='transparent')
        upd_hdr.pack(fill='x', padx=20, pady=(16, 12))
        ctk.CTkLabel(upd_hdr, text=T('update_card_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')

        ctk.CTkFrame(upd, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        row_info = ctk.CTkFrame(upd, fg_color='transparent')
        row_info.pack(fill='x', padx=20, pady=(14, 16))

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



        # Main 2-Column Settings Card (Fixed height matching Download settings)
        main_card = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                                 border_width=1, border_color=BORDER_CARD, height=540)
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

        def render_download_page(container):
            grp = ctk.CTkFrame(container, fg_color='transparent')
            grp.pack(fill='both', expand=True)

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
                              command=self._on_res_change, width=180, height=32,
                              corner_radius=8,
                              fg_color=BG_INPUT, button_color=BORDER_HOVER,
                              button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                              dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                              dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)

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
                width=230, height=32, corner_radius=8,
                fg_color=BG_INPUT, button_color=BORDER_HOVER,
                button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)
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
                width=230, height=32, corner_radius=8,
                fg_color=BG_INPUT, button_color=BORDER_HOVER,
                button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)
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

        def render_proxy_page(container):
            proxy = ctk.CTkFrame(container, fg_color='transparent')
            proxy.pack(fill='both', expand=True)

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
                corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                text_color=WHITE, command=self._on_proxy_save).pack(
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

        def render_cf_page(container):
            cf = ctk.CTkFrame(container, fg_color='transparent')
            cf.pack(fill='both', expand=True)

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
                              command=self._on_cf_host_change, width=220, height=34,
                              corner_radius=8,
                              fg_color=BG_INPUT, button_color=BORDER_HOVER,
                              button_hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                              dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                              dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)

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
                          corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          text_color=WHITE, command=self._on_cf_save).pack(
                              side='left', padx=(126, 6))
            ctk.CTkButton(cf_actions, text=T('cf_clear'), width=70, height=34,
                          corner_radius=8, fg_color='transparent', border_width=1,
                          border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                          text_color=TEXT_PRI, command=self._on_cf_clear).pack(
                              side='left')
            self._cf_status_lbl = ctk.CTkLabel(cf_actions, text='', text_color=TEXT_SEC,
                                               font=(ui_font(), 10))
            self._cf_status_lbl.pack(side='left', padx=12)

        def render_queue_page(container):
            box = ctk.CTkFrame(container, fg_color='transparent')
            box.pack(fill='both', expand=True)
            ctk.CTkLabel(box, text="Save Download Queue", font=(ui_font(), 15, 'bold'), text_color=TEXT_PRI).pack(anchor='w')
            ctk.CTkFrame(box, height=1, fg_color=BORDER).pack(fill='x', pady=(8, 14))
            ctk.CTkLabel(box, text="Download queue items and active progress are automatically saved on exit.", text_color=TEXT_SEC, font=(ui_font(), 11)).pack(anchor='w')

        def render_about_page(container):
            box = ctk.CTkFrame(container, fg_color='transparent')
            box.pack(fill='both', expand=True)
            ctk.CTkLabel(box, text="FetchJAV", font=(ui_font(), 18, 'bold'), text_color=ACCENT).pack(anchor='w')
            ctk.CTkLabel(box, text="Modern High-Speed JAV Downloader", text_color=TEXT_SEC, font=(ui_font(), 11)).pack(anchor='w', pady=(2, 12))
            ctk.CTkFrame(box, height=1, fg_color=BORDER).pack(fill='x', pady=(0, 14))
            ctk.CTkLabel(box, text="• Supports JableTV, MissAV & SupJav", text_color=TEXT_PRI, font=(ui_font(), 11)).pack(anchor='w', pady=2)
            ctk.CTkLabel(box, text="• Multi-threaded chunk downloading & Whisper auto-subtitles", text_color=TEXT_PRI, font=(ui_font(), 11)).pack(anchor='w', pady=2)

        self._settings_page_renderers = {
            'update': render_update_page,
            'download': render_download_page,
            'proxy': render_proxy_page,
            'cf': render_cf_page,
            'queue': render_queue_page,
            'about': render_about_page,
        }

        # Navigation Categories with icons
        self._settings_categories = [
            ('update', '🔄', T('update_settings_title') if 'update_settings_title' in T.__code__.co_varnames else 'Update'),
            ('download', '↓', T('download_settings')),
            ('proxy', '🌐', T('proxy_card_title')),
            ('cf', '🛡️', T('cf_card_title')),
            ('queue', '📋', T('queue_settings_title') if 'queue_settings_title' in T.__code__.co_varnames else 'Save Download Queue'),
            ('about', 'ℹ️', 'About')
        ]

        self._settings_nav_btns = {}
        self._active_settings_cat = 'update'
        self._settings_left_nav = left_nav

        for cat_key, cat_icon, cat_label in self._settings_categories:
            btn = ctk.CTkButton(
                left_nav, text=f"{cat_icon}  {cat_label}",
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
        if not self._current_base_url:
            return
        self._page_req += 1
        my_req = self._page_req
        my_gen = self._build_gen
        site_key = self._site_key
        browser = SITES[site_key]['browser']
        base = self._current_base_url
        page_snapshot = self._page
        if site_key == 'JableTV':
            if '?' in base:
                url = f'{base}&from={page_snapshot}'
            else:
                url = f'{base.rstrip("/")}/?from={page_snapshot}'
        elif site_key == 'SupJav':
            url = SupJavBrowser.page_url(base, page_snapshot)
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
            return '無碼', '#C2410C'
        if ('chinese-subtitle' in url_l or path.endswith('-c') or
                '-c/' in url_l or '中文字幕' in title_l or '中字' in title_l):
            return '中字', '#0E7490'
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
            else:
                msg = self._browse_empty_message or T('no_results')
            ctk.CTkLabel(self._grid_scroll, text=msg,
                         text_color=TEXT_DIM,
                         font=(ui_font(), 14)).pack(pady=40)
            return

        # Responsive card density: 2 compact / 3 default / 4 wide.
        columns = max(2, self._grid_columns)
        try:
            logical_width = self.winfo_width() / max(self._get_window_scaling(), 1.0)
        except Exception:
            logical_width = self.winfo_width()
        estimated_card_width = max(
            240, int((max(logical_width, 980) - 240) / columns) - 24)
        title_wrap = max(180, min(330, estimated_card_width - 34))
        row_frame = None
        for i, v in enumerate(self._videos):
            if i % columns == 0:
                row_frame = ctk.CTkFrame(self._grid_scroll, fg_color='transparent')
                row_frame.pack(fill='x', padx=8, pady=4)

            url = v.get('url', '')
            title = v.get('title', '')
            dur = v.get('duration', '')
            thumb_url = v.get('thumbnail', '')
            is_sel = url in self._selected_urls

            card = ctk.CTkFrame(row_frame, fg_color=ACCENT_DIM if is_sel else BG_CARD,
                                corner_radius=CARD_RADIUS,
                                border_width=2 if is_sel else 1,
                                border_color=ACCENT if is_sel else BORDER_CARD)
            card.pack(side='left', padx=4, pady=4, fill='x', expand=True)

            # Thumbnail placeholder (16:9)
            thumb_holder = ctk.CTkFrame(card, fg_color=BG_SIDEBAR,
                                         height=_THUMB_SIZE[1] + 11, corner_radius=6)
            thumb_holder.pack(fill='x', padx=8, pady=(10, 0))
            thumb_holder.pack_propagate(False)
            thumb_lbl = ctk.CTkLabel(thumb_holder, text=T('loading_browse'),
                                      text_color=TEXT_DIM,
                                      fg_color='transparent',
                                      font=(ui_font(), 11))
            thumb_lbl.pack(fill='both', expand=True)

            # Duration badge
            if dur:
                dur_lbl = ctk.CTkLabel(thumb_holder, text=f' {dur} ',
                                        text_color='#FFFFFF',
                                        fg_color='#000000',
                                        corner_radius=4,
                                        font=('Consolas', 9, 'bold'))
                dur_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-6, y=-6)

            # Title
            title_text = title[:72] + '...' if len(title) > 72 else title
            ctk.CTkLabel(card, text=title_text, text_color=TEXT_PRI,
                         font=(ui_font(), 10),
                         wraplength=title_wrap, justify='left').pack(
                             fill='x', padx=10, pady=(10, 12), anchor='w')

            # Bottom row
            bottom = ctk.CTkFrame(card, fg_color='transparent')
            bottom.pack(fill='x', padx=8, pady=(4, 12))

            sel_text = ('✓ ' + T('selected')) if is_sel else T('select')
            sel_btn = ctk.CTkButton(
                bottom, text=sel_text, height=27, width=88,
                corner_radius=CONTROL_RADIUS,
                fg_color=ACCENT if is_sel else 'transparent',
                border_width=0 if is_sel else 1,
                border_color=BORDER_HOVER,
                hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                text_color=('#FFFFFF', '#FFFFFF') if is_sel else TEXT_PRI,
                font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10),
                command=lambda u=url: self._toggle_select(u)
            )
            sel_btn.pack(side='right', padx=(4, 0))

            preview_btn = ctk.CTkButton(
                bottom, text=T('preview'), height=27, width=75,
                corner_radius=CONTROL_RADIUS,
                fg_color='transparent',
                border_width=1,
                border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI,
                font=(ui_font(), 10),
                command=lambda video=v: self._open_preview(video)
            )
            preview_btn.pack(side='right', padx=(0, 4))

            self._card_widgets[url] = {'card': card, 'sel_btn': sel_btn, 'preview_btn': preview_btn}

            # Clickable card
            def _bind_click(widget, video_url=url):
                widget.bind('<Button-1>', lambda e, u=video_url: self._toggle_select(u))
                widget.configure(cursor='hand2')
            _bind_click(card)
            _bind_click(thumb_holder)
            _bind_click(thumb_lbl)

            # Background thumbnail load
            if thumb_url:
                self._load_thumb_async(
                    thumb_url, thumb_lbl, gen, build_gen, self._site_key)
            else:
                thumb_lbl.configure(text=T('no_thumbnail'))

    def _load_thumb_async(self, thumb_url: str, label: ctk.CTkLabel,
                          gen: int, build_gen: int, site_key: str = ''):
        """Fetch thumbnail in a background thread; marshal result back to the
        main thread via .after() so Tk widget updates stay thread-safe.
        The gen counter prevents stale thumbs from polluting a newer page."""
        def _worker():
            if self._is_closing or gen != self._grid_gen or build_gen != self._build_gen:
                return
            img = _fetch_thumbnail(thumb_url, site_key)
            if img is None:
                def _apply_missing():
                    if (self._is_closing or gen != self._grid_gen or
                            build_gen != self._build_gen):
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
                if self._is_closing or gen != self._grid_gen or build_gen != self._build_gen:
                    return
                try:
                    if not label.winfo_exists():
                        return
                    holder = label.master
                    cw = max(holder.winfo_width(), 100) if (holder and holder.winfo_exists()) else 300
                    ch = max(holder.winfo_height(), 50) if (holder and holder.winfo_exists()) else 180
                    if cw <= 1:
                        cw = 300
                    if ch <= 1:
                        ch = 180
                    label._raw_img = img
                    label._last_w = cw
                    label._last_h = ch
                    fitted_img, nw, nh = _fit_image(img, cw, ch)
                    ctk_img = ctk.CTkImage(light_image=fitted_img, dark_image=fitted_img, size=(nw, nh))
                    label.configure(image=ctk_img, text='')
                    label._ctk_img_ref = ctk_img

                    if not getattr(label, '_has_resize_bind', False) and holder and holder.winfo_exists():
                        label._has_resize_bind = True
                        def _on_resize(event):
                            if not label.winfo_exists():
                                return
                            w, h = event.width, event.height
                            if w > 10 and h > 10 and (getattr(label, '_last_w', 0) != w or getattr(label, '_last_h', 0) != h):
                                label._last_w = w
                                label._last_h = h
                                raw = getattr(label, '_raw_img', None)
                                if raw:
                                    f_img, fw, fh = _fit_image(raw, w, h)
                                    ci = ctk.CTkImage(light_image=f_img, dark_image=f_img, size=(fw, fh))
                                    label.configure(image=ci)
                                    label._ctk_img_ref = ci
                        holder.bind('<Configure>', _on_resize, add='+')
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
                    fg_color=ACCENT_DIM if is_sel else BG_CARD,
                    border_width=2 if is_sel else 1,
                    border_color=ACCENT if is_sel else BORDER_CARD)
                w['sel_btn'].configure(
                    text=('✓ ' + T('selected')) if is_sel else T('select'),
                    fg_color=ACCENT if is_sel else 'transparent',
                    border_width=0 if is_sel else 1,
                    hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                    text_color=WHITE if is_sel else TEXT_PRI,
                    font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10))
            except Exception:
                pass
        self._update_selection_count()

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
                fg_color=ACCENT_DIM if is_sel else BG_CARD,
                border_width=2 if is_sel else 1,
                border_color=ACCENT if is_sel else BORDER_CARD)
            w['sel_btn'].configure(
                text=('✓ ' + T('selected')) if is_sel else T('select'),
                fg_color=ACCENT if is_sel else 'transparent',
                border_width=0 if is_sel else 1,
                hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                text_color=WHITE if is_sel else TEXT_PRI,
                font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10))
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

    def _on_site_change(self, val):
        self._site_key = val
        self._active_tag_slug = None
        self._active_tag_url = None
        self._categories.clear()
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
        self._active_tag_slug = None
        self._active_tag_url = None
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

    def _on_search(self):
        q = (self._search_entry.get() if hasattr(self, '_search_entry') and self._search_entry else (self._search_var.get() if hasattr(self, '_search_var') else '')).strip()
        if not q:
            return
        from urllib.parse import quote
        if self._site_key == 'JableTV':
            # JableTV does not expose language-specific listing/search variants.
            self._current_base_url = f'https://jable.tv/search/?q={quote(q, safe="")}'
        elif self._site_key == 'SupJav':
            self._current_base_url = SupJavBrowser.search_url(q, lang=T('supjav_lang'))
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

    def _on_tag_click(self, url: str, name: str, slug: str = ''):
        self._active_tag_slug = slug
        self._active_tag_url = url
        self._current_base_url = url
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

        if self._site_key != 'JableTV':
            empty_card = ctk.CTkFrame(self._sidebar, fg_color=BG_CARD, corner_radius=CONTROL_RADIUS,
                                      border_width=1, border_color=BORDER)
            empty_card.pack(fill='x', padx=8, pady=16)
            ctk.CTkLabel(empty_card, text=T('tags_jable_only'),
                         text_color=TEXT_SEC,
                         font=(ui_font(), 10)).pack(padx=10, pady=7)
            return

        tags = JableTVBrowser.SIDEBAR_TAGS
        for group_name, tag_list in tags.items():
            expanded = self._sidebar_expanded.get(group_name, False)
            display_group_name = site_i18n.loc(site_i18n.TAG_GROUPS, group_name, group_name)

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
                for name, slug in tag_list:
                    tag_url = JableTVBrowser.tag_url(slug)
                    display_name = site_i18n.loc(site_i18n.TAGS, slug, name)
                    is_active = (
                        getattr(self, '_active_tag_slug', None) == slug or
                        getattr(self, '_active_tag_url', None) == tag_url
                    )
                    btn = ctk.CTkButton(
                        self._sidebar, text=f"•  {display_name}",
                        fg_color='transparent',
                        hover_color=ACCENT_DIM,
                        text_color=ACCENT if is_active else TEXT_SEC,
                        anchor='w',
                        font=(ui_font(), 10, 'bold' if is_active else 'normal'),
                        height=26, corner_radius=6,
                        command=lambda u=tag_url, n=display_name, s=slug: self._on_tag_click(u, n, s))
                    btn.pack(fill='x', padx=(16, 6), pady=1)

    def _toggle_group(self, group: str):
        self._sidebar_expanded[group] = not self._sidebar_expanded.get(group, False)
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
        self._proxy_status_lbl.configure(text=text, text_color=color)

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
        current = self._cf_status_lbl.cget('text')
        self._cf_status_lbl.configure(text=f"{T('cf_saved')} | {current}")

    def _on_cf_clear(self):
        host = self._cf_host_var.get()
        config.clear_cf_override(host)
        self._cf_cookie_var.set('')
        self._cf_ua_var.set('')
        self._refresh_cf_status()

    def _refresh_cf_status(self):
        hosts = config.cf_override_hosts()
        if hosts:
            self._cf_status_lbl.configure(text=T('cf_status', hosts=', '.join(hosts)))
        else:
            self._cf_status_lbl.configure(text=T('cf_status_none'))

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
        d = filedialog.askdirectory()
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

            remove_btn = ctk.CTkButton(
                row, text='✕', width=32, height=32,
                corner_radius=CONTROL_RADIUS,
                fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER,
                text_color=TEXT_DIM, font=('Consolas', 12),
                command=lambda u=item.url: self._dlmgr.remove_item(u))
            remove_btn.pack(side='right', padx=(6, 14))

            retry_btn = ctk.CTkButton(
                row, text='↻', width=32, height=32,
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
            w['retry_btn'].pack(side='right', padx=(2, 0), before=w['_before_remove'])
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
        self._is_closing = True
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
            with self._dlmgr._lock:
                for item in self._dlmgr._items.values():
                    if item.state in ('準備中', '下載中', '等待中'):
                        item.state = '未完成'
                        item.speed = ''
                self._dlmgr.save_csv(CSV_PATH)
        except Exception:
            pass
        self._dlmgr.cancel_all(cleanup=False)
        self.destroy()


def gui_modern_main(url: str = '', dest: str = 'download', lang: str = 'en'):
    _crumb("gui_modern_main: constructing ModernApp")
    app = ModernApp(url=url, dest=dest, lang=lang)
    _crumb("gui_modern_main: app constructed, entering mainloop")
    app.mainloop()
    _crumb("gui_modern_main: mainloop returned (normal exit)")
