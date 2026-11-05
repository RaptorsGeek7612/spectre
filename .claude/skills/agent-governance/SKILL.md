---
name: agent-governance
description: "Gouvernance des agents de Spectre : niveaux READ→CRITICAL, catégories ASK (paiement, inscription, installation, MCP), autonomie méritée (`trust.py`), budgets, audit. Utiliser pour toute question de permission d'un agent."
---

# Agent Governance — Spectre

## Existant
`governance.py` (`Level` READ, UI, WRITE, DESTRUCTIVE, EXTERNAL, CRITICAL ; `auto_max_level` = 2),
`trust.py` (dossier de fiabilité), budget 60 actions/min et 3000/jour, `approvals` + `audit`.

## Règles intangibles
- Paiements et inscriptions : toujours le oui explicite de l'utilisateur, sous-agents compris
  (`payment` = ASK, jamais automatique même pour un agent expert).
- Un agent ne modifie jamais ses propres permissions ni le code de Spectre.
- Destructif : corbeille/annulation, sinon validation.
- Toute nouvelle catégorie d'outil part en ASK ; on assouplit ensuite, sur preuve.

## Tests
Pour chaque outil sensible : un test qui prouve qu'il attend la validation.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
