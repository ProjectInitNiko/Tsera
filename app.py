"""PersonalWhisper — dictée locale push-to-talk.

Maintenir la combinaison configurée (défaut : Ctrl + Espace), parler, relâcher :
le texte transcrit se colle au curseur, dans n'importe quelle application.
Pendant la dictée, un HUD « NK » avec les vagues de son s'affiche en bas d'écran.

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


def load_config() -> dict:
    with open(os.path.join(APP_DIR, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def load_vocab(cfg: dict) -> list[str]:
    """Mots du vocabulaire custom (vocab.txt) — lignes vides et # ignorées."""
    path = os.path.join(APP_DIR, cfg.get("vocab_file", "vocab.txt"))
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [w for w in (line.strip() for line in f) if w and not w.startswith("#")]


class Recorder:
    """Flux micro ouvert en continu ; on ne garde les frames que pendant la dictée."""

    def __init__(self, sample_rate: int, on_level=None):
        self.sample_rate = sample_rate
        self._chunks: list[np.ndarray] = []
        self._active = False
        self._lock = threading.Lock()
        self._on_level = on_level  # rms du chunk courant, pour le HUD
        self._stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

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


class App:
    def __init__(self):
        self.cfg = load_config()
        self.overlay = Overlay(enabled=self.cfg.get("overlay", True))
        self.recorder = Recorder(self.cfg["sample_rate"], on_level=self.overlay.push_level)
        self.recording = False
        self.record_mode: str | None = None  # "ptt" (maintenu) | "toggle" (mains-libres)
        self.record_started_at = 0.0
        self.busy = False
        self.icon: pystray.Icon | None = None
        self._held: dict[str, bool] = {}      # trigger enfoncé (garde anti auto-repeat)
        self._state_lock = threading.Lock()   # transitions recording/busy atomiques

        # Corrections post-transcription (casse + cafouillages connus),
        # les clés les plus longues d'abord pour que « robo dk » passe avant « dk ».
        self._corrections = [
            (re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE), v)
            for k, v in sorted(
                self.cfg.get("corrections", {}).items(), key=lambda kv: -len(kv[0])
            )
        ]

        print("Chargement du modèle…", flush=True)
        vocab = load_vocab(self.cfg)
        self.stt = Transcriber(
            model_dir=os.path.join(APP_DIR, self.cfg["model_dir"]),
            num_threads=self.cfg["num_threads"],
            sample_rate=self.cfg["sample_rate"],
            vocab=vocab,
            vocab_score=self.cfg.get("vocab_score", 2.0),
        )
        mode = f"{len(vocab)} mots boostés (beam search)" if vocab else "aucun (greedy)"
        print(
            f"Modèle chargé en {self.stt.load_time:.1f} s — vocabulaire : {mode}",
            flush=True,
        )

    # --- Feedback -----------------------------------------------------------

    def beep(self, freq: int, ms: int):
        if self.cfg["sounds"]:
            threading.Thread(
                target=winsound.Beep, args=(freq, ms), daemon=True
            ).start()

    def set_tray(self, recording: bool):
        if self.icon is not None:
            self.icon.icon = make_icon(recording)

    # --- Enregistrement (push-to-talk + toggle) -----------------------------

    def _start(self, mode: str):
        """Démarre un enregistrement. `mode` = "ptt" (maintenu) ou "toggle" (mains-libres)."""
        with self._state_lock:
            if self.recording or self.busy:
                return
            self.recording = True
            self.record_mode = mode
        self.record_started_at = time.monotonic()
        self.recorder.start()
        self.set_tray(True)
        self.overlay.show_recording()
        self.beep(880, 70)
        print(f"[debug] start ({mode})", flush=True)
        if mode == "toggle":
            threading.Thread(target=self._toggle_watchdog, daemon=True).start()

    def _stop_and_process(self):
        """Arrête l'enregistrement en cours et lance la transcription si pertinent."""
        with self._state_lock:
            if not self.recording:
                return
            self.recording = False
            mode = self.record_mode
            self.record_mode = None
            self.busy = True  # verrouille tout de suite : pas de nouvel enregistrement
        duration = time.monotonic() - self.record_started_at
        samples = self.recorder.stop()
        self.set_tray(False)
        peak = float(np.abs(samples).max()) if samples.size else 0.0
        print(
            f"[debug] stop ({mode}) {duration:.2f}s, {samples.size} éch., pic {peak:.3f}",
            flush=True,
        )

        if duration < self.cfg["min_duration_s"] or samples.size == 0:
            self.busy = False
            self.overlay.hide()
            return  # appui accidentel
        if peak < self.cfg.get("min_peak", 0.008):
            # Quasi-silence : le beam search + vocabulaire boosté peut
            # halluciner un mot sur du bruit de fond, on n'envoie rien.
            self.busy = False
            self.overlay.hide()
            self.beep(300, 150)
            return
        max_samples = int(self.cfg["max_duration_s"] * self.cfg["sample_rate"])
        samples = samples[:max_samples]

        self.overlay.show_processing()
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
                print("[debug] toggle : limite de durée atteinte, arrêt auto", flush=True)
                self.beep(500, 120)
                self._stop_and_process()
                return
            time.sleep(0.5)

    # --- Hooks clavier (combo suppressif + touche seule) ---------------------

    def _make_hook(self, trigger: str, entries: list[tuple[list[str], str]]):
        """Fabrique le hook bloquant du `trigger`, partagé par tous ses combos.

        `entries` = [(modificateurs, mode), …] trié du plus spécifique au plus
        général (ex. ctrl+shift avant ctrl). Retourner False avale l'événement :
        indispensable pour l'espace, sinon chaque appui (et l'auto-repeat pendant
        la dictée) taperait un espace dans l'application active.
        """

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
                    # auto-repeat : on avale tant qu'un combo est actif / qu'on dicte
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
            # relâchement
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
                print(f"[{duration:.1f}s audio → {dt:.2f}s] {text}", flush=True)
            else:
                self.beep(300, 150)  # rien reconnu
        except Exception as e:
            print(f"Erreur : {e}", file=sys.stderr, flush=True)
            self.beep(200, 300)
        finally:
            self.busy = False
            self.overlay.hide()

    # --- Lancement ----------------------------------------------------------

    def run(self):
        dev = sd.query_devices(kind="input")
        print(f"[debug] micro : {dev['name']}", flush=True)

        ptt = self.cfg.get("hotkey", "ctrl+space")
        toggle = self.cfg.get("toggle_hotkey") or None

        # Regroupe les raccourcis par touche de déclenchement : push-to-talk et
        # toggle peuvent partager le même trigger (ex. « space ») → un seul hook
        # qui choisit le mode selon les modificateurs réellement enfoncés.
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
                # Touche seule (legacy) : non suppressive pour ne rien avaler.
                mode = entries[0][1]
                keyboard.on_press_key(
                    trig, lambda e, m=mode, t=trig: self._single_press(m, t), suppress=False
                )
                keyboard.on_release_key(
                    trig, lambda e, m=mode, t=trig: self._single_release(m, t), suppress=False
                )

        toggle_label = f"  ·  toggle [{toggle}]" if toggle else ""
        menu = pystray.Menu(
            pystray.MenuItem(
                f"PersonalWhisper — maintenir [{ptt}]{toggle_label}", None, enabled=False
            ),
            pystray.MenuItem("Quitter", self._quit),
        )
        self.icon = pystray.Icon("PersonalWhisper", make_icon(False), "PersonalWhisper", menu)
        ready = f"Prêt. Maintiens [{ptt}] pour dicter"
        ready += f", ou [{toggle}] en mains-libres." if toggle else "."
        print(ready, flush=True)
        self.beep(660, 60)
        self.icon.run()  # bloque jusqu'à Quitter

    def _quit(self, icon, _item):
        keyboard.unhook_all()
        icon.stop()
        os._exit(0)


if __name__ == "__main__":
    App().run()
