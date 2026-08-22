import csv
import os
import sys
import types
import queue


def _stub_runtime_dependency(name, factory=None):
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = factory() if factory else types.ModuleType(name)


def _cloudscraper_stub():
    mod = types.ModuleType('cloudscraper')
    mod.create_scraper = lambda *args, **kwargs: None
    return mod


def _m3u8_stub():
    mod = types.ModuleType('m3u8')
    mod.load = lambda *args, **kwargs: None
    return mod


def _customtkinter_stub():
    mod = types.ModuleType('customtkinter')

    class CTk:
        pass

    mod.CTk = CTk
    mod.CTkLabel = CTk
    return mod


_stub_runtime_dependency('cloudscraper', _cloudscraper_stub)
_stub_runtime_dependency('m3u8', _m3u8_stub)
_stub_runtime_dependency('customtkinter', _customtkinter_stub)

import config
import gui_modern
from gui_modern import (
    DownloadItem, DownloadManager, _DownloadTask,
    _select_persist, _visible_window,
)


def _item(url, state):
    return DownloadItem(url, name=url, state=state)


def test_queue_csv_path_uses_appdata_download_queue(monkeypatch, tmp_path):
    monkeypatch.setenv('APPDATA', str(tmp_path))

    assert config.queue_csv_path() == os.path.join(
        str(tmp_path), 'FetchJAV', 'download_queue.csv')


def test_download_queue_csv_round_trip_preserves_destination(tmp_path):
    path = tmp_path / 'download_queue.csv'
    mgr = DownloadManager()
    item = mgr.add_item(
        'https://supjav.com/12345.html',
        name='Example',
        state='未完成',
        dest=r'C:\Videos')
    item.progress = 42

    mgr.save_csv(str(path))

    loaded = DownloadManager()
    loaded.load_csv(str(path))
    loaded_items = loaded.get_items()

    assert len(loaded_items) == 1
    restored = loaded_items[0]
    assert restored.url == 'https://supjav.com/12345.html'
    assert restored.name == 'Example'
    assert restored.state == '未完成'
    assert restored.progress == 42
    assert restored.dest == r'C:\Videos'


def test_download_queue_csv_round_trip_preserves_allowlisted_source_evidence(
        tmp_path):
    path = tmp_path / 'download_queue.csv'
    url = 'https://jable.tv/videos/ipzz-905/'
    manager = DownloadManager()
    manager.add_item(
        url,
        state='未完成',
        source_subtitle_evidence=(
            'jable-category-chinese-subtitle',),
    )

    manager.save_csv(str(path))

    loaded = DownloadManager()
    loaded.load_csv(str(path))
    assert loaded.get_items()[0].source_subtitle_evidence == (
        'jable-category-chinese-subtitle',)


def test_download_queue_csv_rejects_unknown_mismatched_and_oversized_evidence(
        tmp_path):
    path = tmp_path / 'download_queue.csv'
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow([
            '狀態', '名稱', '進度', '速度', '網址', '目標',
            '字幕來源證據',
        ])
        writer.writerow([
            '未完成', 'Unknown', '0%', '',
            'https://example.test/one', '', 'missav-url-chinese-subtitle',
        ])
        writer.writerow([
            '未完成', 'Wrong site', '0%', '',
            'https://supjav.com/1.html', '',
            'jable-category-chinese-subtitle',
        ])
        writer.writerow([
            '未完成', 'Oversized', '0%', '',
            'https://jable.tv/videos/two/', '', 'x' * 513,
        ])

    manager = DownloadManager()
    manager.load_csv(str(path))

    assert all(
        item.source_subtitle_evidence == ()
        for item in manager.get_items())


def test_download_queue_csv_load_tolerates_missing_destination_column(tmp_path):
    path = tmp_path / 'old_queue.csv'
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['狀態', '名稱', '進度', '速度', '網址'])
        writer.writerow(['未完成', 'Old Example', '7%', '', 'https://jable.tv/videos/abc/'])

    mgr = DownloadManager()
    mgr.load_csv(str(path))
    restored = mgr.get_items()[0]

    assert restored.url == 'https://jable.tv/videos/abc/'
    assert restored.name == 'Old Example'
    assert restored.state == '未完成'
    assert restored.progress == 7
    assert restored.dest == ''


