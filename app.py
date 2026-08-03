"""Tsera — dictée locale (push-to-talk + toggle mains-libres) avec UI.

Deux raccourcis globaux :
  - maintenir Ctrl+Espace          → push-to-talk
  - Ctrl+Shift+Espace (1 appui/1)  → toggle mains-libres
Le texte transcrit se colle au curseur, dans n'importe quelle application.

L'interface (web embarquée, pywebview) montre le statut live, l'historique des
dictées et les réglages (langue, raccourcis, micro, vocabulaire, corrections).
Fermer la fenêtre la réduit dans la barre système ; l'app continue d'écouter.
Lancer avec `--tray` pour démarrer réduit (utilisé par le démarrage auto).
Interface en anglais par défaut, français au choix dans les réglages.

Tout tourne en local (Parakeet v3 via sherpa-onnx, CPU). Aucune donnée ne sort du PC.
"""

import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import winsound

import keyboard
import numpy as np
import pyperclip
import pystray
import sounddevice as sd
from PIL import Image

from make_icon import AMBER as _ICON_AMBER
from make_icon import render as _icon_render
from overlay import Overlay
from stt import Transcriber

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Modèle géorgien : nvidia/stt_ka_fastconformer_hybrid_large_pc (CC-BY-4.0),
# export ONNX de LukeJacob2023. Même famille que Parakeet (NeMo transducer),
# donc il se charge par le même chemin. Parakeet reste le modèle par défaut.
MODEL_DIR_KA = "sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc"

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


# Défauts complets : chaque clé lue ailleurs par cfg[...] doit exister ici.
# Un config.json partiel, absent ou corrompu ne doit JAMAIS empêcher le boot.
DEFAULTS: dict = {
    "hotkey": "ctrl+space",
    "toggle_hotkey": "ctrl+shift+space",
    "model_dir": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
    "model_dir_ka": MODEL_DIR_KA,
    "dictation_lang": "multi",
    "num_threads": 4,
    "sample_rate": 16000,
    "device": None,
    "device_name": None,
    "min_duration_s": 0.3,
    "max_duration_s": 120,
    "min_peak": 0.008,
    "sounds": True,
    "restore_clipboard": True,
    "overlay": True,
    "vocab_file": "vocab.txt",
    "vocab_score": 2.0,
    "corrections": {},
    "lang": "en",
}

_CONFIG_LOCK = threading.Lock()  # save_config est appelé depuis plusieurs threads


def _alert(msg: str):
    """Erreur visible même sous pythonw (pas de console : print serait muet)."""
    log(msg)
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, msg, "Tsera", 0x00000030)  # MB_ICONWARNING
    except Exception:
        pass


def load_config() -> dict:
    """DÉFAUTS ← config.json (créé depuis config.example.json au 1er lancement).

    Un fichier absent, tronqué ou invalide ne brique pas l'app : on repart des
    défauts, on met le fichier fautif de côté (.broken) et on prévient."""
    cfg = dict(DEFAULTS)
    path = config_path()
    if not os.path.exists(path):
        for src, dst in (
            ("config.example.json", path),
            ("vocab.example.txt", os.path.join(APP_DIR, "vocab.txt")),
        ):
            example = os.path.join(APP_DIR, src)
            if not os.path.exists(dst) and os.path.exists(example):
                try:
                    shutil.copyfile(example, dst)
                except OSError:
                    pass
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except FileNotFoundError:
        save_config(cfg)  # pas d'exemple non plus : écrit les défauts
    except (OSError, json.JSONDecodeError) as e:
        _alert(f"config.json illisible ({e}).\nRéglages par défaut utilisés ; "
               f"l'ancien fichier est conservé en config.json.broken.")
        try:
            os.replace(path, path + ".broken")
        except OSError:
            pass
        save_config(cfg)
    return cfg


