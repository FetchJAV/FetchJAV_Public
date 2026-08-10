#!/usr/bin/env python
# coding: utf-8
"""Unit tests for the Hot Reloading module (hot_reload.py)."""

import os
import sys
import time
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import hot_reload
from args import get_parser


class TestFileWatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initial_scan(self):
        watcher = hot_reload.FileWatcher(self.root)
        self.assertEqual(watcher._snapshot, {})

        py_file = os.path.join(self.root, "test.py")
        with open(py_file, "w", encoding="utf-8") as f:
            f.write("# hello")

        watcher.reset()
        self.assertIn(py_file, watcher._snapshot)

    def test_file_modification_detection(self):
        py_file = os.path.join(self.root, "app.py")
        with open(py_file, "w", encoding="utf-8") as f:
            f.write("x = 1")

        watcher = hot_reload.FileWatcher(self.root)
        self.assertEqual(watcher.check_changed(), [])

        # Sleep slightly to ensure mtime timestamp differs
        time.sleep(0.05)
        with open(py_file, "w", encoding="utf-8") as f:
            f.write("x = 2")

        changed = watcher.check_changed()
        self.assertIn(py_file, changed)

    def test_file_addition_and_deletion(self):
        watcher = hot_reload.FileWatcher(self.root)
        self.assertEqual(watcher.check_changed(), [])

        new_file = os.path.join(self.root, "new_module.py")
        with open(new_file, "w", encoding="utf-8") as f:
            f.write("# new file")

        changed = watcher.check_changed()
        self.assertIn(new_file, changed)

        # Delete file
        os.remove(new_file)
        changed_after_delete = watcher.check_changed()
        self.assertIn(new_file, changed_after_delete)

    def test_ignore_patterns(self):
        venv_dir = os.path.join(self.root, ".venv")
        os.makedirs(venv_dir, exist_ok=True)
        ignored_py = os.path.join(venv_dir, "lib.py")
        with open(ignored_py, "w", encoding="utf-8") as f:
            f.write("# ignored")

        tmp_file = os.path.join(self.root, "test.tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write("temp data")

        valid_py = os.path.join(self.root, "valid.py")
        with open(valid_py, "w", encoding="utf-8") as f:
            f.write("# valid")

        watcher = hot_reload.FileWatcher(self.root)
        snapshot = watcher.scan()

        self.assertIn(valid_py, snapshot)
        self.assertNotIn(ignored_py, snapshot)
        self.assertNotIn(tmp_file, snapshot)


class TestHotReloadState(unittest.TestCase):
    def test_is_hot_reload_active(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(hot_reload.is_hot_reload_active())
            self.assertFalse(hot_reload.is_child_process())

        with patch.dict(os.environ, {hot_reload.HOT_RELOAD_ENV_VAR: "1"}):
            self.assertTrue(hot_reload.is_hot_reload_active())

        with patch.dict(os.environ, {hot_reload.HOT_RELOAD_CHILD_VAR: "1"}):
            self.assertTrue(hot_reload.is_hot_reload_active())
            self.assertTrue(hot_reload.is_child_process())


class TestCliArgs(unittest.TestCase):
    def test_hot_reload_flag(self):
        parser = get_parser()

        args1 = parser.parse_args([])
        self.assertFalse(args1.hot_reload)
        self.assertEqual(args1.watch_interval, 1.0)

        args2 = parser.parse_args(["--hot-reload"])
        self.assertTrue(args2.hot_reload)

        args3 = parser.parse_args(["-hr", "--watch-interval", "0.5"])
        self.assertTrue(args3.hot_reload)
        self.assertEqual(args3.watch_interval, 0.5)

        args4 = parser.parse_args(["--watch"])
        self.assertTrue(args4.hot_reload)


class TestTriggerHotReload(unittest.TestCase):
    def test_trigger_in_child_process(self):
        mock_app = MagicMock()
        with patch.dict(os.environ, {hot_reload.HOT_RELOAD_CHILD_VAR: "1"}):
            with self.assertRaises(SystemExit) as cm:
                hot_reload.trigger_hot_reload(mock_app)
            self.assertEqual(cm.exception.code, hot_reload.HOT_RELOAD_EXIT_CODE)
            mock_app._on_close.assert_called_once()

    @patch("subprocess.Popen")
    def test_trigger_standalone_nt(self, mock_popen):
        mock_app = MagicMock()
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.name", "nt"):
                with self.assertRaises(SystemExit) as cm:
                    hot_reload.trigger_hot_reload(mock_app)
                self.assertEqual(cm.exception.code, 0)
                mock_app._on_close.assert_called_once()
                mock_popen.assert_called_once()


class TestDynamicReloader(unittest.TestCase):
    @patch("importlib.reload")
    def test_reload_locales(self, mock_reload):
        self.assertTrue(hot_reload.reload_locales())
        mock_reload.assert_called_once()

    @patch("importlib.reload")
    def test_reload_theme(self, mock_reload):
        self.assertTrue(hot_reload.reload_theme())
        mock_reload.assert_called_once()


class TestSupervisor(unittest.TestCase):
    @patch("subprocess.Popen")
    def test_supervisor_child_exit_code_restart(self, mock_popen):
        mock_proc = MagicMock()
        # First poll returns exit code 42 (requested reload), second poll returns 0 (normal exit)
        mock_proc.poll.side_effect = [hot_reload.HOT_RELOAD_EXIT_CODE, 0]
        mock_popen.return_value = mock_proc

        temp_dir = tempfile.TemporaryDirectory()
        try:
            ret = hot_reload.start_reloader_supervisor(
                target_args=["--nogui"],
                watch_dir=temp_dir.name,
                poll_interval=0.01,
                max_restarts=2,
            )
            self.assertEqual(ret, 0)
            self.assertEqual(mock_popen.call_count, 2)
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
