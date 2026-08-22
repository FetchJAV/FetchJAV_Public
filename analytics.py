#!/usr/bin/env python
# coding: utf-8
"""Firebase and Google Analytics 4 (GA4) Tracking for FetchJAV Desktop.

Uses the GA4 Measurement Protocol / HTTP collection endpoint to asynchronously
report telemetry and usage events (app launches, site switches, downloads, searches)
to Firebase Analytics (Measurement ID: G-5Q9PHPBB86).
"""

import os
import platform
import queue
import threading
import time
import uuid
from typing import Any, Dict, Optional

import requests

import config

MEASUREMENT_ID = "G-5Q9PHPBB86"
API_SECRET = "X4qGhQRBTmGWPw3ce9aHZw"
FIREBASE_APP_ID = "1:535382138027:web:40afbe7b9bed9996deebee"
PROJECT_ID = "fetchjav"
COLLECT_ENDPOINT = "https://www.google-analytics.com/mp/collect"

_event_queue: queue.Queue = queue.Queue(maxsize=1000)
_worker_thread: Optional[threading.Thread] = None
_client_id: Optional[str] = None
_client_id_lock = threading.Lock()
_session_id: Optional[int] = None
_enabled = True


def get_client_id() -> str:
    """Retrieve or generate a persistent anonymous UUID for GA4 client tracking."""
    global _client_id
    with _client_id_lock:
        if _client_id:
            return _client_id

        # Try loading from AppData/FetchJAV/client_id.txt
        appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
        d = os.path.join(appdata, 'FetchJAV')
        cid_file = os.path.join(d, 'client_id.txt')

        if os.path.exists(cid_file):
            try:
                with open(cid_file, 'r', encoding='utf-8') as f:
                    val = f.read().strip()
                    if val and len(val) >= 16:
                        _client_id = val
                        return _client_id
            except Exception:
                pass

        # Generate new anonymous client ID
        new_cid = str(uuid.uuid4())
        try:
            os.makedirs(d, exist_ok=True)
            with open(cid_file, 'w', encoding='utf-8') as f:
                f.write(new_cid)
        except Exception:
            pass

        _client_id = new_cid
        return _client_id


def get_session_id() -> int:
    """Return a stable per-run analytics session id (epoch seconds of app start)."""
    global _session_id
    if _session_id is None:
        _session_id = int(time.time())
    return _session_id


def is_enabled() -> bool:
    """Return True if analytics reporting is enabled."""
    global _enabled
    return _enabled


def set_enabled(enabled: bool) -> None:
    """Enable or disable analytics reporting."""
    global _enabled
    _enabled = bool(enabled)


def _analytics_worker():
    """Background daemon worker that drains the event queue and dispatches HTTP hits."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': f'FetchJAV-Desktop/0.1.5 ({platform.system()} {platform.release()})',
    })

    while True:
        try:
            item = _event_queue.get(block=True, timeout=5)
        except queue.Empty:
            continue
        except Exception:
            break

        if item is None:
            break

        if not _enabled:
            _event_queue.task_done()
            continue

        try:
            event_name, params = item
            cid = get_client_id()

            event_params: Dict[str, Any] = {
                'engagement_time_msec': 100,
                'session_id': get_session_id(),
            }
            for k, v in (params or {}).items():
                if v is None:
                    continue
                name = str(k)[:40]
                if isinstance(v, bool):
                    event_params[name] = int(v)
                elif isinstance(v, (int, float)):
                    event_params[name] = v
                else:
                    event_params[name] = str(v)[:100]

            payload = {
                'client_id': cid,
                'events': [{
                    'name': str(event_name)[:40],
                    'params': event_params,
                }],
            }

            proxy_kwargs = {}
            try:
                proxy_kwargs = config.proxy_request_kwargs()
            except Exception:
                pass

            session.post(
                COLLECT_ENDPOINT,
                params={
                    'measurement_id': MEASUREMENT_ID,
                    'api_secret': API_SECRET,
                },
                json=payload,
                timeout=4,
                **proxy_kwargs
            )
        except Exception:
            pass
        finally:
            _event_queue.task_done()


def _ensure_worker_running():
    """Ensure the background dispatch worker thread is active."""
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_analytics_worker, daemon=True, name="AnalyticsDispatcher")
        _worker_thread.start()


def track_event(event_name: str, params: Optional[Dict[str, Any]] = None) -> None:
    """Enqueue an event to be sent asynchronously to Google Analytics / Firebase."""
    if not _enabled:
        return
    _ensure_worker_running()
    try:
        _event_queue.put_nowait((event_name, params or {}))
    except queue.Full:
        pass


def track_app_open(version: str = '0.1.5', lang: str = 'en') -> None:
    """Report application launch event."""
    track_event('app_open', {
        'app_name': 'FetchJAV',
        'app_version': version,
        'os_name': platform.system(),
        'os_version': platform.release(),
        'lang': lang,
    })


def track_site_switch(site_name: str) -> None:
    """Report site category switch (e.g. JableTV, MissAV, HanimeTV, TnaFlix)."""
    track_event('site_switch', {
        'site_name': site_name,
    })


def track_preview_open(site_name: str, format_name: str = 'HLS') -> None:
    """Report opening a video in the embedded preview player."""
    track_event('preview_open', {
        'site_name': site_name,
        'media_format': format_name,
    })


def track_search(site_name: str, is_all_sites: bool = False) -> None:
    """Report a video search event."""
    track_event('search_query', {
        'site_name': 'All Sites' if is_all_sites else site_name,
        'search_all': 1 if is_all_sites else 0,
    })


def track_download_start(site_name: str, quality: str = 'highest') -> None:
    """Report a download task started."""
    track_event('download_start', {
        'site_name': site_name,
        'resolution_pref': quality,
    })


def track_download_complete(site_name: str, duration_sec: int = 0) -> None:
    """Report a download task completed."""
    track_event('download_complete', {
        'site_name': site_name,
        'duration_sec': duration_sec,
    })
