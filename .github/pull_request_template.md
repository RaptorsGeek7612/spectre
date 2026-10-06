## Résumé

<!-- Que change cette PR, et pourquoi ? -->

## Checklist

Python (Spectre) — si `src/spectre/`, `tests/` ou `pyproject.toml` changent :

- [ ] `uv run ruff format --check .` passe en local
- [ ] `uv run ruff check .` passe en local
- [ ] `uv run mypy src` passe en local
- [ ] `uv run pytest -m "not live" --cov=spectre` passe en local (tests ajoutés/mis à jour, couverture ≥ 90 %)
- [ ] Aucun appel réseau dans les tests par défaut (les vrais appels sont marqués `@pytest.mark.live`)
- [ ] Aucun ID de modèle codé en dur hors de `src/spectre/config.py`

Solidity (Foundry) — si `src/Voting.sol`, `test/`, `script/` ou `foundry.toml` changent :

- [ ] `forge fmt --check` passe en local
- [ ] `forge build` passe en local
- [ ] `forge test` passe en local (tests ajoutés/mis à jour, fuzz tests si pertinent)

Général :

- [ ] Aucune clé API, clé privée ni contenu de `.env` dans le diff
- [ ] README / docs / `CHANGELOG.md` mis à jour si le comportement ou l'usage change
