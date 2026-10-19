"""Testes de ciclo de vida e falhas nativas; não requerem Roblox."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import ctypes
from ctypes import wintypes
import io
import os
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import multi_roblox as app


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.code = 0
        self.api = Mock()
        self.api.CreateEventW.side_effect = self.result(101)
        self.api.CreateMutexW.side_effect = self.result(102)
        self.api.ReleaseMutex.return_value = True
        self.api.CloseHandle.return_value = True
        # Em Linux estas funções de ctypes não existem; simulação explícita.
        for name, replacement in (
            ("set_last_error", self.set_error),
            ("get_last_error", lambda: self.code),
            ("FormatError", lambda code: f"mensagem do sistema {code}"),
        ):
            patcher = patch.object(ctypes, name, replacement, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_error(self, code):
        self.code = code

    def result(self, handle, code=0):
        def create(*args):
            self.code = code
            return handle
        return create

    def run_main(self, args=(), wait=KeyboardInterrupt):
        out, err = io.StringIO(), io.StringIO()
        signals = SimpleNamespace(SIGBREAK=21, default_int_handler=Mock(), signal=Mock())
        with (
            patch.object(app, "os", SimpleNamespace(name="nt")),
            patch.object(app, "signal", signals),
            patch.object(app, "load_kernel32", return_value=self.api),
            patch.object(app.time, "sleep", side_effect=wait),
            redirect_stdout(out), redirect_stderr(err),
        ):
            status = app.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def test_event_is_retained_until_context_exit(self):
        with app.hold_object(self.api, "event", app.EVENT_NAME) as handle:
            self.assertEqual(handle, 101)
            self.api.CloseHandle.assert_not_called()
        self.api.CloseHandle.assert_called_once_with(101)
        self.api.ReleaseMutex.assert_not_called()

    def test_preexisting_objects_are_closed_without_acquiring_or_releasing(self):
        for kind, call in (("event", "CreateEventW"), ("mutex", "CreateMutexW")):
            with self.subTest(kind=kind):
                self.api.reset_mock()
                getattr(self.api, call).side_effect = self.result(123, 183)
                with self.assertRaisesRegex(app.ToolError, "183"):
                    with app.hold_object(self.api, kind, "existing"):
                        self.fail("Objeto preexistente não pode ser aceito.")
                self.api.CloseHandle.assert_called_once_with(123)
                self.api.ReleaseMutex.assert_not_called()

    def test_failed_creation_reports_error_without_closing_null(self):
        for kind, call in (("event", "CreateEventW"), ("mutex", "CreateMutexW")):
            for code in (5, 6, 8):
                with self.subTest(kind=kind, code=code):
                    self.api.reset_mock()
                    getattr(self.api, call).side_effect = self.result(None, code)
                    with self.assertRaisesRegex(app.ToolError, f"Win32 {code}"):
                        with app.hold_object(self.api, kind, "blocked"):
                            self.fail("Criação falhou; não deve entrar no contexto.")
                    self.api.CloseHandle.assert_not_called()

    def test_mutex_is_released_before_handle_is_closed(self):
        with app.hold_object(self.api, "mutex", "owned"):
            self.api.ReleaseMutex.assert_not_called()
        calls = [call[0] for call in self.api.mock_calls]
        self.assertLess(calls.index("ReleaseMutex"), calls.index("CloseHandle"))
        self.api.ReleaseMutex.assert_called_once_with(102)

    def test_handle_is_still_closed_when_release_fails(self):
        self.api.ReleaseMutex.side_effect = self.result(False, 288)
        with self.assertRaisesRegex(app.ToolError, "ReleaseMutex.*288"):
            with app.hold_object(self.api, "mutex", "owned"):
                pass
        self.api.CloseHandle.assert_called_once_with(102)

    def test_failed_close_is_reported(self):
        self.api.CloseHandle.side_effect = self.result(False, 6)
        with self.assertRaisesRegex(app.ToolError, "CloseHandle.*6"):
            with app.hold_object(self.api, "event", "test"):
                pass

    def test_later_creation_failure_closes_earlier_event(self):
        self.api.CreateMutexW.side_effect = self.result(None, 5)
        status, out, err = self.run_main(["--legacy-mutex"])
        self.assertEqual(status, 1)
        self.assertNotIn("Evento retido", out)
        self.assertIn("Win32 5", err)
        self.api.CloseHandle.assert_called_once_with(101)

    def test_keep_alive_retains_both_handles_until_interrupted(self):
        sleeps = []

        def wait(seconds):
            sleeps.append(seconds)
            self.api.CloseHandle.assert_not_called()
            self.api.ReleaseMutex.assert_not_called()
            if len(sleeps) == 3:
                raise KeyboardInterrupt

        status, out, err = self.run_main(["--legacy-mutex"], wait)
        self.assertEqual(status, 0)
        self.assertEqual(sleeps, [1, 1, 1])
        self.assertIn("handles locais liberados", out)
        self.assertEqual(err, "")
        self.assertEqual(self.api.CloseHandle.call_args_list[0].args, (102,))
        self.assertEqual(self.api.CloseHandle.call_args_list[1].args, (101,))

    def test_default_mode_does_not_create_mutex(self):
        status, _, err = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(err, "")
        self.api.CreateMutexW.assert_not_called()

    def test_unsupported_platform_has_clear_exit_status(self):
        err = io.StringIO()
        with patch.object(app, "os", SimpleNamespace(name="posix")), redirect_stderr(err):
            self.assertEqual(app.main([]), 2)
        self.assertIn("Windows", err.getvalue())


@unittest.skipUnless(os.name == "nt", "Requer o kernel real do Windows.")
class WindowsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.api = app.load_kernel32()
        self.name = "MultiRobloxTest_" + uuid.uuid4().hex
        for method in (self.api.OpenEventW, self.api.OpenMutexW):
            method.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            method.restype = wintypes.HANDLE
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.SetEvent.argtypes = [wintypes.HANDLE]
        self.api.SetEvent.restype = wintypes.BOOL
        self.api.GetHandleInformation.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)
        ]
        self.api.GetHandleInformation.restype = wintypes.BOOL

    def assert_missing(self, kind):
        opener = self.api.OpenEventW if kind == "event" else self.api.OpenMutexW
        handle = opener(0x00100000, False, self.name)  # SYNCHRONIZE
        code = ctypes.get_last_error()
        if handle:
            self.api.CloseHandle(handle)
        self.assertFalse(handle)
        self.assertEqual(code, 2)  # ERROR_FILE_NOT_FOUND

    def test_event_has_manual_reset_state_and_noninheritable_handle(self):
        with app.hold_object(self.api, "event", self.name) as handle:
            flags = wintypes.DWORD()
            self.assertTrue(self.api.GetHandleInformation(handle, ctypes.byref(flags)))
            self.assertEqual(flags.value & 1, 0)  # HANDLE_FLAG_INHERIT
            self.assertEqual(self.api.WaitForSingleObject(handle, 0), 258)  # WAIT_TIMEOUT
            self.assertTrue(self.api.SetEvent(handle))
            self.assertEqual(self.api.WaitForSingleObject(handle, 0), 0)
            self.assertEqual(self.api.WaitForSingleObject(handle, 0), 0)
        self.assert_missing("event")

    def test_event_is_visible_to_another_process_only_while_retained(self):
        child = """
