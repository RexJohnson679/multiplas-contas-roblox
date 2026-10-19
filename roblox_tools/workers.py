"""Threads cooperativas: nenhuma delas acessa widgets da interface."""

from contextlib import ExitStack, contextmanager
import ctypes
from dataclasses import dataclass
import threading

from multi_roblox import (
    ERROR_ALREADY_EXISTS, EVENT_NAME, LEGACY_MUTEX_NAME, ToolError,
    hold_object, load_kernel32, native_error,
)


@contextmanager
def application_lock():
    """Uma GUI por sessão evita dois editores concorrentes do diário de FPS."""
    api = load_kernel32()
    name = "Local\\MultiRobloxDesktopControl"
    ctypes.set_last_error(0)
    # Este mutex mantém só a existência; não precisa adquirir propriedade.
    handle = api.CreateMutexW(None, False, name)
    code = ctypes.get_last_error()
    if not handle:
        raise native_error("CreateMutexW", name, code)
    try:
        if code == ERROR_ALREADY_EXISTS:
            raise ToolError("O Multi Roblox já está aberto nesta sessão. Use a janela existente.")
        yield
    finally:
        if not api.CloseHandle(handle):
            raise native_error("CloseHandle", name, ctypes.get_last_error())


@dataclass(frozen=True)
class WorkerEvent:
    feature: str
    kind: str
    message: str = ""


class FeatureWorker:
    def __init__(self, feature, task, events):
        self.feature = feature
        self.task = task
        self.events = events
        self.stop_event = threading.Event()
        self.thread = None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def report(self, kind, message=""):
        self.events.put(WorkerEvent(self.feature, kind, message))

    def start(self):
        if self.running:
            raise RuntimeError("A tarefa anterior ainda está encerrando.")
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run, name=f"multi-roblox-{self.feature}", daemon=False,
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self):
        try:
            self.task(self.stop_event, self.report)
        except Exception as error:
            self.report("error", str(error))
        finally:
            # O evento só chega depois dos blocos finally da tarefa.
            self.report("stopped")


def multi_instance_task(stop, report):
    # Criação, propriedade e liberação ocorrem nesta MESMA thread do Windows.
    api = load_kernel32()
    with ExitStack() as stack:
        stack.enter_context(hold_object(api, "event", EVENT_NAME))
        stack.enter_context(hold_object(api, "mutex", LEGACY_MUTEX_NAME))
        report("ready", "Multi-instância ativa. Agora você pode abrir os clientes.")
        stop.wait()
