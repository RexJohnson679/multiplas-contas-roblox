"""GUI CustomTkinter. Toda atualização de widgets ocorre na thread principal."""

from datetime import datetime
from contextlib import nullcontext
from functools import partial
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from queue import Empty, Queue
from tkinter import Canvas, messagebox

import customtkinter as ctk

from . import __version__
from .fps import FpsSettingsManager
from .optimizer import optimizer_task
from .settings import FPS_CHOICES, SettingsStore
from .workers import FeatureWorker, application_lock, multi_instance_task
from multi_roblox import ToolError

BG = "#181818"
PANEL = "#232326"
BORDER = "#343438"
MUTED = "#9B9BA6"
TEXT = "#F5F5F7"
ACCENT = "#A78BFA"
PURPLE = "#8255E8"
GREEN = "#70D6A5"
RED = "#FF9CA7"
FONT = "Segoe UI" if os.name == "nt" else "Helvetica"
MONO = "Consolas" if os.name == "nt" else "Courier"

FEATURES = {
    "multi_instance": (
        "layers", "Multi-instância", "Ative antes de abrir o Roblox.",
    ),
    "optimizer": (
        "cpu", "Anti-lag", "Prioridade de CPU por janela ativa.",
    ),
    "fps_unlock": (
        "display", "FPS", "Aplicado ao reabrir o jogo.",
    ),
}


