"""Teste com widgets reais; os recursos do Windows são simulados neste caso."""

import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "GUI requer um display.")
class GuiTests(unittest.TestCase):
    def test_toggle_persists_choice_and_closing_waits_for_worker_cleanup(self):
        import customtkinter as ctk
        from roblox_tools import gui
        from roblox_tools.settings import SettingsStore

        ready = threading.Event()
        cleaned = threading.Event()

        def task(stop, report):
            report("ready", "Ativo no teste")
            ready.set()
            try:
                stop.wait()
            finally:
                cleaned.set()

        ctk.set_appearance_mode("dark")
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(directory)
            app = gui.DesktopApp(store, store.load(), smoke_test=True)
            closed = False
            try:
                with patch.object(gui, "multi_instance_task", task):
                    app.variables["multi_instance"].set(True)
                    app._toggle("multi_instance")
                    self.assertTrue(ready.wait(3))
                    app._drain_events()
                    app.update_idletasks()
                    self.assertEqual(app.statuses["multi_instance"].cget("text"), "Ativo")
                    self.assertTrue(store.load().multi_instance)
                    worker = app.workers["multi_instance"]
                    app._start("multi_instance")
                    self.assertIs(app.workers["multi_instance"], worker)
                    app.begin_close()
                    app._restore_choices()  # callback de inicialização atrasado
                    worker.thread.join(3)
                    self.assertTrue(cleaned.is_set())
                    self.assertFalse(worker.running)
                    app._finish_close()
                    closed = True
                    self.assertTrue(store.load().multi_instance)
                    self.assertFalse((Path(directory) / "fps-backup.json").exists())
            finally:
                for worker in app.workers.values():
                    worker.stop()
                    worker.thread.join(3)
                if not closed:
                    app.destroy()
