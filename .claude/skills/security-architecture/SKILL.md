---
name: security-architecture
description: "Architecture de sécurité de Spectre : moindre privilège (OWASP), niveaux du portail, catégories ASK, frontières de confiance, menaces. Utiliser pour tout composant qui exécute, écrit, envoie ou touche un secret."
---

# Security Architecture — Spectre

## Les 10 principes du cahier, et où ils vivent
1. Aucun agent n'a tous les droits : `Tool.agents`, `Tool.lead_only`, kits par métier.
2. Opérations sensibles validées : `governance.py` (niveau > `auto_max_level` → approbation).
3. Clés hors code : `~/.spectre/assistant/.env`, `${NOM}` dans les fiches MCP.
4. Données personnelles protégées : tout reste sur le PC ; confidences verrouillées en mémoire.
5. Connexions authentifiées : `web/auth.py`, Tailscale, jeton de l'extension Chrome.
6. Actions journalisées : table `audit`, `events`.
7. Fichiers téléchargés non fiables : pièces jointes lues comme données, jamais exécutées.
8. Outils externes encadrés : `mcp_clients.py` (niveau + liste `auto`), `agent_tools.py` (pas de shell).
9. Pas d'auto-modification des permissions : catégorie CRITICAL, jamais modifier son propre code.
10. Destructif bloqué sans oui : niveau DESTRUCTIVE + corbeille/annulation (`undo`).

## Méthode
Modèle de menace (STRIDE) par nouveau flux, frontière de confiance dessinée, contrôle placé du
côté serveur, test qui prouve le refus.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
