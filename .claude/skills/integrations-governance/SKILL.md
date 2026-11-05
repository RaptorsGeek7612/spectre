---
name: integrations-governance
description: "Gouverne les intégrations externes de Spectre (MCP, webhooks, Telegram, API SaaS, CLI d'agents, extensions) : inventaire, permissions, secrets, revue, retrait. Utiliser avant d'ajouter ou d'élargir une intégration."
---

# Integrations Governance — Spectre

## Registre
Chaque intégration a : propriétaire (agent), niveau, outils auto, secret (`${NOM}`), date
d'ajout, raison, source et licence, procédure de retrait. Inventaire = fiches `serveurs-mcp/`,
`outils-agents/`, webhooks (`webhooks.py`, signature obligatoire), `saas.py` (lecture seule).

## Processus
1. Besoin exprimé par l'utilisateur → fiche préparée par Spectre → validation (ASK).
2. Lecture d'abord ; écriture accordée outil par outil, après usage observé.
3. Revue mensuelle : outils inutilisés retirés, jetons expirants renouvelés.
4. Incident : couper la fiche (désactiver), révoquer le jeton, consigner.

## Interdits
Intégration propriétaire quand une libre suffit ; secret dans une fiche ; webhook non signé.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
