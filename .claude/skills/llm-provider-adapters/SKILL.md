---
name: llm-provider-adapters
description: "Adaptateurs de fournisseurs LLM de Spectre : CLI Claude Code, Codex, Vibe, Cursor, Antigravity, API compatibles OpenAI (`fournisseur:modèle`). Utiliser pour brancher ou corriger un fournisseur."
---

# LLM Provider Adapters — Spectre

## Existant
`providers.py` (fournisseurs intégrés + `providers.json`), `engines.py` (`resolve`, `Engines.ask`,
secours), `llm.py` (`HttpAgent` OpenAI-compatible, `tool_schemas`, `gate_caller` = outils via le
portail), `codex.py`, `mistral.py`, `cli_agents.py`.

## Règles
- Claude : alias `opus`/`sonnet`/`haiku`, jamais d'ID hors `config.py` ; effort réglé par
  `model_effort` ; jamais `temperature`/`top_p`/`top_k` vers Sonnet/Opus 5.5.
- Clé lue dans l'env ou `~/.spectre/assistant/.env`, jamais écrite en config ni journalisée.
- Erreurs normalisées (quota 402/429, délai, refus) → `failed(reply)` pour déclencher le secours.
- Chaque adaptateur : délai, taille de sortie bornée, coût enregistré (`spend.record`).
- Test avec un faux transport, aucun appel réseau.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
