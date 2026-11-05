---
name: ci-cd-devops
description: "Automatise l'intégration continue, les vérifications, la construction et la publication de Spectre (GitHub Actions : job Foundry `test`, job `python`, badges, release par CHANGELOG, Dependabot). Utiliser pour la CI, les versions et les PR."
---

# CI/CD DevOps — Spectre

## Flux de version
- Travail sur `feature/labs-skills` ; `master` protégé (checks `test` + `python`, PR obligatoire).
- Version : `CHANGELOG.md` + `pyproject.toml` + `__init__.py` + `uv.lock` ; PR vers master ;
  **c'est toujours l'utilisateur qui fusionne** (`! gh pr merge N --repo RaptorsGeek7612/spectre
  --merge --auto`). Push sur master = release CI.
- Actions épinglées par SHA ; Dependabot regroupé en une PR testée si l'utilisateur le demande.

## Règles
- Jamais de clé en CI ; jamais `--no-verify`.
- Partie Foundry intouchable (`forge fmt --check`, `forge build`, `forge test`).
- YAML vérifié (`uv run --with pyyaml python -c "import yaml,sys;yaml.safe_load(open(sys.argv[1]))" fichier`).

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