def test_download_queue_csv_load_normalizes_active_states(tmp_path):
    path = tmp_path / 'crashed_queue.csv'
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['狀態', '名稱', '進度', '速度', '網址', '目標'])
        writer.writerow(['下載中', 'Active Example', '33%', '1 MB/s',
                         'https://jable.tv/videos/active-001/', r'C:\Videos'])

    mgr = DownloadManager()
    mgr.load_csv(str(path))
    restored = mgr.get_items()[0]

    assert restored.state == '未完成'
    assert restored.progress == 33
    assert restored.dest == r'C:\Videos'


def test__select_persist_keeps_all_resumable_and_caps_completed():
    items = [
        _item('c0', '已下載'),
        _item('r0', '未完成'),
        _item('c1', '已下載'),
        _item('r1', '等待中'),
        _item('c2', '已下載'),
        _item('r2', '封鎖/解析失敗'),
        _item('c3', '已下載'),
        _item('c4', '已下載'),
    ]

    kept = _select_persist(items, 5)

    assert [i.url for i in kept] == ['r0', 'r1', 'r2', 'c3', 'c4']


def test__select_persist_never_drops_resumable_over_cap():
    items = [
        _item('r0', '未完成'),
        _item('r1', '等待中'),
        _item('r2', '封鎖/解析失敗'),
        _item('c0', '已下載'),
    ]

    kept = _select_persist(items, 2)

    assert [i.url for i in kept] == ['r0', 'r1', 'r2']


def test_save_csv_caps_with_monkeypatched_max(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_modern, 'MAX_PERSIST_ROWS', 4)
    path = tmp_path / 'download_queue.csv'
    mgr = DownloadManager()
    for idx in range(2):
        mgr.add_item(f'https://example.test/r{idx}', state='未完成')
    for idx in range(5):
        mgr.add_item(f'https://example.test/c{idx}', state='已下載')

    mgr.save_csv(str(path))

    loaded = DownloadManager()
    loaded.load_csv(str(path))
    urls = [item.url for item in loaded.get_items()]

    assert len(urls) <= 4
    assert 'https://example.test/r0' in urls
    assert 'https://example.test/r1' in urls
    assert urls[-2:] == ['https://example.test/c3', 'https://example.test/c4']


def test_load_csv_caps_large_file(monkeypatch, tmp_path):
    monkeypatch.setattr(gui_modern, 'MAX_PERSIST_ROWS', 4)
    path = tmp_path / 'large_queue.csv'
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['狀態', '名稱', '進度', '速度', '網址', '目標'])
        for idx in range(2):
            writer.writerow(['未完成', f'Resumable {idx}', '0%', '',
                             f'https://example.test/r{idx}', ''])
        for idx in range(5):
            writer.writerow(['已下載', f'Completed {idx}', '100%', '',
                             f'https://example.test/c{idx}', ''])

    mgr = DownloadManager()
    mgr.load_csv(str(path))
    urls = [item.url for item in mgr.get_items()]

    assert len(urls) <= 4
    assert 'https://example.test/r0' in urls
    assert 'https://example.test/r1' in urls
    assert urls[-2:] == ['https://example.test/c3', 'https://example.test/c4']


def test_load_csv_handles_corrupt_file(tmp_path):
    path = tmp_path / 'bad_queue.csv'
    path.write_bytes(b'\xff\xfe\x00not utf-8')

    mgr = DownloadManager()
    mgr.load_csv(str(path))

    assert len(mgr.get_items()) == 0
    assert os.path.exists(str(path) + '.bak')


def test_clear_then_save_writes_header_only(tmp_path):
    path = tmp_path / 'download_queue.csv'
    mgr = DownloadManager()
    mgr.add_item('https://example.test/r0', state='未完成')
    mgr.add_item('https://example.test/c0', state='已下載')

    mgr.clear_all()
    mgr.save_csv(str(path))

    with open(path, 'r', encoding='utf-8', newline='') as f:
        rows = list(csv.reader(f))
    assert rows == [[
        '狀態', '名稱', '進度', '速度', '網址', '目標',
        '字幕來源證據', '續傳',
    ]]


