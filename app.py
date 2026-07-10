"""PersonalWhisper — dictée locale (push-to-talk + toggle mains-libres) avec UI.

Deux raccourcis globaux :
  - maintenir Ctrl+Espace          → push-to-talk
  - Ctrl+Shift+Espace (1 appui/1)  → toggle mains-libres
Le texte transcrit se colle au curseur, dans n'importe quelle application.

L'interface (customtkinter) montre le statut live, l'historique des dictées et
les réglages (raccourcis, micro, vocabulaire, corrections). Fermer la fenêtre la
réduit dans la barre système ; l'app continue d'écouter. Lancer avec `--tray`
pour démarrer directement réduit (utilisé par le raccourci de démarrage auto).

Tout tourne en local (Parakeet v3 via sherpa-onnx, CPU). Aucune donnée ne sort du PC.
"""

import json
import os
import re
import sys
import threading
import time
import winsound

import keyboard
import numpy as np
import pyperclip
import pystray
import sounddevice as sd
from PIL import Image, ImageDraw

from overlay import Overlay
from stt import Transcriber

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Console Windows en cp1252 : force UTF-8 pour les accents et flèches des logs.
# Sous pythonw, stdout/stderr sont None (print = no-op), on ne touche à rien.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def log(*args):
    """print sûr : no-op quand stdout est None (exécution sous pythonw)."""
    if sys.stdout is None:
        return
    try:
        print(*args, flush=True)
    except Exception:
        pass


def config_path() -> str:
    return os.path.join(APP_DIR, "config.json")


def load_config() -> dict:
    with open(config_path(), encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict):
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")


def vocab_path(cfg: dict) -> str:
    return os.path.join(APP_DIR, cfg.get("vocab_file", "vocab.txt"))


def load_vocab(cfg: dict) -> list[str]:
    """Mots du vocabulaire custom (vocab.txt) — lignes vides et # ignorées."""
    path = vocab_path(cfg)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [w for w in (line.strip() for line in f) if w and not w.startswith("#")]


class Recorder:
    """Flux micro ouvert en continu ; on ne garde les frames que pendant la dictée."""

    def __init__(self, sample_rate: int, device=None, on_level=None):
        self.sample_rate = sample_rate
        self.device = device
        self._chunks: list[np.ndarray] = []
        self._active = False
        self._lock = threading.Lock()
        self._on_level = on_level  # rms du chunk courant, pour le HUD
        self._stream = None
        self._open()

    def _open(self):
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def set_device(self, device):
        """Rouvre le flux sur un autre micro (à faire à l'arrêt, pas en dictée)."""
        self._active = False
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self.device = device
        self._open()

    def _callback(self, indata, frames, time_info, status):
        if self._active:
            chunk = indata[:, 0].copy()
            with self._lock:
                self._chunks.append(chunk)
            if self._on_level is not None:
                self._on_level(float(np.sqrt(np.mean(chunk * chunk))))

    def start(self):
        with self._lock:
            self._chunks = []
        self._active = True

    def stop(self) -> np.ndarray:
        self._active = False
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks)


def paste_text(text: str, restore_clipboard: bool):
    """Colle `text` au curseur via le presse-papiers + Ctrl+V simulé."""
    old = None
    if restore_clipboard:
        try:
            old = pyperclip.paste()
        except Exception:
            old = None
    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")
    if restore_clipboard and old is not None:
        # Laisse le temps à l'app cible de lire le presse-papiers avant restauration.
        def _restore():
            time.sleep(0.6)
            try:
                pyperclip.copy(old)
            except Exception:
                pass

        threading.Thread(target=_restore, daemon=True).start()


def make_icon(recording: bool) -> Image.Image:
    """Icône tray : rond gris (repos) ou rouge (enregistrement)."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (232, 67, 31, 255) if recording else (120, 120, 130, 255)
    d.ellipse((8, 8, 56, 56), fill=color)
    # Silhouette micro
    d.rounded_rectangle((26, 16, 38, 38), radius=6, fill=(255, 255, 255, 255))
    d.arc((20, 26, 44, 46), start=0, end=180, fill=(255, 255, 255, 255), width=3)
    d.line((32, 46, 32, 52), fill=(255, 255, 255, 255), width=3)
    return img


def compile_corrections(corrections: dict):
    """Regex mots-entiers, les clés les plus longues d'abord (« robo dk » avant « dk »)."""
    return [
        (re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE), v)
        for k, v in sorted(corrections.items(), key=lambda kv: -len(kv[0]))
    ]


