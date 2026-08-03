/* Tsera — UI web. Bridge pywebview + forme d'onde + interactions. */
"use strict";

const $ = (id) => document.getElementById(id);
const api = () => (window.pywebview && window.pywebview.api) || null;

/* `word` est l'anglais ; la clé sert à retrouver le français. */
const STATUS = {
  loading:          { led: "amber", word: "Loading",       rec: false, wave: "loading" },
  reloading:        { led: "amber", word: "Reloading",     rec: false, wave: "loading" },
  ready:            { led: "green", word: "Ready",         rec: false, wave: "ready" },
  recording_ptt:    { led: "red",   word: "Listening",     rec: true,  wave: "recording" },
  recording_toggle: { led: "red",   word: "Hands-free",    rec: true,  wave: "recording" },
  processing:       { led: "amber", word: "Transcribing",  rec: false, wave: "processing" },
  /* État persistant (modèle absent, échec de boot) : un toast de 2,4 s ne
     suffit pas quand l'app ne peut pas fonctionner du tout. */
  error:            { led: "red",   word: "Error",         rec: false, wave: "ready" },
};

const tr = (key, fallback) => (window.PWI18n ? window.PWI18n.t(key, fallback) : fallback);

let modelReady = false;
let currentStatus = "loading";
let currentDictationLang = "multi";

/* Nom du modèle affiché dans le pied de page. Il suit la langue de dictée : le
   pied était figé sur « Parakeet v3 », il ne bougeait pas au passage en géorgien. */
function setFootModel(dl) {
  if (dl) currentDictationLang = dl === "ka" ? "ka" : "multi";
  const el = $("footModel");
  if (!el) return;
  el.innerHTML = currentDictationLang === "ka"
    ? tr("model_ka", "Georgian")
    : tr("model_multi", "Parakeet&nbsp;v3");
}

/* ---------- Bridge : Python appelle window.PW.on(kind, payload) ---------- */
window.PW = {
  on(kind, payload) {
    if (kind === "status") setStatus(payload);
    else if (kind === "transcription") addTake(payload);
    else if (kind === "notice") toast(payload);
    else if (kind === "model_ready") { modelReady = true; setHeavyEnabled(true); }
    else if (kind === "shown") refreshDevices();  // les micros ont pu changer
  },
};

/* ---------- Statut + forme d'onde ---------- */
function setStatus(s) {
  currentStatus = s;
  const st = STATUS[s] || { led: "amber", word: s, rec: false, wave: "ready" };
  $("led").className = "led led--" + st.led;
  $("statusWord").textContent = tr("status_" + s, st.word);
  $("rec").hidden = !st.rec;
  wave.mode = st.wave;
  if (s === "loading" || s === "reloading") setHeavyEnabled(false);
  else if (s === "ready" && modelReady) setHeavyEnabled(true);
}

function setHeavyEnabled(on) {
  $("applySettings").disabled = !on;
  $("saveVocab").disabled = !on;
}

/* ---------- Raccourcis → keycaps ---------- */
/* Les noms de touches suivent la langue : Maj/Espace en français. */
const KEYNAME = () => ({
  ctrl: "Ctrl", control: "Ctrl", alt: "Alt",
  shift: tr("key_shift", "Shift"), space: tr("key_space", "Space"),
  "right ctrl": tr("key_rctrl", "Right Ctrl"), "right shift": tr("key_rshift", "Right Shift"),
});
/* Le raccourci est du texte libre (champ + config.json) inséré via innerHTML :
   sans échappement, `ctrl+<img onerror=…>` s'exécuterait avec le bridge
   pywebview complet sous la main. Seul point d'insertion non textContent. */
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));
function keycaps(hotkey) {
  if (!hotkey) return "";
  const names = KEYNAME();
  return hotkey.split("+").map((p) => {
    const k = p.trim().toLowerCase();
    const name = names[k] || (k.charAt(0).toUpperCase() + k.slice(1));
    return `<span class="cap">${escapeHtml(name)}</span>`;
  }).join("");
}