def test__visible_window_prioritizes_active():
    items = [
        _item('done', '已下載'),
        _item('queued', '等待中'),
        _item('cancelled', '已取消'),
        _item('incomplete', '未完成'),
        _item('active', '下載中'),
    ]

    visible = _visible_window(items, 3)

    assert [item.state for item in visible] == ['下載中', '等待中', '未完成']


def test_row_retry_resets_transient_fields_and_requeues():
    item = DownloadItem(
        'https://supjav.com/12345.html', state='未完成', dest=r'C:\Videos')
    item.progress = 44
    item.speed = '2 MB/s'
    item.error = 'reset by peer'

    class FakeManager:
        def __init__(self):
            self.calls = []

        def get_items(self):
            return [item]

        def enqueue(self, url, dest):
            self.calls.append((url, dest))

    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._dlmgr = FakeManager()
    app._dest_var = types.SimpleNamespace(get=lambda: r'C:\Fallback')

    app._retry_download(item.url)

    assert (item.progress, item.speed, item.error) == (0, '', '')
    assert app._dlmgr.calls == [(item.url, r'C:\Videos')]


def test__visible_window_latest_downloading_at_top():
    items = [
        _item('https://example.com/dl1', '下載中'),
        _item('https://example.com/dl2', '下載中'),
        _item('https://example.com/dl3', '下載中'),
    ]
    visible = _visible_window(items, 3)
    assert [i.url for i in visible] == [
        'https://example.com/dl3',
        'https://example.com/dl2',
        'https://example.com/dl1',
    ]


def test_manager_readding_existing_item_moves_to_top():
    mgr = DownloadManager()
    mgr.add_item('https://example.com/1', state='下載中')
    mgr.add_item('https://example.com/2', state='下載中')
    items_before = mgr.get_items()
    # Initially item 2 is newer than item 1
    visible_before = _visible_window(items_before, 2)
    assert visible_before[0].url == 'https://example.com/2'

    # Adding/updating item 1 should move it to the latest position
    mgr.add_item('https://example.com/1', state='下載中')
    items = mgr.get_items()
    assert items[-1].url == 'https://example.com/1'
    visible = _visible_window(items, 2)
    assert visible[0].url == 'https://example.com/1'


def test_download_row_retry_and_close_layout():
    import customtkinter as ctk
    root = ctk.CTk()
    root.withdraw()
    try:
        app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
        app._dl_scroll = ctk.CTkFrame(root)
        app._dl_scroll.pack()
        app._dlmgr = DownloadManager()
        app._dest_var = types.SimpleNamespace(get=lambda: r'C:\Downloads')
        app._STATE_COLORS = gui_modern.ModernApp._STATE_COLORS
        app._STATE_BACKGROUNDS = gui_modern.ModernApp._STATE_BACKGROUNDS

        item = DownloadItem('https://example.com/fail', state='未完成')
        w = app._build_dl_row(item)
        root.update()

        # Retry button should be packed inside actions frame to the left of close
        assert w['retry_visible'] is True
        assert w['retry_btn'].master == w['actions']
        assert w['remove_btn'].master == w['actions']

        # Transition to completed/no error -> retry should hide
        item.state = '已下載'
        item.error = ''
        app._update_dl_row(w, item)
        root.update()
        assert w['retry_visible'] is False
    finally:
        root.destroy()


def test_default_theme_is_dark(tmp_path, monkeypatch):
    path = tmp_path / 'ui_prefs_empty.json'
    monkeypatch.setattr(config, '_ui_prefs_path', lambda: str(path))
    assert config.get_theme() == 'dark'


def test_theme_mode_helpers_in_modern_app():
    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._theme_mode = 'dark'
    assert app._theme_display_name('dark') == 'Dark Theme'
    assert app._theme_display_name('light') == 'Light Theme'
    assert app._theme_display_name('system') == 'System Theme'