def save_config(cfg: dict):
    """Écriture atomique (tmp + os.replace) : un crash ou un quit_app en plein
    milieu ne peut pas laisser un config.json tronqué qui bloquerait tous les
    lancements suivants."""
    path = config_path()
    tmp = path + ".tmp"
    with _CONFIG_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)


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
    """Micro ouvert PENDANT la dictée seulement, puis rendu au système.

    Le flux était auparavant ouvert en continu, pour épargner le délai
    d'ouverture au moment d'appuyer. C'était intenable avec un casque USB :
    beaucoup n'exposent qu'une seule interface audio et **ne peuvent pas
    capter et restituer en même temps**. Mesuré sur le casque de référence —
    tant que son micro est tenu ouvert, sa sortie répond « Device
    unavailable » ; Windows bascule le son sur les haut-parleurs et les
    lecteurs vidéo qui tenaient ce point de sortie s'arrêtent sans repartir.
    Tsera tournant en permanence, la panne durait aussi longtemps que l'app.

    Ouvrir à la demande coûte 13 à 95 ms selon le périphérique, largement
    sous le temps qu'on met à commencer à parler après avoir appuyé."""

    def __init__(self, sample_rate: int, device=None, on_level=None, candidates=None):
        self.sample_rate = sample_rate
        self.device = device
        # Index PortAudio du MÊME micro physique vus par des hôtes audio
        # différents, par ordre de préférence. Les épuiser avant de changer de
        # micro : si WASAPI refuse le 16 kHz, on rebascule sur le même casque
        # en MME au lieu de sauter silencieusement sur un autre micro.
        self.candidates: list = list(candidates) if candidates else []
        self.fallback: str | None = None  # nom du micro de repli, le cas échéant
        self._chunks: list[np.ndarray] = []
        self._active = False
        self._lock = threading.Lock()
        self._on_level = on_level  # rms du chunk courant, pour le HUD
        self._stream = None
        # Fréquence réellement obtenue à l'ouverture : elle peut différer de
        # celle attendue par le modèle, auquel cas `stop` rééchantillonne.
        self.capture_rate = sample_rate
        # Volontairement AUCUNE ouverture ici : construire un Recorder ne doit
        # rien prendre au système. Le micro n'est saisi qu'au premier `start`.

    def _try_open(self, device):
        """Ouvre au taux voulu si le périphérique l'accepte, sinon à son taux
        natif — WASAPI en mode partagé n'accepte que celui-là. Le taux
        réellement obtenu est retenu : `stop` rééchantillonne si besoin."""
        try:
            info = sd.query_devices(device) if device is not None else sd.query_devices(kind="input")
        except Exception:
            info = {}
        reglages = _wasapi_settings(device)
        last: Exception | None = None
        for sr in _open_rates(info, self.sample_rate):
            try:
                stream = sd.InputStream(
                    samplerate=sr,
                    channels=1,
                    dtype="float32",
                    device=device,
                    callback=self._callback,
                    extra_settings=reglages,
                )
                stream.start()
            except Exception as e:
                last = e
                continue
            self._stream = stream
            self.capture_rate = sr
            return
        raise last if last is not None else RuntimeError("no usable sample rate")

    def _open(self):
        """Ouvre le micro choisi, sinon replis en trois temps : ses autres
        hôtes audio (même matériel), le défaut système, puis n'importe quel
        micro qui s'ouvre RÉELLEMENT. check_input_settings ne suffit pas — il
        valide un format sans ouvrir, et un périphérique tenu par une autre
        app (Discord…) passe le check puis échoue à l'ouverture. Seul le
        premier temps garde le micro voulu : les deux autres changent de
        matériel et sont donc signalés dans `self.fallback`."""
        self.fallback = None
        last_error: Exception | None = None
        # 1) le micro choisi, par chacun de ses hôtes audio
        for cand in self.candidates or [self.device]:
            try:
                self._try_open(cand)
                return  # même micro physique : rien à signaler
            except Exception as e:
                last_error = e
        # 2) défaut système
        if self.device is not None:
            try:
                self._try_open(None)
                try:
                    self.fallback = sd.query_devices(kind="input")["name"]
                except Exception:
                    self.fallback = "system default"
                return
            except Exception as e:
                last_error = e
        # 3) n'importe quel autre micro
        tried = set(self.candidates) | {self.device}
        for dev in input_devices(self.sample_rate):
            idx = dev["index"]
            if idx in tried:
                continue
            try:
                self._try_open(idx)
                self.fallback = dev["name"]
                return
            except Exception as e:
                last_error = e
        self._stream = None
        raise last_error if last_error is not None else RuntimeError("no input device")

    # Pas de `alive()` : hors dictée le flux est fermé par construction, donc
    # un tel indicateur serait faux en fonctionnement normal. Le seul détecteur
    # fiable d'un micro mort reste « zéro échantillon capté », dans
    # _stop_and_process — certains hôtes laissent `active` à True après un
    # débranchement.

    def close(self):
        self._active = False
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None

    def set_device(self, device, candidates=None):
        """Change de micro. Rien n'est ouvert : la prochaine dictée s'en
        chargera. Changer de micro dans les réglages ne doit pas saisir le
        périphérique, sans quoi choisir un casque USB couperait sa sortie."""
        self.close()
        self.device = device
        self.candidates = list(candidates) if candidates else []
        self.fallback = None

    def _callback(self, indata, frames, time_info, status):
        # Une exception qui s'échappe d'un callback PortAudio tue le flux
        # définitivement (error=paAbort) — et sous pythonw, sans traceback.
        try:
            if self._active:
                chunk = indata[:, 0].copy()
                with self._lock:
                    self._chunks.append(chunk)
                if self._on_level is not None:
                    self._on_level(float(np.sqrt(np.mean(chunk * chunk))))
        except Exception:
            pass

    def start(self):
        """Saisit le micro puis démarre la capture. Lève si rien ne s'ouvre —
        c'est à l'appelant de prévenir et d'abandonner la dictée."""
        with self._lock:
            self._chunks = []
        if self._stream is None:
            self._open()
        self._active = True

    def stop(self) -> np.ndarray:
        """Arrête la capture ET rend le périphérique au système. Le casque USB
        doit récupérer sa sortie dès la fin de la dictée, pas à la fermeture
        de l'app."""
        self._active = False
        with self._lock:
            data = (np.concatenate(self._chunks) if self._chunks
                    else np.zeros(0, dtype=np.float32))
        capte = self.capture_rate
        self.close()
        # Ramené au taux du modèle. Sans conversion, une capture à 48 kHz lue
        # comme du 16 kHz durerait trois fois trop longtemps et sonnerait trois
        # fois trop grave : le modèle n'y reconnaîtrait rien.
        return _resample(data, capte, self.sample_rate)