def list_input_devices() -> list[tuple[int, str]]:
    """(index, nom) des périphériques d'entrée disponibles."""
    out = []
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                out.append((i, dev["name"]))
    except Exception:
        pass
    return out


class Engine:
    """Cœur : micro, raccourcis, transcription. Découplé de l'UI via `on_event`.

    `on_event(kind, payload)` est appelé depuis n'importe quel thread ; l'UI se
    charge de re-router vers son thread principal.
      - ("status", s)          s ∈ loading|ready|recording_ptt|recording_toggle|processing|reloading
      - ("transcription", d)   d = {time, text, audio_s, proc_s}
      - ("notice", msg)        message transitoire (erreur / info)
    """

    def __init__(self, cfg: dict, overlay: Overlay, on_event):
        self.cfg = cfg
        self.overlay = overlay
        self.on_event = on_event
        self.recording = False
        self.record_mode: str | None = None  # "ptt" | "toggle"
        self.record_started_at = 0.0
        self.busy = False
        self.icon: pystray.Icon | None = None
        self.status = "loading"
        self.stt: Transcriber | None = None
        self._held: dict[str, bool] = {}
        self._state_lock = threading.Lock()
        self._corrections = compile_corrections(self.cfg.get("corrections", {}))
        self.recorder = Recorder(
            self.cfg["sample_rate"],
            device=self.cfg.get("device"),
            on_level=self.overlay.push_level,
        )

    # --- Chargement du modèle ------------------------------------------------

    def load_model(self):
        vocab = load_vocab(self.cfg)
        log("Chargement du modèle…")
        self.stt = Transcriber(
            model_dir=os.path.join(APP_DIR, self.cfg["model_dir"]),
            num_threads=self.cfg["num_threads"],
            sample_rate=self.cfg["sample_rate"],
            vocab=vocab,
            vocab_score=self.cfg.get("vocab_score", 2.0),
        )
        mode = f"{len(vocab)} mots boostés (beam search)" if vocab else "aucun (greedy)"
        log(f"Modèle chargé en {self.stt.load_time:.1f} s — vocabulaire : {mode}")

    def reload_async(self):
        """Reconstruit le transcriber (nouveau vocab / score) sans figer l'UI."""
        def _work():
            self._set_status("reloading")
            try:
                self.load_model()
                self.on_event("notice", "Vocabulaire rechargé")
            except Exception as e:
                log(f"Erreur reload : {e}")
                self.on_event("notice", f"Erreur rechargement : {e}")
            finally:
                self._set_status("ready")
        threading.Thread(target=_work, daemon=True).start()

    # --- Feedback ------------------------------------------------------------

    def beep(self, freq: int, ms: int):
        if self.cfg.get("sounds", True):
            threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()

    def set_tray(self, recording: bool):
        if self.icon is not None:
            self.icon.icon = make_icon(recording)

    def _set_status(self, s: str):
        self.status = s
        self.on_event("status", s)

    # --- Enregistrement (push-to-talk + toggle) ------------------------------

    def _start(self, mode: str):
        with self._state_lock:
            if self.recording or self.busy or self.stt is None:
                return
            self.recording = True
            self.record_mode = mode
        self.record_started_at = time.monotonic()
        self.recorder.start()
        self.set_tray(True)
        self.overlay.show_recording()
        self.beep(880, 70)
        self._set_status("recording_toggle" if mode == "toggle" else "recording_ptt")
        log(f"[debug] start ({mode})")
        if mode == "toggle":
            threading.Thread(target=self._toggle_watchdog, daemon=True).start()

    def _stop_and_process(self):
        with self._state_lock:
            if not self.recording:
                return
            self.recording = False
            mode = self.record_mode
            self.record_mode = None
            self.busy = True
        duration = time.monotonic() - self.record_started_at
        samples = self.recorder.stop()
        self.set_tray(False)
        peak = float(np.abs(samples).max()) if samples.size else 0.0
        log(f"[debug] stop ({mode}) {duration:.2f}s, {samples.size} éch., pic {peak:.3f}")

        if duration < self.cfg["min_duration_s"] or samples.size == 0:
            self.busy = False
            self.overlay.hide()
            self._set_status("ready")
            return  # appui accidentel
        if peak < self.cfg.get("min_peak", 0.008):
            # Quasi-silence : le beam + vocab boosté peut halluciner sur le bruit.
            self.busy = False
            self.overlay.hide()
            self.beep(300, 150)
            self._set_status("ready")
            return
        max_samples = int(self.cfg["max_duration_s"] * self.cfg["sample_rate"])
        samples = samples[:max_samples]

        self.overlay.show_processing()
        self._set_status("processing")
        threading.Thread(
            target=self._transcribe_and_paste, args=(samples, duration), daemon=True
        ).start()

    def _toggle_watchdog(self):
        """Sécurité mains-libres : coupe un toggle oublié à max_duration_s."""
        limit = self.cfg["max_duration_s"]
        while True:
            with self._state_lock:
                still_on = self.recording and self.record_mode == "toggle"
            if not still_on:
                return
            if time.monotonic() - self.record_started_at >= limit:
                log("[debug] toggle : limite de durée atteinte, arrêt auto")
                self.beep(500, 120)
                self._stop_and_process()
                return
            time.sleep(0.5)

    def _apply_corrections(self, text: str) -> str:
        for rx, replacement in self._corrections:
            text = rx.sub(replacement, text)
        return text

    def _transcribe_and_paste(self, samples: np.ndarray, duration: float):
        try:
            t0 = time.perf_counter()
            text = self._apply_corrections(self.stt.transcribe(samples))
            dt = time.perf_counter() - t0
            if text:
                paste_text(text, self.cfg["restore_clipboard"])
                log(f"[{duration:.1f}s audio → {dt:.2f}s] {text}")
                self.on_event(
                    "transcription",
                    {
                        "time": time.strftime("%H:%M:%S"),
                        "text": text,
                        "audio_s": duration,
                        "proc_s": dt,
                    },
                )
            else:
                self.beep(300, 150)  # rien reconnu
        except Exception as e:
            log(f"Erreur : {e}")
            self.beep(200, 300)
            self.on_event("notice", f"Erreur transcription : {e}")
        finally:
            self.busy = False
            self.overlay.hide()
            self._set_status("ready")

    # --- Hooks clavier -------------------------------------------------------

    def _make_hook(self, trigger: str, entries: list[tuple[list[str], str]]):
        """Hook bloquant du `trigger`, partagé par tous ses combos (voir README)."""

        def hook(event):
            if event.event_type == "down":
                active = next(
                    (
                        (mods, mode)
                        for mods, mode in entries
                        if all(keyboard.is_pressed(m) for m in mods)
                    ),
                    None,
                )
                if self._held.get(trigger):
                    return False if (active or self.recording) else True
                self._held[trigger] = True
                if self.busy:
                    return False if active else True
                if active is None:
                    return True  # trigger sans ses modificateurs = touche normale
                _, mode = active
                if mode == "ptt":
                    if not self.recording:
                        self._start("ptt")
                elif self.recording and self.record_mode == "toggle":
                    self._stop_and_process()  # 2e appui = fin du mains-libres
                elif not self.recording:
                    self._start("toggle")  # 1er appui = début du mains-libres
                return False
            self._held[trigger] = False
            if self.recording and self.record_mode == "ptt":
                self._stop_and_process()  # PTT : le relâchement arrête
                return False
            return False if self.recording else True  # toggle : ne stoppe pas

        return hook

    def _single_press(self, mode: str, trigger: str):
        """Touche seule (ex. right ctrl), non suppressive : garde anti auto-repeat."""
        if self._held.get(trigger):
            return
        self._held[trigger] = True
        if self.busy:
            return
        if mode == "ptt":
            if not self.recording:
                self._start("ptt")
        elif self.recording and self.record_mode == "toggle":
            self._stop_and_process()
        elif not self.recording:
            self._start("toggle")

    def _single_release(self, mode: str, trigger: str):
        self._held[trigger] = False
        if mode == "ptt" and self.recording and self.record_mode == "ptt":
            self._stop_and_process()

    def bind_hotkeys(self):
        """(Re)installe les hooks depuis la config. Repartir d'une table propre."""
        keyboard.unhook_all()
        self._held.clear()
        ptt = self.cfg.get("hotkey", "ctrl+space")
        toggle = self.cfg.get("toggle_hotkey") or None

        triggers: dict[str, list[tuple[list[str], str]]] = {}

        def add(hk: str, mode: str):
            parts = [p.strip() for p in hk.split("+")]
            triggers.setdefault(parts[-1], []).append((parts[:-1], mode))

        add(ptt, "ptt")
        if toggle:
            add(toggle, "toggle")

        for trig, entries in triggers.items():
            entries.sort(key=lambda e: -len(e[0]))  # plus spécifique d'abord
            if any(mods for mods, _ in entries):
                keyboard.hook_key(trig, self._make_hook(trig, entries), suppress=True)
            else:
                mode = entries[0][1]
                keyboard.on_press_key(
                    trig, lambda e, m=mode, t=trig: self._single_press(m, t), suppress=False
                )
                keyboard.on_release_key(
                    trig, lambda e, m=mode, t=trig: self._single_release(m, t), suppress=False
                )
        log(f"Raccourcis : PTT [{ptt}]" + (f" · toggle [{toggle}]" if toggle else ""))

    # --- Réglages (appelés depuis l'UI, thread principal) --------------------

    def apply_settings(self, s: dict):
        cfg = self.cfg
        rebind = (
            s["hotkey"] != cfg.get("hotkey")
            or (s.get("toggle_hotkey") or None) != (cfg.get("toggle_hotkey") or None)
        )
        device_changed = s.get("device") != cfg.get("device")
        reload_needed = abs(
            float(s["vocab_score"]) - float(cfg.get("vocab_score", 2.0))
        ) > 1e-9

        cfg["hotkey"] = s["hotkey"]
        cfg["toggle_hotkey"] = s.get("toggle_hotkey") or None
        cfg["device"] = s.get("device")
        cfg["sounds"] = bool(s["sounds"])
        cfg["restore_clipboard"] = bool(s["restore_clipboard"])
        cfg["min_peak"] = float(s["min_peak"])
        cfg["vocab_score"] = float(s["vocab_score"])
        cfg["overlay"] = bool(s["overlay"])
        self.overlay.set_enabled(cfg["overlay"])
        save_config(cfg)

        if rebind:
            self.bind_hotkeys()
        if device_changed and not self.recording:
            try:
                self.recorder.set_device(cfg["device"])
            except Exception as e:
                self.on_event("notice", f"Micro indisponible : {e}")
        if reload_needed:
            self.reload_async()
        else:
            self.on_event("notice", "Réglages appliqués")

    def save_vocab_text(self, text: str):
        with open(vocab_path(self.cfg), "w", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n")
        self.reload_async()  # le vocab est figé dans le décodeur → rebuild

    def save_corrections(self, corrections: dict):
        self.cfg["corrections"] = corrections
        self._corrections = compile_corrections(corrections)
        save_config(self.cfg)
        self.on_event("notice", "Corrections enregistrées")

    def shutdown(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


_SINGLE_INSTANCE_MUTEX = None  # gardé en vie tant que le process tourne


def ensure_single_instance():
    """Empêche une 2e instance (donc un 2e hook clavier qui doublerait l'espace)."""
    global _SINGLE_INSTANCE_MUTEX
    import ctypes

    ERROR_ALREADY_EXISTS = 183
    _SINGLE_INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(
        None, False, "PersonalWhisper_SingleInstance_Mutex"
    )
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        log("PersonalWhisper tourne déjà — cette instance se ferme.")
        sys.exit(0)


def main():
    ensure_single_instance()
    start_in_tray = "--tray" in sys.argv
    cfg = load_config()

    import webview  # import tardif : app.py reste importable sans backend GUI
    from webui import Api

    overlay = Overlay(enabled=cfg.get("overlay", True))  # HUD : root Tk dédié (thread)
    api = Api(cfg)
    engine = Engine(cfg, overlay, on_event=api._emit)

    window = webview.create_window(
        "PersonalWhisper",
        url=os.path.join(APP_DIR, "web", "index.html"),
        js_api=api,
        width=640,
        height=800,
        min_size=(560, 680),
        background_color="#14110D",
        frameless=True,
        easy_drag=False,   # drag seulement via .pywebview-drag-region (la barre de titre)
        resizable=True,
        hidden=start_in_tray,
    )
    api._attach(engine, window)

    # Tray : menu Ouvrir / Quitter (double-clic = Ouvrir). run_detached car la
    # boucle principale appartient à webview.
    menu = pystray.Menu(
        pystray.MenuItem(
            "Ouvrir PersonalWhisper", lambda i, it: window.show(), default=True
        ),
        pystray.MenuItem("Quitter", lambda i, it: api.quit_app()),
    )
    icon = pystray.Icon("PersonalWhisper", make_icon(False), "PersonalWhisper", menu)
    engine.icon = icon
    icon.run_detached()

    def _boot():
        try:
            engine.load_model()
            engine.bind_hotkeys()
            engine.beep(660, 60)
            api._emit("status", "ready")
            api._emit("model_ready", None)
        except Exception as e:
            log(f"Erreur au démarrage : {e}")
            api._emit("notice", f"Erreur démarrage : {e}")

    threading.Thread(target=_boot, daemon=True).start()

    webview.start(gui="edgechromium", debug=False)  # bloque jusqu'à destruction
    engine.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
