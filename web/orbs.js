/* Orbe d'état de la faceplate — portage de thinking-orbs.
 *
 * Source : https://github.com/Jakubantalik/thinking-orbs (v0.1.1). Licence MIT,
 * qui autorise la modification et la redistribution à condition que la notice
 * ci-dessous accompagne le code dérivé :
 *
 *   MIT License
 *
 *   Copyright (c) 2026 Jakub Antalik
 *
 *   Permission is hereby granted, free of charge, to any person obtaining a copy
 *   of this software and associated documentation files (the "Software"), to deal
 *   in the Software without restriction, including without limitation the rights
 *   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 *   copies of the Software, and to permit persons to whom the Software is
 *   furnished to do so, subject to the following conditions:
 *
 *   The above copyright notice and this permission notice shall be included in all
 *   copies or substantial portions of the Software.
 *
 *   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 *   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 *   SOFTWARE.
 *
 * Seul le mode « working » (orbits) est porté : des particules courent sur des
 * orbites inclinées, sans noyau. Vraie 3D — projection orthographique, tri en Z
 * et algorithme du peintre ; la profondeur passe par le rayon du point et son
 * intensité, sans aucun flou.
 *
 * Un écart assumé sur l'original, strictement monochrome : ici l'intensité
 * module l'ambre de la maison. Le pendant Python de ce fichier, pour le HUD,
 * est `orbs.py` (modes listening et composing).
 */

(function () {
  "use strict";

  // Preset « working » en taille 64 : ses multiplicateurs valent tous 1, le
  // profil de base passe donc tel quel.
  var OPTS = {
    orbitN: 12, ghostN: 40, ghostR: 0.9, ghostA: 0.5,
    particles: 3, partR: 1.2, partRDepth: 1.6, rsPow: 0.6, rMin: 0.3
  };
  var SPEED = 1.885;

  function hashD(a, b) {
    var h = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
    return h - Math.floor(h);
  }

  function radiusScale(size, pow) {
    return Math.pow(size / 300, pow);
  }

  /* Rotation + inclinaison + projection orthographique. */
  function makeProj(yaw, tilt, cx, cy, scale) {
    var st = Math.sin(tilt), ct = Math.cos(tilt);
    var sy = Math.sin(yaw), cyw = Math.cos(yaw);
    return function (x, y, z) {
      var x1 = x * cyw + z * sy;
      var z1 = -x * sy + z * cyw;
      var y1 = y * ct - z1 * st;
      return [cx + x1 * scale, cy - y1 * scale, y * st + z1 * ct];
    };
  }

  function drawOrbits(ctx, size, t, rgb) {
    var cx = size / 2, cy = size / 2;
    var R = (size / 2) * 0.82;
    var pt = makeProj(t * 0.12, 0.3, cx, cy, 1);
    var rs = radiusScale(size, OPTS.rsPow);
    var dots = [];

    for (var orb = 0; orb < OPTS.orbitN; orb++) {
      var h1 = hashD(orb, 1.7), h2 = hashD(orb, 5.2), h3 = hashD(orb, 8.9);
      var ro = R * (0.45 + 0.52 * h1);
      var th = h1 * 2 * Math.PI;
      var phi = Math.acos(2 * h2 - 1);
      // base (u, v) du plan de l'orbite, perpendiculaire à la normale n
      var nx = Math.sin(phi) * Math.cos(th);
      var ny = Math.cos(phi);
      var nz = Math.sin(phi) * Math.sin(th);
      var ux = -ny, uy = nx, uz = 0;
      var ul = Math.max(1e-6, Math.sqrt(ux * ux + uy * uy));
      ux /= ul; uy /= ul;
      var vx = ny * uz - nz * uy;
      var vy = nz * ux - nx * uz;
      var vz = nx * uy - ny * ux;
      var speed = (0.25 + 0.55 * h3) * (h3 > 0.5 ? 1 : -1);

      // le sillon fantôme de l'orbite
      for (var k = 0; k < OPTS.ghostN; k++) {
        var a = (k / OPTS.ghostN) * 2 * Math.PI;
        var ca = Math.cos(a), sa = Math.sin(a);
        var p = pt((ux * ca + vx * sa) * ro, (uy * ca + vy * sa) * ro, (uz * ca + vz * sa) * ro);
        var depth = (p[2] / ro + 1) / 2;
        dots.push([p[2], p[0], p[1], OPTS.ghostR * rs, 0.72, OPTS.ghostA * (0.4 + 0.6 * depth)]);
      }
      // les particules qui font le travail
      for (var m = 0; m < OPTS.particles; m++) {
        var b = t * speed + (m / OPTS.particles) * 2 * Math.PI + h2 * 6;
        var cb = Math.cos(b), sb = Math.sin(b);
        var q = pt((ux * cb + vx * sb) * ro, (uy * cb + vy * sb) * ro, (uz * cb + vz * sb) * ro);
        var d2 = (q[2] / ro + 1) / 2;
        dots.push([q[2], q[0], q[1], (OPTS.partR + OPTS.partRDepth * d2) * rs, 0.3 - 0.22 * d2, 1]);
      }
    }

    dots.sort(function (p, q) { return p[0] - q[0]; });  // loin → près
    ctx.clearRect(0, 0, size, size);
    for (var i = 0; i < dots.length; i++) {
      var d = dots[i];
      if (d[5] < 0.02) continue;
      // Substrat sombre : l'encre est inversée, les points proches sont clairs.
      var ink = 1 - Math.min(1, Math.max(0, d[4]));
      ctx.fillStyle = "rgba(" + Math.round(rgb[0] * ink) + "," + Math.round(rgb[1] * ink)
        + "," + Math.round(rgb[2] * ink) + "," + Math.min(1, d[5]) + ")";
      ctx.beginPath();
      ctx.arc(d[1], d[2], Math.max(OPTS.rMin, d[3]), 0, Math.PI * 2);
      ctx.fill();
    }
  }

  /* Anime un canvas. L'animation se met en pause quand la fenêtre est cachée
   * (réduite dans la barre système) : inutile de brûler du CPU pour personne. */
  function mount(canvas, opts) {
    opts = opts || {};
    var size = opts.size || 64;
    var rgb = opts.rgb || [255, 201, 107];
    var dpr = Math.min(2, window.devicePixelRatio || 1);  // plafonné, comme la lib
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    canvas.style.width = size + "px";
    canvas.style.height = size + "px";
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    var raf = null;
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function frame() {
      drawOrbits(ctx, size, (performance.now() / 1000) * SPEED, rgb);
      raf = requestAnimationFrame(frame);
    }
    function start() {
      if (raf === null && !reduced) raf = requestAnimationFrame(frame);
    }
    function stop() {
      if (raf !== null) { cancelAnimationFrame(raf); raf = null; }
    }

    // Mouvement réduit : une frame représentative, figée.
    drawOrbits(ctx, size, 0.6 * SPEED, rgb);
    if (!reduced) start();
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop(); else start();
    });
    return { start: start, stop: stop };
  }

  window.PWOrb = { mount: mount };
})();
