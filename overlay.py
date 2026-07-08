"""HUD à la SuperWhisper — pastille en bas d'écran avec « NK » + vagues de son.

Tourne dans son propre thread tkinter ; les autres threads ne font que poser
des drapeaux (`_state`) et empiler des niveaux audio (`push_level`), le thread
UI lit tout ça à ~30 fps. Fenêtre sans bordure, topmost, et surtout
WS_EX_NOACTIVATE : elle ne vole jamais le focus de l'app où l'on dicte.
"""

import collections
import ctypes
import math
import threading
import time
import tkinter as tk

# Couleur-clé rendue transparente (ne jamais l'utiliser dans le dessin).
_TRANSPARENT = "#010203"

_PILL_BG = "#17171B"
_PILL_BORDER = "#2E2E36"
_BAR_COLOR = "#EDEDF2"
_ACCENT = "#FFAA2B"

_W, _H = 300, 56
_N_BARS = 26
_BARS_X0, _BARS_X1 = 66, _W - 24


def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Overlay:
    """États : hidden → recording (vagues) → processing (points) → hidden."""

    def __init__(self, enabled: bool = True):
        self._state = "hidden"
        self._levels = collections.deque(maxlen=_N_BARS)
        self._enabled = enabled
        self._visible = False
        if enabled:
            ready = threading.Event()
            threading.Thread(target=self._run, args=(ready,), daemon=True).start()
            ready.wait(5)

    # --- API (thread-safe, appelable de n'importe où) -------------------------

    def show_recording(self):
        self._levels.clear()
        self._state = "recording"

    def show_processing(self):
        self._state = "processing"

    def hide(self):
        self._state = "hidden"

    def push_level(self, rms: float):
        """rms du dernier chunk micro (float32 [-1,1]) → niveau de barre [0,1]."""
        self._levels.append(min(1.0, (rms * 14) ** 0.6))

    # --- Thread UI -------------------------------------------------------------

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
        canvas.create_text(
            36, _H // 2, text="NK", fill=_ACCENT,
            font=("Segoe UI", 15, "bold"),
        )

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
        self._root.after(33, self._tick)

    def _draw_bars(self):
        c = self._canvas
        cy = _H // 2
        step = (_BARS_X1 - _BARS_X0) / (_N_BARS - 1)
        levels = list(self._levels)
        # Les plus récents à droite ; à gauche, du « plat » tant que ça se remplit.
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
