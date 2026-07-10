"""Interface PersonalWhisper — fenêtre customtkinter (dark « NK »).

Barre de statut live · historique des dictées · réglages · éditeurs de
vocabulaire et de corrections. Fermer la fenêtre la réduit dans la barre
système (l'app continue d'écouter). Toute la communication avec le moteur
(qui tourne sur des threads de fond) passe par une file d'événements vidée
sur le thread principal, seul autorisé à toucher tkinter.
"""

import os
import queue

import customtkinter as ctk
import pyperclip

import app

# --- Palette « NK » ----------------------------------------------------------
BG = "#1A1714"          # charbon chaud
CARD = "#242019"        # surface
CARD2 = "#2C2820"       # surface + survol
AMBER = "#FFAA2B"       # accent signal
AMBER_HOVER = "#E0921F"
RED = "#E8431F"         # enregistrement
GREEN = "#46C46E"       # prêt
INK = "#1A1714"         # texte sur ambre
TXT = "#EDEDE6"         # texte principal
MUTED = "#8A857B"       # texte secondaire

STATUS = {
    "loading": (AMBER, "Chargement du modèle…"),
    "reloading": (AMBER, "Rechargement du vocabulaire…"),
    "ready": (GREEN, "Prêt"),
    "recording_ptt": (RED, "Écoute…  (push-to-talk)"),
    "recording_toggle": (RED, "Écoute…  (mains-libres)"),
    "processing": (AMBER, "Transcription…"),
}