/* ---------- Historique ---------- */
let histCount = 0;
function addTake(d) {
  $("histEmpty").style.display = "none";
  const row = document.createElement("div");
  row.className = "take";
  const time = document.createElement("span");
  time.className = "take__time";
  time.textContent = (d.time || "").slice(0, 5);
  const text = document.createElement("span");
  text.className = "take__text";
  text.textContent = d.text || "";
  const copy = document.createElement("button");
  copy.className = "take__copy";
  copy.textContent = tr("hist_copy", "Copy");
  copy.onclick = () => { if (api()) api().copy_text(d.text || ""); };
  row.append(time, text, copy);
  const list = $("history");
  list.insertBefore(row, list.firstChild);
  histCount++;
  $("histCount").textContent = histCount;
}
function clearHistory() {
  document.querySelectorAll(".take").forEach((n) => n.remove());
  histCount = 0;
  $("histCount").textContent = "0";
  $("histEmpty").style.display = "";
}

/* ---------- Toast ---------- */
let toastTimer = null;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  requestAnimationFrame(() => el.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => { el.hidden = true; }, 220);
  }, 2400);
}

/* ---------- Onglets ---------- */
function initTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  const ink = $("tabsInk") || document.querySelector(".tabs__ink");
  const bar = ink.parentElement;
  function moveInk(tab, animate = true) {
    if (!tab) return;
    // Un repositionnement dû au redimensionnement doit être instantané : animé,
    // le trait glisserait pendant 280 ms à chaque pixel tiré à la poignée.
    if (!animate) ink.style.transition = "none";
    ink.style.left = tab.offsetLeft + "px";
    ink.style.width = tab.offsetWidth + "px";
    if (!animate) {
      void ink.offsetWidth;  // force le reflow avant de rendre la transition
      ink.style.transition = "";
    }
  }
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      document.querySelectorAll(".panel").forEach((p) =>
        p.classList.toggle("is-active", p.dataset.panel === tab.dataset.tab));
      moveInk(tab);
    });
  });
  moveInk(document.querySelector(".tab.is-active"));

  // Les onglets sont en `flex:1` — leur largeur suit celle de la fenêtre —
  // alors que le trait est posé en PIXELS. Sans ce recalcul, agrandir laissait
  // un trait trop court sous l'onglet, et revenir en fenêtré un trait à cheval
  // sur deux onglets. On observe la barre plutôt que window.resize : elle
  // bouge aussi quand une barre de défilement apparaît.
  const reflow = () => moveInk(document.querySelector(".tab.is-active"), false);
  if (window.ResizeObserver) new ResizeObserver(reflow).observe(bar);
  else window.addEventListener("resize", reflow);
}

/* ---------- Listes déroulantes ----------
   Les <select> natifs de Windows peignent un menu système gris qui ignore
   entièrement la feuille de style : au milieu de la faceplate, ça tranche.
   On habille donc chaque select d'un bouton et d'un panneau maison.

   Le <select> reste dans le DOM et garde la valeur. C'est ce qui rend le
   remplacement sans risque : `gatherSettings`, `applyState`, `refreshDevices`
   et l'i18n continuent de lire et d'écrire le select comme avant, et si ce
   script échoue la liste native reprend la main. */

let xselSeq = 0;