_RESTORE_TOKEN = None  # dernier paste_text en date : seul son restore est valable


def paste_text(text: str, restore_clipboard: bool):
    """Colle `text` au curseur via le presse-papiers + Ctrl+V simulé."""
    global _RESTORE_TOKEN
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
        # Laisse le temps à l'app cible de lire le presse-papiers avant
        # restauration. Deux gardes contre la restauration aveugle : un token
        # (chaque nouveau collage invalide les restores en attente) et une
        # vérification de contenu (si l'utilisateur — ou le bouton Copier de
        # l'historique — a écrit autre chose entre-temps, on n'écrase pas).
        token = object()
        _RESTORE_TOKEN = token

        def _restore():
            time.sleep(0.6)
            if _RESTORE_TOKEN is not token:
                return
            try:
                if pyperclip.paste() == text:
                    pyperclip.copy(old)
            except Exception:
                pass

        threading.Thread(target=_restore, daemon=True).start()


# Libellés visibles côté Python (barre système, notices). L'anglais est la
# langue par défaut de l'app ; l'interface, elle, se traduit dans web/i18n.js.
STRINGS = {
    "en": {
        "open": "Open Tsera",
        "quit": "Quit",
        "copied": "Copied to clipboard",
        "startup_error": "Startup error: {}",
        "mic_unavailable": "Microphone unavailable: {}",
        "settings_applied": "Settings applied",
        "vocab_saved": "Vocabulary reloaded",
        "corr_saved": "Corrections saved",
        "reload_error": "Reload error: {}",
        "stt_error": "Transcription error: {}",
        "bad_hotkey": "Invalid hotkey \"{}\" — settings not saved",
        "mic_fallback": "Configured microphone unavailable — using: {}",
        "mic_none": "No working microphone found ({}). Dictation paused — plug one in and try again.",
        "mic_dead": "No audio captured — the microphone stream was dead. Reopened, try again.",
        "model_missing": "Model folder missing: {}. See README (Setup) to download it, then restart.",
        "save_error": "Could not save settings: {}",
    },
    "fr": {
        "open": "Ouvrir Tsera",
        "quit": "Quitter",
        "copied": "Copié dans le presse-papiers",
        "startup_error": "Erreur au démarrage : {}",
        "mic_unavailable": "Micro indisponible : {}",
        "settings_applied": "Réglages appliqués",
        "vocab_saved": "Vocabulaire rechargé",
        "corr_saved": "Corrections enregistrées",
        "reload_error": "Erreur de rechargement : {}",
        "stt_error": "Erreur de transcription : {}",
        "bad_hotkey": "Raccourci invalide « {} » — réglages non enregistrés",
        "mic_fallback": "Micro configuré indisponible — bascule sur : {}",
        "mic_none": "Aucun micro fonctionnel ({}). Dictée en pause — branche un micro et réessaie.",
        "mic_dead": "Aucun audio capté — le flux micro était mort. Rouvert, réessaie.",
        "model_missing": "Dossier du modèle absent : {}. Voir le README (Setup) pour le télécharger, puis relance.",
        "save_error": "Impossible d'enregistrer les réglages : {}",
    },
}


def tr(lang: str, key: str) -> str:
    return STRINGS.get(lang if lang in STRINGS else "en", STRINGS["en"])[key]


def make_icon(recording: bool) -> Image.Image:
    """Icône tray : la pastille « TS », ambre au repos, rouge VU en dictée.

    Même dessin que `icon.ico` (raccourci Bureau) — une seule définition du
    sigle, dans make_icon.py, pour que les deux ne divergent jamais.
    """
    return _icon_render(64, (232, 67, 31, 255) if recording else _ICON_AMBER)


def compile_corrections(corrections: dict):
    """Regex mots-entiers, les clés les plus longues d'abord (« robo dk » avant « dk »)."""
    return [
        (re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE), v)
        for k, v in sorted(corrections.items(), key=lambda kv: -len(kv[0]))
    ]


# --- Micros ----------------------------------------------------------------
#
# Windows expose le MÊME micro par plusieurs hôtes audio : sur la machine de
# référence, 3 micros physiques produisaient 15 entrées dans le sélecteur, et
# 6 d'entre elles ne pouvaient PAS s'ouvrir à 16 kHz. On regroupe donc par
# micro physique et on n'affiche qu'une entrée par micro.

