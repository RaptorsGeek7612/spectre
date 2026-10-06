# Contribuer à Spectre

Le dépôt est hybride : le package Python **Spectre** (`src/spectre/`, `tests/`) et le contrat
Solidity **Voting** (Foundry : `src/Voting.sol`, `test/`, `script/`, `lib/`, Solidity 0.8.35).

1. Forkez le dépôt et créez une branche depuis `master`.
2. Installez l'environnement :
   ```shell
   git submodule update --init --recursive   # dépendances Foundry (ou `forge install` si lib/ est vide)
   uv sync                                   # environnement Python (https://docs.astral.sh/uv/)
   ```
3. Faites vos modifications, puis lancez la vérification de la partie touchée avant d'ouvrir une PR.

   Python (Spectre) :
   ```shell
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy src
   uv run pytest -m "not live" --cov=spectre --cov-report=term-missing
   ```

   Solidity (Foundry) :
   ```shell
   forge fmt --check
   forge build
   forge test
   ```
4. Ouvrez une pull request décrivant le changement (le modèle de PR vous guide). La CI
   (GitHub Actions) doit passer : le job `test` rejoue les étapes Foundry, le job `python` les
   étapes Python et exige une couverture ≥ 90 %.

## Règles du projet

- Ne supprimez pas la partie Foundry : elle fait partie du dépôt.
- Les tests Python par défaut ne font **aucun appel réseau** : utilisez les faux modèles
  LangChain via `build_graph(models=...)`. Un test qui appelle réellement l'API doit être marqué
  `@pytest.mark.live`.
- Les IDs de modèles (`claude-haiku-4-5`, `claude-sonnet-5-5`, `claude-opus-5-5`) ne sont
  définis que dans `src/spectre/config.py`.
- N'envoyez jamais `temperature`, `top_p` ou `top_k` à Sonnet 5.5 / Opus 5.5 (rejeté par
  l'API) : réglez l'effort. Haiku 4.5 n'accepte pas l'effort.
- Ne commitez jamais de clé API, de clé privée de wallet ni de fichier `.env`.
- Mettez à jour `CHANGELOG.md` (section `[Unreleased]`). Ajouter une section de version
  (`## [x.y.z] - AAAA-MM-JJ`) sur `master` déclenche automatiquement le tag et la release.
- Messages destinés à l'utilisateur (CLI, erreurs) en français ; docstrings en anglais.
