"""Génère web/fonts.css : @font-face en data-URI (base64) depuis web/fonts/*.woff2.

WebView2 (Chromium) bloque le chargement des woff2 par CORS sous file:// ; les
embarquer en data-URI contourne ça proprement. Relancer après avoir ajouté ou
changé une police :  python build_fonts_css.py
"""
import base64
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "web", "fonts")
OUT = os.path.join(HERE, "web", "fonts.css")

# Le poids est une chaîne : « 400 » pour un fichier statique, « 100 700 » pour
# une police variable, dont un seul fichier couvre toute la plage. Déclarer une
# variable en poids fixe ne donnerait que son instance par défaut (400) — le
# gras serait silencieusement ignoré.
FACES = [
    ("Anton", "400", "anton-400.woff2"),
    ("Inter", "400", "inter-400.woff2"),
    ("Inter", "500", "inter-500.woff2"),
    ("Inter", "600", "inter-600.woff2"),
    ("Inter", "700", "inter-700.woff2"),
    ("Roboto Mono", "100 700", "robotomono-var.woff2"),
]


def main():
    out = ["/* Généré par build_fonts_css.py — ne pas éditer à la main. */"]
    for family, weight, fn in FACES:
        with open(os.path.join(FONTS, fn), "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        out.append(
            '@font-face{font-family:"%s";font-weight:%s;font-style:normal;'
            'font-display:swap;src:url("data:font/woff2;base64,%s") format("woff2");}'
            % (family, weight, b64)
        )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("Écrit : %s  (%d faces)" % (OUT, len(FACES)))


if __name__ == "__main__":
    main()
