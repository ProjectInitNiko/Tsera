# PersonalWhisper

Dictée vocale locale push-to-talk pour Windows — clone maison de SuperWhisper.

**Maintenir `Ctrl + Espace` → parler → relâcher** : le texte se colle au curseur, dans n'importe quelle app. Pendant la dictée, un HUD « NK » avec les vagues de son s'affiche en bas d'écran (puis des points pulsants pendant la transcription). 100 % local et offline (Parakeet-tdt-0.6b-v3 via sherpa-onnx, CPU).

**Mode mains-libres (toggle) : `Ctrl + Shift + Espace`** — un appui démarre la dictée, un second l'arrête. Pas besoin de maintenir : on peut lâcher les touches et parler entre les deux. Sécurité : un toggle oublié se coupe seul à `max_duration_s`.

L'espace est avalé tant que Ctrl est enfoncé : pas d'espaces parasites tapés dans l'app active pendant la dictée.

## Interface

Fenêtre **web embarquée** (pywebview / WebView2), identité « matériel de studio »
(charbon + ambre signal + rouge VU, Anton / Inter / Roboto Mono). Elle donne :
le **statut live** avec une **forme d'onde** qui réagit à l'état (repos / écoute /
transcription), l'**historique des dictées** (avec copie), des **réglages
éditables** (raccourcis, micro, sons, HUD, sensibilité, force du vocabulaire) et
des **éditeurs de vocabulaire et de corrections**. Fermer la fenêtre la **réduit
dans la barre système** (l'app continue d'écouter) ; l'icône tray propose
*Ouvrir* / *Quitter*.

Le front vit dans `web/` (`index.html` + `style.css` + `app.js`), piloté par le
moteur Python via le bridge `webui.py`. Les polices sont embarquées en data-URI
dans `web/fonts.css` (généré par `build_fonts_css.py` — évite le blocage CORS des
woff2 sous `file://`).

## Lancer

```
.venv\Scripts\python.exe app.py          # fenêtre + console (logs de debug)
.venv\Scripts\pythonw.exe app.py         # fenêtre, sans console
.venv\Scripts\pythonw.exe app.py --tray  # démarre réduit dans le tray (login)
```

## Config (`config.json`)