function enhanceSelect(sel) {
  const wrap = sel.parentElement;
  if (!wrap || wrap.classList.contains("is-enhanced")) return;
  wrap.classList.add("is-enhanced");
  // Retiré du parcours clavier : c'est le bouton qui porte l'ARIA, sinon le
  // focus passerait par un select invisible.
  sel.setAttribute("tabindex", "-1");
  sel.setAttribute("aria-hidden", "true");

  const id = "xsel" + ++xselSeq;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "xsel";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  const val = document.createElement("span");
  val.className = "xsel__value";
  btn.appendChild(val);
  btn.insertAdjacentHTML("beforeend",
    '<svg class="xsel__chev" viewBox="0 0 12 8" aria-hidden="true"><path d="M1 1.5 6 6.5 11 1.5"/></svg>');
  wrap.appendChild(btn);

  let panel = null, cursor = -1, typed = "", typedAt = 0;

  function syncButton() {
    const o = sel.selectedOptions[0];
    val.textContent = o ? o.textContent : "—";
    val.classList.toggle("is-empty", !o);
    btn.title = o ? o.textContent : "";  // les noms de micro dépassent la largeur
  }

  function render() {
    panel.textContent = "";
    [...sel.options].forEach((o, i) => {
      const row = document.createElement("div");
      row.className = "xsel-opt" + (o.disabled ? " is-disabled" : "");
      row.id = id + "o" + i;
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", String(i === sel.selectedIndex));
      row.style.setProperty("--i", String(i));
      row.dataset.i = String(i);
      row.title = o.title || o.textContent;
      const tick = document.createElement("span");
      tick.className = "xsel-opt__tick";
      const lab = document.createElement("span");
      lab.className = "xsel-opt__label";
      lab.textContent = o.textContent;
      row.append(tick, lab);
      panel.appendChild(row);
    });
    markCursor();
  }

  function place() {
    if (!panel) return;
    const r = btn.getBoundingClientRect(), gap = 6;
    // Le formulaire défile sous le panneau : quand le bouton sort de l'écran,
    // le panneau resterait collé au bord, détaché de son champ. On ferme.
    if (r.bottom < 0 || r.top > window.innerHeight) { close(false); return; }
    panel.style.minWidth = r.width + "px";
    panel.style.maxWidth = Math.max(160, window.innerWidth - 16) + "px";
    const h = panel.offsetHeight, w = panel.offsetWidth;
    // La fenêtre descend à 420 px de haut : sous le pli, le panneau se retourne.
    const below = window.innerHeight - r.bottom - gap;
    const up = below < h && r.top - gap > below;
    panel.classList.toggle("is-up", up);
    const top = Math.max(8, Math.min(up ? r.top - gap - h : r.bottom + gap,
                                     window.innerHeight - h - 8));
    panel.style.top = top + "px";
    panel.style.left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8) + "px";
  }

  function markCursor() {
    if (!panel) return;
    [...panel.children].forEach((row, i) => row.classList.toggle("is-cursor", i === cursor));
    const row = panel.children[cursor];
    if (row) {
      btn.setAttribute("aria-activedescendant", row.id);
      row.scrollIntoView({ block: "nearest" });
    }
  }

  function setCursor(i) {
    const n = sel.options.length;
    if (!n) return;
    cursor = Math.max(0, Math.min(n - 1, i));
    markCursor();
  }

  function moveCursor(d) {
    const n = sel.options.length;
    if (!n) return;
    let i = cursor < 0 ? (d > 0 ? -1 : 0) : cursor;
    for (let k = 0; k < n; k++) {           // saute les options désactivées
      i = (i + d + n) % n;
      if (!sel.options[i].disabled) break;
    }
    setCursor(i);
  }

  function open() {
    if (panel) return;
    panel = document.createElement("div");
    panel.className = "xsel-panel";
    panel.setAttribute("role", "listbox");
    cursor = sel.selectedIndex;
    render();
    document.body.appendChild(panel);
    place();
    btn.setAttribute("aria-expanded", "true");
    panel.addEventListener("pointerdown", (e) => e.preventDefault());  // garde le focus au bouton
    panel.addEventListener("click", (e) => {
      const row = e.target.closest(".xsel-opt");
      if (row) choose(+row.dataset.i);
    });
    document.addEventListener("pointerdown", onDocDown, true);
    window.addEventListener("resize", place);
    // En capture : `.form` défile en overflow-y:auto, et son défilement ne
    // remonte pas jusqu'à window en phase de bouillonnement.
    window.addEventListener("scroll", place, true);
  }

  function close(refocus) {
    if (!panel) return;
    const p = panel;
    panel = null;
    btn.setAttribute("aria-expanded", "false");
    btn.removeAttribute("aria-activedescendant");
    document.removeEventListener("pointerdown", onDocDown, true);
    window.removeEventListener("resize", place);
    window.removeEventListener("scroll", place, true);
    // Le panneau reste affiché le temps de son animation de sortie. On le sort
    // tout de suite des sélecteurs vivants : sinon, ouvrir une autre liste
    // pendant ces 130 ms fait cohabiter deux `.xsel-panel` dans le document.
    // Le panneau reste affiché le temps de son animation de sortie. On lui
    // retire son rôle et son curseur tout de suite : une liste en train de
    // disparaître ne doit plus être annoncée ni comptée comme active.
    p.classList.add("is-closing");
    p.removeAttribute("role");
    [...p.children].forEach((row) => row.classList.remove("is-cursor"));
    const drop = () => p.remove();
    p.addEventListener("animationend", drop, { once: true });
    setTimeout(drop, 260);  // filet : en reduced-motion il n'y a pas d'animation
    if (refocus) btn.focus();
  }

  function choose(i) {
    const o = sel.options[i];
    if (!o || o.disabled) return;
    if (sel.selectedIndex !== i) {
      sel.selectedIndex = i;
      // Le code existant écoute `change` sur #lang — il doit continuer à partir.
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
    syncButton();
    close(true);
  }

  function onDocDown(e) {
    if (!panel) return;
    if (!panel.contains(e.target) && !btn.contains(e.target)) close(false);
  }

  btn.addEventListener("click", () => (panel ? close(true) : open()));

  btn.addEventListener("keydown", (e) => {
    const k = e.key;
    // Ctrl+Espace est le raccourci de DICTÉE. Sans cette sortie, lancer la
    // dictée alors qu'un bouton de liste a le focus validait l'option sous le
    // curseur — c'est ainsi que la langue de dictée est passée en géorgien et
    // le micro a changé, à l'insu de l'utilisateur. Aucune combinaison avec un
    // modificateur n'appartient à la liste : on la laisse passer.
    if (e.ctrlKey || e.altKey || e.metaKey) { if (panel) close(false); return; }
    if (k === "Escape") { if (panel) { e.preventDefault(); close(true); } return; }
    if (k === "ArrowDown" || k === "ArrowUp") {
      e.preventDefault();
      if (!panel) open(); else moveCursor(k === "ArrowDown" ? 1 : -1);
      return;
    }
    if (k === "Enter" || k === " ") {
      e.preventDefault();
      if (!panel) open(); else choose(cursor);
      return;
    }
    if (panel && (k === "Home" || k === "End")) {
      e.preventDefault();
      setCursor(k === "Home" ? 0 : sel.options.length - 1);
      return;
    }
    // Saisie au clavier : les noms de micro se ressemblent tous par le début,
    // on accumule donc les lettres tapées coup sur coup.
    if (k.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
      const now = Date.now();
      typed = now - typedAt > 800 ? k : typed + k;
      typedAt = now;
      const p = typed.toLowerCase();
      const hit = [...sel.options].findIndex(
        (o) => !o.disabled && o.textContent.toLowerCase().startsWith(p));
      if (hit >= 0) { if (!panel) open(); setCursor(hit); }
    }
  });

  // Le reste du code reconstruit les <option> (liste des micros), écrit
  // `.value` / `.selectedIndex` et laisse l'i18n réécrire les libellés. On
  // couvre les deux voies : l'observateur pour le DOM, l'interception des
  // accesseurs pour la valeur — `sel.value = "2"` ne produit ni mutation ni
  // événement, et le bouton afficherait encore l'ancien micro.
  new MutationObserver(() => { syncButton(); if (panel) render(); }).observe(sel, {
    childList: true, subtree: true, characterData: true, attributes: true,
  });
  ["value", "selectedIndex"].forEach((prop) => {
    const d = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, prop);
    if (!d || !d.set) return;
    Object.defineProperty(sel, prop, {
      configurable: true,
      get() { return d.get.call(this); },
      set(v) { d.set.call(this, v); syncButton(); if (panel) render(); },
    });
  });

  syncButton();
}