# Ordre de préférence des hôtes audio.
#
# WASAPI d'abord, et c'est un choix mesuré, pas esthétique. Sur un casque USB
# qui n'expose qu'une interface, **ouvrir le micro par MME rend sa sortie
# indisponible** : Windows rabat le son sur les haut-parleurs et les lecteurs
# vidéo qui tenaient ce point de sortie s'arrêtent sans repartir. WASAPI en
# mode partagé n'a pas ce défaut — c'est la voie qu'empruntent Google Meet et
# les navigateurs, d'où le duplex qui « marche très bien » chez eux. Son seul
# prix est d'imposer la fréquence native du périphérique ; on capte donc au
# taux natif et on rééchantillonne (voir `_resample`).
#
# WDM-KS reste exclu : accès exclusif, donc il vole le micro aux autres
# applications et échoue lui-même dès qu'une autre le tient — testé, il passe
# et casse d'une minute à l'autre selon ce que fait le navigateur. Il nomme en
# plus le même matériel autrement que les autres hôtes.
_HOST_PREFERENCE = ("Windows WASAPI", "Windows DirectSound", "MME")

# Alias du défaut système exposés comme du matériel. La ligne « défaut
# système » du sélecteur les couvre déjà. Ces noms sont codés en dur dans
# PortAudio, donc identiques quelle que soit la langue de Windows.
_PSEUDO_DEVICES = ("microsoft sound mapper - input", "primary sound capture driver")


# MME coupe les noms à 31 caractères (MAXPNAMELEN, terminateur compris) :
# 'Microphone (2- High Definition ' est le même matériel que
# 'Microphone (2- High Definition Audio Device)'.
_MME_NAME_MAX = 31


def _lowpass(x: np.ndarray, cutoff: float, taps: int = 101) -> np.ndarray:
    """Passe-bas FIR (sinc fenêtré Hamming). `cutoff` en fraction de la
    fréquence d'échantillonnage, entre 0 et 0,5."""
    n = np.arange(taps) - (taps - 1) / 2.0
    h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(taps)
    h /= h.sum()
    return np.convolve(x, h, mode="same")


def _resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Mono float32 de `src` vers `dst` Hz.

    Écrit à la main plutôt qu'avec scipy : la seule fonction utile pèserait
    plus lourd que tout le reste des dépendances réunies, pour une app qu'on
    veut pouvoir empaqueter. Précision suffisante pour de la parole.

    Le passe-bas n'est pas optionnel en descente : sans lui, tout ce qui
    dépasse la nouvelle fréquence de Nyquist se replie dans la bande utile et
    le modèle entend un sifflement superposé à la voix."""
    if x.size == 0 or src == dst:
        return x.astype(np.float32, copy=False)
    if dst < src:
        x = _lowpass(x, cutoff=0.45 * dst / src)
    n = int(round(x.size * dst / float(src)))
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    pos = np.linspace(0.0, x.size - 1.0, n)
    return np.interp(pos, np.arange(x.size), x).astype(np.float32)


def _wasapi_settings(device):
    """`auto_convert` autorise WASAPI à convertir la fréquence à l'intérieur du
    moteur audio de Windows. Sans lui, le mode partagé n'accepte QUE le taux
    natif du périphérique et refuse nos 16 kHz — et c'était l'unique raison
    pour laquelle WASAPI avait été écarté, ce qui renvoyait la capture vers
    MME, l'hôte qui coupe la sortie des casques USB. C'est aussi ce que fait un
    navigateur : de là vient le duplex qui « marche très bien » sur Meet.

    `None` pour les autres hôtes, qui n'ont pas ce réglage."""
    try:
        info = sd.query_devices(device) if device is not None else sd.query_devices(kind="input")
        if sd.query_hostapis(info["hostapi"])["name"] != "Windows WASAPI":
            return None
        return sd.WasapiSettings(auto_convert=True)
    except Exception:
        return None


def _open_rates(dev: dict, wanted: int) -> list[int]:
    """Fréquences à essayer pour ce périphérique, dans l'ordre. Le taux voulu
    d'abord — s'il passe, aucun rééchantillonnage n'est nécessaire — puis le
    taux natif, seul accepté par WASAPI en mode partagé."""
    natif = int(dev.get("default_samplerate") or 0)
    return [wanted] + ([natif] if natif and natif != wanted else [])


def _same_mic(a: str, b: str) -> bool:
    """Deux libellés désignent-ils le même micro physique ?"""
    na, nb = " ".join(a.split()).casefold(), " ".join(b.split()).casefold()
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Sinon, seule une troncature MME peut expliquer l'écart. On exige que le
    # nom court soit coupé PILE à la limite de l'API : un préfixe accepté sans
    # cette condition confondrait deux micros bien distincts, du genre
    # 'Micro (USB Audio)' et 'Micro (USB Audio) 2'.
    if len(na) > len(nb):
        na, nb, a = nb, na, b
    return len(a.rstrip()) >= _MME_NAME_MAX - 1 and nb.startswith(na)


