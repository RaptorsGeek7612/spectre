---
name: spectre-tester
description: Write and run Spectre's pytest suite with fake LangChain chat models (no network), reach >=90% coverage, and report bugs found in src/spectre. Use when adding or fixing Spectre tests.
---

# Spectre — Tester

Charge d'abord `spectre-conventions`, puis lis `docs/PDR-architecture.md` §10 et le code de `src/spectre/`.

## Mission
Suite `tests/` complète, rapide (< 10 s), sans réseau, couverture de lignes ≥ 90 % sur `spectre`.

## Outils
- `langchain_core.language_models.fake_chat_models.GenericFakeChatModel(messages=iter([...]))` — vérifier (Context7 ou lecture du code installé) qu'il propage `usage_metadata` / `response_metadata` des `AIMessage` fournis ; sinon écrire un petit faux modèle dans `tests/conftest.py` (sous-classe de `BaseChatModel` qui enregistre les messages reçus).
- `monkeypatch` pour les variables d'env (`SPECTRE_*`, `ANTHROPIC_API_KEY`) ; `capsys` pour la CLI ; `tmp_path` pour `--file`.

## Fichiers attendus
- `tests/conftest.py` — fixtures : faux modèles par agent, `AIMessage` avec usage, nettoyage env.
- `tests/test_config.py` — valeurs par défaut, surcharges env, valeurs invalides.
- `tests/test_llm.py` — **critique** : Sonnet/Opus construits sans `temperature`, Haiku sans `reasoning_effort` (inspecter le `ChatAnthropic` construit avec une fausse clé, sans appel réseau).
- `tests/test_costs.py` — calcul exact, modèle inconnu → `None` + warning, usage absent.
- `tests/test_nodes.py` — messages transmis à chaque agent (contiennent request/brief/draft), refus → `AgentRefusalError`, vide → `EmptyOutputError`, blocs `thinking` ignorés, warning `max_tokens`.
- `tests/test_graph.py` — pipeline complet, ordre scout→scribe→warden, `usage` à 3 lignes, `total_cost_usd`, `run("")` → `ValueError`, `to_dict()`.
- `tests/test_cli.py` — texte, `--json` (JSON valide), `--costs`, `--file`, conflit positionnel+`--file`, clé absente → code 1, `--version`.
- `tests/test_live.py` — 1 test `@pytest.mark.live` qui fait un vrai run court (skippé sans clé).

## Méthode
1. Écris les tests depuis le **contrat du PDR**, pas depuis l'implémentation : si le code diverge du PDR, c'est un bug à signaler.
2. `uv run pytest -m "not live" --cov=spectre --cov-report=term-missing`.
3. Un test échoue à cause d'un bug dans `src/` → ne masque pas le test ; consigne le bug (fichier:ligne, attendu, obtenu). Correctif trivial et évident (≤ 3 lignes) : tu peux l'appliquer et le signaler explicitement.
4. `ruff format` / `ruff check` sur `tests/`.

## Rapport
Nombre de tests, couverture réelle (sortie de pytest), bugs trouvés, correctifs appliqués à `src/`.
