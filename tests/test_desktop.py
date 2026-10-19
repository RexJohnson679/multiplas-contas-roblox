"""Testes das preferências, prioridades, threads e restauração de FPS."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
from queue import Queue
import tempfile
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import psutil

from roblox_tools.fps import FPS_KEY, FpsSettingsError, FpsSettingsManager
from roblox_tools.optimizer import ForegroundWindow, IDLE_PRIORITY, NORMAL_PRIORITY, PriorityOptimizer
from roblox_tools.settings import AppConfig, SettingsStore, read_object, write_object
from roblox_tools.workers import FeatureWorker, multi_instance_task


class SettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = SettingsStore(temporary.name)

    def test_choices_round_trip(self):
        config = AppConfig(True, True, True, 144)
        self.store.save(config)
        self.assertEqual(self.store.load(), config)

    def test_defaults_require_no_existing_file(self):
        self.assertEqual(self.store.load(), AppConfig())

    def test_invalid_configuration_is_preserved_before_reset(self):
        for content in ('{"optimizer": "false"}', '{"fps_limit": true}', 'broken', '[]'):
            with self.subTest(content=content):
                self.store.path.write_text(content)
                self.assertEqual(self.store.load(), AppConfig())
                self.assertTrue(self.store.warning)
                backups = list(self.store.directory.glob("config.invalid-*.json"))
                self.assertTrue(any(path.read_text() == content for path in backups))

    def test_failed_atomic_replace_preserves_existing_config(self):
        self.store.save(AppConfig())
        previous = self.store.path.read_bytes()
        with patch("roblox_tools.settings.os.replace", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.store.save(AppConfig(optimizer=True))
        self.assertEqual(self.store.path.read_bytes(), previous)
        self.assertFalse(list(self.store.directory.glob("*.tmp")))


class FakeProcess:
    def __init__(self, pid, name="RobloxPlayerBeta.exe", priority=0x8000, created=10):
        self.pid = pid
        self.info = {"name": name}
        self.priority = priority
        self.created = created
        self.alive = True
        self.denied = False
        self.changes = []

    def create_time(self):
        return self.created

    def is_running(self):
        return self.alive

    def nice(self, value=None):
        if self.denied:
            raise psutil.AccessDenied(self.pid)
        if not self.alive:
            raise psutil.NoSuchProcess(self.pid)
        if value is None:
            return self.priority
        self.priority = value
        self.changes.append(value)


class OptimizerTests(unittest.TestCase):
    def setUp(self):
        self.first = FakeProcess(10)
        self.second = FakeProcess(20)
        self.other = FakeProcess(30, name="browser.exe")
        self.focus = 10
        self.processes = [self.first, self.second, self.other]
        self.optimizer = PriorityOptimizer(lambda: self.focus, lambda: self.processes)

    def test_foreground_normal_background_low_then_swap(self):
        self.assertEqual(self.optimizer.tick()[:2], (2, 1))
        self.assertEqual(self.first.priority, NORMAL_PRIORITY)
        self.assertEqual(self.second.priority, IDLE_PRIORITY)
        self.assertFalse(self.other.changes)
        self.focus = 20
        self.optimizer.tick()
        self.assertEqual(self.first.priority, IDLE_PRIORITY)
        self.assertEqual(self.second.priority, NORMAL_PRIORITY)

    def test_other_application_in_focus_lowers_all_clients(self):
        self.focus = 30
        self.assertEqual(self.optimizer.tick()[:2], (2, 0))
        self.assertEqual(self.first.priority, IDLE_PRIORITY)
        self.assertEqual(self.second.priority, IDLE_PRIORITY)

    def test_restore_uses_each_original_priority(self):
        self.second.priority = NORMAL_PRIORITY
        self.optimizer.tick()
        self.optimizer.restore()
        self.assertEqual(self.first.priority, 0x8000)
        self.assertEqual(self.second.priority, NORMAL_PRIORITY)
        self.assertFalse(self.optimizer.originals)

    def test_exited_or_reused_pid_is_not_restored(self):
        self.optimizer.tick()
        self.first.created = 99
        self.second.alive = False
        self.optimizer.restore()
        self.assertEqual(self.first.changes, [NORMAL_PRIORITY])
        self.assertEqual(self.second.changes, [IDLE_PRIORITY])

    def test_access_denied_does_not_prevent_other_clients_from_updating(self):
        self.first.denied = True
        _, _, warning = self.optimizer.tick()
        self.assertIn("AccessDenied", warning)
        self.assertEqual(self.second.priority, IDLE_PRIORITY)
        self.assertNotIn((self.first.pid, self.first.created), self.optimizer.originals)

    def test_unchanged_priority_is_not_written_repeatedly(self):
        self.optimizer.tick()
        self.optimizer.tick()
        self.assertEqual(self.first.changes, [NORMAL_PRIORITY])

    def test_restore_denial_is_reported_and_record_retained(self):
        self.optimizer.tick()
        self.first.denied = True
        with self.assertRaisesRegex(RuntimeError, "restaurar"):
            self.optimizer.restore()
        self.assertEqual(len(self.optimizer.originals), 1)
        self.assertEqual(self.second.priority, 0x8000)

    def test_worker_restores_after_monitoring_failure(self):
        self.optimizer.tick()
        with patch.object(self.optimizer, "tick", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                self.optimizer.run(threading.Event(), lambda *args: None)
        self.assertEqual(self.first.priority, 0x8000)


class FpsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.versions = self.root / "Versions"
        self.state = self.root / "state"
        self.manager = FpsSettingsManager(self.versions, self.state)
        self.path = self.install("version-a")

    def install(self, name):
        directory = self.versions / name
        directory.mkdir(parents=True)
        (directory / "RobloxPlayerBeta.exe").touch()
        return directory / "ClientSettings" / "ClientAppSettings.json"

    def test_merge_and_restore_preserve_existing_flags(self):
        original = {"OtherFlag": True, FPS_KEY: "144"}
        write_object(self.path, original)
        self.manager.apply(240)
        self.assertEqual(read_object(self.path), {"OtherFlag": True, FPS_KEY: 240})
        self.manager.restore()
        self.assertEqual(read_object(self.path), original)

    def test_created_file_is_removed_after_restore(self):
        self.manager.apply(240)
        self.assertTrue(self.path.exists())
        self.manager.restore()
        self.assertFalse(self.path.exists())

    def test_external_edit_to_fps_is_preserved(self):
        self.manager.apply(240)
        write_object(self.path, {FPS_KEY: 165})
        self.assertEqual(self.manager.restore(), 1)
        self.assertEqual(read_object(self.path)[FPS_KEY], 165)

    def test_external_edit_to_other_flag_is_preserved(self):
        self.manager.apply(240)
        write_object(self.path, {FPS_KEY: 240, "NewFlag": "value"})
        self.manager.restore()
        self.assertEqual(read_object(self.path), {"NewFlag": "value"})

    def test_existing_empty_file_is_not_deleted(self):
        write_object(self.path, {})
        self.manager.apply(144)
        self.manager.restore()
        self.assertEqual(read_object(self.path), {})

    def test_journal_allows_recovery_after_restart(self):
        write_object(self.path, {FPS_KEY: None})
        self.manager.apply(240)
        restarted = FpsSettingsManager(self.versions, self.state)
        restarted.restore()
        self.assertEqual(read_object(self.path), {FPS_KEY: None})

    def test_new_version_is_discovered_without_rewriting_existing_override(self):
        self.manager.apply(240)
        write_object(self.path, {FPS_KEY: 120})
        second = self.install("version-b")
        self.assertEqual(self.manager.apply(240), 1)
        self.assertEqual(read_object(second)[FPS_KEY], 240)
        self.assertEqual(read_object(self.path)[FPS_KEY], 120)
        self.manager.restore()

    def test_invalid_client_json_is_not_overwritten(self):
        self.path.parent.mkdir()
        self.path.write_text("not JSON")
        with self.assertRaises(ValueError):
            self.manager.apply(240)
        self.assertEqual(self.path.read_text(), "not JSON")

    def test_failed_journal_write_never_changes_client(self):
        write_object(self.path, {"Untouched": True})
        with patch.object(self.manager, "_save_journal", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.manager.apply(240)
        self.assertEqual(read_object(self.path), {"Untouched": True})

    def test_partial_apply_failure_rolls_back_previous_installations(self):
        second = self.install("version-b")
        second.parent.mkdir()
        second.write_text("invalid JSON")
        with self.assertRaises(ValueError):
            self.manager.run(threading.Event(), lambda *args: None)
        self.assertFalse(self.path.exists())
        self.assertEqual(second.read_text(), "invalid JSON")

    def test_failed_restore_keeps_journal_for_future_retry(self):
        self.manager.apply(240)
        self.path.write_text("invalid JSON")
        with self.assertRaisesRegex(FpsSettingsError, "pendente"):
            self.manager.restore()
        self.assertTrue(read_object(self.manager.journal)["files"])
        write_object(self.path, {FPS_KEY: 240})
        self.manager.restore()
        self.assertFalse(self.path.exists())

    def test_outside_path_in_journal_is_rejected(self):
        unrelated = self.root / "untouched.json"
        write_object(unrelated, {FPS_KEY: 240})
        write_object(self.manager.journal, {"schema": 1, "files": {str(unrelated): {}}})
        with self.assertRaises(FpsSettingsError):
            self.manager.restore()
        self.assertEqual(read_object(unrelated), {FPS_KEY: 240})

    def test_absent_installation_is_reported(self):
        (self.path.parent.parent / "RobloxPlayerBeta.exe").unlink()
        with self.assertRaisesRegex(FpsSettingsError, "não encontrado"):
            self.manager.apply(240)


class WorkerTests(unittest.TestCase):
    def test_native_objects_are_acquired_and_released_on_same_worker_thread(self):
        records = []
        ready = threading.Event()

        @contextmanager
        def fake_hold(api, kind, name):
            records.append(("open", kind, threading.get_ident()))
            try:
                yield 123
            finally:
                records.append(("close", kind, threading.get_ident()))

        def task(stop, report):
            def notify(kind, message):
                report(kind, message)
                if kind == "ready":
                    ready.set()
            multi_instance_task(stop, notify)

        events = Queue()
        worker = FeatureWorker("multi_instance", task, events)
        with patch("roblox_tools.workers.load_kernel32"), patch("roblox_tools.workers.hold_object", fake_hold):
            worker.start()
            self.addCleanup(worker.stop)
            try:
                self.assertTrue(ready.wait(3))
                self.assertTrue(worker.running)
                self.assertEqual(len(records), 2)
                worker.stop()
                worker.thread.join(3)
                self.assertFalse(worker.running)
            finally:
                worker.stop()
                worker.thread.join(3)
        self.assertEqual([record[:2] for record in records], [
            ("open", "event"), ("open", "mutex"), ("close", "mutex"), ("close", "event")
        ])
        self.assertEqual(len({record[2] for record in records}), 1)
        self.assertNotEqual(records[0][2], threading.get_ident())
        self.assertEqual([events.get_nowait().kind for _ in range(2)], ["ready", "stopped"])

    def test_error_is_delivered_before_stopped_notification(self):
        def fail(stop, report):
            raise PermissionError("denied")

        events = Queue()
        worker = FeatureWorker("test", fail, events)
        worker.start()
        worker.thread.join(3)
        self.assertFalse(worker.running)
        self.assertEqual(events.get_nowait().kind, "error")
        self.assertEqual(events.get_nowait().kind, "stopped")


@unittest.skipUnless(os.name == "nt", "Requer as APIs de processos do Windows.")
class WindowsOptimizerTests(unittest.TestCase):
    def test_foreground_window_uses_native_pointer_and_pid_types(self):
        pid = ForegroundWindow().pid()
        self.assertIsInstance(pid, int)
        self.assertGreaterEqual(pid, 0)

    def test_real_process_priority_is_changed_and_restored(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            process = psutil.Process(child.pid)
            original = process.nice()
            # O filtro por nome já é testado separadamente; este caso valida a API.
            process.info = {"name": "RobloxPlayerBeta.exe"}
            focus = [child.pid]
            optimizer = PriorityOptimizer(lambda: focus[0], lambda: [process])
            try:
                optimizer.tick()
                self.assertEqual(process.nice(), NORMAL_PRIORITY)
                focus[0] = 0
                optimizer.tick()
                self.assertEqual(process.nice(), IDLE_PRIORITY)
            finally:
                optimizer.restore()
            self.assertEqual(process.nice(), original)
        finally:
            child.terminate()
            child.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
