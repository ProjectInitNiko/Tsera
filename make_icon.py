"""Génère icon.ico (raccourci Bureau / barre système) — pastille « TS » ambre.

À relancer si on veut retoucher le visuel :  python make_icon.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

APP_DIR = os.path.dirname(os.path.abspath(__file__))

BG = (26, 23, 20, 255)       # charbon chaud (#1A1714)
AMBER = (255, 170, 43, 255)  # ambre signal (#FFAA2B) — la couleur du HUD


def _font(size: int):
    for name in ("arialbd.ttf", "seguisb.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(px: int, fg=AMBER) -> Image.Image:
    """Pastille « TS ». `fg` colore le sigle : la barre système réutilise ce
    dessin en rouge pendant l'enregistrement plutôt que d'en avoir un autre."""
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, round(px * 0.06))
    radius = round(px * 0.22)
    d.rounded_rectangle((pad, pad, px - pad, px - pad), radius=radius, fill=BG)

    text = "TS"
    font = _font(round(px * 0.42))
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(
        ((px - tw) / 2 - box[0], (px - th) / 2 - box[1]),
        text,
        font=font,
        fill=fg,
    )
    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = render(256)
    out = os.path.join(APP_DIR, "icon.ico")
    base.save(out, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Écrit : {out}  (tailles {', '.join(map(str, sizes))})")


if __name__ == "__main__":
    main()
