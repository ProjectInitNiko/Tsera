"""Bridge pywebview ↔ moteur Tsera.

L'objet `Api` est exposé au JS via `js_api`. pywebview expose au JS **toutes les
méthodes publiques** de cet objet et récurserait dans ses attributs-objets — d'où
le préfixe `_` sur tout l'état interne (`_engine`, `_window`, `_cfg`…) et sur les
méthodes non destinées au JS (`_emit`, `_attach`). Seules restent publiques les
méthodes réellement appelées côté JS : ready / apply_settings / save_vocab /
save_corrections / copy_text / minimize / quit_app, plus les commandes de
fenêtre (window_bounds / set_bounds / toggle_maximize / toggle_fullscreen).

Les événements du moteur sont poussés vers le JS via `evaluate_js` ; ceux émis
avant que le JS n'ait signalé `ready()` sont tamponnés puis rejoués.
"""

import json
import os
import queue
import threading

import pyperclip

import app as _app

# Plancher de redimensionnement : en dessous, la faceplate se disloque.
_MIN_W, _MIN_H = 380, 420


class Api:
    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._engine = None
        self._window = None
        self._ready = False
        self._buffer = []
        self._lock = threading.Lock()
        self._status = "loading"
        self._history = []
        self._maximized = False
        self._restore_bounds = None  # taille d'avant l'agrandissement
        self._fullscreen = False
        # evaluate_js bloque sur un aller-retour vers le thread UI WinForms.
        # Appelé depuis le hook clavier (via on_event), il gelait le clavier
        # système entier. Une file + un unique thread pompe : _push devient
        # fire-and-forget pour tous les appelants, l'ordre est préservé.
        self._js_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._js_pump, daemon=True).start()

    def _attach(self, engine, window):
        self._engine = engine
        self._window = window

    # --- Python → JS --------------------------------------------------------

    def _emit(self, kind: str, payload):
        """Passé au moteur comme `on_event` ; appelable depuis n'importe quel thread."""
        if kind == "status":
            self._status = payload
        elif kind == "transcription":
            self._history.insert(0, payload)
            del self._history[50:]
        with self._lock:
            if not self._ready or self._window is None:
                self._buffer.append((kind, payload))
                return
        self._push(kind, payload)

    def _push(self, kind: str, payload):
        self._js_q.put((kind, payload))

    def _js_pump(self):
        while True:
            kind, payload = self._js_q.get()
            if self._window is None:
                continue
            try:
                self._window.evaluate_js(
                    "window.PW && window.PW.on(%s, %s)"
                    % (json.dumps(kind), json.dumps(payload))
                )
            except Exception:
                pass

    def _read_vocab(self) -> str:
        path = _app.vocab_path(self._cfg)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
        return ""

    # --- JS → Python (window.pywebview.api.*) -------------------------------

    def ready(self):
        """Le JS est prêt : vide le tampon et renvoie l'état initial."""
        with self._lock:
            self._ready = True
            buffered = self._buffer[:]
            self._buffer.clear()
        for kind, payload in buffered:
            self._push(kind, payload)
        cfg = self._cfg
        return {
            "status": self._status,
            "hotkey": cfg.get("hotkey", "ctrl+space"),
            "toggle_hotkey": cfg.get("toggle_hotkey") or "",
            "devices": self.list_devices(),
            "lang": cfg.get("lang", "en"),
            "dictation_lang": cfg.get("dictation_lang", "multi"),
            "has_georgian": os.path.isdir(
                os.path.join(_app.APP_DIR, cfg.get("model_dir_ka", _app.MODEL_DIR_KA))
            ),
            # Index du micro configuré tel qu'il existe MAINTENANT : celui du
            # fichier de config peut avoir été décalé par un branchement, et
            # sélectionnerait alors la mauvaise ligne (ou aucune).
            "device": _app.resolve_device(cfg)[0],
            "sounds": cfg.get("sounds", True),
            "overlay": cfg.get("overlay", True),
            "restore_clipboard": cfg.get("restore_clipboard", True),
            "min_peak": cfg.get("min_peak", 0.008),
            "vocab_score": cfg.get("vocab_score", 2.0),
            "vocab_text": self._read_vocab(),
            "corrections": [
                {"error": k, "replacement": v}
                for k, v in cfg.get("corrections", {}).items()
            ],
            "history": self._history,
        }

    def apply_settings(self, s: dict):
        if self._engine:
            self._engine.apply_settings(s)
        return True

    def list_devices(self):
        """Ré-énumère les micros — la liste de ready() devient obsolète dès
        qu'un périphérique est branché ou débranché. Une entrée par micro
        physique : les alias par hôte audio sont regroupés côté app.py."""
        sr = self._cfg.get("sample_rate", 16000)
        return [{"index": m["index"], "name": m["name"]} for m in _app.input_devices(sr)]

    def save_vocab(self, text: str):
        if self._engine:
            self._engine.save_vocab_text(text)
        return True

    def save_corrections(self, items):
        corr = {}
        for it in items or []:
            k = (it.get("error") or "").strip()
            v = (it.get("replacement") or "").strip()
            if k and v:
                corr[k] = v
        if self._engine:
            self._engine.save_corrections(corr)
        return True

    def set_lang(self, lang: str):
        """Langue de l'interface. Écrite dans config.json (et pas seulement dans
        le front) : elle sert aussi au menu de la barre système, qui est construit
        côté Python, et elle survit au redémarrage."""
        lang = "fr" if lang == "fr" else "en"
        self._cfg["lang"] = lang
        try:
            _app.save_config(self._cfg)
        except Exception as e:
            # Avaler l'échec en silence = langue revenue à l'anglais au
            # prochain lancement sans explication. On prévient.
            self._emit("notice", _app.tr(lang, "save_error").format(e))
        if self._engine:
            self._engine.refresh_tray_menu(lang)
        return lang

    def copy_text(self, text: str):
        try:
            pyperclip.copy(text or "")
            self._emit("notice", _app.tr(self._cfg.get("lang", "en"), "copied"))
        except Exception:
            pass
        return True

    def minimize(self):
        if self._window:
            try:
                self._window.hide()
            except Exception:
                pass
        return True

    # --- Fenêtre : la faceplate est sans bordure, donc rien de tout ça n'est
    # fourni par Windows — les poignées et les boutons sont dessinés par le
    # front, qui appelle ces méthodes.

    def window_bounds(self):
        """Position et taille courantes, en pixels écran. Le JS s'en sert comme
        point de départ d'un redimensionnement (il raisonne ensuite en
        coordonnées écran, insensibles au déplacement de la fenêtre)."""
        w = self._window
        if not w:
            return None
        try:
            return {"x": w.x, "y": w.y, "width": w.width, "height": w.height}
        except Exception:
            return None

    def set_bounds(self, x: int, y: int, width: int, height: int):
        w = self._window
        if not w:
            return False
        try:
            width = max(_MIN_W, int(width))
            height = max(_MIN_H, int(height))
            w.resize(width, height)
            w.move(int(x), int(y))
        except Exception:
            return False
        return True

    @staticmethod
    def _work_area(w):
        """Zone de travail de l'écran où se trouve la fenêtre, c'est-à-dire
        l'écran MOINS la barre des tâches. `None` si on ne sait pas la lire.

        WinForms dimensionne une fenêtre `frameless` passée en `Maximized` sur
        le moniteur ENTIER, pas sur la zone de travail : la barre des tâches
        disparaît sous la fenêtre. On agrandit donc à la main. On passe par
        `Screen` plutôt que par l'API Win32 pour rester dans le référentiel de
        coordonnées de WinForms, le même que `w.move` et `w.resize`."""
        try:
            import clr

            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            from System.Drawing import Point
            from System.Windows.Forms import Screen

            # L'écran est choisi par le CENTRE de la fenêtre : sur un poste à
            # deux écrans, son coin haut-gauche peut appartenir au voisin.
            centre = Point(int(w.x + w.width / 2), int(w.y + w.height / 2))
            a = Screen.FromPoint(centre).WorkingArea
            return int(a.X), int(a.Y), int(a.Width), int(a.Height)
        except Exception:
            return None

    def toggle_maximize(self):
        """Renvoie l'état atteint pour que le bouton change d'icône."""
        w = self._window
        if not w:
            return False
        try:
            if self._maximized:
                b = self._restore_bounds
                if b:
                    w.resize(b["width"], b["height"])
                    w.move(b["x"], b["y"])
                else:
                    w.restore()
                self._maximized = False
            else:
                area = self._work_area(w)
                if area is None:
                    w.maximize()  # repli : agrandit, mais masque la barre des tâches
                else:
                    x, y, cw, ch = area
                    # Mémorisé AVANT de bouger, sinon on restaure la taille agrandie.
                    self._restore_bounds = {
                        "x": w.x, "y": w.y, "width": w.width, "height": w.height
                    }
                    w.resize(cw, ch)
                    w.move(x, y)
                self._maximized = True
        except Exception:
            return self._maximized
        return self._maximized

    def toggle_fullscreen(self):
        if self._window:
            try:
                self._window.toggle_fullscreen()
                self._fullscreen = not self._fullscreen
            except Exception:
                pass
        return self._fullscreen

    def quit_app(self):
        if self._engine:
            self._engine.shutdown()
        os._exit(0)
