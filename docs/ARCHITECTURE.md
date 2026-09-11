# FetchJAV Repository Architecture

This document describes the layout, history, and integration strategy of the
FetchJAV project so future work (and future upstream syncs) can be done safely.

## Repository layout

```
JableTV/                                   (outer wrapper repo)
└── JableTV-MissAV-Downloader-GUI-2026-master/   (canonical FetchJAV repo — all work happens here)
    ├── gui_modern.py                      FetchJAV UI (ModernApp class ~line 1417) — fetchjav-owned
    ├── ui_theme.py                        FetchJAV theme/design system — fetchjav-owned
    ├── args.py                            CLI flags incl. --hot-reload — shared, hot-reload block via preserve map
    ├── video_preview.py                   in-app video preview player — fetchjav-owned
    ├── metadata_fetcher.py                cross-site metadata search — fetchjav-owned
    ├── hot_reload.py                      dev hot-reload watcher — shared (kept; upstream deleted it)
    ├── updater.py                         self-updater (points at FetchJAV releases) — fetchjav-owned
    ├── translation_settings_ui.py         translation settings screen — fetchjav-owned
    ├── subtitle/                          FetchJAV subtitle package — fetchjav-owned
    ├── M3U8Sites/                         scraper/site adapters — shared (3-way merge)
    ├── config.py                          settings + history helpers — shared
    ├── gui.py / jable_smalltool.py / main.py / subtitle_engine.py  shared
    ├── locales.py                         i18n strings — shared (conflict-prone)
    ├── crashlog.py                        diagnostics — shared (conflict-prone)
    ├── tests/                             pytest suite (670 tests) — mix of owned/shared
    ├── scripts/sync_upstream.py           upstream sync tool (this architecture)
    ├── docs/sync/ownership.json           ownership map consumed by the tool
    └── build_tmp/                         local packaging artifacts (untracked, gitignored on main)
```

## Git model

- No shared ancestry with upstream: FetchJAV's root commit `360e11a` is a
  squashed fork snapshot and serves as the 3-way merge base.
- `origin` = FetchJAV, `upstream` = Alos21750's project. Sync uses local
  branches only; `main` is the integration branch.
- `docs/sync/ownership.json` partitions files into `fetchjav_owned`,
  `upstream_owned`, and `shared`, plus a `preserve` map for kept-feature blocks —
  the contract that keeps auto-sync safe.

## Feature inventory (FetchJAV-specific)

These are the FetchJAV deliverables that the sync must always preserve:

- **Preview**: in-app video preview player (`video_preview.py`), preview
  browser, `preview_block.txt`; upstream dropped the whole feature.
- **View/download history**: persisted in prefs JSON under `%APPDATA%\FetchJAV`;
  helpers in `config.py` (`get_view_history`, `add_view_history`, …). **User
  data lives outside the repo and is never touched by sync.**
- **Related videos / video identity**: `video_identity.py`, related-video
  section in the browser.
- **Custom UI**: `gui_modern.py` (9.2k lines vs ~4k upstream), `ui_theme.py`
  (custom colors incl. `BG_OVERLAY`/`ACCENT`), translation settings screen,
  modern dialogs/nav/thumbnails, custom icon set in `img/`.
- **Subtitle system**: `subtitle/` package + `subtitle_engine.py` additions
  (sidecar `.ja/.en/.zh-TW.srt` generation), `metadata_fetcher.py`.
- **Hot reload** (`hot_reload.py`, `--hot-reload` flag) — upstream deleted it.
- **Branding**: `README.md`/`README.en.md`, `WINDOWS_SECURITY.md`, logos/favicons.
- **Updater**: downloads releases of *FetchJAV* (`FetchJAV/FetchJAV_Public`),
  not upstream builds.

## Key integration surfaces

- Upstream backend improvements worth syncing: scraper robustness in
  `M3U8Sites/`, download/network handling in `browser.py` + `M3U8Crawler.py`,
  translation/LLM stack (`llm_translation.py`, `translation_settings.py`),
  build tooling (`build_tmp/gen_version.py`, spec files), dependency bumps
  (`requirements.txt`).
- Danger spots where auto-merge is unsafe: `ui_theme.py`, `gui_modern.py`,
  `locales.py`, `.gitignore`. These are fetchjav-owned or conflict-prone and are
  always surfaced for manual review. `args.py` is shared but protected by a
  `preserve` rule that re-inserts the `--hot-reload`/`--watch-interval` block.