| Clé | Défaut | Description |
| --- | --- | --- |
| `hotkey` | `ctrl+space` | Push-to-talk : combo `modificateurs+touche` (la touche finale est avalée pendant la dictée) ou touche seule (ex. `right ctrl`) |
| `toggle_hotkey` | `ctrl+shift+space` | Mode mains-libres : 1er appui démarre, 2e arrête. `null` ou `""` pour désactiver. Peut partager le trigger du `hotkey` |
| `model_dir` | `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` | Dossier du modèle |
| `num_threads` | `4` | Threads CPU pour l'inférence |
| `min_duration_s` | `0.3` | En dessous = appui accidentel, ignoré |
| `max_duration_s` | `120` | Coupe de sécurité |
| `min_peak` | `0.008` | Pic audio minimal — en dessous = silence, rien n'est collé (évite les hallucinations du beam search sur le bruit de fond) |
| `sounds` | `true` | Bips de feedback (début / erreur) |
| `restore_clipboard` | `true` | Restaure le presse-papiers après collage |
| `overlay` | `true` | HUD « NK » + vagues de son en bas d'écran pendant la dictée |
| `device` | `null` (absent) | Index du micro (voir la liste dans Réglages) ; `null`/absent = défaut système |
| `vocab_file` | `vocab.txt` | Vocabulaire custom (un mot/expression par ligne, `#` = commentaire) |
| `vocab_score` | `2.0` | Force du biasing (validé : 2 = doux, 4 = fort, 8 = le mot s'invite partout) |
| `corrections` | `{...}` | Remplacements post-transcription, insensibles à la casse, mots entiers (casse finale + cafouillages connus) |

## Vocabulaire custom

Deux couches complémentaires :

1. **`vocab.txt`** — les mots listés sont boostés dans le décodeur (hotwords sherpa-onnx,
   passe automatiquement en `modified_beam_search`, ~1,2× plus lent que greedy).
   Validé : « Mechazic → Mecazic », « Adomias → Adomeos », « Superbase → Supabase ».
   Fichier vide ou absent = greedy (comportement d'origine).
2. **`corrections`** (config.json) — post-traitement déterministe : casse
   (`perseus` → `PERSEUS`) et cafouillages récurrents (`robo dk` → `RoboDK`).
   Quand un nom sort mal écrit à l'usage, ajouter l'erreur observée ici.

Note technique : le modèle exporté n'embarque pas son sentencepiece ; un
`bpe_from_tokens.vocab` (scores uniformes) est généré au premier lancement dans le
dossier du modèle pour encoder les hotwords — biasing vérifié effectif avec ça.

## Installation comme app Windows (raccourci + démarrage auto)

```
powershell -ExecutionPolicy Bypass -File install.ps1
```

Crée un **raccourci sur le Bureau** (`PersonalWhisper`, icône « NK », ouvre la
fenêtre) **et** un raccourci dans `shell:startup` pour le **démarrage automatique
à chaque login Windows** (avec `--tray` : démarre réduit, sans ouvrir la fenêtre).
Les deux lancent via `pythonw.exe` (aucune console). Options :

- `install.ps1 -NoStartup` — Bureau seulement, pas de démarrage auto
- `install.ps1 -Uninstall` — retire les deux raccourcis

Une seule instance peut tourner à la fois (mutex nommé Windows) : démarrage auto
+ double-clic sur le raccourci ne créent jamais deux hooks clavier. L'icône se
régénère avec `python make_icon.py`.

Clic droit sur l'icône de la barre système → **Quitter**.

## Setup depuis zéro

```
python -m venv .venv
.venv\Scripts\pip install sherpa-onnx sounddevice numpy keyboard pyperclip pystray pillow pywebview
curl.exe -L --ssl-no-revoke -o parakeet-v3-int8.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2
tar -xjf parakeet-v3-int8.tar.bz2
```

(`--ssl-no-revoke` : nécessaire avec Avast, son certificat MITM n'a pas d'info de révocation.)

Le `tar` de Windows ne sait pas décompresser le bzip2 (« unable to run program "bzip2 -d" ») :
`python -c "import tarfile; t=tarfile.open('parakeet-v3-int8.tar.bz2','r:bz2'); t.extractall('.')"`.

## Langue de dictée

Deux modèles, choisis dans **Réglages → Langue de dictée** ; en changer recharge
le modèle (quelques secondes). Parakeet reste le défaut.

| | Parakeet-tdt-0.6b-v3 (défaut) | Géorgien |
| --- | --- | --- |
| Couverture | 25 langues européennes | ქართული uniquement |
| Poids | 641 Mo (int8) | 477 Mo (fp32) |
| Chargement | ~12 s | ~16 s |
| Vocabulaire custom | oui | non (voir plus bas) |

Le modèle géorgien est **[`nvidia/stt_ka_fastconformer_hybrid_large_pc`](https://huggingface.co/nvidia/stt_ka_fastconformer_hybrid_large_pc)**
(NVIDIA, **licence CC-BY-4.0**, ~115 M paramètres, entraîné sur ~163 h de Common
Voice 17 + Fleurs), dans l'export ONNX de
[LukeJacob2023](https://huggingface.co/LukeJacob2023/sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc).
Même famille que Parakeet (NeMo transducer) : il se charge par le même chemin.

WER annoncé : **5,73 %** sur le test Common Voice, **13,44 %** sur Fleurs. Le
second est le plus représentatif d'une dictée réelle — sensiblement moins bon que
le français, 163 h d'entraînement seulement.

Le **vocabulaire custom ne s'applique pas** en géorgien : il est écrit en alphabet
latin, pour lequel ce modèle n'a aucun token. Le biasing n'aurait rien à quoi
s'accrocher, il est donc désactivé dans ce mode.

Installation (le dossier est hors dépôt, comme les autres modèles) :

```
mkdir sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc
cd sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc
curl.exe -L --ssl-no-revoke -O https://huggingface.co/LukeJacob2023/sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc/resolve/main/encoder.onnx
curl.exe -L --ssl-no-revoke -O https://huggingface.co/LukeJacob2023/sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc/resolve/main/decoder.onnx
curl.exe -L --ssl-no-revoke -O https://huggingface.co/LukeJacob2023/sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc/resolve/main/joiner.onnx
curl.exe -L --ssl-no-revoke -O https://huggingface.co/LukeJacob2023/sherpa-onnx-stt_ka_fastconformer_hybrid_large_pc/resolve/main/tokens.txt
```

Sans ce dossier, l'option reste grisée dans les réglages.

## Crédits

- **Modèle géorgien** : NVIDIA `stt_ka_fastconformer_hybrid_large_pc`, licence [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).
- **Orbes d'état** (`orbs.py`, `web/orbs.js`) : portage de [thinking-orbs](https://github.com/Jakubantalik/thinking-orbs) de Jakub Antalik, licence MIT — notice complète en tête de chaque fichier.

## Roadmap

- [ ] Modes IA (reformulation mail / note / prompt custom via LLM) — décidé 09/07 :
      déclenchement par 2e raccourci dédié (Ctrl+Alt+Space), moteur LLM à choisir
      le moment venu (API Haiku ~0,1 ¢/usage vs Ollama local gratuit mais lent CPU)
- [x] Vocabulaire custom (noms propres : PERSEUS, Mecazic, GHL…) — hotwords + corrections
- [x] Toggle mains-libres (Ctrl+Shift+Espace) en plus du push-to-talk
- [x] Interface (statut, historique, réglages, éditeurs vocab/corrections) + réduction au tray
