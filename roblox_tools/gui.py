"""GUI CustomTkinter. Toda atualização de widgets ocorre na thread principal."""

from datetime import datetime
from contextlib import nullcontext
from functools import partial
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox

import customtkinter as ctk

from . import __version__
from .fps import FpsSettingsManager
from .optimizer import optimizer_task
from .settings import FPS_CHOICES, SettingsStore
from .workers import FeatureWorker, application_lock, multi_instance_task
from multi_roblox import ToolError

BG = "#0B101B"
PANEL = "#131C2C"
MUTED = "#9AAAC3"
TEXT = "#EFF4FF"
ACCENT = "#8572F8"
GREEN = "#6EE7BA"
RED = "#FDA4AF"
FONT = "Segoe UI" if os.name == "nt" else "Helvetica"
MONO = "Consolas" if os.name == "nt" else "Courier"

FEATURES = {
    "multi_instance": (
        "01", "Multi-instância", "Abra o Roblox depois de ativar.\nMantenha este aplicativo aberto.",
    ),
    "optimizer": (
        "02", "Otimizador de desempenho", "Cliente em foco: prioridade Normal.\nClientes em segundo plano: prioridade Baixa.",
    ),
    "fps_unlock": (
        "03", "Desbloquear FPS", "Solicita um limite maior na próxima abertura.\nO efeito depende da versão do Roblox.",
    ),
}


