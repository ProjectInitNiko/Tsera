# PersonalWhisper

Dictée vocale locale push-to-talk pour Windows — clone maison de SuperWhisper.

**Maintenir `Ctrl droit` → parler → relâcher** : le texte se colle au curseur, dans n'importe quelle app. 100 % local et offline (Parakeet-tdt-0.6b-v3 via sherpa-onnx, CPU).

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
| `hotkey` | `right ctrl` | Touche push-to-talk (syntaxe lib `keyboard`) |
| `model_dir` | `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8` | Dossier du modèle |
| `num_threads` | `4` | Threads CPU pour l'inférence |
| `min_duration_s` | `0.3` | En dessous = appui accidentel, ignoré |
| `max_duration_s` | `120` | Coupe de sécurité |
| `sounds` | `true` | Bips de feedback (début / erreur) |
| `restore_clipboard` | `true` | Restaure le presse-papiers après collage |

## Démarrage automatique avec Windows

Créer un raccourci vers `.venv\Scripts\pythonw.exe` avec argument `app.py`
(répertoire de démarrage : `D:\Projects\PersonalWhisper`) dans le dossier
`shell:startup`.

## Setup depuis zéro

```
python -m venv .venv
.venv\Scripts\pip install sherpa-onnx sounddevice numpy keyboard pyperclip pystray pillow
curl.exe -L --ssl-no-revoke -o parakeet-v3-int8.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2
tar -xjf parakeet-v3-int8.tar.bz2
```

(`--ssl-no-revoke` : nécessaire avec Avast, son certificat MITM n'a pas d'info de révocation.)

## Roadmap

- [ ] Modes IA (reformulation mail / note / prompt custom via LLM)
- [ ] Vocabulaire custom (noms propres : PERSEUS, Mecazic, GHL…)
- [ ] Toggle en plus du push-to-talk
