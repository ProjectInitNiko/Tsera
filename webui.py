"""Bridge pywebview ↔ moteur PersonalWhisper.

L'objet `Api` est exposé au JS via `js_api`. pywebview expose au JS **toutes les
méthodes publiques** de cet objet et récurserait dans ses attributs-objets — d'où
le préfixe `_` sur tout l'état interne (`_engine`, `_window`, `_cfg`…) et sur les
méthodes non destinées au JS (`_emit`, `_attach`). Seules restent publiques les
méthodes réellement appelées côté JS : ready / apply_settings / save_vocab /
save_corrections / copy_text / minimize / quit_app.

Les événements du moteur sont poussés vers le JS via `evaluate_js` ; ceux émis
avant que le JS n'ait signalé `ready()` sont tamponnés puis rejoués.
"""

import json
import os
import threading

import pyperclip

import app as _app


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
            "devices": [{"index": i, "name": n} for i, n in _app.list_input_devices()],
            "device": cfg.get("device"),
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

    def copy_text(self, text: str):
        try:
            pyperclip.copy(text or "")
            self._emit("notice", "Copié dans le presse-papiers")
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

    def quit_app(self):
        if self._engine:
            self._engine.shutdown()
        os._exit(0)
