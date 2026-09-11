# FetchJAV Regression Checklist

Walk this after any upstream sync (or before any release). Automated tests
cover the core logic; this covers what pytest cannot: GUI, packaging, data
safety, and end-to-end behavior.

## 1. CLI (fetchjav-owned flags must survive a sync)

```powershell
python main.py --help          # --hot-reload, --watch-interval, --random, etc. still listed
python main.py --hot-reload    # launches the dev watcher, no crash
```

## 2. GUI smoke test (manual)

Run `python main.py` (or the packaged exe) and check:

- [ ] App launches, shows the FetchJAV Modern UI (not the upstream skin).
- [ ] Search / browse a site — results render as cards, thumbnails load.
- [ ] Preview player opens (`video_preview.py`) and plays a sample.
- [ ] Related videos section appears on a video page.
- [ ] History: open several videos, then check View History entries persist
      after restart (data lives in `%APPDATA%\FetchJAV`).
- [ ] Downloader: start a download, segment workers spawn, progress updates.
- [ ] Settings screen incl. Translation Settings (`translation_settings_ui.py`)
      opens and saves.
- [ ] Accent/theme colors render (ui_theme constants intact).
- [ ] About dialog shows FetchJAV version (not upstream's).

## 3. Subtitle system

- [ ] `python -m pytest tests/test_subtitle_system.py tests/test_subtitle_integration.py -q`
- [ ] Generate subtitles on a sample video → `.ja.srt`/`.en.srt`/`.zh-TW.srt`
      sidecars appear and are selectable in a media player.
- [ ] Metadata cross-search (`metadata_fetcher.py`) still returns results.

## 4. Automated regression

```powershell
python -m pytest tests -q        # expect 670 passed
python -c "import config, gui_modern, video_preview, video_identity, subtitle_engine, subtitle, updater, main"
```

## 5. Data safety

- [ ] No settings/history/preferences were reset by the sync (check
      `%APPDATA%\FetchJAV` still holds your data).
- [ ] Repo contains no secrets/keys; `.gitignore` still ignores `build_tmp/`
      and the nested repo folder.

## 6. Packaging / updater

- [ ] `updater.py` reports FetchJAV's repo/version (never upstream's).
- [ ] Packaging builds from `build_tmp/*.spec` succeed (spec files were synced
      from upstream).

## 7. Post-sync hygiene

- [ ] `git log --oneline -5` shows the sync merge on `main` with `--no-ff`.
- [ ] Sync branch deleted (`git branch -D upstream-sync/<date>`).
- [ ] If the sync touched `locales.py`/`crashlog.py` conflicts, re-ran tests
      after resolving.
