---
name: distributed-systems
description: "Communication entre les process et services de Spectre (service, serveur MCP stdio, CLI d'agents, ComfyUI, Ollama/LM Studio, n8n, téléphone via Tailscale) : délais, reprises, idempotence, cohérence. Utiliser quand un flux traverse plusieurs process."
---

# Distributed Systems — Spectre

## Topologie
Service Python (port 8765) ↔ process MCP lancé par `claude -p` (stdio) ↔ même `spectre.db`.
Services locaux : ComfyUI 8188, LM Studio, Ollama, n8n 5678, Paperless 8010, lanceur 8764.
Distants : API des fournisseurs LLM, serveurs MCP HTTP, Telegram.

## Règles
- Chaque appel réseau a un délai (`timeout`) et un nombre de reprises bornés ; reprise
  seulement si l'opération est idempotente.
- Effets externes (paiement, envoi, publication) : jamais rejoués automatiquement.
- Missions et routines : état en base, reprise après redémarrage (`recover()`, une seule reprise
  après panne pour les routines).
- Dégradation : un service local absent → message clair, repli (`fallback_models`), pas de blocage.
- Horloges : tout en UTC, la machine est la seule source de l'heure.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
