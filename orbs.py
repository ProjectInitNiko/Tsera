"""Orbes d'état du HUD — port Python de thinking-orbs.

Portage de https://github.com/Jakubantalik/thinking-orbs (v0.1.1), dont la
licence MIT autorise la modification et la redistribution à condition que la
notice ci-dessous accompagne le code dérivé :

    MIT License

    Copyright (c) 2026 Jakub Antalik

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

Vraie 3D rendue en 2D : anneaux latitude/longitude ou lattice de Fibonacci,
rotation yaw + tilt, projection orthographique, tri en Z et algorithme du
peintre. La profondeur est portée par le rayon du point et son intensité —
aucun flou, aucun filtre (les filtres canvas rendaient différemment selon le
navigateur ; ici ils coûteraient surtout trop cher en Python).

Deux modes portés, ceux dont le HUD a besoin :
  - « listening » (wave)   : une onde roule dans les anneaux → pendant la dictée
  - « composing » (ribbon) : une écharpe de bandes ondule    → pendant la transcription

Deux écarts assumés par rapport à l'original :
  1. L'original est strictement monochrome (aucune prop de couleur). Ici
     l'intensité module la couleur ambre du HUD — même langage de profondeur,
     teinte de la maison.
  2. L'anticrénelage vient d'un surdimensionnement puis d'une réduction
     LANCZOS, faute d'un `ctx.arc` anticrénelé côté PIL.

Les presets sont ceux de la taille 64 de la lib, résolus ici par le même
calcul (multiplicateurs de densité et de rayon) plutôt que recopiés à la main.
"""

import math

from PIL import Image, ImageDraw

# --- Résolution des presets (presets.ts + engine/profiles.ts) ----------------

# Profils « fine » de base, avant multiplicateurs.
_BASE_PROFILES = {
    "wave": {"rings": 15, "lonDensity": 40, "rBase": 0.6, "rDepth": 1.7, "rsPow": 0.6, "rMin": 0.3},
    "ribbon": {"lanes": 5, "segs": 88, "ghostN": 150, "rBase": 1.1, "rDepth": 1.7, "rsPow": 0.6, "rMin": 0.3},
}

# Presets livrés pour la taille 64 (échelle avatar).
_PRESETS_64 = {
    "wave": {"speed": 4.388, "count": 0.341, "size": 1.0, "extra": {}},
    "ribbon": {"speed": 2.34, "count": 0.25, "size": 0.85,
               "extra": {"spin": 0.0, "bandMul": 3.9, "wobMul": 1.0}},
}

_COUNT_PAIRS = (("latRings", "lonDensity"), ("rings", "lonDensity"), ("lanes", "segs"))
_COUNT_KEYS = ("orbitN", "ghostN")
_RADIUS_KEYS = ("rBase", "rDepth", "rActive", "rDot", "ghostR", "partR", "partRDepth")


def _js_round(x: float) -> int:
    """Math.round de JavaScript : les demis vont vers le haut (round() de Python
    fait de l'arrondi bancaire, ce qui décalerait les densités)."""
    return math.floor(x + 0.5)


def _scale_counts(opts: dict, scale: float) -> dict:
    """Les lattices 2D vont par paires : chaque côté prend √scale pour que le
    nombre TOTAL de points suive `scale`. Les listes plates suivent linéairement."""
    out = dict(opts)
    done = set()
    rt = math.sqrt(scale)
    for a, b in _COUNT_PAIRS:
        if out.get(a) is not None and out.get(b) is not None and a not in done and b not in done:
            out[a] = max(2, _js_round(out[a] * rt))
            out[b] = max(2, _js_round(out[b] * rt))
            done.update((a, b))
    for k in _COUNT_KEYS:
        if out.get(k) is not None and k not in done:
            out[k] = max(1, _js_round(out[k] * scale))
    return out


def _scale_radii(opts: dict, scale: float) -> dict:
    out = dict(opts)
    for k in _RADIUS_KEYS:
        if out.get(k) is not None:
            out[k] = out[k] * scale
    return out


def resolve_preset(mode: str) -> tuple[dict, float]:
    """(options entièrement résolues, vitesse) pour un mode en taille 64."""
    p = _PRESETS_64[mode]
    opts = dict(_BASE_PROFILES[mode])
    if p["count"] != 1:
        opts = _scale_counts(opts, p["count"])
    if p["size"] != 1:
        opts = _scale_radii(opts, p["size"])
    opts.update(p["extra"])
    return opts, p["speed"]