class IconBadge(ctk.CTkFrame):
    """Ícones vetoriais locais, sem fontes de símbolos ou imagens externas."""

    def __init__(self, parent, icon, size=44, background="#32283F", color=ACCENT):
        super().__init__(parent, width=size, height=size, fg_color=background, corner_radius=12)
        self.icon = icon
        self.color = color
        self.canvas = Canvas(self, background=background, highlightthickness=0, borderwidth=0)
        self.canvas.place(relx=0.5, rely=0.5, relwidth=0.62, relheight=0.62, anchor="center")
        self.canvas.bind("<Configure>", self._render_icon)

    def _render_icon(self, event):
        self.canvas.delete("all")
        scale = min(event.width, event.height) / 32
        stroke = max(1.5, 1.8 * scale)

        def line(*points):
            self.canvas.create_line(*[point * scale for point in points], fill=self.color,
                                    width=stroke, capstyle="round", joinstyle="round")

        def rectangle(x1, y1, x2, y2):
            self.canvas.create_rectangle(x1 * scale, y1 * scale, x2 * scale, y2 * scale,
                                         outline=self.color, width=stroke)

        if self.icon == "layers":
            line(7, 21, 3, 21, 3, 4, 23, 4, 23, 8)
            rectangle(9, 10, 29, 27)
            line(9, 15, 29, 15)
        elif self.icon == "cpu":
            rectangle(8, 8, 24, 24)
            rectangle(12, 12, 20, 20)
            for offset in (11, 16, 21):
                line(offset, 3, offset, 7)
                line(offset, 25, offset, 29)
                line(3, offset, 7, offset)
                line(25, offset, 29, offset)
        else:
            rectangle(3, 5, 29, 23)
            line(16, 23, 16, 28)
            line(10, 28, 22, 28)
            line(12, 16, 16, 12, 20, 16)
            line(16, 12, 16, 20)


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
        self.cards = {}
        self.active_features = set()
        self.activity_visible = False
        self.closing = False
        self.close_errors = []
        versions = Path(os.environ.get("LOCALAPPDATA", str(store.directory))) / "Roblox" / "Versions"
        self.fps = FpsSettingsManager(versions, store.directory)
        self.title("Multi Roblox")
        # Considera o fator de DPI do CustomTkinter para caber em telas menores.
        scale = self._get_window_scaling()
        width = min(1120, int(self.winfo_screenwidth() / scale) - 60)
        height = min(790, int(self.winfo_screenheight() / scale) - 90)
        self.geometry(f"{max(900, width)}x{max(600, height)}")
        self.minsize(900, 600)
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
        side = ctk.CTkFrame(self, width=88, corner_radius=0, fg_color="#111113")
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(3, weight=1)
        IconBadge(side, "layers", size=48, background=PURPLE, color=TEXT).grid(
            row=0, column=0, pady=(30, 8))
        ctk.CTkLabel(side, text="MR", font=(FONT, 11, "bold"), text_color=MUTED).grid(
            row=1, column=0)
        ctk.CTkFrame(side, height=1, fg_color="#2B2B30").grid(
            row=2, column=0, sticky="ew", padx=22, pady=24)
        ctk.CTkButton(
            side, text="Pasta", command=self._open_settings, width=64, height=38,
            corner_radius=11, fg_color="#232326", hover_color="#333338",
            text_color=MUTED, font=(FONT, 12),
        ).grid(row=4, column=0, padx=12, pady=(0, 14))
        ctk.CTkLabel(side, text=f"v{__version__}", text_color="#72727C", font=(FONT, 10)).grid(
            row=5, column=0, pady=(0, 24))

    def _build_content(self):
        content = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color="#343438",
            scrollbar_button_hover_color="#4D4D55",
        )
        content.grid(row=0, column=1, sticky="nsew", padx=(32, 22), pady=24)
        content.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(content, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 26))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Multi Roblox", text_color=TEXT,
                     font=(FONT, 32, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="Instâncias e desempenho", text_color=MUTED,
                     font=(FONT, 13)).grid(row=1, column=0, sticky="w", pady=(1, 0))
        self.session_pill = ctk.CTkLabel(
            header, text="●  Em espera", width=125, height=32, corner_radius=16,
            fg_color="#28282C", text_color=MUTED, font=(FONT, 11),
        )
        self.session_pill.grid(row=0, column=1, rowspan=2, sticky="e", padx=(20, 4))
        self._build_multi_card(content)
        lower = ctk.CTkFrame(content, fg_color="transparent")
        lower.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        lower.grid_columnconfigure((0, 1), weight=1, uniform="performance")
        self._build_cpu_card(lower)
        self._build_fps_card(lower)
        activity = ctk.CTkFrame(content, fg_color="transparent")
        activity.grid(row=3, column=0, sticky="ew", pady=(20, 12))
        activity.grid_columnconfigure(1, weight=1)
        self.activity_button = ctk.CTkButton(
            activity, text="Ver atividade", command=self._toggle_activity,
            width=132, height=34, corner_radius=9, fg_color="#28282C",
            hover_color="#343438", text_color=TEXT, font=(FONT, 12),
        )
        self.activity_button.grid(row=0, column=0, sticky="w")
        self.activity_summary = ctk.CTkLabel(
            activity, text="Sem eventos", text_color=MUTED,
            font=(FONT, 11), anchor="w", justify="left", wraplength=420,
        )
        self.activity_summary.grid(row=0, column=1, sticky="w", padx=16)
        self.activity_panel = ctk.CTkFrame(content, fg_color="#121214", corner_radius=14)
        self.activity_panel.grid(row=4, column=0, sticky="ew", pady=(0, 14))
        self.log_view = ctk.CTkTextbox(
            self.activity_panel, height=120, fg_color="transparent", text_color=MUTED,
            corner_radius=0, font=(MONO, 11), wrap="word", state="disabled",
        )
        self.log_view.pack(fill="both", expand=True, padx=10, pady=10)
        self.activity_panel.grid_remove()
        self.footer = ctk.CTkLabel(
            content, text="Salvando...", text_color=MUTED, font=(FONT, 11), anchor="w",
        )
        self.footer.grid(row=5, column=0, sticky="ew", pady=(0, 8))

    def _card(self, parent, feature):
        card = ctk.CTkFrame(parent, fg_color=PANEL, border_width=1,
                            border_color=BORDER, corner_radius=18)
        self.cards[feature] = card
        return card

    def _switch(self, parent, feature):
        variable = ctk.BooleanVar(value=getattr(self.config, feature))
        self.variables[feature] = variable
        switch = ctk.CTkSwitch(
            parent, text="", variable=variable, width=52, height=28,
            switch_width=48, switch_height=26, progress_color=PURPLE,
            fg_color="#45454D", button_color=TEXT, button_hover_color="#DCD7EC",
            command=partial(self._toggle, feature),
        )
        self.controls[feature] = switch
        return switch

    def _status(self, parent, feature, wraplength=280):
        label = ctk.CTkLabel(
            parent, text="Desativado", text_color=MUTED, anchor="w",
            justify="left", wraplength=wraplength, font=(FONT, 11),
        )
        self.statuses[feature] = label
        return label

    def _build_multi_card(self, parent):
        card = self._card(parent, "multi_instance")
        card.grid(row=1, column=0, sticky="ew")
        card.grid_columnconfigure(1, weight=1)
        IconBadge(card, "layers", size=48).grid(row=0, column=0, rowspan=2,
                                               sticky="n", padx=(26, 18), pady=26)
        ctk.CTkLabel(card, text="Multi-instância", text_color=TEXT,
                     font=(FONT, 23, "bold"), anchor="w").grid(
                         row=0, column=1, sticky="w", pady=(23, 0))
        ctk.CTkLabel(card, text=FEATURES["multi_instance"][2], text_color=MUTED,
                     font=(FONT, 13)).grid(row=1, column=1, sticky="w", pady=(2, 7))
        self._status(card, "multi_instance", 450).grid(
            row=2, column=1, sticky="w", pady=(0, 22))
        self._switch(card, "multi_instance").grid(
            row=0, column=2, rowspan=2, sticky="ne", padx=26, pady=30)

    def _compact_header(self, card, feature):
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 16))
        head.grid_columnconfigure(0, weight=1)
        IconBadge(head, FEATURES[feature][0], size=40).grid(row=0, column=0, sticky="w")
        self._switch(head, feature).grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(card, text=FEATURES[feature][1], text_color=TEXT,
                     font=(FONT, 20, "bold"), anchor="w").grid(
                         row=1, column=0, sticky="w", padx=24)
        ctk.CTkLabel(card, text=FEATURES[feature][2], text_color=MUTED,
                     font=(FONT, 12), anchor="w").grid(
                         row=2, column=0, sticky="w", padx=24, pady=(2, 16))

    def _build_cpu_card(self, parent):
        card = self._card(parent, "optimizer")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        card.grid_columnconfigure(0, weight=1)
        self._compact_header(card, "optimizer")
        policy = ctk.CTkFrame(card, fg_color="#1B1B1E", corner_radius=10)
        policy.grid(row=3, column=0, sticky="ew", padx=24)
        policy.grid_columnconfigure(0, weight=1)
        for row, (label, value, color) in enumerate((
            ("Em foco", "Normal", TEXT), ("Segundo plano", "Baixa", ACCENT),
        )):
            ctk.CTkLabel(policy, text=label, text_color=MUTED, font=(FONT, 12)).grid(
                row=row, column=0, sticky="w", padx=14, pady=(7 if row == 0 else 0, 7))
            ctk.CTkLabel(policy, text=value, text_color=color, font=(FONT, 12, "bold")).grid(
                row=row, column=1, sticky="e", padx=14, pady=(7 if row == 0 else 0, 7))
        self._status(card, "optimizer").grid(row=4, column=0, sticky="w", padx=24, pady=(12, 20))

    def _build_fps_card(self, parent):
        card = self._card(parent, "fps_unlock")
        card.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        card.grid_columnconfigure(0, weight=1)
        self._compact_header(card, "fps_unlock")
        target = ctk.CTkFrame(card, fg_color="transparent")
        target.grid(row=3, column=0, sticky="ew", padx=24)
        self.fps_choice = ctk.CTkComboBox(
            target, values=[str(value) for value in FPS_CHOICES], width=130,
            height=42, state="readonly", command=self._change_fps,
            corner_radius=10, border_width=1, fg_color="#1B1B1E",
            border_color="#414147", button_color="#414147", button_hover_color="#54545E",
            dropdown_fg_color=PANEL, dropdown_hover_color=PURPLE,
            font=(FONT, 20, "bold"), dropdown_font=(FONT, 13), text_color=TEXT,
        )
        self.fps_choice.set(str(self.config.fps_limit))
        self.fps_choice.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(target, text="FPS", text_color=MUTED, font=(FONT, 12, "bold")).grid(
            row=0, column=1, padx=12, sticky="w")
        ctk.CTkLabel(target, text="Experimental · pode aumentar o uso de GPU", text_color=MUTED,
                     font=(FONT, 10), wraplength=280, anchor="w", justify="left").grid(
                         row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._status(card, "fps_unlock").grid(row=4, column=0, sticky="w", padx=24, pady=(12, 20))

    def _toggle_activity(self):
        self.activity_visible = not self.activity_visible
        if self.activity_visible:
            self.activity_panel.grid()
        else:
            self.activity_panel.grid_remove()
        self.activity_button.configure(text="Ocultar atividade" if self.activity_visible else "Ver atividade")

    def _update_session_status(self):
        count = len(self.active_features)
        if self.closing:
            self.session_pill.configure(text="Encerrando...", text_color=MUTED)
        else:
            text = "●  Em espera" if not count else f"●  {count} ativo" + ("s" if count > 1 else "")
            self.session_pill.configure(text=text, text_color=GREEN if count else MUTED)
        for feature, card in self.cards.items():
            error = self.statuses[feature].cget("text_color") == RED
            border = "#624D8C" if feature in self.active_features else "#75444C" if error else BORDER
            card.configure(border_color=border)

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
        preview = message if len(message) <= 68 else message[:65] + "…"
        self.activity_summary.configure(text=f"{stamp}  {preview}", text_color=RED if level == "error" else MUTED)
        if level in ("error", "warning") and not self.activity_visible:
            self._toggle_activity()

    def _save_config(self):
        try:
            self.store.save(self.config)
            self.footer.configure(text="●  Salvo", text_color=GREEN)
        except OSError as error:
            self.footer.configure(text="Falha ao salvar", text_color=RED)
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
        self._update_session_status()
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
                self.active_features.add(feature)
                self.statuses[feature].configure(text="Ativo", text_color=GREEN)
                if not self.closing:
                    self.controls[feature].configure(state="normal")
                self._log(message)
            elif kind == "status":
                self.statuses[feature].configure(text=message, text_color=GREEN)
            elif kind == "error":
                self.active_features.discard(feature)
                self.statuses[feature].configure(text="Falha — consulte a atividade", text_color=RED)
                self._log(message, "error")
                if self.closing:
                    self.close_errors.append(message)
                else:
                    self.variables[feature].set(False)
                    setattr(self.config, feature, False)
                    self._save_config()
            elif kind == "stopped":
                self.active_features.discard(feature)
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
            self._update_session_status()

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
        self._update_session_status()
        self.footer.configure(text="Restaurando e encerrando...", text_color=MUTED)
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
