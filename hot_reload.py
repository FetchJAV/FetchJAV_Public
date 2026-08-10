#!/usr/bin/env python
# coding: utf-8
"""
Hot Reloading framework for JableTV / MissAV Downloader GUI.
Provides file system watching, terminal keyboard controls (r / Ctrl+R / q),
and subprocess reloader supervisor.
"""

import importlib
import os
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

HOT_RELOAD_ENV_VAR = "JABLE_HOT_RELOAD"
HOT_RELOAD_CHILD_VAR = "JABLE_HOT_RELOAD_CHILD"
HOT_RELOAD_EXIT_CODE = 42

DEFAULT_WATCH_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".ini", ".css"}
DEFAULT_IGNORE_PATTERNS = {
    "__pycache__", ".venv", ".git", ".pytest_cache", ".vscode",
    "build_tmp", "download", "img", "third_party_licenses",
    "download_queue.csv", "cf_overrides.json", "ui_prefs.json",
    ".tmp", ".log"
}


class FileWatcher:
    """Watches a directory tree for file modifications, additions, or deletions."""

    def __init__(
        self,
        root_dir: str,
        extensions: Optional[Set[str]] = None,
        ignore_patterns: Optional[Set[str]] = None,
    ):
        self.root_dir = os.path.abspath(root_dir)
        self.extensions = extensions if extensions is not None else DEFAULT_WATCH_EXTENSIONS
        self.ignore_patterns = ignore_patterns if ignore_patterns is not None else DEFAULT_IGNORE_PATTERNS
        self._snapshot: Dict[str, Tuple[float, int]] = {}
        self.reset()

    def _should_ignore(self, path: str) -> bool:
        norm_path = os.path.normpath(path)
        parts = norm_path.split(os.sep)
        for part in parts:
            if part in self.ignore_patterns:
                return True
            for pat in self.ignore_patterns:
                if pat.startswith("*") and part.endswith(pat[1:]):
                    return True
                if pat.endswith("*") and part.startswith(pat[:-1]):
                    return True
        filename = os.path.basename(path)
        if any(filename.endswith(ext) for ext in [".tmp", ".log", ".csv.tmp"]):
            return True
        return False

    def scan(self) -> Dict[str, Tuple[float, int]]:
        snapshot = {}
        if not os.path.exists(self.root_dir):
            return snapshot
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not self._should_ignore(os.path.join(root, d))]
            for file in files:
                filepath = os.path.join(root, file)
                if self._should_ignore(filepath):
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext in self.extensions:
                    try:
                        stat = os.stat(filepath)
                        snapshot[filepath] = (stat.st_mtime, stat.st_size)
                    except OSError:
                        pass
        return snapshot

    def reset(self):
        self._snapshot = self.scan()

    def check_changed(self) -> List[str]:
        new_snapshot = self.scan()
        changed_files = []

        for path, info in new_snapshot.items():
            if path not in self._snapshot or self._snapshot[path] != info:
                changed_files.append(path)

        for path in self._snapshot:
            if path not in new_snapshot:
                changed_files.append(path)

        self._snapshot = new_snapshot
        return changed_files


class TerminalInputListener(threading.Thread):
    """Monitors terminal keyboard input for manual restart (r / Ctrl+R) or quit (q)."""

    def __init__(self, on_restart: Callable[[], None], on_quit: Callable[[], None]):
        super().__init__(daemon=True)
        self.on_restart = on_restart
        self.on_quit = on_quit
        self.running = True

    def run(self):
        if os.name == 'nt':
            try:
                import msvcrt
                while self.running:
                    if msvcrt.kbhit():
                        try:
                            ch = msvcrt.getwch()
                        except Exception:
                            try:
                                ch = msvcrt.getch().decode('utf-8', errors='ignore')
                            except Exception:
                                ch = ''
                        if ch in ('r', 'R', '\x12'):  # 'r', 'R', or Ctrl+R (\x12)
                            self.on_restart()
                        elif ch in ('q', 'Q', '\x03'):  # 'q', 'Q', or Ctrl+C (\x03)
                            self.on_quit()
                            break
                    time.sleep(0.1)
                return
            except Exception:
                pass

        try:
            while self.running:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd = line.strip().lower()
                if cmd in ('r', 'ctrl+r'):
                    self.on_restart()
                elif cmd == 'q':
                    self.on_quit()
                    break
        except Exception:
            pass


def is_hot_reload_active() -> bool:
    """Return True if application is running under hot reload supervisor or hot reload env is set."""
    return os.environ.get(HOT_RELOAD_ENV_VAR) == "1" or os.environ.get(HOT_RELOAD_CHILD_VAR) == "1"


def is_child_process() -> bool:
    """Return True if current process is a worker spawned by the hot reload supervisor."""
    return os.environ.get(HOT_RELOAD_CHILD_VAR) == "1"