import ctypes, sys
from ctypes import wintypes
api = ctypes.WinDLL('kernel32.dll', use_last_error=True)
api.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
api.OpenEventW.restype = wintypes.HANDLE
api.CloseHandle.argtypes = [wintypes.HANDLE]
api.CloseHandle.restype = wintypes.BOOL
handle = api.OpenEventW(0x00100000, False, sys.argv[1])
code = ctypes.get_last_error()
if not handle:
    sys.exit(2 if code == 2 else 3)
sys.exit(0 if api.CloseHandle(handle) else 4)
"""

        def probe():
            return subprocess.run(
                [sys.executable, "-c", child, self.name],
                capture_output=True, text=True, timeout=15,
            )

        with app.hold_object(self.api, "event", self.name):
            result = probe()
            self.assertEqual(result.returncode, 0, result.stderr)
        result = probe()
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_rejecting_existing_event_preserves_original_handle(self):
        with app.hold_object(self.api, "event", self.name) as original:
            with self.assertRaisesRegex(app.ToolError, "183"):
                with app.hold_object(self.api, "event", self.name):
                    self.fail("Evento já existente aceito.")
            self.assertTrue(self.api.SetEvent(original))
        self.assert_missing("event")

    def test_event_and_mutex_names_cannot_collide(self):
        with app.hold_object(self.api, "event", self.name):
            with self.assertRaisesRegex(app.ToolError, "Win32 6"):
                with app.hold_object(self.api, "mutex", self.name):
                    self.fail("Tipos diferentes aceitaram o mesmo nome.")
        self.assert_missing("event")

    def test_rejecting_existing_mutex_does_not_release_its_owner(self):
        with app.hold_object(self.api, "mutex", self.name) as original:
            with self.assertRaisesRegex(app.ToolError, "183"):
                with app.hold_object(self.api, "mutex", self.name):
                    self.fail("Mutex já existente aceito.")
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(self.api.WaitForSingleObject, original, 0).result(5)
            self.assertEqual(result, 258)
        self.assert_missing("mutex")

    def test_mutex_is_owned_until_cleanup_then_available_to_another_thread(self):
        secondary = None
        try:
            with app.hold_object(self.api, "mutex", self.name):
                secondary = self.api.OpenMutexW(0x00100001, False, self.name)
                self.assertTrue(secondary)  # SYNCHRONIZE | MUTEX_MODIFY_STATE
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(self.api.WaitForSingleObject, secondary, 0).result(5)
                self.assertEqual(result, 258)

            def acquire_and_release():
                result = self.api.WaitForSingleObject(secondary, 0)
                if result in (0, 128):  # WAIT_OBJECT_0 / WAIT_ABANDONED
                    if not self.api.ReleaseMutex(secondary):
                        raise ctypes.WinError(ctypes.get_last_error())
                return result

            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(acquire_and_release).result(5), 0)
        finally:
            if secondary:
                self.api.CloseHandle(secondary)
        self.assert_missing("mutex")


if __name__ == "__main__":
    unittest.main()
