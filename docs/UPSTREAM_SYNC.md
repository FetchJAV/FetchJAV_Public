# FetchJAV <- Upstream Sync Guide

How to safely pull backend improvements from the upstream JableTV/MissAV
downloader into FetchJAV without losing FetchJAV's UI, features, branding, or
user data.

## Background

- FetchJAV is a customized fork of `Alos21750/JableTV-MissAV-Downloader-GUI-2026`.
- The fork base is a **squashed snapshot** (`360e11a`), so Git has no shared
  ancestry with upstream. `git merge` cannot be used directly.
- `scripts/sync_upstream.py` performs a **per-file 3-way merge** against the
  fork snapshot (`--base 360e11a`) instead, guided by `docs/sync/ownership.json`.
- The tool never touches the `upstream` remote: it works on local branches and
  lets you review the result before merging to `main`.

## Remotes and branches

```
origin   = https://github.com/DeepanshuK2002/FetchJAV.git        (FetchJAV)
upstream = https://github.com/Alos21750/JableTV-MissAV-Downloader-GUI-2026.git
```

- `main` is the FetchJAV integration branch.
- Upstream's `master` is current; upstream `develop` is an older flavor — ignore it.
- Fetch upstream before every sync:
  `git fetch upstream master --depth=60` (shallow is fine; the fork base is used
  for merging, not the upstream history).

## Ownership model

Every file is classified in `docs/sync/ownership.json` (patterns are fnmatch
globs). On each sync the tool computes, per file, whether upstream changed it
since the fork base:

- **fetchjav_owned** — never auto-modified by the tool. Upstream changes are
  reported as `[review]`; you decide whether to extract anything manually.
  Includes the FetchJAV UI/theme/branding/features: `gui_modern.py`,
  `ui_theme.py`, `args.py` (FetchJAV CLI flags like `--hot-reload`), `.gitignore`,
  `README*`, `updater.py`, `video_preview.py`, `hot_reload.py`, `subtitle/**`,
  `metadata_fetcher.py`, custom icons/logos, and FetchJAV-only tests.
- **upstream_owned** — safe to take upstream's version automatically when
  FetchJAV has not diverged (prefer "theirs" on conflict). Used for upstream-only
  helpers/readme assets.
- **shared** (the default) — automatic 3-way merge with the fork base. Clean
  merges apply; conflicts are reported as `[conflict]` and FetchJAV's copy is
  left in place for manual resolution.

### Why these files are protected (learned the hard way)

- **`ui_theme.py`** — a "clean" 3-way merge with upstream dropped FetchJAV's
  theme constants (`BG_OVERLAY`, etc.) because both sides rewrote the same
  region. `translation_settings_ui.py` failed to import afterwards. Upstream
  theme changes are surfaced for manual review instead of auto-merged.
- **`args.py`** — upstream removed the `--hot-reload` / `--watch-interval`
  flags when they deleted the hot-reload feature. Because FetchJAV had not
  edited `args.py` since the fork, the tool adopted upstream's removal and the
  `hot_reload` CLI test failed. Files tied to FetchJAV features that upstream
  deleted are classified fetchjav-owned.
- **Rule of thumb**: when upstream deletes a feature, expect the affected
  shared files (`args.py`, `main.py`, `config.py`, `gui.py`, `locales.py`) to
  need a manual look — the test gate is designed to catch this.

## Sync workflow (recommended)

```powershell
# 1. Fetch latest upstream
git fetch upstream master --depth=60

# 2. Preview the plan without changing anything
python scripts/sync_upstream.py --dry-run --theirs upstream/master

# 3. Do a real sync on a disposable branch (no commit yet)
python scripts/sync_upstream.py --theirs upstream/master --branch upstream-sync/<date>
```

The tool: creates the branch from `main`, applies adopt/merge operations,
runs an import sanity check, then the full pytest suite, and prints a review
list. It leaves you on the sync branch so you can inspect `git diff`.

### After the tool finishes

