---
name: mcp-server-development
description: "Développe les serveurs MCP de Spectre : le serveur d'outils `mcp_server.py` (FastMCP, stdio) qui expose le portail aux moteurs, et tout nouveau serveur MCP. Utiliser pour ajouter ou modifier un outil exposé en MCP."
---

# MCP Server Development — Spectre

## Existant
`mcp_server.py` : `build_server(call, agent)` enveloppe chaque `Tool` de `tools.py`
(`tool_wrapper`) ; l'appel passe par `tools.execute` (gouvernance + audit). Lancé par Claude
Code en stdio ; aussi branché dans VS Code (`vscode.py`).

## Ajouter un outil
1. Le définir dans `tools.py` : nom, description claire (quand l'utiliser), paramètres typés,
   niveau, catégorie, `agents`/`lead_only`.
2. L'implémenter dans `actions.py` (ou le module métier), erreurs en `ActionError`.
3. Tester : appel autorisé, appel refusé pour un agent non listé, validation demandée au-delà
   du niveau auto.
4. Context7 sur le SDK MCP Python si l'API change.

## Règles
Pas d'outil générique « exécute ce shell » ; sorties bornées en taille ; aucun secret renvoyé.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
