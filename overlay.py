"""HUD de dictée — pastille en bas d'écran avec « TS » + vagues de son.

Tourne dans son propre thread tkinter (root Tk dédié) : la fenêtre principale
est en WebView2 (pywebview), pas en tkinter, donc le HUD est indépendant. Les
autres threads ne font que poser des drapeaux (`_state`) et empiler des niveaux
audio (`push_level`) ; le thread UI lit tout ça à ~30 fps. Fenêtre sans bordure,
topmost, et surtout WS_EX_NOACTIVATE : elle ne vole jamais le focus de l'app où
l'on dicte.
"""

import collections
import ctypes
import math
import os
import threading
import time
import tkinter as tk

# Couleur-clé rendue transparente (ne jamais l'utiliser dans le dessin).
_TRANSPARENT = "#010203"

_PILL_BG = "#17140F"
_PILL_BORDER = "#332C22"
_BAR_COLOR = "#FFC96B"
_ACCENT = "#FFAA2B"

_ORB = 46                      # diamètre de l'orbe d'état, à droite des ondes
_H = 56
_BARS_X0, _BARS_X1 = 66, 276   # les ondes gardent leur place d'origine
_W = _BARS_X1 + 12 + _ORB + 20  # … la pastille s'allonge pour loger l'orbe
_ORB_CX = _BARS_X1 + 12 + _ORB // 2
_N_BARS = 26

# Teinte des orbes : (23, 20, 15) = _PILL_BG, (255, 201, 107) = _BAR_COLOR.
_ORB_RGB = (255, 201, 107)
_PILL_RGB = (23, 20, 15)

# Orbes d'état : agrément visuel, jamais un point de panne. Si PIL ou le module
# manquent, le HUD retombe sur les ondes et les points seuls.
try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk

    from orbs import OrbRenderer

    _ORBS_OK = True
except Exception:  # pragma: no cover - dépend de l'environnement
    _ORBS_OK = False


