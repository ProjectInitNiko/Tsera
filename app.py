"""PersonalWhisper — dictée locale push-to-talk.

Maintenir la combinaison configurée (défaut : Ctrl + Espace), parler, relâcher :
le texte transcrit se colle au curseur, dans n'importe quelle application.
Pendant la dictée, un HUD « NK » avec les vagues de son s'affiche en bas d'écran.

Tout tourne en local (Parakeet v3 via sherpa-onnx, CPU). Aucune donnée ne sort du PC.
"""

import json
import os
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


def load_config() -> dict:
    with open(os.path.join(APP_DIR, "config.json"), encoding="utf-8") as f:
        return json.load(f)


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
        self.record_started_at = 0.0
        self.busy = False
        self.icon: pystray.Icon | None = None

        print("Chargement du modèle…", flush=True)
        self.stt = Transcriber(
            model_dir=os.path.join(APP_DIR, self.cfg["model_dir"]),
            num_threads=self.cfg["num_threads"],
            sample_rate=self.cfg["sample_rate"],
        )
        print(f"Modèle chargé en {self.stt.load_time:.1f} s", flush=True)

    # --- Feedback -----------------------------------------------------------

    def beep(self, freq: int, ms: int):
        if self.cfg["sounds"]:
            threading.Thread(
                target=winsound.Beep, args=(freq, ms), daemon=True
            ).start()

    def set_tray(self, recording: bool):
        if self.icon is not None:
            self.icon.icon = make_icon(recording)

    # --- Push-to-talk -------------------------------------------------------

    def on_press(self, event):
        print(f"[debug] press: {event.name} (scan {event.scan_code})", flush=True)
        if self.recording or self.busy:
            return
        self.recording = True
        self.record_started_at = time.monotonic()
        self.recorder.start()
        self.set_tray(True)
        self.overlay.show_recording()
        self.beep(880, 70)

    def on_release(self, event):
        print(f"[debug] release: {event.name}", flush=True)
        if not self.recording:
            return
        self.recording = False
        duration = time.monotonic() - self.record_started_at
        samples = self.recorder.stop()
        self.set_tray(False)
        peak = float(np.abs(samples).max()) if samples.size else 0.0
        print(
            f"[debug] {duration:.2f}s, {samples.size} échantillons, pic {peak:.3f}",
            flush=True,
        )

        if duration < self.cfg["min_duration_s"] or samples.size == 0:
            self.overlay.hide()
            return  # appui accidentel
        max_samples = int(self.cfg["max_duration_s"] * self.cfg["sample_rate"])
        samples = samples[:max_samples]

        self.busy = True
        self.overlay.show_processing()
        threading.Thread(
            target=self._transcribe_and_paste, args=(samples, duration), daemon=True
        ).start()

    # --- Combo modificateur + touche (ex. ctrl+space) -------------------------

    def _modifiers_down(self) -> bool:
        return all(keyboard.is_pressed(m) for m in self._modifiers)

    def _combo_hook(self, event):
        """Hook bloquant sur la touche de déclenchement.

        Retourner False avale l'événement : indispensable pour l'espace, sinon
        chaque appui (et l'auto-repeat pendant la dictée) taperait des espaces
        dans l'application active.
        """
        if event.event_type == "down":
            if self.recording:
                return False  # auto-repeat pendant la dictée
            if self._modifiers_down():
                if not self.busy:
                    self.on_press(event)
                return False
            return True  # touche seule : comportement normal
        # relâchement
        if self.recording:
            self.on_release(event)
            return False
        return True

    def _transcribe_and_paste(self, samples: np.ndarray, duration: float):
        try:
            t0 = time.perf_counter()
            text = self.stt.transcribe(samples)
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
        hotkey = self.cfg["hotkey"]
        if "+" in hotkey:
            # Combo « modificateurs + déclencheur » (ex. ctrl+space) : hook
            # bloquant sur le déclencheur, modificateurs vérifiés à la volée.
            parts = [p.strip() for p in hotkey.split("+")]
            self._modifiers, trigger = parts[:-1], parts[-1]
            keyboard.hook_key(trigger, self._combo_hook, suppress=True)
        else:
            keyboard.on_press_key(hotkey, self.on_press, suppress=False)
            keyboard.on_release_key(hotkey, self.on_release, suppress=False)

        menu = pystray.Menu(
            pystray.MenuItem(f"PersonalWhisper — maintenir [{hotkey}]", None, enabled=False),
            pystray.MenuItem("Mode : Brut", None, enabled=False),
            pystray.MenuItem("Quitter", self._quit),
        )
        self.icon = pystray.Icon("PersonalWhisper", make_icon(False), "PersonalWhisper", menu)
        print(f"Prêt. Maintiens [{hotkey}] pour dicter.", flush=True)
        self.beep(660, 60)
        self.icon.run()  # bloque jusqu'à Quitter

    def _quit(self, icon, _item):
        keyboard.unhook_all()
        icon.stop()
        os._exit(0)


if __name__ == "__main__":
    App().run()