def test_csv_round_trip_preserves_resume_flag(tmp_path):
    path = tmp_path / 'queue_resume.csv'
    mgr = DownloadManager()
    item = mgr.add_item('https://example.test/r0', state='未完成')
    item.resume = True
    mgr.save_csv(str(path))

    loaded = DownloadManager()
    loaded.load_csv(str(path))
    restored = loaded.get_items()[0]

    assert restored.resume is True
    assert restored.state == '未完成'


def test_csv_load_defaults_resume_flag_false_for_legacy_files(tmp_path):
    path = tmp_path / 'queue_legacy.csv'
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['狀態', '名稱', '進度', '速度', '網址', '目標'])
        writer.writerow(['未完成', 'Legacy', '0%', '',
                         'https://example.test/r0', ''])

    mgr = DownloadManager()
    mgr.load_csv(str(path))

    assert mgr.get_items()[0].resume is False


def test_mark_inflight_for_resume_flags_active_states():
    mgr = DownloadManager()
    items = {}
    for idx, state in enumerate([
            '下載中', '等待中', '字幕準備中', '字幕辨識中', '字幕翻譯中']):
        items[state] = mgr.add_item(
            f'https://example.test/i{idx}', state=state)
    mgr.add_item('https://example.test/done', state='已下載')
    mgr.add_item('https://example.test/incomplete', state='未完成')

    mgr.mark_inflight_for_resume()

    by_state = {item.url: item for item in mgr.get_items()}
    for state, item in items.items():
        assert item.state == '未完成'
        assert item.resume is True
        assert item.speed == ''
    assert by_state['https://example.test/done'].state == '已下載'
    assert by_state['https://example.test/done'].resume is False
    assert by_state['https://example.test/incomplete'].state == '未完成'
    assert by_state['https://example.test/incomplete'].resume is False


def test_auto_resume_pending_enqueues_only_flagged(monkeypatch):
    mgr = DownloadManager()
    flagged = mgr.add_item('https://example.test/flag', state='未完成')
    flagged.resume = True
    flagged.progress = 44
    flagged.speed = '1 MB/s'
    flagged.error = 'reset'
    plain = mgr.add_item('https://example.test/plain', state='未完成')
    calls = []
    monkeypatch.setattr(
        mgr, 'enqueue', lambda url, dest: calls.append((url, dest)))

    mgr.auto_resume_pending()

    assert calls == [('https://example.test/flag', 'download')]
    assert flagged.resume is False
    assert flagged.progress == 44
    assert flagged.speed == ''
    assert flagged.error == ''
    assert plain.resume is False


def test_auto_resume_pending_uses_item_dest(monkeypatch):
    mgr = DownloadManager()
    flagged = mgr.add_item(
        'https://example.test/flag', state='未完成', dest=r'C:\Videos')
    flagged.resume = True
    calls = []
    monkeypatch.setattr(
        mgr, 'enqueue', lambda url, dest: calls.append((url, dest)))

    mgr.auto_resume_pending()

    assert calls == [('https://example.test/flag', r'C:\Videos')]


def test_inflight_count_counts_active_and_pending():
    mgr = DownloadManager()
    assert mgr.inflight_count == 0
    mgr._active['https://example.test/a'] = _DownloadTask(
        'https://example.test/a', '', 0)
    mgr._pending.append(_DownloadTask('https://example.test/b', '', 0))
    mgr._subtitle_active['https://example.test/c'] = _DownloadTask(
        'https://example.test/c', '', 0)
    mgr._subtitle_pending.append(_DownloadTask('https://example.test/d', '', 0))

    assert mgr.inflight_count == 4

    mgr._active.pop('https://example.test/a')
    assert mgr.inflight_count == 3


def test_on_close_routes_by_inflight(monkeypatch):
    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._is_closing = False
    app._close_dlg = None
    calls = []

    class _Mgr:
        inflight_count = 0

    app._dlmgr = _Mgr()
    monkeypatch.setattr(
        app, '_do_close_quit', lambda: calls.append('quit'))
    monkeypatch.setattr(
        app, '_show_close_dialog', lambda: calls.append('dialog'))

    app._on_close()
    assert calls == ['quit']

    calls.clear()
    app._dlmgr = type('_F', (), {'inflight_count': 2})()
    app._on_close()
    assert calls == ['dialog']

    calls.clear()
    app._close_dlg = object()
    app._on_close()
    assert calls == []


