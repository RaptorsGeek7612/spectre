---
name: python-backend
description: "Développement Python du moteur de Spectre (src/spectre, Python ≥ 3.11, typé strict, uv, ruff, mypy, pytest). Utiliser pour écrire ou modifier du code Python du dépôt."
---

# Python Backend — Spectre

## Règles de code
- Annotations partout, `mypy --strict` ; `from __future__ import annotations`.
- Docstrings courtes en anglais ; messages pour l'utilisateur en français.
- Dataclasses `frozen=True` pour les valeurs ; pas d'état global mutable.
- Fichiers : `encoding="utf-8"` explicite ; écrire par `write_bytes(s.encode())` dans les scripts
  de patch (évite CRLF et `\n` cassés sous Windows).
- Sous-processus : liste d'arguments, jamais `shell=True`, délai obligatoire.
- IDs de modèles seulement dans `src/spectre/config.py`.

## Commandes (Windows)
```
uv run --no-sync ruff format . ; uv run --no-sync ruff check .
.venv/Scripts/python.exe -m mypy --no-native-parser src
uv run --no-sync pytest -m "not live" -q
```
Jamais `uv sync` nu (retire les extras voix/vision) : `uv sync --extra voice --extra vision`.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
