---
name: spectre-conventions
description: Shared ground rules for every agent working on the Spectre repo (multi-agent Claude pipeline in Python with langchain-anthropic + LangGraph). Load before touching any file in this project — stack, layout, model rules, commands, definition of done.
---

# Spectre — conventions communes

Spectre est un orchestrateur multi-agents **100 % Claude** : Scout (Haiku 4.5) → Scribe (Sonnet 5.5) → Warden (Opus 5.5), orchestré par LangGraph via `langchain-anthropic`.

## Sources de vérité (lire avant de coder)
- `docs/cahier-des-charges.md` — exigences F1–F10, NF1–NF9, critères d'acceptation.
- `docs/PDR-architecture.md` — arborescence, signatures, état, erreurs, tests, CI. **Le respecter** ; tout écart doit être justifié dans ton rapport.
- `docs/PDR-produit.md` — périmètre par version (boucle de révision Warden → Scribe depuis la v0.4, `SPECTRE_MAX_REVISIONS`).

## Dépôt hybride
Le dépôt garde la partie **Foundry** du template d'origine (contrat `src/Voting.sol`, `test/Voting.t.sol`, `script/Voting.s.sol`, submodules `lib/`, `foundry.toml`) en **Solidity 0.8.35** (`solc_version = "0.8.35"`, `pragma solidity ^0.8.35;`). **Ne jamais supprimer ces fichiers.** Commandes : `forge fmt --check`, `forge build`, `forge test` (forge n'est pas installé localement ; la CI les exécute).

## Règles non négociables
1. Le produit s'appelle **Spectre**. Jamais « claude agent » dans le code, la CLI ou les docs.
2. IDs de modèles exacts, sans suffixe de date : `claude-haiku-4-5`, `claude-sonnet-5-5`, `claude-opus-5-5`. Ils n'apparaissent **que** dans `src/spectre/config.py` (les tests et docs peuvent les citer).
3. **Jamais de `temperature`/`top_p`/`top_k` vers Sonnet 5.5 ou Opus 5.5** (HTTP 400). On règle `reasoning_effort`. Haiku 4.5 : `temperature` OK, **pas** d'effort.
4. `max_tokens` (pas `max_output_tokens`). Pas de prefill assistant. Pas de `budget_tokens`.
5. Aucun appel réseau dans les tests par défaut. Les vrais appels sont marqués `@pytest.mark.live`.
6. Ne jamais lire, afficher ou committer une vraie clé API. `.env` est ignoré par git.
7. Doc de librairie : interroger Context7 (`mcp__context7__resolve-library-id` puis `mcp__context7__query-docs`) plutôt que se fier à sa mémoire pour LangChain/LangGraph.

## Stack et commandes (Windows : utiliser `uv run`, pas d'activation de venv)
```
uv sync                                   # installe tout (dev inclus)
uv run ruff format .                      # formate
uv run ruff format --check . ; uv run ruff check .
uv run mypy src
uv run pytest -m "not live" --cov=spectre --cov-report=term-missing
uv run spectre "demande" --costs          # nécessite ANTHROPIC_API_KEY
```

## Style de code
- Python ≥ 3.11, annotations partout, `mypy --strict` sur `src/`.
- Ruff, longueur de ligne 100, guillemets doubles (cohérent avec l'ancien `forge fmt` du template).
- Docstrings courtes en anglais ; messages utilisateur (CLI, erreurs) en français.
- Pas de dépendance hors `langchain-core`, `langchain-anthropic`, `langgraph`, `python-dotenv` sans le justifier.

## Propriété des fichiers (éviter les conflits entre agents)
| Agent | Possède |
|---|---|
| builder | `src/spectre/**`, `pyproject.toml`, `uv.lock` |
| tester | `tests/**` (peut corriger un bug trivial ≤ 3 lignes dans `src/` en le signalant ; sinon le rapporter) |
| devops | `.github/**`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CLAUDE.md`, `.gitignore`, `.gitattributes`, `.env.example`, `examples/`, suppression des fichiers Solidity/Foundry |
| reviewer | lecture seule ; produit un rapport |

## Definition of done
- `ruff format --check`, `ruff check`, `mypy src`, `pytest -m "not live"` passent (pour ce qui relève de ton périmètre).
- Pas de commit, pas de push : la session principale s'en charge.
- Rapport final : fichiers touchés, commandes lancées avec leur résultat réel, écarts au PDR, points ouverts.
