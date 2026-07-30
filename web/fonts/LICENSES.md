# Licences des polices redistribuées

Ce dossier contient des fichiers de police tiers redistribués avec Tsera. Ils ne
sont **pas** couverts par la licence MIT du projet : chacun conserve la sienne.

Les polices sont également embarquées en data-URI dans `fonts.css` (généré par
`build_fonts_css.py`, pour contourner le blocage CORS des woff2 sous `file://`).
**Cette copie encodée est soumise aux mêmes licences que les fichiers source.**

---

## Anton — OFL-1.1

- Fichier : `anton-400.woff2`
- Copyright : Vernon Adams et les auteurs du projet Anton
- Licence : SIL Open Font License 1.1 — texte complet dans [`OFL.txt`](OFL.txt)
- Source : https://github.com/google/fonts/tree/main/ofl/anton

## Inter — OFL-1.1

- Fichiers : `inter-400.woff2`, `inter-500.woff2`, `inter-600.woff2`,
  `inter-700.woff2`, et `../../assets/inter-600.ttf`
- Copyright (c) 2016 The Inter Project Authors
- Licence : SIL Open Font License 1.1 — texte complet dans [`OFL.txt`](OFL.txt)
- Source : https://github.com/rsms/inter

## Roboto Mono — Apache-2.0

- Fichier : `robotomono-var.woff2`
- Copyright : Christian Robertson / Google
- Licence : Apache License 2.0 — texte complet dans [`Apache-2.0.txt`](Apache-2.0.txt)
- Source : https://github.com/googlefonts/robotomono

---

## Obligations concrètes

**OFL-1.1** (Anton, Inter) : la notice de copyright et le texte de la licence
doivent accompagner les fichiers — c'est le rôle de ce dossier. Les polices ne
peuvent pas être vendues seules, et un dérivé modifié ne peut pas conserver le
nom réservé de la police d'origine.

**Apache-2.0** (Roboto Mono) : conserver la notice de copyright et le texte de
la licence.

Aucune des trois n'impose de contrainte sur la licence du logiciel qui les
utilise. Le MIT de Tsera n'est pas affecté.