def test_do_close_quit_order_and_idempotency(monkeypatch):
    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._is_closing = False
    app._close_dlg = None
    app._dl_drain_id = None
    calls = []

    class _Mgr:
        def mark_inflight_for_resume(self):
            calls.append('mark')

        def save_csv(self, path):
            calls.append('save')

        def cancel_all(self, cleanup=False):
            calls.append('cancel')

    class _Exec:
        def shutdown(self, **kwargs):
            calls.append('thumb')

    app._dlmgr = _Mgr()
    app._thumb_executor = _Exec()
    monkeypatch.setattr(app, '_stop_tray', lambda: calls.append('tray'))
    monkeypatch.setattr(app, 'destroy', lambda: calls.append('destroy'))

    app._do_close_quit()
    assert calls == ['thumb', 'mark', 'save', 'cancel', 'tray', 'destroy']
    assert app._is_closing is True

    calls.clear()
    app._do_close_quit()
    assert calls == []


def test_stop_tray_noops_without_tray():
    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._tray_icon = None
    app._tray_available = False
    app._tray_cmd_drain_id = None
    app._background_poll_id = None

    app._stop_tray()

    assert app._tray_icon is None
    assert app._tray_available is False


def _fake_pystray_module():
    mod = types.ModuleType('pystray')
    created = {}

    class _MenuItem:
        def __init__(self, text, action, default=False):
            self.text = text
            self.action = action
            self.default = default

    class _Menu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class _Icon:
        def __init__(self, name, image, title, menu):
            created.update({
                'name': name, 'image': image,
                'title': title, 'menu': menu,
            })

        def run_detached(self):
            created['detached'] = True

        def stop(self):
            created['stopped'] = True

        def notify(self, message, title):
            created['notified'] = (message, title)

    mod.Menu = _Menu
    mod.MenuItem = _MenuItem
    mod.Icon = _Icon
    return mod, created


def test_ensure_tray_creates_detached_icon(monkeypatch):
    fake_mod, created = _fake_pystray_module()
    monkeypatch.setitem(sys.modules, 'pystray', fake_mod)

    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._tray_icon = None
    app._tray_available = False
    app._tray_cmds = None
    app._tray_cmd_drain_id = None
    app._background_poll_id = None
    app._window_hidden = False
    app._is_closing = False
    monkeypatch.setattr(app, '_arm_tray_cmd_drain', lambda: None)

    app._ensure_tray()

    assert app._tray_available is True
    assert app._tray_icon is not None
    assert created.get('detached') is True
    assert created.get('name') == 'FetchJAV'
    assert len(created['menu'].items) == 3


def test_ensure_tray_handles_missing_pystray(monkeypatch):
    def _no_pystray():
        raise ImportError('no pystray')
    monkeypatch.setitem(
        sys.modules, 'pystray', None)
    import builtins
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == 'pystray':
            raise ImportError('blocked')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', _blocked)

    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._tray_icon = None
    app._tray_available = False
    app._tray_cmds = None
    app._tray_cmd_drain_id = None
    app._background_poll_id = None
    app._is_closing = False

    app._ensure_tray()

    assert app._tray_available is False
    assert app._tray_icon is None


def test_drain_tray_cmds_handles_restore_and_quit(monkeypatch):
    app = gui_modern.ModernApp.__new__(gui_modern.ModernApp)
    app._tray_cmds = queue.Queue()
    app._tray_icon = object()
    app._tray_cmd_drain_id = None
    app._is_closing = False
    app._log = []
    monkeypatch.setattr(app, '_arm_tray_cmd_drain', lambda: None)
    monkeypatch.setattr(
        app, '_restore_from_tray', lambda: app._log.append('restore'))
    monkeypatch.setattr(
        app, '_do_close_quit', lambda: app._log.append('quit'))

    app._tray_cmds.put('restore')
    app._tray_cmds.put('restore')
    app._drain_tray_cmds()
    assert app._log == ['restore', 'restore']

    app._tray_cmds.put('quit')
    app._drain_tray_cmds()
    assert app._log == ['restore', 'restore', 'quit']

