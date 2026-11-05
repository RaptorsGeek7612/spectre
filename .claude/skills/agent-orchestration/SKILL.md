---
name: agent-orchestration
description: "Orchestration multi-agents de Spectre : Spectre seul point d'entrée, découpage d'objectif, missions en parallèle, vérification Kaïto, aide à un agent bloqué, réunions, tableau de tâches. Utiliser pour toute coordination d'agents."
---

# Agent Orchestration — Spectre

## Contrôle central (Partie 10 du cahier)
Spectre décide : quel modèle, quel agent, quels outils, quoi mémoriser, quand demander
l'autorisation, quand reprendre une mission. Les agents ne s'appellent pas en direct sans lui
(`ask_agent` passe par le portail).

## Mécanismes
`missions.py` (plan → étapes → exécutant → vérificateur → rapport ; `mission_parallel` 1–4 ;
`steer_mission`, `stop_mission` ; `HELPER` pour un agent bloqué ; `rollback_mission`),
`company.py` (tableau par entreprise, dépendances, « à valider », pilote automatique),
`meeting.py`, `board.py`.

## Règles
- Périmètres disjoints entre agents parallèles (pas deux agents sur le même fichier).
- Chaque étape a un livrable vérifiable ; échec = leçon (`lessons.py`).
- État persistant : reprise exacte après redémarrage.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
