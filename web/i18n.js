/* Langues de la faceplate.
 *
 * L'anglais est écrit en dur dans le HTML (langue par défaut) ; le français vit
 * dans le dictionnaire ci-dessous. Au premier basculement, le texte anglais
 * d'origine est mémorisé, ce qui permet de revenir en arrière sans recharger.
 *
 * Marquage dans le HTML :
 *   data-i18n        → textContent
 *   data-i18n-html   → innerHTML (quand la phrase contient du gras ou un <br>)
 *   data-i18n-title  → attribut title (infobulle)
 *   data-i18n-aria   → attribut aria-label
 */

(function () {
  "use strict";

  var FR = {
    // Barre de titre
    tt_min: "Réduire dans la barre système",
    tt_max: "Agrandir · double-clic sur la barre · F11 = plein écran",
    tt_close: "Réduire dans la barre système",
    aria_min: "Réduire",
    aria_max: "Agrandir",
    aria_close: "Fermer",

    // Signal
    st_starting: "Démarrage",
    keys_hold: "maintenir",
    keys_handsfree: "mains-libres",

    // Onglets
    tab_history: "Historique",
    tab_settings: "Réglages",
    tab_vocab: "Vocabulaire",
    tab_corr: "Corrections",

    // Historique
    hist_takes: "Prises",
    hist_clear: "Effacer",
    hist_empty: "Aucune prise pour l'instant.<br />Maintiens <b>Ctrl + Espace</b> et parle.",

    // Réglages
    lbl_lang: "Langue",
    lbl_dictation: "Langue de dictée",
    hint_dictation: "Changer recharge le modèle, ce qui prend quelques secondes. Le vocabulaire custom est en alphabet latin : il ne s'applique pas en géorgien.",
    opt_multi: "Multilingue — Parakeet v3 (25 langues)",
    opt_ka: "ქართული — Géorgien",
    ka_missing: "Modèle géorgien absent",
    lbl_ptt: "Raccourci push-to-talk",
    lbl_toggle: "Raccourci mains-libres (toggle)",
    lbl_mic: "Microphone",
    sw_sounds: "Sons de feedback",
    sw_overlay: "HUD à l'écran pendant la dictée",
    sw_restore: "Restaurer le presse-papiers",
    lbl_peak: "Sensibilité au silence",
    lbl_score: "Force du vocabulaire",
    hint_score: "2 = doux · 4 = fort · 8 = le mot s'invite partout. Changer la force ou le micro applique après un court rechargement.",
    btn_apply: "Appliquer les réglages",

    // Vocabulaire et corrections
    hint_vocab: "Un mot ou nom propre par ligne · <b>#</b> = commentaire. Ces mots sont boostés à la transcription.",
    btn_savevocab: "Enregistrer &amp; recharger",
    hint_corr: "Une correction par ligne : <b>erreur = remplacement</b> (insensible à la casse, mots entiers). Appliqué instantanément.",
    btn_savecorr: "Enregistrer les corrections",

    // Pied de page — le nom du modèle est posé par le script (setFootModel)
    foot_local: "100&nbsp;% local",
    foot_offline: "hors ligne",
    model_multi: "Parakeet&nbsp;v3",
    model_ka: "Géorgien",
    btn_quit: "Quitter",

    // Chaînes posées par le script (statuts, touches, listes)
    status_loading: "Chargement",
    status_reloading: "Rechargement",
    status_ready: "Prêt",
    status_recording_ptt: "Écoute",
    status_recording_toggle: "Mains-libres",
    status_processing: "Transcription",
    key_shift: "Maj",
    key_space: "Espace",
    key_rctrl: "Ctrl D",
    key_rshift: "Maj D",
    mic_default: "Défaut système",
    copied: "Copié dans le presse-papiers",
  };

  var lang = "en";
  var saved = new Map();  // élément+attribut → texte anglais d'origine

  function remember(el, attr, value) {
    var key = attr;
    var box = saved.get(el);
    if (!box) { box = {}; saved.set(el, box); }
    if (!(key in box)) box[key] = value;
    return box[key];
  }

  /** Traduit une clé. En anglais, `fallback` (le texte du HTML) fait foi. */
  function t(key, fallback) {
    if (lang === "fr" && FR[key] != null) return FR[key];
    return fallback != null ? fallback : key;
  }

  function each(attr, read, write) {
    document.querySelectorAll("[" + attr + "]").forEach(function (el) {
      var key = el.getAttribute(attr);
      var en = remember(el, attr, read(el));
      write(el, lang === "fr" && FR[key] != null ? FR[key] : en);
    });
  }

  function apply(l) {
    lang = l === "fr" ? "fr" : "en";
    document.documentElement.lang = lang;
    each("data-i18n", function (e) { return e.textContent; },
      function (e, v) { e.textContent = v; });
    each("data-i18n-html", function (e) { return e.innerHTML; },
      function (e, v) { e.innerHTML = v; });
    each("data-i18n-title", function (e) { return e.title; },
      function (e, v) { e.title = v; });
    each("data-i18n-aria", function (e) { return e.getAttribute("aria-label"); },
      function (e, v) { e.setAttribute("aria-label", v); });
    document.dispatchEvent(new CustomEvent("pw-lang", { detail: lang }));
  }

  window.PWI18n = {
    apply: apply,
    t: t,
    get lang() { return lang; },
  };
})();