def input_devices(sample_rate: int) -> list[dict]:
    """Un enregistrement par micro PHYSIQUE : `{name, index, candidates}`.

    `candidates` liste tous les index PortAudio du même micro par ordre de
    préférence d'hôte, ce qui permet à Recorder de replier sans changer de
    matériel. Le tri par `check_input_settings` attrape le refus du 16 kHz par
    WASAPI pour 12 ms sur toute la liste, là où ouvrir réellement chaque
    entrée coûte 470 ms. Ce test ment encore sur la disponibilité de l'instant
    (un micro tenu par Discord le passe) : c'est l'ouverture qui tranche, d'où
    les candidats ordonnés plutôt qu'un index unique."""
    try:
        apis = sd.query_hostapis()
        devs = sd.query_devices()
    except Exception:
        return []

    groups: list[dict] = []
    for i, dev in enumerate(devs):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = str(dev.get("name", "")).strip()
        if not name or " ".join(name.split()).casefold() in _PSEUDO_DEVICES:
            continue
        try:
            host = apis[dev["hostapi"]]["name"]
        except Exception:
            continue
        if host not in _HOST_PREFERENCE:
            continue  # hôte écarté (WDM-KS)
        # Le taux voulu OU le taux natif suffit : ce qui n'entre pas en 16 kHz
        # est capté au taux du périphérique puis rééchantillonné. C'est ce qui
        # rend WASAPI utilisable, et donc le duplex possible sur un casque USB.
        reglages = _wasapi_settings(i)
        for sr in _open_rates(dev, sample_rate):
            try:
                sd.check_input_settings(
                    device=i, samplerate=sr, channels=1, dtype="float32",
                    extra_settings=reglages,
                )
                break
            except Exception:
                continue
        else:
            continue  # aucune fréquence acceptée : entrée morte

        rank = _HOST_PREFERENCE.index(host)
        for g in groups:
            if _same_mic(g["name"], name):
                g["_cands"].append((rank, i))
                # Le libellé affiché vient du nom le plus complet du groupe :
                # celui de l'hôte préféré peut être la troncature MME.
                if len(name) > len(g["name"]):
                    g["name"] = name
                break
        else:
            groups.append({"name": name, "_cands": [(rank, i)]})

    out = []
    for g in groups:
        idxs = [i for _, i in sorted(g["_cands"])]
        out.append({"name": g["name"], "index": idxs[0], "candidates": idxs})
    return out


def resolve_device(cfg: dict) -> tuple[object, list]:
    """(index préféré, candidats) du micro configuré, `(None, [])` pour le
    défaut système. L'identité stable est le NOM : les index PortAudio se
    décalent dès qu'un périphérique apparaît ou disparaît, donc un index brut
    peut désigner silencieusement un autre micro au lancement suivant."""
    name = cfg.get("device_name")
    idx = cfg.get("device")
    mics = input_devices(cfg.get("sample_rate", 16000))

    if name:
        for m in mics:
            if _same_mic(m["name"], name):
                return m["index"], m["candidates"]
    # Config historique sans nom : l'index brut sert une dernière fois, le
    # temps que save_settings réécrive un nom.
    if not name and isinstance(idx, int):
        for m in mics:
            if idx in m["candidates"]:
                return m["index"], m["candidates"]
    return None, []  # micro configuré introuvable → défaut système