1. Read the `[review]` and `[conflict]` entries.
2. `git diff` — especially merged shared files (`config.py`, `gui.py`,
   `main.py`, `jable_smalltool.py`, `locales.py`, `M3U8Sites/*`).
3. Resolve conflicts manually; re-run tests:
   `python -m pytest tests -q` (import check first: `python -c "import config, gui_modern"`).
4. Walk the manual checklist: `docs/REGRESSION_CHECKLIST.md`.
5. When satisfied, merge to `main` (preserves history):
   `git switch main; git merge --no-ff upstream-sync/<date>`
6. Discard the branch: `git branch -D upstream-sync/<date>`.

### Auto-commit mode

`--commit` commits the integrated result on the sync branch, but only if there
are no conflicts and all tests pass. Safer to leave it off and review first.

## Pitfall: never `git reset --hard` right after a sync run

During a real (non-`--dry-run`) sync the tool force-stages upstream's
`build_tmp/*` files (`git add -f`), because they are gitignored on `main` but
tracked upstream. If you then discard the sync branch with
`git switch main && git reset --hard`, those files are removed from the index
**and deleted from disk** — destroying your local untracked `build_tmp/`
copies and breaking the build-system tests
(`tests/test_ui_theme.py::test_windows_version_resources_match_app_version`,
`test_windows_distribution_is_hardened_and_verifiable`).

- To discard a sync branch without committing: `git switch main; git reset`
  (mixed reset — keeps worktree) then `git restore --staged --worktree .`
  for any remaining tracked diffs. Do **not** use `git reset --hard`.
- If the files were already lost, restore them from upstream:
  `git checkout upstream/master -- build_tmp/gen_version.py build_tmp/JableTV_Modern.spec build_tmp/JableTV_Modern.version build_tmp/Jable_smalltool.spec build_tmp/Jable_smalltool.version`
  (upstream's content satisfies the FetchJAV build tests), then unstage:
  `git reset HEAD build_tmp/`.
- Prefer `--dry-run` for planning so nothing is staged or deleted.

## Exit codes / safety guarantees

- The tool requires a clean tracked worktree (untracked files are allowed).
- It refuses to run if the sync branch name already exists.
- On any exception it switches back to the starting branch.
- It never commits to `main`, never pushes, never force-pushes, and never
  rewrites history. Untracked local files (e.g. `build_tmp/*`) are never
  overwritten — they become `[keep]`/review entries instead.
- Exit code 1 when conflicts or review items remain, so CI can gate on it.

## What the sync does NOT do

- Does not delete FetchJAV-only files that upstream removed (`subtitle/**`,
  `hot_reload.py`, `video_preview.py`, custom icons, etc.).
- Does not merge FetchJAV's UI (`gui_modern.py` is never overwritten).
- Does not replace the updater (`updater.py` points at FetchJAV releases).
- Does not reset your user data (stored outside the repo under `%APPDATA%\FetchJAV`).

## Simulated end-to-end validation (Phase 17-18)

A fake upstream release `fake-upstream-v2.6.0` was created to prove the flow:

| Simulated upstream change | Expected | Result |
|---|---|---|
| `M3U8Sites/M3U8Crawler.py` — new `playlist_dedupe()` | merged | present at line ~209 |
| `browser.py` — thumbnail timeout 20 -> 30 | merged | present |
| `subtitle_engine.py` — `lang_filter=` param | merged | present |
| `requirements.txt` — `requests>=2.32.0` | adopted | present |
| `gui_modern.py` — UI label change | NOT adopted (review) | gui_modern.py identical to `main` |

Validation: 670/670 tests pass; FetchJAV features (`subtitle/`, preview,
hot_reload, history) all present; `--hot-reload` CLI flag retained.

## Known follow-ups

- `.github/workflows/windows-build.yml` triggers on `branches: [master]`;
  FetchJAV uses `main`. Update when you want CI to run on `main`.
- Upstream is shallow-fetched (depth 60). If you ever need deeper history for
  merge context, increase the depth.
- Consider committing `docs/sync/ownership.json` + `scripts/sync_upstream.py`
  and, optionally, a `--commit` baseline so syncs start from a clean `main`.
