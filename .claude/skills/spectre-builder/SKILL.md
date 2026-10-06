---
name: spectre-builder
description: Implement the Spectre Python package (src/spectre — config, llm factory, prompts, state, costs, nodes, LangGraph graph, CLI) and pyproject.toml per docs/PDR-architecture.md. Use when building or changing Spectre's runtime code.
---

# Spectre — Builder

Charge d'abord la skill `spectre-conventions`, puis lis `docs/PDR-architecture.md` en entier.

## Mission
Livrer `src/spectre/` (sections 3 à 9 du PDR architecture) et `pyproject.toml`.

## Étapes
1. **Vérifier les API** avec Context7 avant d'écrire :
   - LangGraph : `StateGraph(State)`, `START`, `END`, reducer `Annotated[list, operator.add]`, type de retour de `compile()`.
   - LangChain : `ChatAnthropic` (params `model`, `max_tokens`, `temperature`, `reasoning_effort`, `max_retries`, `timeout`), `AIMessage.usage_metadata`, `response_metadata["stop_reason"]`, `AIMessage.text`.
2. **`pyproject.toml`** : build backend `hatchling`, layout `src/`, `requires-python = ">=3.11"`, deps `langchain-core>=1.5.2`, `langchain-anthropic>=1.5.3`, `langgraph>=1.0`, `python-dotenv>=1.0` ; groupe dev (`[dependency-groups] dev`) `pytest`, `pytest-cov`, `ruff`, `mypy` ; script `spectre = "spectre.cli:main"` ; config ruff (line-length 100, règles E,F,I,UP,B,SIM), mypy strict, pytest (`markers = ["live: real Anthropic API calls"]`, `addopts = "-m 'not live'"`, `testpaths = ["tests"]`). Puis `uv lock` et `uv sync`.
3. **Ordre d'implémentation** : `errors.py` → `config.py` → `costs.py` → `state.py` → `prompts.py` → `llm.py` → `nodes.py` → `graph.py` → `__init__.py` → `cli.py`.
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
- Pas de boucle de révision (v0.2).
- Pas de suite de tests dans `tests/` (c'est le tester).
- Pas d'appel réel à l'API Anthropic.
