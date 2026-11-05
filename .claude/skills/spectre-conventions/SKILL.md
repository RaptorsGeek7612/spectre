---
name: spectre-conventions
description: "Règles communes à tout agent qui travaille sur le dépôt Spectre (pipeline Claude Scout → Scribe → Warden et assistant personnel multi-agents dans src/spectre/assistant). À charger avant de toucher un fichier du projet : sources de vérité, règles des modèles, portail, commandes Windows, périmètres, définition du fini."
---

# Spectre — conventions communes

Spectre a deux parties : le **pipeline** Scout (Haiku 4.5) → Scribe (Sonnet 5.5) → Warden
(Opus 5.5) orchestré par LangGraph (`src/spectre/*.py`), et l'**assistant personnel**
multimodal et multi-agents (`src/spectre/assistant/`, interface `src/spectre/web/`).

## Sources de vérité (lire avant de coder)
- `CLAUDE.md` (carte des modules, règles essentielles).
- `docs/cahier-des-charges.md` (pipeline, F1–F10 / NF1–NF9) et
  `docs/conformite-ia-personnelle.md` (cahier « IA personnelle » : exigences, état, écarts).
- `docs/PDR-architecture.md`, `docs/PDR-produit.md`, `CHANGELOG.md`.
- Skills de domaine (`software-architect`, `temporal-awareness`, `agent-governance`,
  `prompt-injection-defense`…) selon le sujet ; règles `.claude/rules/`.

## Dépôt hybride
La partie **Foundry** du template (`src/Voting.sol`, `test/`, `script/`, `lib/`,
`foundry.toml`, `foundry.lock`, `remappings.txt`, `.gitmodules`, Solidity 0.8.35) ne se
supprime **jamais** ; la CI la vérifie (job `test`).

## Règles non négociables
1. Le produit s'appelle **Spectre**.
2. IDs de modèles exacts (`claude-haiku-4-5`, `claude-sonnet-5-5`, `claude-opus-5-5`)
   **uniquement** dans `src/spectre/config.py` ; ailleurs, alias `haiku`/`sonnet`/`opus`.
3. Jamais `temperature`/`top_p`/`top_k` vers Sonnet 5.5 ou Opus 5.5 : on règle l'effort.
   Haiku 4.5 : `temperature` OK, pas d'effort. `max_tokens`, pas de prefill, pas de `budget_tokens`.
4. **Portail** : toute action de l'assistant passe par `tools.execute` (gouvernance + audit).
5. Aucun appel réseau dans les tests par défaut (`@pytest.mark.live` pour les vrais).
6. Jamais lire, afficher ni committer une clé ; `.env` est ignoré par git.
7. Dates : stockage UTC (`db.now_iso`), affichage dans le fuseau IANA (`timeline.py`) ; le
   modèle ne devine jamais la date.
8. Chaque agent de Spectre garde son LLM par défaut ; paiements et inscriptions = oui explicite
   de l'utilisateur ; les noms d'agents sont donnés par l'utilisateur.
9. Doc d'une librairie : Context7, pas la mémoire. Tout en open source.

## Commandes (Windows : `uv run --no-sync`, pas d'activation de venv)
```
uv run --no-sync ruff format . ; uv run --no-sync ruff check .
.venv/Scripts/python.exe -m mypy --no-native-parser src
uv run --no-sync pytest -m "not live" --cov=spectre --cov-report=term-missing
```
**Jamais `uv sync` nu** (il retire les extras voix/vision) : `uv sync --extra voice --extra
vision`, ou `uv sync --frozen --all-extras --inexact`. Scripts de patch : `write_bytes(s.encode())`
(pas de CRLF, pas de `\n` cassé par un heredoc).

## Style de code
Python ≥ 3.11, annotations partout, `mypy --strict` ; ruff (ligne 100, guillemets doubles) ;
docstrings courtes en anglais, messages utilisateur en français. Nouvelle dépendance : bornes
dans `pyproject.toml`, licence libre vérifiée, justifiée dans le rapport.

## Périmètres (éviter les modifications concurrentes)
| Rôle (sous-agent) | Possède |
|---|---|
| architecte-en-chef | `docs/**`, `CLAUDE.md`, `.claude/**` ; arbitre les autres |
| dev-backend | `src/spectre/assistant/**` hors voix/vision/mémoire/missions, `src/spectre/web/*.py`, pipeline `src/spectre/*.py` |
| dev-frontend | `src/spectre/web/static/**`, `tools/chrome-extension/**` |
| expert-voice-ai | `src/spectre/assistant/voice/**`, `vision/**`, `meeting.py`, `videos.py` |
| expert-llm | `providers.py`, `engines.py`, `llm.py`, `codex.py`, `mistral.py`, `cli_agents.py`, `local_models.py` |
| expert-memoire | `memory.py`, `timeline.py`, `learning.py`, `lessons.py`, `db.py` |
| expert-multi-agents | `missions.py`, `company.py`, `routines.py`, `team.py`, `board.py`, `mcp_clients.py`, `mcp_server.py` |
| expert-cybersecurite | lecture seule + `governance.py`, `trust.py`, `web/auth.py` sur demande |
| expert-devops | `.github/**`, `pyproject.toml`, `uv.lock`, `tools/*.ps1|*.cmd`, `README.md`, `CHANGELOG.md` |
| agent-qa | `tests/**` (bug trivial ≤ 3 lignes dans `src/` permis, signalé) |

## Définition du fini
- `ruff format --check`, `ruff check`, `mypy src`, `pytest -m "not live"` passent.
- Pas de commit ni de push : la session principale s'en charge ; c'est l'utilisateur qui fusionne.
- Rapport : fichiers touchés, commandes et résultats réels, écarts, points ouverts.
