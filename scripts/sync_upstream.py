#!/usr/bin/env python3
# coding: utf-8
"""
FetchJAV <-> upstream synchronization tool.

Brings upstream backend improvements into FetchJAV while preserving every
FetchJAV-owned file (custom UI, Preview, History, subtitle package, custom
thumbnails, branding, dialogs, settings) and all FetchJAV user data.

Why this exists
---------------
FetchJAV forked upstream (github.com/Alos21750/JableTV-MissAV-Downloader-GUI-2026)
as a squashed snapshot, so there is no shared Git ancestry to `git merge`.
This tool performs a file-level 3-way integration instead, using the fork
snapshot as the merge base:

    base    = the fork snapshot (by default the first FetchJAV commit)
    ours    = the current FetchJAV branch
    theirs  = upstream (default: upstream/master)

Per-file decision
-----------------
1. Upstream did not change the file        -> keep ours (no-op)
2. Upstream changed it, FetchJAV did not:
     - fetchjav-owned file                 -> do NOT overwrite, flag for review
     - otherwise                           -> adopt upstream version
3. Both sides changed:
     - fetchjav-owned file                 -> do NOT auto-merge, flag for review
     - shared file (text)                  -> 3-way merge; conflicts flagged
     - shared file (binary)                -> keep ours, flag for review
4. Upstream deleted a file we kept         -> keep it (never delete FetchJAV work),
                                              flag when it was an upstream file
5. Upstream added a new file               -> adopt it
6. We added a file upstream lacks          -> keep it

Ownership rules live in docs/sync/ownership.json.

Safety guarantees
-----------------
This tool NEVER rewrites history, force-pushes, touches the upstream remote,
blindly overwrites FetchJAV-owned files, or deletes FetchJAV features. It works
on a dedicated branch and requires a clean working tree.

Usage
-----
    python scripts/sync_upstream.py                    # sync from upstream/master
    python scripts/sync_upstream.py --dry-run          # preview only
    python scripts/sync_upstream.py --theirs v2.6.0    # sync from a tag/branch
    python scripts/sync_upstream.py --commit           # commit the clean result
    python scripts/sync_upstream.py --list-ownership   # print the ownership map
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OWNERSHIP_FILE = REPO_ROOT / 'docs' / 'sync' / 'ownership.json'

# The fork snapshot: the first FetchJAV commit, which squashes the upstream
# code base as it existed at fork time (plus FetchJAV's initial work).
DEFAULT_BASE = '360e11a'
DEFAULT_THEIRS = 'upstream/master'

OWNERSHIP_CLASSES = ('fetchjav_owned', 'upstream_owned', 'shared')


class SyncError(Exception):
    pass


# --------------------------------------------------------------------------- #
# git helpers
# --------------------------------------------------------------------------- #

def run_git(args, check=True, **kwargs):
    """Run a git command inside the repo and return (returncode, stdout)."""
    cmd = ['git']
    cmd.extend(str(a) for a in args)
    proc = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding='utf-8', errors='replace', **kwargs)
    if check and proc.returncode != 0:
        raise SyncError(
            f"git {' '.join(cmd)} failed:\n{proc.stdout.strip()}\n{proc.stderr.strip()}")
    return proc.returncode, proc.stdout


def git_stdout(args, check=True):
    _, out = run_git(args, check=check)
    return out


def ref_exists(ref):
    code, _ = run_git(['rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}'], check=False)
    return code == 0


def blob_content(ref, path):
    """Return blob content for 'ref:path' or None if it does not exist."""
    code, _ = run_git(['cat-file', '-e', f'{ref}:{path}'], check=False)
    if code != 0:
        return None
    proc = subprocess.run(
        ['git', 'show', f'{ref}:{path}'], cwd=str(REPO_ROOT),
        capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_binary(data):
    return b'\x00' in data[:8192] if data else False


def tree_files(ref):
    out = git_stdout(['ls-tree', '-r', '--name-only', ref])
    return {line for line in out.splitlines() if line.strip()}


def current_branch():
    code, out = run_git(['symbolic-ref', '--short', 'HEAD'], check=False)
    if code == 0:
        return out.strip()
    code, out = run_git(['rev-parse', '--short', 'HEAD'], check=False)
    return out.strip() or 'HEAD'


def worktree_clean(include_untracked):
    code, out = run_git(['status', '--porcelain'], check=False)
    if code != 0:
        return False, 'cannot read git status'
    for line in out.splitlines():
        st = line[:2].strip()
        if st == '??' and not include_untracked:
            continue
        if st:
            return False, line
    return True, ''


# --------------------------------------------------------------------------- #
# ownership map
# --------------------------------------------------------------------------- #

def load_ownership():
    rules = {'fetchjav_owned': [], 'upstream_owned': []}
    if OWNERSHIP_FILE.exists():
        try:
            data = json.loads(OWNERSHIP_FILE.read_text(encoding='utf-8'))
            for cls in ('fetchjav_owned', 'upstream_owned'):
                rules[cls] = list(data.get(cls) or [])
        except Exception as exc:  # pragma: no cover - config is trusted
            raise SyncError(f'cannot parse {OWNERSHIP_FILE}: {exc}')
    return rules


def classify(rules, path):
    for cls in ('fetchjav_owned', 'upstream_owned'):
        for pattern in rules[cls]:
            if fnmatch.fnmatch(path, pattern):
                return cls
    return 'shared'


def print_ownership():
    rules = load_ownership()
    print(f'Ownership map loaded from {OWNERSHIP_FILE.relative_to(REPO_ROOT)}')
    for cls in OWNERSHIP_CLASSES:
        print(f'\n[{cls}]')
        for pat in rules.get(cls, []):
            print(f'  {pat}')


# --------------------------------------------------------------------------- #
# 3-way merge
# --------------------------------------------------------------------------- #

def three_way_merge(base_data, ours_data, theirs_data, path, tmp):
    """Return (ok, merged_bytes). ok=False means conflicts or binary."""
    if is_binary(base_data) or is_binary(ours_data) or is_binary(theirs_data):
        return False, ours_data
    base_f = tmp / 'base.txt'
    ours_f = tmp / 'ours.txt'
    theirs_f = tmp / 'theirs.txt'
    base_f.write_bytes(base_data)
    ours_f.write_bytes(ours_data)
    theirs_f.write_bytes(theirs_data)
    proc = subprocess.run(
        ['git', 'merge-file', '-p',
         '-L', 'ours:HEAD', '-L', 'base:fork-snapshot', '-L', 'theirs:upstream',
         str(ours_f), str(base_f), str(theirs_f)],
        cwd=str(REPO_ROOT), capture_output=True)
    merged = proc.stdout
    return proc.returncode == 0, merged


# --------------------------------------------------------------------------- #
# sync engine
# --------------------------------------------------------------------------- #

def plan_sync(base_ref, theirs_ref, rules, tmp):
    """Classify every file and return a list of operations."""
    base_files = tree_files(base_ref)
    ours_files = tree_files('HEAD')
    theirs_files = tree_files(theirs_ref)

    ops = []          # dicts describing actions
    reviews = []      # (severity, path, message)
    noops = []

    all_files = sorted(base_files | ours_files | theirs_files)

    for path in all_files:
        cls = classify(rules, path)
        base_data = blob_content(base_ref, path)
        ours_data = blob_content('HEAD', path)
        theirs_data = blob_content(theirs_ref, path)

        theirs_changed = theirs_data != base_data
        ours_changed = ours_data != base_data

        # 1. Upstream did not change the file.
        if not theirs_changed:
            if ours_data is None and theirs_data is None:
                continue
            if ours_data is None:          # upstream deleted a file we dropped too
                continue
            if base_data is not None and ours_data is not None and \
                    base_data == ours_data:
                noops.append(path)
                continue
            if theirs_data is None:        # upstream deleted it, we still keep it
                reviews.append((
                    'keep', path,
                    f'upstream deleted this file; FetchJAV still has it '
                    f'({"fetchjav-owned" if cls == "fetchjav_owned" else cls}). Keep.'))
                continue
            noops.append(path)
            continue

        # Upstream changed the file.
        if base_data is None:
            # Upstream added a brand-new file.
            if ours_data is None:
                if (REPO_ROOT / path).exists():
                    reviews.append((
                        'keep', path,
                        'upstream added this file but an untracked local file '
                        'already exists; NOT overwritten. Review manually.'))
                else:
                    ops.append({'action': 'adopt', 'path': path,
                                'ref': theirs_ref, 'note': f'new upstream file ({cls})'})
            else:
                ok, merged = three_way_merge(b'', ours_data, theirs_data, path, tmp)
                if ok:
                    ops.append({'action': 'merge', 'path': path,
                                'data': merged, 'note': 'new file on both sides'})
                else:
                    reviews.append(('conflict', path,
                                    'new file added on both sides; cannot auto-merge'))
            continue

        if not ours_changed:
            # Upstream changed a file FetchJAV did not touch.
            if cls == 'fetchjav_owned':
                if theirs_data is None:
                    msg = ('upstream deleted this file; FetchJAV keeps its own '
                           'copy. NOT deleted.')
                else:
                    msg = ('upstream changed a fetchjav-owned file; NOT '
                           'overwritten. Review manually and extract backend '
                           'improvements if any.')
                reviews.append(('review', path, msg))
            else:
                ops.append({'action': 'adopt', 'path': path,
                            'ref': theirs_ref, 'note': f'upstream change ({cls})'})
            continue

        # Both sides changed.
        if cls == 'fetchjav_owned':
            reviews.append((
                'review', path,
                'both sides changed a fetchjav-owned file; NOT auto-merged. '
                'Review manually.'))
            continue

        ok, merged = three_way_merge(base_data, ours_data, theirs_data, path, tmp)
        if ok:
            if merged != ours_data:
                ops.append({'action': 'merge', 'path': path, 'data': merged,
                            'note': '3-way merge (clean)'})
            else:
                noops.append(path)
        else:
            if cls == 'upstream_owned':
                # Auto-generated / upstream-maintained file we rarely touch:
                # prefer upstream on conflict.
                ops.append({'action': 'adopt', 'path': path,
                            'ref': theirs_ref,
                            'note': 'upstream_owned file; preferred theirs on conflict'})
            else:
                reviews.append(('conflict', path,
                                'both sides changed; 3-way merge has conflicts. Resolve manually.'))

    return ops, reviews, noops


def apply_ops(ops, reviews, theirs_ref, dry_run):
    if dry_run:
        return
    for op in ops:
        path = REPO_ROOT / op['path']
        if op['action'] == 'adopt':
            data = blob_content(op['ref'], op['path'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            # -f so gitignored paths (e.g. build_tmp/) can be tracked.
            run_git(['add', '-f', '--', op['path']])
        elif op['action'] == 'merge':
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(op['data'])
            run_git(['add', '--', op['path']])


def run_tests():
    print('\n== Running tests ==')
    cmd = [sys.executable, '-m', 'pytest', 'tests', '-q']
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                          text=True, encoding='utf-8', errors='replace')
    print(proc.stdout[-3000:])
    if proc.returncode != 0:
        print(proc.stderr[-1500:])
    return proc.returncode == 0


def import_check():
    print('\n== Import sanity check ==')
    cmd = [sys.executable, '-c',
           'import config, gui_modern, video_preview, video_identity, '
           'subtitle_engine, subtitle, updater, main']
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                          text=True, encoding='utf-8', errors='replace')
    if proc.returncode != 0:
        print(proc.stdout[-1500:])
        print(proc.stderr[-1500:])
        return False
    print('all core modules imported successfully')
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Sync upstream backend improvements into FetchJAV safely.')
    parser.add_argument('--theirs', default=DEFAULT_THEIRS,
                        help=f'upstream ref to sync from (default: {DEFAULT_THEIRS})')
    parser.add_argument('--base', default=DEFAULT_BASE,
                        help='fork snapshot commit used as merge base '
                             f'(default: {DEFAULT_BASE})')
    parser.add_argument('--branch', default=None,
                        help='name of the sync branch (default: upstream-sync/<date>)')
    parser.add_argument('--dry-run', action='store_true',
                        help='only print the plan, change nothing')
    parser.add_argument('--commit', action='store_true',
                        help='commit the integrated result (only if no conflicts '
                             'and tests pass)')
    parser.add_argument('--no-test', action='store_true',
                        help='skip the pytest + import validation steps')
    parser.add_argument('--list-ownership', action='store_true',
                        help='print the ownership map and exit')
    args = parser.parse_args()

    if args.list_ownership:
        print_ownership()
        return 0

    rules = load_ownership()

    if not ref_exists(args.base):
        raise SyncError(f'base ref does not exist: {args.base} '
                        f'(expected the fork snapshot commit)')
    if not ref_exists(args.theirs):
        raise SyncError(f'theirs ref does not exist: {args.theirs}')

    clean, dirty = worktree_clean(include_untracked=bool(args.commit))
    if not clean:
        raise SyncError(
            f'working tree is not clean: {dirty}\n'
            'Commit or stash your changes first, or use --dry-run.')

    start = current_branch()
    _, theirs_desc = run_git(['rev-parse', '--short', args.theirs])
    theirs_desc = theirs_desc.strip()
    branch = args.branch or f'upstream-sync/{theirs_desc.replace("/", "-")}'
    print(f'FetchJAV repo      : {REPO_ROOT}')
    print(f'base (fork snapshot): {args.base}')
    print(f'theirs (upstream)  : {args.theirs} ({theirs_desc})')
    print(f'starting from      : {start} @ HEAD={git_stdout(["rev-parse", "--short", "HEAD"]).strip()}')

    # Plan first (read-only). A branch is only created once we know we can apply.
    with tempfile.TemporaryDirectory(prefix='fetchjav_sync_') as tmpd:
        tmp = Path(tmpd)
        ops, reviews, noops = plan_sync(args.base, args.theirs, rules, tmp)

    print('\n== Plan ==')
    print(f'  files to update from upstream : {len([o for o in ops if o["action"] == "adopt"])}')
    print(f'  files to 3-way merge          : {len([o for o in ops if o["action"] == "merge"])}')
    print(f'  files unchanged (no-op)       : {len(noops)}')
    print(f'  files flagged for review      : {len(reviews)}')
    for op in ops:
        print(f'    {"adopt" if op["action"] == "adopt" else "merge"}  {op["path"]:<45} {op["note"]}')
    if reviews:
        detailed = [r for r in reviews if r[0] in ('conflict', 'review')]
        kept = [r for r in reviews if r[0] == 'keep']
        if kept:
            from collections import Counter
            grouped = Counter()
            for _, path, _ in kept:
                top = path.split('/')[0] if '/' in path else path
                grouped[top] += 1
            grouped_str = ', '.join(f'{n} in {k}/*' for k, n in grouped.most_common())
            print(f'\n  kept {len(kept)} files (upstream deleted them, or new '
                  f'upstream files blocked by untracked local copies) - '
                  f'{grouped_str}. Nothing to do.')
        if detailed:
            print('\n== MANUAL REVIEW REQUIRED ==')
            for sev, path, msg in detailed:
                print(f'  [{sev:<8}] {path}\n             {msg}')

    if args.dry_run:
        print('\n[--dry-run] no changes applied, no branch created.')
        return 1 if reviews else 0

    if ref_exists(branch):
        raise SyncError(
            f'branch already exists: {branch}\n'
            'Refusing to overwrite it. Inspect/delete it first, then rerun.')

    run_git(['switch', '-c', branch])
    try:
        apply_ops(ops, reviews, args.theirs, dry_run=False)

        if args.no_test:
            print('\n[--no-test] validation skipped.')
            validation = None
            import_ok = tests_ok = None
        else:
            import_ok = import_check()
            tests_ok = run_tests()
            validation = import_ok and tests_ok

        if args.commit:
            if reviews:
                print('\nNot committing: manual review / conflicts remain. '
                      'Resolve them, then commit manually.')
            elif validation is False:
                print('\nNot committing: validation failed.')
            else:
                summary = (f'sync with upstream {theirs_desc.strip()} '
                           f'({len(ops)} files updated, {len(noops)} unchanged)')
                run_git(['add', '-A'])
                run_git(['commit', '-m', summary])
                print(f'\nCommitted on branch {branch}: {summary}')

        print('\n== NEXT STEPS ==')
        if reviews:
            print('  Review the files flagged above; extract useful upstream '
                  'backend logic manually.')
        print('  Inspect changes: git status / git diff')
        print(f'  Test manually : run main.py and walk the FetchJAV checklist '
              f'(docs/REGRESSION_CHECKLIST.md)')
        print(f'  When satisfied, merge to main:')
        print(f'    git switch {start}')
        print(f'    git merge --no-ff {branch}')
        print(f'  Discard the branch with: git branch -D {branch}')
        return 1 if reviews else 0
    except BaseException:
        run_git(['switch', start], check=False)
        raise


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SyncError as exc:
        print(f'error: {exc}', file=sys.stderr)
        raise SystemExit(2)
