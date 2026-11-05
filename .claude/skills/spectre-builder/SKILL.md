---
name: spectre-builder
description: "Implement Spectre's Python code — the Claude pipeline (src/spectre: config, llm, prompts, state, costs, nodes, LangGraph graph, CLI) and the personal assistant (src/spectre/assistant, src/spectre/web) — per CLAUDE.md and docs/PDR-architecture.md. Use when building or changing Spectre's runtime code."
---

# Spectre — Builder

Charge d'abord la skill `spectre-conventions`, puis lis `docs/PDR-architecture.md` en entier.

## Mission
Faire évoluer `src/spectre/` (pipeline : sections 3 à 9 du PDR architecture ; assistant :
carte des modules de `CLAUDE.md`) et `pyproject.toml`. Pour l'assistant, charger aussi la skill
de domaine du sujet (`python-backend`, `temporal-awareness`, `agent-governance`…).

## Étapes
1. **Vérifier les API** avec Context7 avant d'écrire :
   - LangGraph : `StateGraph(State)`, `START`, `END`, reducer `Annotated[list, operator.add]`, type de retour de `compile()`.
   - LangChain : `ChatAnthropic` (params `model`, `max_tokens`, `temperature`, `reasoning_effort`, `max_retries`, `timeout`), `AIMessage.usage_metadata`, `response_metadata["stop_reason"]`, `AIMessage.text`.
2. **`pyproject.toml`** : build backend `hatchling`, layout `src/`, `requires-python = ">=3.11"`, dépendances avec bornes (voir le fichier actuel) ; groupe dev (`[dependency-groups] dev`) `pytest`, `pytest-cov`, `ruff`, `mypy` ; script `spectre = "spectre.cli:main"` ; config ruff (line-length 100, règles E,F,I,UP,B,SIM), mypy strict, pytest (`markers = ["live: real Anthropic API calls"]`, `addopts = "-m 'not live'"`, `testpaths = ["tests"]`). Puis `uv lock` et `uv sync --extra voice --extra vision` (jamais `uv sync` nu).
3. **Ordre d'implémentation (pipeline)** : `errors.py` → `config.py` → `costs.py` → `state.py` → `prompts.py` → `llm.py` → `nodes.py` → `graph.py` → `__init__.py` → `cli.py`.
4. **Points d'attention**
   - `llm.py` : n'ajoute `temperature` / `reasoning_effort` au constructeur que s'ils ne sont pas `None`. Aucun client créé à l'import.
   - `load_dotenv()` appelé dans `build_graph`/`main`, pas à l'import du package.
   - Texte de réponse : ignorer les blocs `thinking` (Sonnet/Opus 5.5 en renvoient, souvent vides).
   - `usage_metadata` peut être `None` (faux modèles) → tokens à 0.
   - Coût = `input_tokens * prix_in / 1e6 + output_tokens * prix_out / 1e6`, arrondi à 6 décimales ; modèle absent de `PRICING` → `None` + `warnings.warn`.
   - CLI : `sys.stdout.reconfigure(encoding="utf-8")` si possible ; codes de sortie 0/1/2 ; clé absente détectée **avant** tout appel.
   - Prompts : en français, clairs, sans sur-instruction. Warden renvoie **uniquement** le texte final corrigé.
5. **Smoke test sans réseau** : un script jetable (hors du repo) qui appelle `run()` avec trois faux modèles et affiche le résultat.
6. Lance `ruff format`, `ruff check`, `mypy src`. Corrige jusqu'au vert.

## Ne pas faire
- Pas d'action de l'assistant hors du portail (`tools.execute`).
- Les tests de fond sont au tester ; un test minimal du contrat accompagne quand même chaque
  nouveau code.
- Pas d'appel réel à l'API Anthropic ni à un service tiers.