def trigger_hot_reload(app_instance=None):
    """
    Trigger application restart / hot reload.
    Gracefully cleans up the app_instance if provided, then signals supervisor or re-executes process.
    """
    if app_instance is not None and hasattr(app_instance, "_on_close"):
        try:
            app_instance._on_close()
        except Exception:
            pass

    if is_child_process():
        sys.exit(HOT_RELOAD_EXIT_CODE)
    else:
        args = [sys.executable] + sys.argv
        if os.name == 'nt':
            subprocess.Popen(args)
            sys.exit(0)
        else:
            os.execv(sys.executable, args)


def reload_locales():
    """Dynamically reloads locales module."""
    try:
        import locales
        importlib.reload(locales)
        return True
    except Exception as e:
        print(f"[HotReload] Failed to reload locales: {e}")
        return False


def reload_theme():
    """Dynamically reloads ui_theme module."""
    try:
        import ui_theme
        importlib.reload(ui_theme)
        return True
    except Exception as e:
        print(f"[HotReload] Failed to reload ui_theme: {e}")
        return False


def start_reloader_supervisor(
    target_args: Optional[List[str]] = None,
    watch_dir: Optional[str] = None,
    poll_interval: float = 1.0,
    max_restarts: Optional[int] = None,
    enable_terminal_listener: bool = True,
) -> int:
    """
    Starts supervisor process loop to monitor source files and restart target process on change.
    Listens for terminal keyboard shortcuts (r / Ctrl+R to restart, q to quit).
    """
    if watch_dir is None:
        watch_dir = os.path.dirname(os.path.abspath(sys.argv[0])) or os.getcwd()

    if target_args is None:
        target_args = sys.argv[:]

    watcher = FileWatcher(watch_dir)
    env = dict(os.environ)
    env[HOT_RELOAD_ENV_VAR] = "1"
    env[HOT_RELOAD_CHILD_VAR] = "1"

    cmd = [sys.executable] + target_args
    print(f"[HotReload] Supervisor started. Watching directory: {watch_dir}")
    print(f"[HotReload] Terminal Controls: Press [r / Ctrl+R] to restart | Press [q] to quit")
    print(f"[HotReload] Command: {' '.join(cmd)}")

    manual_restart_event = threading.Event()
    manual_quit_event = threading.Event()

    input_listener = None
    if enable_terminal_listener:
        input_listener = TerminalInputListener(
            on_restart=lambda: manual_restart_event.set(),
            on_quit=lambda: manual_quit_event.set(),
        )
        input_listener.start()

    restarts = 0
    process = None
    try:
        process = subprocess.Popen(cmd, env=env)
        while True:
            time.sleep(max(0.1, poll_interval))

            # Check manual terminal quit request
            if manual_quit_event.is_set():
                print("[HotReload] Terminal quit requested. Terminating process...")
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                return 0

            # Check manual terminal restart request
            if manual_restart_event.is_set():
                manual_restart_event.clear()
                restarts += 1
                if max_restarts is not None and restarts >= max_restarts:
                    print(f"[HotReload] Reached max restarts ({max_restarts}). Exiting.")
                    if process and process.poll() is None:
                        process.terminate()
                    return 0

                print("[HotReload] Terminal restart requested. Restarting target...")
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

                process = subprocess.Popen(cmd, env=env)
                watcher.reset()
                continue

            # Check if child process exited on its own
            ret_code = process.poll()
            if ret_code is not None:
                if ret_code == HOT_RELOAD_EXIT_CODE:
                    restarts += 1
                    if max_restarts is not None and restarts >= max_restarts:
                        print(f"[HotReload] Reached max restarts ({max_restarts}). Exiting.")
                        return ret_code
                    print("[HotReload] Child process requested hot reload restart...")
                    process = subprocess.Popen(cmd, env=env)
                    watcher.reset()
                    continue
                else:
                    print(f"[HotReload] Child process exited with code {ret_code}.")
                    return ret_code

            # Check for file changes
            changed = watcher.check_changed()
            if changed:
                restarts += 1
                if max_restarts is not None and restarts >= max_restarts:
                    print(f"[HotReload] Reached max restarts ({max_restarts}). Exiting.")
                    if process and process.poll() is None:
                        process.terminate()
                    return 0

                rel_paths = [os.path.relpath(p, watch_dir) for p in changed[:3]]
                summary = ", ".join(rel_paths)
                if len(changed) > 3:
                    summary += f" and {len(changed) - 3} more"
                print(f"[HotReload] Change detected in: {summary}. Restarting target...")

                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

                process = subprocess.Popen(cmd, env=env)
                watcher.reset()
    except KeyboardInterrupt:
        print("\n[HotReload] Supervisor interrupted by user. Terminating child process...")
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        return 0
    finally:
        if input_listener:
            input_listener.running = False
