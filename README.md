# PersonalWhisper

Dictée vocale locale push-to-talk pour Windows — clone maison de SuperWhisper.

**Maintenir `Ctrl + Espace` → parler → relâcher** : le texte se colle au curseur, dans n'importe quelle app. Pendant la dictée, un HUD « NK » avec les vagues de son s'affiche en bas d'écran (puis des points pulsants pendant la transcription). 100 % local et offline (Parakeet-tdt-0.6b-v3 via sherpa-onnx, CPU).

**Mode mains-libres (toggle) : `Ctrl + Shift + Espace`** — un appui démarre la dictée, un second l'arrête. Pas besoin de maintenir : on peut lâcher les touches et parler entre les deux. Sécurité : un toggle oublié se coupe seul à `max_duration_s`.

L'espace est avalé tant que Ctrl est enfoncé : pas d'espaces parasites tapés dans l'app active pendant la dictée.

## Lancer

```
.venv\Scripts\python.exe app.py
```

Sans console (tray uniquement) :

```
.venv\Scripts\pythonw.exe app.py
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

Crée un **raccourci sur le Bureau** (`PersonalWhisper`, icône « NK », lance en
tray sans console via `pythonw.exe`) **et** un raccourci dans `shell:startup`
pour le **démarrage automatique à chaque login Windows**. Options :

- `install.ps1 -NoStartup` — Bureau seulement, pas de démarrage auto
- `install.ps1 -Uninstall` — retire les deux raccourcis

Une seule instance peut tourner à la fois (mutex nommé Windows) : démarrage auto
+ double-clic sur le raccourci ne créent jamais deux hooks clavier. L'icône se
régénère avec `python make_icon.py`.

Clic droit sur l'icône de la barre système → **Quitter**.

## Setup depuis zéro

```
python -m venv .venv
.venv\Scripts\pip install sherpa-onnx sounddevice numpy keyboard pyperclip pystray pillow
curl.exe -L --ssl-no-revoke -o parakeet-v3-int8.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2
tar -xjf parakeet-v3-int8.tar.bz2
```

(`--ssl-no-revoke` : nécessaire avec Avast, son certificat MITM n'a pas d'info de révocation.)

## Roadmap

- [ ] Modes IA (reformulation mail / note / prompt custom via LLM) — décidé 09/07 :
      déclenchement par 2e raccourci dédié (Ctrl+Alt+Space), moteur LLM à choisir
      le moment venu (API Haiku ~0,1 ¢/usage vs Ollama local gratuit mais lent CPU)
- [x] Vocabulaire custom (noms propres : PERSEUS, Mecazic, GHL…) — hotwords + corrections
- [x] Toggle mains-libres (Ctrl+Shift+Espace) en plus du push-to-talk