def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Overlay:
    """États : hidden → recording (vagues) → processing (points) → hidden.

    Construit dans son thread ; l'affichage est conditionné par `_enabled`,
    qu'on peut basculer à chaud depuis les réglages.
    """

    def __init__(self, enabled: bool = True):
        self._state = "hidden"
        self._levels = collections.deque(maxlen=_N_BARS)
        self._enabled = enabled
        self._visible = False
        self._root = None
        self._canvas = None
        self._orb_photo = None
        self._orb_renderers = {}
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True).start()
        ready.wait(5)

    # --- API (thread-safe, appelable de n'importe où) -------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if not enabled:
            self._state = "hidden"

    def show_recording(self):
        if not self._enabled:
            return
        self._levels.clear()
        self._state = "recording"

    def show_processing(self):
        if not self._enabled:
            return
        self._state = "processing"

    def hide(self):
        self._state = "hidden"

    def push_level(self, rms: float):
        """rms du dernier chunk micro (float32 [-1,1]) → niveau de barre [0,1]."""
        self._levels.append(min(1.0, (rms * 14) ** 0.6))

    # --- Thread UI ------------------------------------------------------------

    def _run(self, ready: threading.Event):
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", _TRANSPARENT)
        root.attributes("-alpha", 0.0)  # évite le flash du mapping initial

        x = (root.winfo_screenwidth() - _W) // 2
        y = root.winfo_screenheight() - _H - 64
        root.geometry(f"{_W}x{_H}+{x}+{y}")

        canvas = tk.Canvas(
            root, width=_W, height=_H, bg=_TRANSPARENT, highlightthickness=0
        )
        canvas.pack()
        _round_rect(
            canvas, 1, 1, _W - 2, _H - 2, _H // 2 - 1,
            fill=_PILL_BG, outline=_PILL_BORDER, width=1,
        )
        # Le sigle est peint par PIL, pas par tkinter : aucune des polices de la
        # maison n'est installée sur le système, et tkinter ne sait charger
        # qu'une police installée — il retombait donc sur Segoe UI, la police par
        # défaut de Windows, qu'on ne veut nulle part. PIL, lui, lit un fichier.
        self._mono_photo = None
        if _ORBS_OK:
            try:
                font = ImageFont.truetype(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "assets", "inter-600.ttf"), 19)
                im = Image.new("RGB", (44, _H), _PILL_RGB)
                dr = ImageDraw.Draw(im)
                box = dr.textbbox((0, 0), "TS", font=font)
                dr.text(((44 - (box[2] - box[0])) / 2 - box[0],
                         (_H - (box[3] - box[1])) / 2 - box[1]),
                        "TS", font=font, fill=_ACCENT)
                self._mono_photo = ImageTk.PhotoImage(im)
                canvas.create_image(36, _H // 2, image=self._mono_photo)
            except Exception:
                self._mono_photo = None
        if self._mono_photo is None:  # filet : mieux vaut un sigle que pas de sigle
            canvas.create_text(36, _H // 2, text="TS", fill=_ACCENT,
                               font=("Arial", 15, "bold"))

        # Orbe d'état : une seule PhotoImage réutilisée (paste par frame) plutôt
        # qu'une allocation à chaque tick. La référence doit rester vivante,
        # sinon le ramasse-miettes la retire sous les pieds de Tk.
        self._orb_photo = None
        self._orb_renderers = {}
        if _ORBS_OK:
            try:
                self._orb_renderers = {
                    "recording": OrbRenderer("wave", _ORB, _ORB_RGB, _PILL_RGB),
                    "processing": OrbRenderer("ribbon", _ORB, _ORB_RGB, _PILL_RGB),
                }
                self._orb_photo = ImageTk.PhotoImage(
                    Image.new("RGB", (_ORB, _ORB), _PILL_RGB)
                )
                canvas.create_image(_ORB_CX, _H // 2, image=self._orb_photo)
            except Exception:
                self._orb_photo = None

        # Mapper une fois (invisible via alpha 0) pour obtenir un HWND stable,
        # puis poser WS_EX_NOACTIVATE + WS_EX_TOOLWINDOW : pas de vol de focus,
        # pas d'entrée dans Alt-Tab.
        root.update_idletasks()
        root.deiconify()
        root.update()
        try:
            hwnd = int(root.wm_frame(), 16)
            GWL_EXSTYLE = -20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | 0x08000000 | 0x00000080
            )
        except Exception:
            pass
        root.withdraw()
        root.attributes("-alpha", 1.0)

        self._root, self._canvas = root, canvas
        ready.set()
        self._tick()
        root.mainloop()

    def _tick(self):
        state = self._state
        if state == "hidden":
            if self._visible:
                self._root.withdraw()
                self._visible = False
        else:
            if not self._visible:
                self._root.deiconify()
                self._root.attributes("-topmost", True)
                self._visible = True
            self._canvas.delete("dyn")
            if state == "recording":
                self._draw_bars()
            else:
                self._draw_dots()
            self._draw_orb(state)
        self._root.after(33, self._tick)

    def _draw_orb(self, state: str):
        """« listening » pendant la dictée, « composing » pendant la transcription."""
        if self._orb_photo is None:
            return
        renderer = self._orb_renderers.get(state)
        if renderer is None:
            return
        try:
            self._orb_photo.paste(renderer.render(time.monotonic()))
        except Exception:
            self._orb_photo = None  # on n'insiste pas : le HUD continue sans orbe

    def _draw_bars(self):
        c = self._canvas
        cy = _H // 2
        step = (_BARS_X1 - _BARS_X0) / (_N_BARS - 1)
        levels = list(self._levels)
        levels = [0.0] * (_N_BARS - len(levels)) + levels
        for i, lvl in enumerate(levels):
            x = _BARS_X0 + i * step
            h = max(3.0, lvl * 30.0)
            c.create_line(
                x, cy - h / 2, x, cy + h / 2,
                fill=_BAR_COLOR, width=4, capstyle=tk.ROUND, tags="dyn",
            )

    def _draw_dots(self):
        c = self._canvas
        cy = _H // 2
        cx = (_BARS_X0 + _BARS_X1) / 2
        t = time.monotonic()
        for i in range(3):
            r = 3.0 + 2.0 * (0.5 + 0.5 * math.sin(t * 6.0 - i * 0.9))
            x = cx + (i - 1) * 18
            c.create_oval(
                x - r, cy - r, x + r, cy + r,
                fill=_ACCENT, outline="", tags="dyn",
            )
