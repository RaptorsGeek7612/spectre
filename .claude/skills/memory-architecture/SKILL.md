---
name: memory-architecture
description: "Architecture des trois mémoires de Spectre : immédiate (session), long terme (faits, persona, conversations), opérationnelle (missions, tâches, routines, audit). Utiliser pour toute évolution de la mémoire."
---

# Memory Architecture — Spectre

## Les trois niveaux du cahier
| Niveau | Où |
|---|---|
| Immédiate | session du cerveau (`brain_session`, une par jour), fil récent pour les autres moteurs (12 échanges) |
| Long terme | `facts` (+ FTS5), persona (`spectre-memoire`), `events` (conversations), leçons, compétences apprises |
| Opérationnelle | `missions`, `tasks`/`task_events`, `routines`, `reminders`, `approvals`, `audit` |

## Règles
- Le prompt reçoit au plus 150 faits / 45 000 car., les plus fiables d'abord ; le reste par recherche.
- Compactage de nuit : sauvegarde d'abord, fusions vérifiées, rien d'effacé, règles et
  confidences verrouillées, `restore` possible.
- Un fait a une source (`source_event`), une confiance, un statut ; un fait contredit est
  remplacé (`superseded_by`), pas écrasé.
- Préférence conservée seulement si l'utilisateur la veut conservée.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