function initSelects() {
  document.querySelectorAll(".select > select").forEach(enhanceSelect);
}

/* ---------- Forme d'onde (canvas) ---------- */
const wave = { mode: "loading", cv: null, ctx: null, bars: [], grad: null };
const NB = 54;
function initWave() {
  wave.cv = $("wave");
  wave.ctx = wave.cv.getContext("2d");
  wave.bars = new Array(NB).fill(0.05);
  resizeWave();
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) drawWave(0);
  else requestAnimationFrame(loopWave);
}
function resizeWave() {
  const dpr = window.devicePixelRatio || 1;
  const w = wave.cv.clientWidth, h = wave.cv.clientHeight;
  wave.cv.width = w * dpr; wave.cv.height = h * dpr;
  wave.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const g = wave.ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, "#FFD07A"); g.addColorStop(0.5, "#FFAA2B"); g.addColorStop(1, "#D9922F");
  wave.grad = g;
}
function targetAmp(i, t, mode) {
  const x = i / (NB - 1);
  if (mode === "recording") {
    const s = Math.sin(t * 7 + i * 0.55) * Math.sin(t * 3.3 + i * 0.22);
    const env = 0.4 + 0.5 * Math.abs(Math.sin(t * 2.1 + i * 0.4));
    return 0.14 + env * Math.abs(s) * 0.92;
  }
  if (mode === "processing") {
    const head = (t * 0.5) % 1;
    const d = x - head;
    return 0.07 + Math.exp(-(d * d) / (2 * 0.05 * 0.05)) * 0.8 + 0.03 * Math.sin(t * 8 + i);
  }
  if (mode === "loading") {
    return 0.06 + 0.05 * (0.5 + 0.5 * Math.sin(t * 2.4 + i * 0.5));
  }
  return 0.05 + 0.05 * (0.5 + 0.5 * Math.sin(t * 1.15 + i * 0.35)); // ready
}
function drawWave(t) {
  const ctx = wave.ctx, w = wave.cv.clientWidth, h = wave.cv.clientHeight, cy = h / 2;
  ctx.clearRect(0, 0, w, h);
  const gap = w / NB, bw = Math.max(2.5, gap * 0.4), r = bw / 2;
  const rec = wave.mode === "recording";
  ctx.fillStyle = wave.grad;
  ctx.globalAlpha = wave.mode === "ready" ? 0.5 : rec ? 1 : 0.75;
  ctx.shadowColor = "rgba(255,170,43,0.5)";
  ctx.shadowBlur = rec ? 10 : 0;
  for (let i = 0; i < NB; i++) {
    const tgt = targetAmp(i, t, wave.mode);
    wave.bars[i] += (tgt - wave.bars[i]) * 0.22;
    const bh = Math.max(bw, wave.bars[i] * h * 0.9);
    const x = i * gap + (gap - bw) / 2;
    ctx.beginPath();
    ctx.roundRect(x, cy - bh / 2, bw, bh, r);
    ctx.fill();
  }
  ctx.globalAlpha = 1; ctx.shadowBlur = 0;
}
function loopWave(ts) {
  drawWave(ts / 1000);
  requestAnimationFrame(loopWave);
}

