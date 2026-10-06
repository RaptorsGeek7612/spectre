# Spectre — Cahier des charges

> Version 0.1 · 2026-10-06 · Propriétaire : RaptorsGeek7612

## 1. Contexte et objectif

Construire **Spectre**, un orchestrateur multi-agents en Python dont **tous les
agents sont des modèles Claude** appelés via `langchain-anthropic`, orchestrés
par **LangGraph**. Spectre transforme une demande en texte final validé, en
répartissant le travail entre un modèle rapide, un modèle rédacteur et un modèle
vérificateur.

Le projet est bâti sur l'ossature du dépôt `template-foundry` (CI, releases,
documentation de dépôt), dont la partie Solidity est retirée.

## 2. Périmètre

### Dans le périmètre (v0.1)
- Package Python `spectre` installable (`uv` / `pip`).
- Trois agents : Scout (Haiku 4.5), Scribe (Sonnet 5.5), Warden (Opus 5.5).
- Graphe LangGraph linéaire avec état typé.
- Suivi des tokens et du coût en dollars par agent et au total.
- Interface en ligne de commande.
- Tests automatisés sans appel réseau, CI GitHub Actions.

### Hors périmètre (v0.1)
- Boucle de révision (prévue v0.2).
- Interface web, API HTTP, base de données.
- Tout fournisseur de modèles autre qu'Anthropic.

## 3. Exigences fonctionnelles

| ID | Exigence | Priorité |
|---|---|---|
| F1 | L'utilisateur fournit une demande en texte libre ; Spectre renvoie un texte final validé. | Must |
| F2 | **Scout** (Haiku 4.5) produit un brief : intention, public, contraintes, plan en points. | Must |
| F3 | **Scribe** (Sonnet 5.5) rédige le texte complet à partir de la demande d'origine et du brief. | Must |
| F4 | **Warden** (Opus 5.5) vérifie exactitude, cohérence et style, puis renvoie la version corrigée. | Must |
| F5 | Chaque agent enregistre : modèle, tokens d'entrée, tokens de sortie, coût $. | Must |
| F6 | Le résultat expose `brief`, `draft`, `final_text`, `usage` (par agent) et `total_cost_usd`. | Must |
| F7 | CLI : `spectre "demande"` affiche le texte final ; `--costs` ajoute le tableau des coûts ; `--json` sort tout l'état en JSON ; `--file chemin` lit la demande depuis un fichier. | Must |
| F8 | Les modèles et `max_tokens` de chaque agent sont surchargeables par variables d'environnement. | Should |
| F9 | Un refus du modèle (`stop_reason == "refusal"`) ou une sortie vide produit une erreur explicite nommant l'agent. | Should |
| F10 | Utilisable comme bibliothèque : `from spectre import run` / `build_graph`. | Must |

## 4. Exigences non fonctionnelles

| ID | Exigence |
|---|---|
| NF1 | Python ≥ 3.11. Dépendances : `langchain-core`, `langchain-anthropic`, `langgraph`, `python-dotenv`. |
| NF2 | Aucun nom de modèle codé en dur hors de `spectre/config.py`. |
| NF3 | Pas de `temperature` envoyé à Sonnet 5.5 / Opus 5.5 (rejeté par l'API). Profondeur de raisonnement réglée par l'effort. |
| NF4 | La clé `ANTHROPIC_API_KEY` est lue depuis l'environnement / `.env` ; jamais journalisée ni commitée. |
| NF5 | Tests : `pytest`, **aucun appel réseau** par défaut, couverture de lignes ≥ 90 %. Tests réels optionnels marqués `live`. |
| NF6 | Qualité : `ruff format`, `ruff check`, `mypy --strict` sur `src/` passent. |
| NF7 | Retries automatiques sur 429/5xx (`max_retries`), timeout configurable. |
| NF8 | Le nom du produit est **Spectre** partout (code, docs, CLI) — jamais « claude agent ». |
| NF9 | Compatible Windows, macOS, Linux. |

## 5. Contraintes

- Bibliothèque imposée : `langchain-anthropic` (`ChatAnthropic`) + LangGraph.
- Modèles imposés : Claude uniquement.
- Dépôt basé sur `template-foundry` : conserver CI, release auto par CHANGELOG, badge de couverture, templates GitHub.

## 6. Livrables

1. Code source `src/spectre/` + point d'entrée CLI `spectre`.
2. Tests `tests/`.
3. `pyproject.toml`, `.env.example`, `README.md`, `CHANGELOG.md` (version 0.1.0).
4. CI GitHub Actions adaptée.
5. Documentation : ce cahier des charges, PDR produit, PDR architecture.
6. Skills d'agents dans `.claude/skills/`.

## 7. Critères d'acceptation

- [ ] `uv sync && uv run pytest` passe sans clé API, couverture ≥ 90 %.
- [ ] `uv run ruff format --check . && uv run ruff check . && uv run mypy src` passent.
- [ ] Avec une clé valide, `uv run spectre "Explique la relativité restreinte simplement" --costs` affiche un texte final et un coût total.
- [ ] `spectre --json` produit un JSON valide contenant `final_text` et `total_cost_usd`.
- [ ] Plus aucun fichier Solidity/Foundry dans le dépôt.
- [ ] La CI GitHub s'exécute sur Python.
