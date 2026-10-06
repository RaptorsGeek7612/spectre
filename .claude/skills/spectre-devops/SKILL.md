---
name: spectre-devops
description: Maintain Spectre's hybrid repo infrastructure — Foundry part (Solidity 0.8.35 Voting contract, forge CI) kept from template-foundry alongside the Python package — GitHub Actions CI (forge job + uv/ruff/mypy/pytest job, coverage badges, changelog-driven release), README, CHANGELOG, contributing docs, .env.example, .gitignore, CLAUDE.md. Use for Spectre repo infrastructure work.
---

# Spectre — DevOps

Charge d'abord `spectre-conventions`, puis lis `docs/brainstorming.md` §4 et `docs/PDR-architecture.md` §3 et §11.

## Principe
Le dépôt vient de `RaptorsGeek7612/template-foundry`. **La partie Foundry est conservée** (Solidity 0.8.35) et le pipeline Python Spectre vit à côté. Ne supprime jamais `src/Voting.sol`, `test/`, `script/`, `lib/`, `foundry.toml`, `foundry.lock`, `remappings.txt`, `.gitmodules`.

## CI `.github/workflows/ci.yml` (branche `master`)
- `test` (Foundry) : checkout avec `submodules: recursive` → `foundry-rs/foundry-toolchain@v1` → `forge fmt --check` → `forge build --sizes` → `forge test -vvv` → `forge coverage --report lcov`.
- `python` : checkout → `astral-sh/setup-uv` (épinglé par SHA, pas de tag majeur depuis v8) → `uv sync --frozen` → `uv run ruff format --check .` → `uv run ruff check .` → `uv run mypy src` → `uv run pytest -m "not live" --cov=spectre --cov-report=lcov:lcov.info --cov-fail-under=90`.
- `coverage-badge` : badge Foundry `coverage.json` conservé (même calcul awk) + badge Python `coverage-python.json` calculé pareil, les deux publiés sur la branche orpheline `badges` en un seul commit.
- `release` : `needs: [test, python]`, logique CHANGELOG inchangée. Jamais de `ANTHROPIC_API_KEY` en CI.
- Dependabot : `github-actions` + `uv` sur `/`. Pas `gitsubmodule` (voir commentaire historique, à conserver).

## Documentation dépôt
- `README.md` : Spectre d'abord (pipeline, modèles/prix, installation, CLI, bibliothèque, config `SPECTRE_*`, dev), puis une section **« Contrat Solidity (Foundry) »** qui reprend l'essentiel de l'ancien README (workflow Voting, build/test, Anvil, Sepolia, keystore, cast) avec Solidity 0.8.35. Badges : CI, release, licence, couverture Foundry et Python.
- `CONTRIBUTING.md`, `.github/pull_request_template.md`, issue templates : checklist Python **et** Foundry.
- `examples/README.md` : exemples Spectre (CLI, bibliothèque, faux modèles) + exemples Foundry d'origine.
- `CHANGELOG.md` : Keep a Changelog ; l'entrée 0.1.0 mentionne le passage à Solidity 0.8.35.
- `.env.example` : variables Sepolia **et** Anthropic.
- `CLAUDE.md` : fiche projet, mentionne la partie Foundry.

## Vérification
- Parser les YAML (PyYAML via `uv run --with pyyaml python -c ...`).
- `git status` : aucun fichier Foundry supprimé.
- Rapport : fichiers modifiés, hypothèses, points à valider par l'humain.
