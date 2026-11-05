---
name: scalability
description: "Montée en charge et performances de Spectre sur un PC modeste (Ryzen 7 5825U, 15 Go, CPU seul) : files, parallélisme, cache, limites mémoire du prompt. Utiliser quand une fonction ralentit ou va traiter plus de volume."
---

# Scalability — Spectre

## Contraintes réelles
CPU seulement (ComfyUI, Whisper, modèles locaux lents), 15 Go de RAM, SQLite mono-fichier.

## Leviers
- Parallélisme borné : `mission_parallel` (1 à 4), pas de pool illimité.
- Prompt : mémoire plafonnée (150 faits / 45 000 car.), compactage de nuit ; recherche (`recall`,
  FTS5) au lieu de tout injecter.
- Tâches longues (images, vidéos, portraits) : en fond, numéro + durée estimée, jamais bloquantes.
- Base : index, transactions courtes, purge des journaux anciens (`activity.KEEP_DAYS`).
- Mesurer avant d'optimiser : `time.perf_counter`, `spend.record` (durée par rôle).

## Seuils d'alerte
Tour de conversation > 30 s hors outil lent ; base > 1 Go ; prompt système proche de 32 767
car. (déjà géré par `--system-prompt-file`).

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