def _radius_scale(size: float, pow_: float) -> float:
    """Les rayons ont été réglés pour un cadre de 300 pt ; l'échelle sous-linéaire
    garde les petites tailles lisibles."""
    return (size / 300.0) ** pow_


def _fib_dir(i: int, n: int) -> tuple[float, float, float]:
    """Directions stables sur la sphère unité (lattice de Fibonacci)."""
    golden = math.pi * (3.0 - math.sqrt(5.0))
    y = 1.0 - (2.0 * (i + 0.5)) / n
    rad = math.sqrt(max(0.0, 1.0 - y * y))
    a = i * golden
    return rad * math.cos(a), y, rad * math.sin(a)


# --- Rendu -------------------------------------------------------------------


class OrbRenderer:
    """Rend un orbe animé en image PIL.

    La géométrie invariante (angles des anneaux, directions de Fibonacci) est
    calculée une seule fois ici ; chaque frame ne refait que la déformation, la
    projection et le tri.
    """

    def __init__(self, mode: str, size: int, color=(255, 201, 107), bg=(23, 20, 15), ss: int = 3):
        self.mode = mode
        self.size = size
        self.ss = ss                    # facteur de surdimensionnement (anticrénelage)
        self.color = color
        self.bg = bg
        self.opts, self.speed = resolve_preset(mode)
        self._rs = _radius_scale(size, self.opts.get("rsPow", 0.6))
        self._r_min = self.opts.get("rMin", 0.3)
        if mode == "wave":
            self._init_wave()
        elif mode == "ribbon":
            self._init_ribbon()
        else:
            raise ValueError(f"mode non porté : {mode}")

    # --- Précalculs géométriques ---

    def _init_wave(self):
        rings = self.opts["rings"]
        lon_density = self.opts["lonDensity"]
        self._R = (self.size / 2.0) * 0.874
        self._ring_geo = []
        for ri in range(rings + 1):
            lat = -math.pi / 2.0 + (ri / rings) * math.pi
            cos_lat, sin_lat = math.cos(lat), math.sin(lat)
            lon_count = max(1, _js_round(abs(cos_lat) * lon_density))
            lons = []
            for lj in range(lon_count):
                lon = (lj / lon_count) * 2.0 * math.pi
                lons.append((cos_lat * math.cos(lon), cos_lat * math.sin(lon)))
            self._ring_geo.append((sin_lat, lons))

    def _init_ribbon(self):
        self._R = (self.size / 2.0) * 0.78
        ghost_n = self.opts["ghostN"]
        self._ghosts = [_fib_dir(i, ghost_n) for i in range(ghost_n)]
        # `lanes` du profil est encore multiplié par bandMul au moment du dessin
        lanes = max(1, _js_round(self.opts["lanes"] * self.opts.get("bandMul", 1.0)))
        segs = self.opts["segs"]
        self._lanes = lanes
        self._segs_geo = [(math.cos((k / segs) * 2.0 * math.pi),
                           math.sin((k / segs) * 2.0 * math.pi),
                           (k / segs) * 2.0 * math.pi) for k in range(segs)]

    # --- Une frame ---

    def _dots_wave(self, t: float) -> list:
        """L'onde : deux sinus de tempi différents parcourent les anneaux, si bien
        que le motif ne se répète jamais tout à fait."""
        o = self.opts
        R, rs = self._R, self._rs
        cx = cy = self.size / 2.0
        yaw, tilt = t * 0.18, 0.38
        st, ct = math.sin(tilt), math.cos(tilt)
        sy, cyw = math.sin(yaw), math.cos(yaw)
        r_base, r_depth = o["rBase"], o["rDepth"]
        dots = []
        for ri, (sin_lat, lons) in enumerate(self._ring_geo):
            w = 0.62 * math.sin(t * 2.1 - ri * 0.52) + 0.38 * math.sin(t * 1.27 + ri * 0.83)
            rr = R * (0.88 + 0.105 * w)
            crest = max(0.0, w)
            y = sin_lat * rr
            r_crest = 1.0 + 0.4 * crest
            ink_crest = 0.1 * crest
            for cl_cos, cl_sin in lons:
                x, z = cl_cos * rr, cl_sin * rr
                x1 = x * cyw + z * sy
                z1 = -x * sy + z * cyw
                y1 = y * ct - z1 * st
                z2 = y * st + z1 * ct
                depth = (z2 / R + 1.0) / 2.0
                dots.append((
                    z2, cx + x1, cy - y1,
                    (r_base + r_depth * depth) * r_crest * rs,
                    0.66 - 0.56 * depth - ink_crest,
                    1.0,
                ))
        return dots

    def _dots_ribbon(self, t: float) -> list:
        """L'écharpe : des bandes parallèles chevauchent un grand cercle. Le preset
        fige la rotation 3D (spin = 0) et ne laisse que l'ondulation qui voyage."""
        o = self.opts
        R, rs = self._R, self._rs
        cx = cy = self.size / 2.0
        spin = o.get("spin", 1.0)
        yaw, tilt = t * 0.1 * spin, 0.3
        st, ct = math.sin(tilt), math.cos(tilt)
        sy, cyw = math.sin(yaw), math.cos(yaw)

        def proj(x, y, z):
            x1 = x * cyw + z * sy
            z1 = -x * sy + z * cyw
            return cx + x1, cy - (y * ct - z1 * st), y * st + z1 * ct

        dots = []
        # Le halo de points fantômes qui suggère la sphère sous la bande.
        for dx, dy, dz in self._ghosts:
            px, py, z = proj(dx * R, dy * R, dz * R)
            depth = (z / R + 1.0) / 2.0
            dots.append((z, px, py, 0.8 * rs, 0.78, 0.1 + 0.22 * depth))

        # Le plan de la bande, figé quand spin = 0.
        ya = t * 0.24 * spin
        ta = 0.55 + 0.3 * math.sin(t * 0.18) * spin
        ux, uy, uz = math.cos(ya), 0.0, math.sin(ya)
        sin_ta, cos_ta = math.sin(ta), math.cos(ta)
        vx, vy, vz = -uz * sin_ta, cos_ta, ux * sin_ta
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx

        lanes, wob_mul = self._lanes, o.get("wobMul", 1.0)
        r_base, r_depth = o["rBase"], o["rDepth"]
        half = max(1.0, (lanes - 1) / 2.0)
        for w in range(lanes):
            lane_off = (w - (lanes - 1) / 2.0) * 0.075
            edge = abs(w - (lanes - 1) / 2.0) / half
            r_edge = 1.0 - 0.25 * edge
            ink_edge = 0.18 * edge
            for ca, sa, a in self._segs_geo:
                wob = (0.16 * math.sin(a * 3.0 - t * 1.7 + w * 0.22)
                       + 0.07 * math.sin(a * 5.0 + t * 1.1)) * wob_mul
                off = lane_off + wob
                x = ux * ca + vx * sa + nx * off
                y = uy * ca + vy * sa + ny * off
                z = uz * ca + vz * sa + nz * off
                l = math.sqrt(x * x + y * y + z * z) or 1.0
                px, py, zr = proj(x / l * R, y / l * R, z / l * R)
                depth = (zr / R + 1.0) / 2.0
                dots.append((
                    zr, px, py,
                    (r_base + r_depth * depth) * r_edge * rs,
                    0.52 - 0.44 * depth + ink_edge,
                    0.4 + 0.6 * depth,
                ))
        return dots

    def render(self, t_seconds: float) -> Image.Image:
        """Image RGB de `size`×`size`, fond compris. `t_seconds` = horloge murale ;
        la vitesse du preset est appliquée ici, comme dans la lib."""
        t = t_seconds * self.speed
        dots = self._dots_wave(t) if self.mode == "wave" else self._dots_ribbon(t)
        dots.sort(key=lambda d: d[0])  # loin → près : algorithme du peintre

        ss = self.ss
        im = Image.new("RGB", (self.size * ss, self.size * ss), self.bg)
        # Le mode « RGBA » du contexte de dessin active le vrai mélange alpha
        # avec ce qui est déjà peint — indispensable pour les points fantômes.
        draw = ImageDraw.Draw(im, "RGBA")
        cr, cg, cb = self.color
        r_min = self._r_min
        for _z, x, y, r, white, a in dots:
            if a < 0.02:
                continue
            # Substrat sombre : l'encre est inversée, les points proches sont clairs.
            ink = 1.0 - min(1.0, max(0.0, white))
            rr = max(r_min, r) * ss
            x0, y0 = (x * ss - rr), (y * ss - rr)
            draw.ellipse(
                (x0, y0, x0 + 2 * rr, y0 + 2 * rr),
                fill=(int(cr * ink), int(cg * ink), int(cb * ink), int(255 * min(1.0, a))),
            )
        return im.resize((self.size, self.size), Image.LANCZOS)