/* ---------- Réglages ---------- */
function fillState(s) {
  // La langue d'abord : tout ce qui suit s'écrit déjà dans la bonne.
  setLang(s.lang === "fr" ? "fr" : "en", false);
  $("lang").value = window.PWI18n ? window.PWI18n.lang : "en";
  $("ptt").value = s.hotkey || "";
  $("toggle").value = s.toggle_hotkey || "";
  $("pttKeys").innerHTML = keycaps(s.hotkey);
  $("toggleKeys").innerHTML = keycaps(s.toggle_hotkey);

  const sel = $("device");
  sel.innerHTML = "";
  const def = new Option(tr("mic_default", "System default"), "");
  sel.add(def);
  (s.devices || []).forEach((d) => sel.add(new Option(d.name, String(d.index))));
  sel.value = s.device == null ? "" : String(s.device);
  if (sel.selectedIndex < 0) sel.value = "";  // index configuré disparu → défaut

  $("sounds").checked = s.sounds !== false;
  $("overlay").checked = s.overlay !== false;
  $("restore").checked = s.restore_clipboard !== false;

  $("peak").value = s.min_peak ?? 0.008;
  $("peakVal").textContent = Number(s.min_peak ?? 0.008).toFixed(3);
  $("score").value = s.vocab_score ?? 2.0;
  $("scoreVal").textContent = Number(s.vocab_score ?? 2.0).toFixed(1);

  // Le géorgien n'est proposé que si son modèle est réellement sur le disque.
  $("dictationLang").value = s.dictation_lang === "ka" ? "ka" : "multi";
  const kaOpt = $("dictationLang").querySelector('option[value="ka"]');
  if (kaOpt) {
    kaOpt.disabled = s.has_georgian === false;
    // L'option grisée sans un mot d'explication laissait deviner pourquoi.
    if (kaOpt.disabled) {
      const hint = tr("ka_missing", "Georgian model not installed — see README");
      kaOpt.title = hint;
      $("dictationLang").title = hint;
    }
  }
  setFootModel(s.dictation_lang);

  $("vocab").value = s.vocab_text || "";
  $("corr").value = (s.corrections || []).map((c) => `${c.error} = ${c.replacement}`).join("\n");

  (s.history || []).forEach(addTake);
  setStatus(s.status || "loading");
}

