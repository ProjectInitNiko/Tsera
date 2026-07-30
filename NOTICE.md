# NOTICE — composants tiers

Tsera est publié sous licence MIT (voir `LICENSE`). Ce fichier liste les
composants tiers que le projet embarque, télécharge ou redistribue, avec leurs
obligations propres. **Toute redistribution de Tsera — source ou binaire — doit
conserver ce fichier.**

---

## Modèles de transcription

Les deux modèles sont publiés par NVIDIA sous **CC-BY-4.0**, qui autorise
l'usage commercial mais **exige une attribution explicite**. Ils ne sont pas
versionnés dans ce dépôt : ils se téléchargent au setup (voir README).

### Parakeet-tdt-0.6b-v3 — modèle par défaut, 25 langues européennes

- Modèle : [`nvidia/parakeet-tdt-0.6b-v3`](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) — NVIDIA Corporation
- Licence : [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- Export ONNX int8 utilisé ici : [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models), Apache-2.0

### stt_ka_fastconformer_hybrid_large_pc — dictée géorgienne

- Modèle : [`nvidia/stt_ka_fastconformer_hybrid_large_pc`](https://huggingface.co/nvidia/stt_ka_fastconformer_hybrid_large_pc) — NVIDIA Corporation
- Licence : [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
- ~115 M paramètres, entraîné sur ~163 h (Common Voice 17 + Fleurs)
- Export ONNX utilisé ici : [LukeJacob2023](https://huggingface.co/LukeJacob2023/sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc)

---

## Code repris

### thinking-orbs — Jakub Antalik

- Source : [Jakubantalik/thinking-orbs](https://github.com/Jakubantalik/thinking-orbs)
- Licence : MIT
- Portage dans `orbs.py` (rendu PIL) et `web/orbs.js` (canvas), teinte adaptée.
- Notice complète conservée en tête de chacun des deux fichiers.

---

## Polices

Redistribuées dans `web/fonts/` (woff2) et `assets/` (ttf). Détail des
copyrights et textes de licence complets : [`web/fonts/LICENSES.md`](web/fonts/LICENSES.md).

| Police | Licence | Fichiers |
| --- | --- | --- |
| Anton | OFL-1.1 | `web/fonts/anton-400.woff2` |
| Inter | OFL-1.1 | `web/fonts/inter-{400,500,600,700}.woff2`, `assets/inter-600.ttf` |
| Roboto Mono | Apache-2.0 | `web/fonts/robotomono-var.woff2` |

---

## Dépendances Python

Licences relevées depuis les métadonnées des paquets installés (`importlib.metadata`).

| Paquet | Version | Licence |
| --- | --- | --- |
| sherpa-onnx | 1.13.4 | Apache-2.0 |
| sounddevice | 0.5.5 | MIT |
| numpy | 2.5.1 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| keyboard | 0.13.5 | MIT |
| pyperclip | 1.11.0 | BSD-3-Clause |
| **pystray** | 0.19.5 | **LGPL-3.0** |
| pillow | 12.3.0 | MIT-CMU (HPND) |
| pywebview | 6.2.1 | BSD-3-Clause |

**Note sur pystray (LGPL-3.0).** C'est la seule dépendance copyleft de la pile.
Tsera l'utilise comme bibliothèque, sans la modifier, ce qui est explicitement
couvert par la LGPL. Tsera étant distribué en source ouverte, la clause de
relink de la LGPL est satisfaite de fait. À reconsidérer uniquement si une
version fermée ou un binaire à liaison statique était envisagé un jour.

---

## Composants système

- **Microsoft Edge WebView2 Runtime** — requis par pywebview pour l'interface.
  Non redistribué : présent sur Windows 11, installé via le bootstrapper
  Microsoft sur Windows 10.

---

## Marques

Tsera est un projet indépendant, sans affiliation ni approbation de la part de
Superwhisper, Wispr Flow, NVIDIA ou Microsoft. Ces noms n'apparaissent dans la
documentation qu'à titre de référence descriptive, pour situer le projet.
