---
name: async-task-processing
description: "Tâches de fond de Spectre : missions, routines planifiées (équivalent APScheduler), rappels, consolidation de nuit, générations longues. Le cahier cite Redis ; Spectre utilise SQLite + threads. Utiliser pour toute tâche asynchrone ou planifiée."
---

# Async Task Processing — Spectre

## Existant
- File de missions en base (`missions.py`, `MissionEngine.tick`), reprise après redémarrage
  (`recover()` note `mission_interrupted` puis remet en file).
- Routines (`routines.py`) : horaires en mots ou cron, `next_run`, une reprise après panne, alerte
  après 3 échecs. Rappels (`reminders`). Consolidation et compactage mémoire la nuit.
- Générations ComfyUI : lancées, suivies par numéro, jamais attendues dans un tour.

## Règles
- État en base, pas en mémoire : survit au redémarrage.
- Idempotence : une tâche relancée ne double pas un effet externe.
- Durée enregistrée (début `ts`, fin `updated_at`) : `timeline.py` la restitue.
- Redis/APScheduler seulement si un besoin mesuré l'exige (décision utilisateur, dépendance libre).

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