/* Ré-énumère les micros sans toucher au reste de l'état. Appelé quand la
   fenêtre revient du tray : brancher/débrancher un périphérique entre-temps
   rendait la liste de ready() obsolète. */
async function refreshDevices() {
  if (!api() || !api().list_devices) return;
  try {
    const devices = await api().list_devices();
    const sel = $("device");
    // On retient le NOM et pas l'index : débrancher un micro décale les index
    // PortAudio, et restaurer l'ancien sélectionnerait un autre micro.
    const curName = sel.selectedIndex > 0 ? sel.options[sel.selectedIndex].text : "";
    while (sel.options.length > 1) sel.remove(1);
    (devices || []).forEach((d) => sel.add(new Option(d.name, String(d.index))));
    sel.value = "";
    for (let i = 1; i < sel.options.length; i++) {
      if (sel.options[i].text === curName) { sel.selectedIndex = i; break; }
    }
  } catch (_) { /* bridge indisponible : la liste actuelle reste affichée */ }
}

function gatherSettings() {
  const dev = $("device").value;
  return {
    hotkey: $("ptt").value.trim() || "ctrl+space",
    toggle_hotkey: $("toggle").value.trim(),
    device: dev === "" ? null : parseInt(dev, 10),
    dictation_lang: $("dictationLang").value,
    sounds: $("sounds").checked,
    overlay: $("overlay").checked,
    restore_clipboard: $("restore").checked,
    min_peak: parseFloat($("peak").value),
    vocab_score: parseFloat($("score").value),
  };
}

function wireControls() {
  $("peak").addEventListener("input", (e) => $("peakVal").textContent = Number(e.target.value).toFixed(3));
  $("score").addEventListener("input", (e) => $("scoreVal").textContent = Number(e.target.value).toFixed(1));

  $("applySettings").addEventListener("click", () => {
    if (!api()) return;
    const s = gatherSettings();
    api().apply_settings(s);
    $("pttKeys").innerHTML = keycaps(s.hotkey);
    $("toggleKeys").innerHTML = keycaps(s.toggle_hotkey);
    setFootModel(s.dictation_lang);
  });
  $("saveVocab").addEventListener("click", () => api() && api().save_vocab($("vocab").value));
  $("saveCorr").addEventListener("click", () => {
    if (!api()) return;
    const list = [];
    $("corr").value.split("\n").forEach((line) => {
      line = line.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) return;
      const idx = line.indexOf("=");
      const error = line.slice(0, idx).trim(), replacement = line.slice(idx + 1).trim();
      if (error && replacement) list.push({ error, replacement });
    });
    api().save_corrections(list);
  });

  // La langue s'applique tout de suite : elle ne passe pas par « Appliquer les
  // réglages », qui recharge le modèle.
  $("lang").addEventListener("change", (e) => setLang(e.target.value, true));

  $("clearHist").addEventListener("click", clearHistory);
  $("min").addEventListener("click", () => api() && api().minimize());
  $("close").addEventListener("click", () => api() && api().minimize());
  $("quit").addEventListener("click", () => api() && api().quit_app());
}

