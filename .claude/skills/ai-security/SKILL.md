---
name: ai-security
description: "Sécurité propre à l'IA dans Spectre : injection de prompt, exfiltration via outils, empoisonnement de mémoire, fuite de secrets dans les prompts, abus des agents. Utiliser pour tout prompt, outil ou source de contenu nouvelle."
---

# AI Security — Spectre

## Menaces suivies (OWASP Top 10 LLM)
- Injection directe/indirecte (pages web, PDF, vidéos, e-mails, sorties d'outils) → voir
  `prompt-injection-defense`.
- Gestion de sortie non sûre : une sortie de modèle n'est jamais exécutée telle quelle.
- Agence excessive : outils minimaux par agent, validation humaine au-delà du niveau auto.
- Fuite d'informations : pas de secret dans les prompts, journaux ou comptes rendus.
- Empoisonnement de mémoire : un fait n'est mémorisé que s'il vient de l'utilisateur ou d'une
  source vérifiée ; la consolidation ne réécrit pas les règles verrouillées.
- Consommation non bornée : budgets d'actions et de coûts.

## Contrôles
Test d'adversaire pour chaque nouvel outil (« et si le contenu lu ordonnait X ? ») ; le portail
doit refuser ou demander, quel que soit le texte lu.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
