---
name: observability
description: "Met en place les journaux, métriques, traces et alertes de Spectre (events, audit, spend, activité, état des services, notifications). Utiliser pour comprendre l'état et le comportement du système ou ajouter une alerte."
---

# Observability — Spectre

## Sources
`events` (journal immuable), `audit` (chaque action du portail), `spend` (jetons, coût, durée),
`activity.py` (ce que font les agents, 30 jours), `/api/status`, lanceur/watchdog (port 8764),
notifications (`webpush.py`, Telegram), alertes SaaS (`saas.py`, retour à la normale).

## Règles
- Un événement = type, source, horodatage UTC, données JSON sans secret.
- Métriques utiles : durée d'un tour, taux d'échec par moteur, missions échouées, budget
  d'actions consommé, taille de la base.
- Alerte = seuil + délai de récupération (cooldown) + message actionnable ; pas d'alerte bavarde.
- Tableau de bord local seulement ; aucune télémétrie vers un tiers.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
