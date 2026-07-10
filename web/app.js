/* PersonalWhisper — UI web. Bridge pywebview + forme d'onde + interactions. */
"use strict";

const $ = (id) => document.getElementById(id);
const api = () => (window.pywebview && window.pywebview.api) || null;

const STATUS = {
  loading:          { led: "amber", word: "Chargement",     rec: false, wave: "loading" },
  reloading:        { led: "amber", word: "Rechargement",   rec: false, wave: "loading" },
  ready:            { led: "green", word: "Prêt",           rec: false, wave: "ready" },
  recording_ptt:    { led: "red",   word: "Écoute",         rec: true,  wave: "recording" },
  recording_toggle: { led: "red",   word: "Mains-libres",   rec: true,  wave: "recording" },
  processing:       { led: "amber", word: "Transcription",  rec: false, wave: "processing" },
};

let modelReady = false;

/* ---------- Bridge : Python appelle window.PW.on(kind, payload) ---------- */
window.PW = {
  on(kind, payload) {
    if (kind === "status") setStatus(payload);
    else if (kind === "transcription") addTake(payload);
    else if (kind === "notice") toast(payload);
    else if (kind === "model_ready") { modelReady = true; setHeavyEnabled(true); }
    else if (kind === "shown") { /* fenêtre ré-affichée */ }
  },
};

/* ---------- Statut + forme d'onde ---------- */
function setStatus(s) {
  const st = STATUS[s] || { led: "amber", word: s, rec: false, wave: "ready" };
  $("led").className = "led led--" + st.led;
  $("statusWord").textContent = st.word;
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
const KEYNAME = { ctrl: "Ctrl", control: "Ctrl", shift: "Maj", alt: "Alt", space: "Espace",
  "right ctrl": "Ctrl D", "right shift": "Maj D" };
function keycaps(hotkey) {
  if (!hotkey) return "";
  return hotkey.split("+").map((p) => {
    const k = p.trim().toLowerCase();
    const name = KEYNAME[k] || (k.charAt(0).toUpperCase() + k.slice(1));
    return `<span class="cap">${name}</span>`;
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
  copy.textContent = "Copier";
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
  function moveInk(tab) {
    ink.style.left = tab.offsetLeft + "px";
    ink.style.width = tab.offsetWidth + "px";
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
  $("ptt").value = s.hotkey || "";
  $("toggle").value = s.toggle_hotkey || "";
  $("pttKeys").innerHTML = keycaps(s.hotkey);
  $("toggleKeys").innerHTML = keycaps(s.toggle_hotkey);

  const sel = $("device");
  sel.innerHTML = "";
  const def = new Option("Défaut système", "");
  sel.add(def);
  (s.devices || []).forEach((d) => sel.add(new Option(`${d.index} · ${d.name}`, String(d.index))));
  sel.value = s.device == null ? "" : String(s.device);

  $("sounds").checked = s.sounds !== false;
  $("overlay").checked = s.overlay !== false;
  $("restore").checked = s.restore_clipboard !== false;

  $("peak").value = s.min_peak ?? 0.008;
  $("peakVal").textContent = Number(s.min_peak ?? 0.008).toFixed(3);
  $("score").value = s.vocab_score ?? 2.0;
  $("scoreVal").textContent = Number(s.vocab_score ?? 2.0).toFixed(1);

  $("vocab").value = s.vocab_text || "";
  $("corr").value = (s.corrections || []).map((c) => `${c.error} = ${c.replacement}`).join("\n");

  (s.history || []).forEach(addTake);
  setStatus(s.status || "loading");
}

function gatherSettings() {
  const dev = $("device").value;
  return {
    hotkey: $("ptt").value.trim() || "ctrl+space",
    toggle_hotkey: $("toggle").value.trim(),
    device: dev === "" ? null : parseInt(dev, 10),
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

  $("clearHist").addEventListener("click", clearHistory);
  $("min").addEventListener("click", () => api() && api().minimize());
  $("close").addEventListener("click", () => api() && api().minimize());
  $("quit").addEventListener("click", () => api() && api().quit_app());
}

/* ---------- Démarrage ---------- */
window.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initWave();
  wireControls();
  window.addEventListener("resize", () => { resizeWave(); });
});
window.addEventListener("pywebviewready", async () => {
  try {
    const state = await window.pywebview.api.ready();
    fillState(state);
  } catch (e) { console.error("ready() a échoué", e); }
});