class MainWindow(ctk.CTk):
    def __init__(self, cfg: dict):
        super().__init__(fg_color=BG)
        self.cfg = cfg
        self.engine = None
        self._events: queue.Queue = queue.Queue()
        self._model_ready = False
        self._notice_token = 0
        self._history_rows = []
        self._device_map: dict[str, object] = {}

        ctk.set_appearance_mode("dark")
        self.title("PersonalWhisper")
        self.geometry("580x680")
        self.minsize(520, 560)
        try:
            self.iconbitmap(os.path.join(app.APP_DIR, "icon.ico"))
        except Exception:
            pass

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_statusbar()
        self._build_tabs()
        self._build_footer()

        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.after(80, self._drain)

    # =====================================================================
    # Construction
    # =====================================================================

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        bar.grid_columnconfigure(1, weight=1)

        self.dot = ctk.CTkLabel(bar, text="●", text_color=AMBER,
                                font=ctk.CTkFont(size=18))
        self.dot.grid(row=0, column=0, padx=(14, 8), pady=12)

        self.status_label = ctk.CTkLabel(
            bar, text="Démarrage…", text_color=TXT,
            font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        )
        self.status_label.grid(row=0, column=1, sticky="w")

        self.hotkeys_label = ctk.CTkLabel(
            bar, text="", text_color=MUTED, font=ctk.CTkFont(size=12), anchor="e",
        )
        self.hotkeys_label.grid(row=0, column=2, sticky="e", padx=(8, 14))

        self.notice_label = ctk.CTkLabel(
            bar, text="", text_color=AMBER, font=ctk.CTkFont(size=12), anchor="w",
        )
        self.notice_label.grid(row=1, column=0, columnspan=3, sticky="w",
                               padx=14, pady=(0, 8))

    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(
            self, fg_color=CARD, segmented_button_selected_color=AMBER,
            segmented_button_selected_hover_color=AMBER_HOVER,
            segmented_button_unselected_color=CARD2,
            text_color=TXT, corner_radius=14,
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=14, pady=4)
        for name in ("Historique", "Réglages", "Vocabulaire", "Corrections"):
            self.tabs.add(name)

        self._build_history_tab(self.tabs.tab("Historique"))
        self._build_settings_tab(self.tabs.tab("Réglages"))
        self._build_vocab_tab(self.tabs.tab("Vocabulaire"))
        self._build_corrections_tab(self.tabs.tab("Corrections"))

    def _build_history_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(tab, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Dernières dictées", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(head, text="Effacer", width=72, height=26,
                      fg_color=CARD2, hover_color="#3A362B", text_color=TXT,
                      command=self._clear_history).grid(row=0, column=1, sticky="e")

        self.history = ctk.CTkScrollableFrame(tab, fg_color=BG, corner_radius=10)
        self.history.grid(row=1, column=0, sticky="nsew")
        self.history.grid_columnconfigure(0, weight=1)

        self.empty_label = ctk.CTkLabel(
            self.history, text="Aucune dictée pour l'instant.", text_color=MUTED,
        )
        self.empty_label.grid(row=0, column=0, pady=24)

    def _build_settings_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        f = ctk.CTkScrollableFrame(tab, fg_color=BG, corner_radius=10)
        f.grid(row=0, column=0, sticky="nsew")
        f.grid_columnconfigure(1, weight=1)
        r = 0

        def label(text):
            ctk.CTkLabel(f, text=text, text_color=TXT, anchor="w").grid(
                row=r, column=0, sticky="w", padx=10, pady=(12, 2), columnspan=2
            )

        def field_label(text, row):
            ctk.CTkLabel(f, text=text, text_color=MUTED, anchor="w").grid(
                row=row, column=0, sticky="w", padx=10, pady=8
            )

        field_label("Raccourci push-to-talk", r)
        self.ptt_entry = ctk.CTkEntry(f)
        self.ptt_entry.grid(row=r, column=1, sticky="ew", padx=10, pady=8)
        r += 1
        field_label("Raccourci mains-libres (toggle)", r)
        self.toggle_entry = ctk.CTkEntry(f)
        self.toggle_entry.grid(row=r, column=1, sticky="ew", padx=10, pady=8)
        r += 1
        field_label("Microphone", r)
        self.device_menu = ctk.CTkOptionMenu(
            f, values=["Défaut système"], fg_color=CARD2, button_color=CARD2,
            button_hover_color="#3A362B",
        )
        self.device_menu.grid(row=r, column=1, sticky="ew", padx=10, pady=8)
        r += 1

        self.sounds_switch = self._switch(f, "Sons de feedback", r); r += 1
        self.overlay_switch = self._switch(f, "HUD à l'écran (overlay)", r); r += 1
        self.restore_switch = self._switch(f, "Restaurer le presse-papiers", r); r += 1

        field_label("Sensibilité au silence (min_peak)", r)
        self.peak_val = ctk.CTkLabel(f, text="", text_color=AMBER, width=54)
        self.peak_val.grid(row=r, column=1, sticky="e", padx=10)
        r += 1
        self.peak_slider = ctk.CTkSlider(
            f, from_=0.002, to=0.05, number_of_steps=48, progress_color=AMBER,
            button_color=AMBER, button_hover_color=AMBER_HOVER,
            command=lambda v: self.peak_val.configure(text=f"{v:.3f}"),
        )
        self.peak_slider.grid(row=r, column=0, columnspan=2, sticky="ew", padx=10)
        r += 1

        field_label("Force du vocabulaire (vocab_score)", r)
        self.score_val = ctk.CTkLabel(f, text="", text_color=AMBER, width=54)
        self.score_val.grid(row=r, column=1, sticky="e", padx=10)
        r += 1
        self.score_slider = ctk.CTkSlider(
            f, from_=0.0, to=8.0, number_of_steps=16, progress_color=AMBER,
            button_color=AMBER, button_hover_color=AMBER_HOVER,
            command=lambda v: self.score_val.configure(text=f"{v:.1f}"),
        )
        self.score_slider.grid(row=r, column=0, columnspan=2, sticky="ew", padx=10)
        r += 1
        ctk.CTkLabel(
            f, text="2 = doux · 4 = fort · 8 = le mot s'invite partout. "
            "Changer la force ou le micro applique après un court rechargement.",
            text_color=MUTED, font=ctk.CTkFont(size=11), wraplength=460, justify="left",
        ).grid(row=r, column=0, columnspan=2, sticky="w", padx=10, pady=(6, 10))
        r += 1

        self.apply_btn = ctk.CTkButton(
            f, text="Appliquer les réglages", fg_color=AMBER, hover_color=AMBER_HOVER,
            text_color=INK, font=ctk.CTkFont(weight="bold"), command=self._apply_settings,
        )
        self.apply_btn.grid(row=r, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 12))

    def _build_vocab_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            tab, text="Un mot ou nom propre par ligne  ·  # = commentaire. "
            "Ces mots sont boostés à la transcription.",
            text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w", justify="left",
            wraplength=500,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(6, 6))
        self.vocab_box = ctk.CTkTextbox(tab, fg_color=BG, text_color=TXT,
                                        font=ctk.CTkFont(family="Consolas", size=13))
        self.vocab_box.grid(row=1, column=0, sticky="nsew")
        self.vocab_save_btn = ctk.CTkButton(
            tab, text="Enregistrer & recharger", fg_color=AMBER, hover_color=AMBER_HOVER,
            text_color=INK, font=ctk.CTkFont(weight="bold"), command=self._save_vocab,
        )
        self.vocab_save_btn.grid(row=2, column=0, sticky="ew", pady=(8, 4))

    def _build_corrections_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            tab, text="Une correction par ligne, au format :  erreur = remplacement "
            "(insensible à la casse, mots entiers). Appliqué instantanément.",
            text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w", justify="left",
            wraplength=500,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(6, 6))
        self.corr_box = ctk.CTkTextbox(tab, fg_color=BG, text_color=TXT,
                                       font=ctk.CTkFont(family="Consolas", size=13))
        self.corr_box.grid(row=1, column=0, sticky="nsew")
        ctk.CTkButton(
            tab, text="Enregistrer les corrections", fg_color=AMBER,
            hover_color=AMBER_HOVER, text_color=INK, font=ctk.CTkFont(weight="bold"),
            command=self._save_corrections,
        ).grid(row=2, column=0, sticky="ew", pady=(8, 4))

    def _build_footer(self):
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=14, pady=(6, 12))
        foot.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            foot, text="Réduire au tray", fg_color=CARD2, hover_color="#3A362B",
            text_color=TXT, command=self.hide_to_tray,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            foot, text="Quitter", fg_color="#3A2018", hover_color=RED,
            text_color=TXT, width=100, command=self._quit,
        ).grid(row=0, column=1, sticky="e")

    def _switch(self, parent, text, row):
        sw = ctk.CTkSwitch(parent, text=text, text_color=TXT,
                           progress_color=AMBER, button_color=TXT)
        sw.grid(row=row, column=0, columnspan=2, sticky="w", padx=10, pady=8)
        return sw

    # =====================================================================
    # Branchement du moteur
    # =====================================================================

    def attach_engine(self, engine):
        self.engine = engine
        cfg = self.cfg

        self.ptt_entry.insert(0, cfg.get("hotkey", "ctrl+space"))
        self.toggle_entry.insert(0, cfg.get("toggle_hotkey") or "")

        # Micros : "Défaut système" + chaque entrée "<idx> · <nom>".
        self._device_map = {"Défaut système": None}
        values = ["Défaut système"]
        for idx, name in app.list_input_devices():
            disp = f"{idx} · {name}"
            self._device_map[disp] = idx
            values.append(disp)
        self.device_menu.configure(values=values)
        cur = cfg.get("device")
        sel = next((d for d, i in self._device_map.items() if i == cur), "Défaut système")
        self.device_menu.set(sel)

        (self.sounds_switch.select if cfg.get("sounds", True) else self.sounds_switch.deselect)()
        (self.overlay_switch.select if cfg.get("overlay", True) else self.overlay_switch.deselect)()
        (self.restore_switch.select if cfg.get("restore_clipboard", True)
         else self.restore_switch.deselect)()

        self.peak_slider.set(float(cfg.get("min_peak", 0.008)))
        self.peak_val.configure(text=f"{float(cfg.get('min_peak', 0.008)):.3f}")
        self.score_slider.set(float(cfg.get("vocab_score", 2.0)))
        self.score_val.configure(text=f"{float(cfg.get('vocab_score', 2.0)):.1f}")

        self.vocab_box.insert("1.0", self._read_vocab_text())
        self.corr_box.insert("1.0", self._corrections_text())

        self._update_hotkeys_label()
        self._set_heavy_enabled(False)  # verrouillé tant que le modèle charge

    # =====================================================================
    # File d'événements (thread-safe)
    # =====================================================================

    def post_event(self, kind: str, payload):
        """Appelable depuis n'importe quel thread (moteur, tray)."""
        self._events.put((kind, payload))

    def _drain(self):
        try:
            while True:
                kind, payload = self._events.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _handle(self, kind, payload):
        if kind == "status":
            self._set_status(payload)
        elif kind == "transcription":
            self._add_history(payload)
        elif kind == "notice":
            self._notice(payload)
        elif kind == "model_ready":
            self._model_ready = True
            self._set_heavy_enabled(True)
        elif kind == "show":
            self.show_window()
        elif kind == "quit":
            self._quit()

    # =====================================================================
    # Mises à jour d'affichage
    # =====================================================================

    def _set_status(self, s: str):
        color, text = STATUS.get(s, (MUTED, s))
        self.dot.configure(text_color=color)
        self.status_label.configure(text=text)
        if s in ("loading", "reloading"):
            self._set_heavy_enabled(False)
        elif s == "ready" and self._model_ready:
            self._set_heavy_enabled(True)

    def _update_hotkeys_label(self):
        ptt = self.cfg.get("hotkey", "ctrl+space")
        toggle = self.cfg.get("toggle_hotkey") or None
        self.hotkeys_label.configure(text=ptt + (f"   ·   {toggle}" if toggle else ""))

    def _notice(self, msg: str):
        self._notice_token += 1
        token = self._notice_token
        self.notice_label.configure(text=msg)
        self.after(4000, lambda: self._clear_notice(token))

    def _clear_notice(self, token):
        if token == self._notice_token:
            self.notice_label.configure(text="")

    def _set_heavy_enabled(self, on: bool):
        state = "normal" if on else "disabled"
        for b in (getattr(self, "apply_btn", None), getattr(self, "vocab_save_btn", None)):
            if b is not None:
                b.configure(state=state)

    def _add_history(self, d: dict):
        self.empty_label.grid_remove()
        row = ctk.CTkFrame(self.history, fg_color=CARD, corner_radius=8)
        row.grid(sticky="ew", padx=4, pady=4)
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            row, text=d["time"], text_color=MUTED,
            font=ctk.CTkFont(family="Consolas", size=11),
        ).grid(row=0, column=0, sticky="nw", padx=(10, 8), pady=8)
        ctk.CTkLabel(
            row, text=d["text"], text_color=TXT, anchor="w", justify="left",
            wraplength=380,
        ).grid(row=0, column=1, sticky="ew", pady=8)
        ctk.CTkButton(
            row, text="Copier", width=64, height=26, fg_color=CARD2,
            hover_color="#3A362B", text_color=TXT,
            command=lambda t=d["text"]: self._copy(t),
        ).grid(row=0, column=2, sticky="ne", padx=8, pady=8)
        self._history_rows.append(row)
        # Le plus récent en haut : on remonte la nouvelle ligne.
        for i, w in enumerate(reversed(self._history_rows)):
            w.grid_configure(row=i)

    def _clear_history(self):
        for w in self._history_rows:
            w.destroy()
        self._history_rows.clear()
        self.empty_label.grid()

    def _copy(self, text: str):
        try:
            pyperclip.copy(text)
            self._notice("Copié dans le presse-papiers")
        except Exception:
            pass

    # =====================================================================
    # Actions réglages / vocab / corrections
    # =====================================================================

    def _gather_settings(self) -> dict:
        return {
            "hotkey": self.ptt_entry.get().strip() or "ctrl+space",
            "toggle_hotkey": self.toggle_entry.get().strip(),
            "device": self._device_map.get(self.device_menu.get()),
            "sounds": bool(self.sounds_switch.get()),
            "overlay": bool(self.overlay_switch.get()),
            "restore_clipboard": bool(self.restore_switch.get()),
            "min_peak": float(self.peak_slider.get()),
            "vocab_score": float(self.score_slider.get()),
        }

    def _apply_settings(self):
        if self.engine is None:
            return
        self.engine.apply_settings(self._gather_settings())
        self._update_hotkeys_label()

    def _save_vocab(self):
        if self.engine is None:
            return
        self.engine.save_vocab_text(self.vocab_box.get("1.0", "end"))

    def _save_corrections(self):
        if self.engine is None:
            return
        corrections = {}
        for line in self.corr_box.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                corrections[k] = v
        self.engine.save_corrections(corrections)

    def _read_vocab_text(self) -> str:
        path = app.vocab_path(self.cfg)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
        return ""

    def _corrections_text(self) -> str:
        items = self.cfg.get("corrections", {})
        return "\n".join(f"{k} = {v}" for k, v in items.items())

    # =====================================================================
    # Tray / fenêtre / quitter
    # =====================================================================

    def hide_to_tray(self):
        self.withdraw()

    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit(self):
        if self.engine is not None:
            self.engine.shutdown()
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)