/* ---------- Langue ----------
   L'anglais est la langue par défaut (elle est écrite dans le HTML) ; i18n.js
   substitue le français. Le choix est écrit dans config.json côté Python, donc
   il survit au redémarrage et sert aussi au menu de la barre système. */
function setLang(lang, persist) {
  if (window.PWI18n) window.PWI18n.apply(lang);
  // Les textes posés par le script ne portent pas de data-i18n : on les refait.
  setStatus(currentStatus);
  setFootModel();
  $("pttKeys").innerHTML = keycaps($("ptt").value);
  $("toggleKeys").innerHTML = keycaps($("toggle").value);
  const sel = $("device");
  if (sel.options.length) sel.options[0].text = tr("mic_default", "System default");
  document.querySelectorAll(".take__copy").forEach((b) => {
    b.textContent = tr("hist_copy", "Copy");  // les prises déjà affichées
  });
  if (persist && api()) api().set_lang(lang);
}

/* ---------- Fenêtre : agrandir, plein écran, redimensionner ----------
   La fenêtre est sans bordure : Windows ne fournit ni bouton d'agrandissement
   ni poignées, tout est ici. */

let maximized = false;

async function toggleMax() {
  if (!api()) return;
  maximized = await api().toggle_maximize();
  document.body.classList.toggle("is-max", !!maximized);
  resizeWave();
}

function initWindowControls() {
  $("max").addEventListener("click", toggleMax);

  // Double-clic sur la barre de titre : le geste Windows attendu.
  document.querySelector(".titlebar").addEventListener("dblclick", (e) => {
    if (!e.target.closest(".winbtn")) toggleMax();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "F11") { e.preventDefault(); api() && api().toggle_fullscreen(); }
  });

  // Poignées. On raisonne en coordonnées ÉCRAN : la fenêtre bouge sous le
  // curseur pendant le tirage, donc les coordonnées client seraient un
  // référentiel mouvant. Un seul appel au bridge par frame d'affichage.
  let drag = null, pending = null, raf = null;

  const flush = () => {
    raf = null;
    if (pending && api()) { api().set_bounds(pending.x, pending.y, pending.w, pending.h); }
    pending = null;
  };

  document.querySelectorAll(".rz").forEach((h) => {
    h.addEventListener("pointerdown", async (e) => {
      if (e.button !== 0 || !api() || maximized) return;
      const b = await api().window_bounds();
      if (!b) return;
      drag = { edge: h.dataset.edge, sx: e.screenX, sy: e.screenY, b };
      h.setPointerCapture(e.pointerId);  // les mouvements suivent hors fenêtre
      e.preventDefault();
    });

    h.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.screenX - drag.sx, dy = e.screenY - drag.sy, E = drag.edge;
      let { x, y, width: w, height: hh } = drag.b;
      // Tirer par le haut ou la gauche déplace l'origine autant qu'il
      // redimensionne — sinon la fenêtre glisserait au lieu de s'étirer.
      if (E.includes("e")) w += dx;
      if (E.includes("s")) hh += dy;
      if (E.includes("w")) { w -= dx; x += dx; }
      if (E.includes("n")) { hh -= dy; y += dy; }
      pending = { x, y, w, h: hh };
      if (raf === null) raf = requestAnimationFrame(flush);
    });

    const end = (e) => {
      if (!drag) return;
      drag = null;
      if (raf !== null) { cancelAnimationFrame(raf); flush(); }
      try { h.releasePointerCapture(e.pointerId); } catch (_) {}
      resizeWave();
    };
    h.addEventListener("pointerup", end);
    h.addEventListener("pointercancel", end);
  });
}

/* ---------- Démarrage ---------- */
window.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initSelects();
  initWave();
  wireControls();
  initWindowControls();
  // L'orbe « working » : l'app est vivante et prête à écouter.
  if (window.PWOrb) {
    const el = $("stateOrb");
    if (el) window.PWOrb.mount(el, { size: window.innerWidth < 560 ? 34 : 44 });
  }
  window.addEventListener("resize", () => { resizeWave(); });
});
window.addEventListener("pywebviewready", async () => {
  try {
    const state = await window.pywebview.api.ready();
    fillState(state);
  } catch (e) { console.error("ready() a échoué", e); }
});