class DesktopApp(ctk.CTk):
    def __init__(self, store, config, smoke_test=False):
        super().__init__()
        self.store = store
        self.config = config
        self.smoke_test = smoke_test
        self.events = Queue()
        self.workers = {}
        self.controls = {}
        self.variables = {}
        self.statuses = {}
        self.closing = False
        self.close_errors = []
        versions = Path(os.environ.get("LOCALAPPDATA", str(store.directory))) / "Roblox" / "Versions"
        self.fps = FpsSettingsManager(versions, store.directory)
        self.title("Multi Roblox")
        # Considera o fator de DPI do CustomTkinter para caber em telas menores.
        scale = self._get_window_scaling()
        width = min(1020, int(self.winfo_screenwidth() / scale) - 60)
        height = min(820, int(self.winfo_screenheight() / scale) - 90)
        self.geometry(f"{max(860, width)}x{max(560, height)}")
        self.minsize(860, 560)
        self.configure(fg_color=BG)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_content()
        self.protocol("WM_DELETE_WINDOW", self.begin_close)
        self.after(100, self._poll_events)
        self._save_config()
        if store.warning:
            self._log(store.warning, "warning")
        if smoke_test:
            # O smoke test não permite disparar recursos reais por um clique.
            for control in self.controls.values():
                control.configure(state="disabled")
            self.fps_choice.configure(state="disabled")
        else:
            self.after(150, self._restore_choices)

    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=218, corner_radius=0, fg_color="#101725")
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(4, weight=1)
        ctk.CTkLabel(side, text="M", width=56, height=56, corner_radius=16,
                     fg_color=ACCENT, text_color="white", font=(FONT, 32, "bold")).grid(
                         row=0, column=0, sticky="w", padx=25, pady=(32, 12))
        ctk.CTkLabel(side, text="MULTI ROBLOX", text_color=TEXT,
                     font=(FONT, 18, "bold")).grid(row=1, column=0, sticky="w", padx=25)
        ctk.CTkLabel(side, text="Mais controle para jogar.", text_color=MUTED,
                     font=(FONT, 12)).grid(row=2, column=0, sticky="w", padx=25, pady=(2, 32))
        ctk.CTkLabel(side, text="●   Painel de controle", text_color=GREEN,
                     fg_color="#1A2C32", corner_radius=10, height=42,
                     font=(FONT, 13)).grid(row=3, column=0, sticky="ew", padx=16)
        ctk.CTkButton(side, text="Pasta de configurações", command=self._open_settings,
                      fg_color="#202C40", hover_color="#2D3C54", height=36,
                      font=(FONT, 12)).grid(row=5, column=0, sticky="ew", padx=16, pady=12)
        ctk.CTkLabel(side, text=f"v{__version__}  ·  licença MIT\nCódigo aberto. Controle local.",
                     text_color=MUTED, justify="left", font=(FONT, 11)).grid(
                         row=6, column=0, sticky="w", padx=25, pady=(0, 25))

    def _build_content(self):
        content = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color="#2D3C54",
            scrollbar_button_hover_color="#405273",
        )
        content.grid(row=0, column=1, sticky="nsew", padx=30, pady=25)
        content.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(content, text="WINDOWS  /  DESKTOP", text_color=ACCENT,
                     font=(FONT, 11, "bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(content, text="Seu jogo. Seu controle.", text_color=TEXT,
                     font=(FONT, 29, "bold")).grid(row=1, column=0, sticky="w", pady=(3, 2))
        ctk.CTkLabel(content, text="Gerencie instâncias e distribua a prioridade de CPU.",
                     text_color=MUTED, font=(FONT, 13)).grid(row=2, column=0, sticky="w", pady=(0, 14))
        for row, (feature, (number, title, description)) in enumerate(FEATURES.items(), 3):
            card = ctk.CTkFrame(content, fg_color=PANEL, border_width=1,
                               border_color="#223048", corner_radius=16)
            card.grid(row=row, column=0, sticky="ew", pady=(0, 10))
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(card, text=number, width=34, height=34, corner_radius=10,
                         fg_color="#252841", text_color="#BAADFF", font=(FONT, 13, "bold")).grid(
                             row=0, column=0, sticky="n", padx=(17, 13), pady=18)
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.grid(row=0, column=1, sticky="ew", pady=(14, 12))
            ctk.CTkLabel(body, text=title, text_color=TEXT, font=(FONT, 17, "bold"),
                         anchor="w").pack(fill="x")
            ctk.CTkLabel(body, text=description, text_color=MUTED, justify="left",
                         anchor="w", font=(FONT, 12)).pack(fill="x", pady=(2, 3))
            status = ctk.CTkLabel(body, text="Desativado", text_color=MUTED,
                                  anchor="w", justify="left", wraplength=380, font=(FONT, 11))
            status.pack(fill="x")
            self.statuses[feature] = status
            variable = ctk.BooleanVar(value=getattr(self.config, feature))
            self.variables[feature] = variable
            switch = ctk.CTkSwitch(
                card, text="", variable=variable, width=46, switch_width=46,
                switch_height=25, progress_color=ACCENT, button_color=TEXT,
                command=partial(self._toggle, feature),
            )
            switch.grid(row=0, column=2, sticky="ne", padx=(12, 18), pady=21)
            self.controls[feature] = switch
            if feature == "fps_unlock":
                options = ctk.CTkFrame(body, fg_color="transparent")
                options.pack(fill="x", pady=(6, 0))
                self.fps_choice = ctk.CTkComboBox(
                    options, values=[str(value) for value in FPS_CHOICES], width=86,
                    height=28, state="readonly", command=self._change_fps,
                    fg_color="#1A263B", border_color="#344662", button_color="#344662",
                )
                self.fps_choice.set(str(self.config.fps_limit))
                self.fps_choice.pack(side="left")
                ctk.CTkLabel(options, text="FPS  ·  Mais FPS pode aumentar o uso de GPU.",
                             text_color=MUTED, font=(FONT, 11)).pack(side="left", padx=9)
        ctk.CTkLabel(content, text="ATIVIDADE", text_color=MUTED,
                     font=(FONT, 11, "bold")).grid(row=6, column=0, sticky="w", pady=(1, 5))
        self.log_view = ctk.CTkTextbox(content, height=100, fg_color="#0E1625",
                                      text_color=MUTED, corner_radius=12, font=(MONO, 11),
                                      wrap="word", state="disabled")
        self.log_view.grid(row=7, column=0, sticky="ew")
        self.footer = ctk.CTkLabel(content, text="Pronto  ·  Opções salvas automaticamente",
                                    text_color=GREEN, font=(FONT, 11), anchor="w")
        self.footer.grid(row=8, column=0, sticky="ew", pady=(8, 0))

    def _log(self, message, level="info"):
        getattr(logging.getLogger("multiroblox"), level)(message)
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.configure(state="normal")
        self.log_view.insert("end", f"{stamp}  {message}\n")
        # Mantém o painel e o log em disco com tamanho limitado.
        if int(self.log_view.index("end-1c").split(".")[0]) > 200:
            self.log_view.delete("1.0", "30.0")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def _save_config(self):
        try:
            self.store.save(self.config)
            self.footer.configure(text="Opções salvas automaticamente", text_color=GREEN)
        except OSError as error:
            self.footer.configure(text="Não foi possível salvar as opções", text_color=RED)
            self._log(f"Falha ao salvar config.json: {error}", "error")

    def _change_fps(self, value):
        self.config.fps_limit = int(value)
        self._save_config()

    def _restore_choices(self):
        if self.closing:
            return
        for feature in FEATURES:
            if getattr(self.config, feature):
                self._start(feature)
        if not self.config.fps_unlock and self.fps.journal.exists():
            self._start("fps_unlock", recover_only=True)

    def _start(self, feature, recover_only=False):
        if self.closing:
            return
        previous = self.workers.get(feature)
        if previous and previous.running:
            return
        self.controls[feature].configure(state="disabled")
        self.statuses[feature].configure(text="Restaurando..." if recover_only else "Ativando...", text_color=MUTED)
        if feature == "fps_unlock":
            self.fps_choice.configure(state="disabled")
            limit = self.config.fps_limit
            task = lambda stop, report: self.fps.run(stop, report, limit, recover_only)
        else:
            task = multi_instance_task if feature == "multi_instance" else optimizer_task
        worker = FeatureWorker(feature, task, self.events)
        self.workers[feature] = worker
        worker.start()

    def _toggle(self, feature):
        if self.closing:
            return
        enabled = self.variables[feature].get()
        setattr(self.config, feature, bool(enabled))
        self._save_config()
        if enabled:
            self._start(feature)
        else:
            self.controls[feature].configure(state="disabled")
            self.statuses[feature].configure(text="Restaurando e desligando...", text_color=MUTED)
            worker = self.workers.get(feature)
            if worker:
                worker.stop()

    def _drain_events(self):
        while True:
            try:
                event = self.events.get_nowait()
            except Empty:
                break
            feature, kind, message = event.feature, event.kind, event.message
            if kind == "ready":
                self.statuses[feature].configure(text="Ativo", text_color=GREEN)
                if not self.closing:
                    self.controls[feature].configure(state="normal")
                self._log(message)
            elif kind == "status":
                self.statuses[feature].configure(text=message, text_color=GREEN)
            elif kind == "error":
                self.statuses[feature].configure(text="Falha — consulte a atividade", text_color=RED)
                self._log(message, "error")
                if self.closing:
                    self.close_errors.append(message)
                else:
                    self.variables[feature].set(False)
                    setattr(self.config, feature, False)
                    self._save_config()
            elif kind == "stopped":
                if not self.closing:
                    self.controls[feature].configure(state="normal")
                    if feature == "fps_unlock":
                        self.fps_choice.configure(state="readonly")
                    # Mantém a indicação de erro até a próxima tentativa.
                    if self.statuses[feature].cget("text_color") != RED:
                        self.statuses[feature].configure(text="Desativado", text_color=MUTED)
                    self._log(f"{FEATURES[feature][1]}: tarefa encerrada.")
            else:
                self._log(message, "warning" if kind == "warning" else "info")

    def _poll_events(self):
        self._drain_events()
        self.after(100, self._poll_events)

    def _open_settings(self):
        try:
            self.store.directory.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.store.directory))
        except (OSError, AttributeError) as error:
            self._log(f"Não foi possível abrir a pasta: {error}", "error")

    def begin_close(self):
        if self.closing:
            return
        self.closing = True
        self.footer.configure(text="Encerrando e restaurando configurações...", text_color=MUTED)
        for control in self.controls.values():
            control.configure(state="disabled")
        self.fps_choice.configure(state="disabled")
        for worker in self.workers.values():
            worker.stop()
        # after mantém a interface responsiva enquanto os finally executam.
        self.after(100, self._finish_close)

    def _finish_close(self):
        self._drain_events()
        if any(worker.running for worker in self.workers.values()):
            self.after(100, self._finish_close)
            return
        self._drain_events()
        if self.close_errors:
            messagebox.showwarning(
                "Restauração pendente",
                "\n".join(self.close_errors) + "\nConsulte app.log. Reabra o aplicativo para tentar restaurar o FPS.",
                parent=self,
            )
        self.destroy()


def run_application(directory, smoke_test=False):
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    store = SettingsStore(directory)
    logger = logging.getLogger("multiroblox")
    handler = None
    try:
        with nullcontext() if smoke_test else application_lock():
            store.directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(store.directory / "app.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)
            config = store.load()
            app = DesktopApp(store, config, smoke_test=smoke_test)
            if smoke_test:
                app.after(500, app.begin_close)
            app.mainloop()
            return 0
    except (OSError, ValueError, ToolError) as error:
        logger.exception("Falha de inicialização")
        messagebox.showerror("Multi Roblox", str(error))
        return 1
    finally:
        if handler is not None:
            logger.removeHandler(handler)
            handler.close()