def validate_hotkey(combo: str) -> str | None:
    """None si le combo est utilisable, sinon le fragment fautif.

    Vérifie exactement ce que bind_hotkeys installera (le trigger passe par
    hook_key) et ce que le hook interrogera (les modificateurs passent par
    is_pressed) : les deux résolvent via keyboard.key_to_scan_codes."""
    for part in (p.strip() for p in combo.split("+")):
        if not part:
            return combo
        try:
            keyboard.key_to_scan_codes(part)
        except Exception:
            return part
    return None


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
        self.reloading = False  # échange de modèle en cours : dictée en pause
        self.icon: pystray.Icon | None = None
        self.build_tray_menu = None  # posé par main() : (lang) → pystray.Menu
        self.status = "loading"
        self.stt: Transcriber | None = None
        self._held: dict[str, bool] = {}
        self._acted: dict[str, bool] = {}  # ce maintien a déjà déclenché son action
        self._state_lock = threading.Lock()
        self._corrections = compile_corrections(self.cfg.get("corrections", {}))
        # Les hooks clavier tournent DANS la procédure WH_KEYBOARD_LL de
        # Windows : tout travail lent là-dedans (tray PIL, overlay, evaluate_js,
        # numpy) gèle le clavier système entier, et au-delà de
        # LowLevelHooksTimeout (~200 ms) Windows retire le hook sans un mot.
        # Les hooks ne font donc que DÉCIDER ; les actions passent par cette
        # file, drainée par un unique worker (FIFO = ordre press/release sûr).
        self._work_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._work_loop, daemon=True).start()
        self.recorder = self._make_recorder()

    def _work_loop(self):
        while True:
            fn = self._work_q.get()
            try:
                fn()
            except Exception as e:
                log(f"[worker] {e}")

    def _defer(self, fn):
        self._work_q.put(fn)

    def _make_recorder(self) -> Recorder:
        """Prépare le micro SANS le saisir : le périphérique n'est ouvert qu'au
        moment de dicter. Ne peut donc plus échouer ici — les problèmes
        d'ouverture se signalent au premier appui, dans `_begin_capture`."""
        device, candidates = resolve_device(self.cfg)
        return Recorder(
            self.cfg["sample_rate"],
            device=device,
            on_level=self.overlay.push_level,
            candidates=candidates,
        )

    def _begin_capture(self) -> bool:
        """Saisit le micro et lance la capture. False si rien ne s'ouvre.
        Deux essais : le second repart d'un Recorder neuf, ce qui re-résout le
        micro configuré — il a pu être rebranché, ou libéré par une autre app,
        depuis le dernier échec."""
        lang = self.cfg.get("lang", "en")
        last: Exception | None = None
        for essai in (0, 1):
            if self.recorder is None:
                self.recorder = self._make_recorder()
            try:
                self.recorder.start()
            except Exception as e:
                last = e
                log(f"[mic] ouverture impossible (essai {essai + 1}) : {e}")
                old, self.recorder = self.recorder, None
                if old is not None:
                    old.close()
                continue
            if self.recorder.fallback:
                self.on_event("notice", tr(lang, "mic_fallback").format(self.recorder.fallback))
            return True
        self.on_event("notice", tr(lang, "mic_none").format(last))
        return False

    def _reopen_recorder(self):
        old, self.recorder = self.recorder, None
        if old is not None:
            old.close()
        self.recorder = self._make_recorder()

    def refresh_tray_menu(self, lang: str):
        """Réécrit le menu de la barre système dans la langue choisie."""
        if not self.icon or not self.build_tray_menu:
            return
        try:
            self.icon.menu = self.build_tray_menu(lang)
            self.icon.update_menu()
        except Exception:
            pass

    # --- Chargement du modèle ------------------------------------------------

    def model_dir(self) -> str:
        """Dossier du modèle correspondant à la langue de dictée choisie."""
        if self.cfg.get("dictation_lang") == "ka":
            return self.cfg.get("model_dir_ka", MODEL_DIR_KA)
        return self.cfg["model_dir"]

    def load_model(self):
        georgian = self.cfg.get("dictation_lang") == "ka"
        # Le vocabulaire custom (noms propres, marques) est écrit en alphabet
        # latin : le modèle géorgien n'a aucun token pour l'encoder, le biasing
        # n'aurait rien à quoi s'accrocher. On le laisse de côté dans ce mode.
        vocab = [] if georgian else load_vocab(self.cfg)
        log("Chargement du modèle…")
        self.stt = Transcriber(
            model_dir=os.path.join(APP_DIR, self.model_dir()),
            num_threads=self.cfg["num_threads"],
            sample_rate=self.cfg["sample_rate"],
            vocab=vocab,
            vocab_score=self.cfg.get("vocab_score", 2.0),
        )
        mode = f"{len(vocab)} mots boostés (beam search)" if vocab else "aucun (greedy)"
        log(f"Modèle chargé en {self.stt.load_time:.1f} s — "
            f"{'géorgien' if georgian else 'multilingue'} · vocabulaire : {mode}")

    def reload_async(self):
        """Reconstruit le transcriber (nouveau vocab / score) sans figer l'UI."""
        self.reloading = True  # bloque _start : pas de dictée pendant l'échange

        def _work():
            self._set_status("reloading")
            try:
                self.load_model()
                self.on_event("notice", tr(self.cfg.get("lang", "en"), "vocab_saved"))
            except Exception as e:
                log(f"Erreur reload : {e}")
                self.on_event("notice", tr(self.cfg.get("lang", "en"), "reload_error").format(e))
            finally:
                self.reloading = False
                # Pas de « ready » en dur : si une dictée ou une transcription
                # est en cours à cet instant, on réaffiche son état réel.
                with self._state_lock:
                    if self.recording:
                        s = "recording_toggle" if self.record_mode == "toggle" else "recording_ptt"
                    elif self.busy:
                        s = "processing"
                    else:
                        s = "ready"
                self._set_status(s)
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
            if self.recording or self.busy or self.reloading or self.stt is None:
                return
            self.recording = True
            self.record_mode = mode
        if not self._begin_capture():
            with self._state_lock:
                self.recording = False
                self.record_mode = None
            self.beep(200, 300)
            return
        self.record_started_at = time.monotonic()
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

        if duration < self.cfg["min_duration_s"]:
            self.busy = False
            self.overlay.hide()
            self._set_status("ready")
            return  # appui accidentel
        if samples.size == 0:
            # Durée réelle mais zéro échantillon : le flux micro est mort
            # (débranché, pris par une autre app) sans que PortAudio prévienne.
            # Bip + notice + réouverture, au lieu de jeter la dictée en silence.
            self.busy = False
            self.overlay.hide()
            self.beep(200, 300)
            self.on_event("notice", tr(self.cfg.get("lang", "en"), "mic_dead"))
            self._reopen_recorder()
            self._set_status("ready")
            return
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
                self._defer(self._stop_and_process)  # sérialisé avec press/release
                return
            time.sleep(0.5)

    def _apply_corrections(self, text: str) -> str:
        for rx, replacement in self._corrections:
            # sub() par callable : le remplacement est du texte LITTÉRAL, pas
            # un gabarit regex — un « \ » ou un « \g » saisi par l'utilisateur
            # ne doit pas faire échouer toutes les transcriptions suivantes.
            text = rx.sub(lambda m, _v=replacement: _v, text)
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
            self.on_event("notice", tr(self.cfg.get("lang", "en"), "stt_error").format(e))
        finally:
            self.busy = False
            self.overlay.hide()
            self._set_status("ready")

    # --- Hooks clavier -------------------------------------------------------

    # Exécutés sur le worker (jamais dans le hook clavier). Ils relisent l'état
    # au moment où ils tournent : les appels différés sont donc idempotents.
    def _on_press(self, mode: str):
        if mode == "ptt":
            if not self.recording:
                self._start("ptt")
        elif self.recording and self.record_mode == "toggle":
            self._stop_and_process()  # 2e appui = fin du mains-libres
        elif not self.recording:
            self._start("toggle")  # 1er appui = début du mains-libres

    def _on_ptt_release(self):
        if self.recording and self.record_mode == "ptt":
            self._stop_and_process()  # PTT : le relâchement arrête

    def _make_hook(self, trigger: str, entries: list[tuple[list[str], str]]):
        """Hook bloquant du `trigger`, partagé par tous ses combos (voir README).

        Tourne DANS la procédure WH_KEYBOARD_LL : il décide (suppression,
        quelle action) et délègue l'exécution au worker via _defer. Tout
        travail lent ici gèlerait le clavier système entier, et au-delà de
        ~200 ms Windows retirerait le hook sans un mot."""

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
                    # Auto-repeat. Rattrapage : si les modificateurs sont là et
                    # que ce maintien n'a encore rien déclenché (Espace arrivé
                    # quelques ms avant Ctrl, ou appui pendant une transcription
                    # encore en cours), on démarre maintenant — sans ça, la
                    # dictée entière partait dans le vide.
                    if active and not self.recording and not self.busy \
                            and not self._acted.get(trigger):
                        self._acted[trigger] = True
                        _, mode = active
                        self._defer(lambda m=mode: self._on_press(m))
                        return False
                    return False if (active or self.recording) else True
                self._held[trigger] = True
                self._acted[trigger] = False
                if self.busy:
                    return False if active else True
                if active is None:
                    return True  # trigger sans ses modificateurs = touche normale
                self._acted[trigger] = True
                _, mode = active
                self._defer(lambda m=mode: self._on_press(m))
                return False
            self._held[trigger] = False
            if self.recording and self.record_mode == "ptt":
                self._defer(self._on_ptt_release)
                return False
            return False if self.recording else True  # toggle : ne stoppe pas

        return hook

    def _single_press(self, mode: str, trigger: str):
        """Touche seule (ex. right ctrl), non suppressive : garde anti auto-repeat."""
        if self._held.get(trigger):
            # Même rattrapage que le hook : appui arrivé pendant une
            # transcription → démarre dès que busy retombe, sur l'auto-repeat.
            if not self.recording and not self.busy and not self._acted.get(trigger):
                self._acted[trigger] = True
                self._defer(lambda: self._on_press(mode))
            return
        self._held[trigger] = True
        if self.busy:
            self._acted[trigger] = False
            return
        self._acted[trigger] = True
        self._defer(lambda: self._on_press(mode))

    def _single_release(self, mode: str, trigger: str):
        self._held[trigger] = False
        if mode == "ptt" and self.recording and self.record_mode == "ptt":
            self._defer(self._on_ptt_release)

    def bind_hotkeys(self):
        """(Re)installe les hooks depuis la config. Repartir d'une table propre."""
        keyboard.unhook_all()
        self._held.clear()
        self._acted.clear()
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
        lang = cfg.get("lang", "en")
        # Valider les raccourcis AVANT toute écriture : un combo invalide
        # persisté puis bindé briquerait la session (unhook_all déjà fait) ET
        # le lancement suivant (bind lève au boot, Apply reste grisé — plus
        # aucun moyen de corriger depuis l'UI).
        for combo in (s.get("hotkey") or "", s.get("toggle_hotkey") or ""):
            if combo:
                bad = validate_hotkey(combo)
                if bad is not None:
                    self.on_event("notice", tr(lang, "bad_hotkey").format(bad))
                    return
        rebind = (
            s["hotkey"] != cfg.get("hotkey")
            or (s.get("toggle_hotkey") or None) != (cfg.get("toggle_hotkey") or None)
        )
        # Le micro se compare par NOM, pas par index : deux listes successives
        # peuvent réutiliser le même index pour deux micros différents, et un
        # changement serait alors passé sous silence.
        new_index = s.get("device")
        new_name = None
        if isinstance(new_index, int):
            for m in input_devices(cfg.get("sample_rate", 16000)):
                if new_index in m["candidates"]:
                    new_name = m["name"]  # nom canonique du groupe, jamais la troncature MME
                    break
        device_changed = new_name != cfg.get("device_name")
        # Changer de langue de dictée change de modèle : rechargement obligatoire.
        lang_changed = s.get("dictation_lang", "multi") != cfg.get("dictation_lang", "multi")
        reload_needed = lang_changed or abs(
            float(s["vocab_score"]) - float(cfg.get("vocab_score", 2.0))
        ) > 1e-9

        cfg["hotkey"] = s["hotkey"]
        cfg["toggle_hotkey"] = s.get("toggle_hotkey") or None
        # L'identité STABLE d'un micro est son nom — les index PortAudio se
        # décalent au moindre branchement. resolve_device s'en sert au boot ;
        # l'index n'est gardé que comme préférence.
        cfg["device"] = new_index if new_name else None
        cfg["device_name"] = new_name
        cfg["sounds"] = bool(s["sounds"])
        cfg["restore_clipboard"] = bool(s["restore_clipboard"])
        cfg["min_peak"] = float(s["min_peak"])
        cfg["vocab_score"] = float(s["vocab_score"])
        cfg["dictation_lang"] = "ka" if s.get("dictation_lang") == "ka" else "multi"
        cfg["overlay"] = bool(s["overlay"])
        self.overlay.set_enabled(cfg["overlay"])
        save_config(cfg)

        if rebind:
            try:
                self.bind_hotkeys()
            except Exception as e:
                self.on_event("notice", tr(lang, "bad_hotkey").format(e))
        # Le nouveau micro est seulement enregistré : rien n'est ouvert tant
        # qu'on ne dicte pas. Choisir un casque USB dans les réglages ne doit
        # pas saisir son interface audio — ça lui couperait la sortie.
        if device_changed and not self.recording:
            if self.recorder is None:
                self.recorder = self._make_recorder()
            else:
                self.recorder.set_device(*resolve_device(cfg))
        if reload_needed:
            self.reload_async()
        else:
            self.on_event("notice", tr(lang, "settings_applied"))

    def save_vocab_text(self, text: str):
        with open(vocab_path(self.cfg), "w", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n")
        self.reload_async()  # le vocab est figé dans le décodeur → rebuild

    def save_corrections(self, corrections: dict):
        self.cfg["corrections"] = corrections
        self._corrections = compile_corrections(corrections)
        save_config(self.cfg)
        self.on_event("notice", tr(self.cfg.get("lang", "en"), "corr_saved"))

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
    # use_last_error : lire GetLastError via ctypes.windll peut renvoyer le
    # last-error de la machinerie ctypes elle-même (GetProcAddress entre les
    # deux appels), et rater ERROR_ALREADY_EXISTS = deux hooks clavier.
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, "Tsera_SingleInstance_Mutex")
    if handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        log("Tsera tourne déjà — cette instance se ferme.")
        sys.exit(0)
    _SINGLE_INSTANCE_MUTEX = handle  # gardé en vie tant que le process tourne


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
        "Tsera",
        url=os.path.join(APP_DIR, "web", "index.html"),
        js_api=api,
        width=640,
        height=800,
        # Plancher bas : la faceplate se resserre en dessous de 560 px de large
        # (voir la requête média du style). Doit rester aligné sur _MIN_W/_MIN_H
        # de webui.py, qui borne aussi le redimensionnement à la poignée.
        min_size=(380, 420),
        background_color="#14110D",
        frameless=True,
        easy_drag=False,   # drag seulement via .pywebview-drag-region (la barre de titre)
        resizable=True,
        hidden=start_in_tray,
    )
    api._attach(engine, window)

    # Tray : menu Ouvrir / Quitter (double-clic = Ouvrir). run_detached car la
    # boucle principale appartient à webview. Le menu se reconstruit quand la
    # langue change dans les réglages, d'où la fabrique gardée sur l'engine.
    def _show_window(*_a):
        window.show()
        api._emit("shown", None)  # le front rafraîchit la liste des micros

    def _tray_menu(lang: str):
        return pystray.Menu(
            pystray.MenuItem(tr(lang, "open"), _show_window, default=True),
            pystray.MenuItem(tr(lang, "quit"), lambda i, it: api.quit_app()),
        )

    engine.build_tray_menu = _tray_menu
    icon = pystray.Icon(
        "Tsera", make_icon(False), "Tsera",
        _tray_menu(cfg.get("lang", "en")),
    )
    engine.icon = icon
    icon.run_detached()

    def _boot():
        # Chaque étape échoue séparément : un modèle absent n'empêche pas de
        # binder les raccourcis, un raccourci cassé (config éditée à la main)
        # n'empêche pas d'atteindre « ready » — sinon Apply reste grisé et
        # l'utilisateur ne peut plus JAMAIS corriger depuis l'UI.
        model_ok = False
        try:
            engine.load_model()
            model_ok = True
        except FileNotFoundError:
            log(f"Modèle absent : {engine.model_dir()}")
            api._emit("status", "error")  # état persistant, pas un toast de 2 s
            api._emit(
                "notice", tr(cfg.get("lang", "en"), "model_missing").format(engine.model_dir())
            )
        except Exception as e:
            log(f"Erreur au démarrage : {e}")
            api._emit("status", "error")
            api._emit("notice", tr(cfg.get("lang", "en"), "startup_error").format(e))
        try:
            engine.bind_hotkeys()
        except Exception as e:
            log(f"Raccourcis : {e}")
            api._emit("notice", tr(cfg.get("lang", "en"), "bad_hotkey").format(e))
        if model_ok:
            engine.beep(660, 60)
            api._emit("status", "ready")
            api._emit("model_ready", None)

    threading.Thread(target=_boot, daemon=True).start()

    webview.start(gui="edgechromium", debug=False)  # bloque jusqu'à destruction
    engine.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
