---
name: spectre-devops
description: Convert the template-foundry repo scaffolding into Spectre's Python repo — remove Solidity/Foundry files and submodules, adapt GitHub Actions CI (uv, ruff, mypy, pytest, coverage badge, changelog-driven release), README, CHANGELOG, contributing docs, .env.example, .gitignore, CLAUDE.md. Use for Spectre repo infrastructure work.
---

# Spectre — DevOps

Charge d'abord `spectre-conventions`, puis lis `docs/brainstorming.md` §4 et `docs/PDR-architecture.md` §11.

## Mission
Le dépôt vient de `RaptorsGeek7612/template-foundry` (Solidity). Garder son **ossature** (CI, release auto par CHANGELOG, badge de couverture auto-hébergé, templates GitHub), retirer tout Solidity, passer en Python.

## 1. Nettoyage
- Supprimer : `src/Voting.sol`, `test/`, `script/`, `foundry.toml`, `foundry.lock`, `remappings.txt`, `.gitmodules`.
- Submodules `lib/forge-std`, `lib/openzeppelin-contracts` : `git rm` puis supprimer `lib/` et `.git/modules/lib` s'il existe. Ne touche **pas** à `src/spectre/` (builder).
- `.gitattributes` : retirer la règle `foundry.lock`, garder la normalisation LF, ajouter `uv.lock linguist-generated=true`.

## 2. CI `.github/workflows/ci.yml`
Garder les 3 jobs et leur logique (`test`, `coverage-badge`, `release`), branche `master`.
- `test` : checkout → `astral-sh/setup-uv` (vérifier la dernière version majeure) → `uv sync --frozen` → `uv run ruff format --check .` → `uv run ruff check .` → `uv run mypy src` → `uv run pytest -m "not live" --cov=spectre --cov-report=lcov:lcov.info --cov-fail-under=90`.
- `coverage-badge` : mêmes étapes d'installation, génère `lcov.info` avec pytest, **réutilise tel quel** le calcul awk + push sur `badges`.
- `release` : inchangé. Pas de `ANTHROPIC_API_KEY` en CI.
- Dependabot : garder `github-actions`, ajouter l'écosystème `uv` (vérifier qu'il est supporté ; sinon `pip`) sur `/`.

## 3. Documentation dépôt
- `README.md` : Spectre (badges repointés vers `RaptorsGeek7612/spectre` — hypothèse de nom à signaler), pitch, schéma Scout→Scribe→Warden, tableau modèles/prix, installation (`uv sync`, `.env`), usage CLI et bibliothèque, configuration `SPECTRE_*`, développement, liens vers `docs/`. En français.
- `CHANGELOG.md` : repartir à zéro (Keep a Changelog), `## [Unreleased]` vide puis `## [0.1.0] - 2026-10-06` décrivant le MVP et la conversion depuis le template.
- `CONTRIBUTING.md`, `.github/pull_request_template.md`, issue templates : commandes Python au lieu de `forge`.
- `SECURITY.md` : clé API Anthropic, fuite de secrets, injection de prompt.
- `.env.example` : `ANTHROPIC_API_KEY=sk-ant-...` + surcharges `SPECTRE_*` commentées (noms exacts dans `docs/PDR-architecture.md` §4).
- `.gitignore` : `.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `lcov.info`, `htmlcov/`, `dist/` ; garder `.env` ignoré et `!.env.example`.
- `examples/README.md` : exemples Spectre (CLI, bibliothèque, faux modèles).
- `CLAUDE.md` à la racine : courte fiche projet pointant vers `docs/` et les skills `.claude/skills/spectre-*`.

## Vérification
- `git status` : plus aucun `.sol`, ni `foundry*`, ni `lib/`.
- Valider le YAML (parser Python si disponible, sinon relecture attentive).
- Rapport : fichiers supprimés/modifiés, hypothèses, points à valider par l'humain.
