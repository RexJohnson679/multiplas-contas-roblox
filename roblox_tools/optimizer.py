"""Prioridade de CPU por foco; não lê nem modifica a memória do jogo."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import psutil

ROBLOX_PROCESS = "robloxplayerbeta.exe"
# Valores documentados de SetPriorityClass (Windows).
NORMAL_PRIORITY = 0x20
IDLE_PRIORITY = 0x40


class ForegroundWindow:
    def __init__(self):
        self.api = ctypes.WinDLL("user32.dll", use_last_error=True)
        self.api.GetForegroundWindow.argtypes = []
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        self.api.GetWindowThreadProcessId.restype = wintypes.DWORD

    def pid(self):
        # O HWND pode desaparecer durante uma troca de janela; PID zero é seguro.
        window = self.api.GetForegroundWindow()
        if not window:
            return 0
        pid = wintypes.DWORD()
        if not self.api.GetWindowThreadProcessId(window, ctypes.byref(pid)):
            return 0
        return pid.value


@dataclass
class OriginalPriority:
    process: object
    priority: int


class PriorityOptimizer:
    def __init__(self, foreground_pid, processes=None):
        self.foreground_pid = foreground_pid
        self.processes = processes or (lambda: psutil.process_iter(["name"]))
        self.originals = {}
        self.last_warning = ""

    def tick(self):
        foreground = self.foreground_pid()
        live = set()
        total, focused = 0, 0
        warnings = []
        for process in self.processes():
            try:
                name = process.info.get("name")
                if not name or name.casefold() != ROBLOX_PROCESS:
                    continue
                # PID + instante de criação evita restaurar um PID reutilizado.
                identity = (process.pid, process.create_time())
                live.add(identity)
                if not process.is_running():
                    continue
                total += 1
                active = process.pid == foreground
                focused += int(active)
                desired = NORMAL_PRIORITY if active else IDLE_PRIORITY
                current = process.nice()
                if current != desired:
                    # psutil usa OpenProcess/SetPriorityClass e valida PID reuse.
                    process.nice(desired)
                    if identity not in self.originals:
                        self.originals[identity] = OriginalPriority(process, current)
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError) as error:
                warnings.append(f"PID {process.pid}: prioridade indisponível ({type(error).__name__}).")
        for identity in list(self.originals):
            if identity not in live:
                record = self.originals[identity]
                try:
                    # Mantém registros inacessíveis para tentar restaurar depois.
                    if not record.process.is_running():
                        del self.originals[identity]
                except psutil.NoSuchProcess:
                    del self.originals[identity]
                except (psutil.AccessDenied, OSError):
                    pass
        return total, focused, " ".join(warnings)

    def restore(self):
        errors = []
        for identity, record in list(self.originals.items()):
            try:
                process = record.process
                if process.is_running() and process.create_time() == identity[1]:
                    process.nice(record.priority)
                del self.originals[identity]
            except psutil.NoSuchProcess:
                del self.originals[identity]
            except (psutil.AccessDenied, OSError) as error:
                errors.append(f"PID {identity[0]}: {type(error).__name__}")
        if errors:
            raise RuntimeError("Não foi possível restaurar todas as prioridades: " + "; ".join(errors))

    def run(self, stop, report):
        previous = None
        try:
            while not stop.is_set():
                total, focused, warning = self.tick()
                if previous is None:
                    report("ready", "Otimizador ativo: Normal em foco, Baixa em segundo plano.")
                summary = f"{total} cliente(s) · {focused} em foco"
                if summary != previous:
                    report("status", summary)
                    previous = summary
                if warning and warning != self.last_warning:
                    report("warning", warning)
                self.last_warning = warning
                if stop.wait(0.75):
                    break
        finally:
            self.restore()


def optimizer_task(stop, report):
    foreground = ForegroundWindow()
    PriorityOptimizer(foreground.pid).run(stop, report)
