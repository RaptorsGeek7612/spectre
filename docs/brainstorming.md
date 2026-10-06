# Spectre — Brainstorming

> Date : 2026-10-06 · Statut : base de travail pour le cahier des charges et le PDR.

## 1. Point de départ

L'exemple fourni décrit un pipeline LangGraph « tout Claude » en trois étapes :
résumé (Haiku) → rédaction (Sonnet) → validation/correction (Opus). L'idée est
bonne (le modèle premium ne travaille qu'en dernier, sur un texte déjà préparé),
mais le code n'est pas exécutable en l'état :

| Problème dans l'exemple | Conséquence | Correction Spectre |
|---|---|---|
| Modèles `claude-3-*` (dont `claude-3-sonnet-20240620`, qui n'a jamais existé) | 404 / modèles retirés | `claude-haiku-4-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, centralisés dans la config |
| `max_output_tokens=` | Paramètre inconnu de `ChatAnthropic` | `max_tokens=` |
| `temperature=` sur Sonnet 5.5 / Opus 5.5 | **400** : ces modèles n'acceptent plus de valeur de sampling non par défaut | `temperature` seulement sur Haiku ; sur Sonnet/Opus on règle l'**effort** |
| `StateGraph()` sans schéma | Exception à la construction | `StateGraph(SpectreState)` avec un `TypedDict` |
| `.invoke({"messages": [...]})` sur un chat model | Mauvais format d'entrée | `.invoke([SystemMessage(...), HumanMessage(...)])` |
| `start_node` qui renomme `input` → `prompt` | Nœud inutile | Entrée directe via `START` |
| Pas de gestion d'erreurs, de coûts, de tests | Impossible à exploiter | Suivi `usage_metadata`, coûts en $, tests sans réseau |

## 2. Vision

**Spectre** est un orchestrateur multi-agents 100 % Claude : chaque agent est un
wrapper autour d'un modèle Claude choisi pour son rapport qualité/coût, et
LangGraph fait circuler un état typé entre eux. On paie le modèle cher uniquement
là où il apporte de la valeur.

### Les trois agents (noms de code)

| Agent | Modèle | Rôle | Pourquoi ce modèle |
|---|---|---|---|
| **Scout** (l'éclaireur) | Claude Haiku 4.5 | Analyse la demande, en extrait l'intention, les contraintes et un plan court | Rapide, $1/$5 par MTok, tâche simple |
| **Scribe** (la plume) | Claude Sonnet 5.5 | Rédige le texte complet à partir du plan | Bon rédacteur, $2/$10 |
| **Warden** (le gardien) | Claude Opus 5.5 | Vérifie cohérence/exactitude, corrige, rend un verdict | Le plus rigoureux, $4/$20, n'intervient qu'une fois |

## 3. Idées (triées)

### Retenu pour la v0.1 (MVP)
- Pipeline linéaire Scout → Scribe → Warden, état typé.
- Registre de modèles centralisé (`config.py`) surchargeable par variables d'environnement (`SPECTRE_SCOUT_MODEL`, …).
- Suivi des tokens et du coût par agent et total (via `usage_metadata`).
- CLI `spectre "ma demande"` avec `--json` et `--costs`.
- Injection de dépendances : `build_graph(models=...)` pour tester avec des faux modèles, **zéro appel réseau en CI**.
- Prompts système versionnés dans un module dédié.

### Retenu pour la v0.2
- **Boucle de révision** : Warden rend un verdict structuré (`approved` / `needs_revision` + remarques) ; si rejet, retour à Scribe, max N tours (arête conditionnelle LangGraph).
- Sortie structurée pour le verdict (`with_structured_output`).
- Streaming de la sortie finale dans la CLI.

### Backlog (plus tard)
- Nœuds « extra-processing » branchables (traduction, mise en forme Markdown, génération de titre).
- Checkpointing LangGraph (reprise d'une exécution interrompue).
- Prompt caching des prompts système.
- Batch API (–50 %) pour traiter des lots de demandes.
- Petite API HTTP (FastAPI) ou UI.
- Jeu d'évaluation (qualité des sorties) pour comparer réglages d'effort/modèles.

### Écarté
- Mélanger d'autres fournisseurs (OpenAI, etc.) — hors périmètre : Spectre est 100 % Claude.

## 4. Le template Foundry

`RaptorsGeek7612/template-foundry` est un template **Solidity** (contrat `Voting`).
**Décision (2026-10-06) : la partie Foundry est conservée** et mise à jour en
**Solidity 0.8.35** ; le pipeline Python Spectre vit à côté, dans le même dépôt,
sans lien fonctionnel entre les deux pour l'instant.

| Élément du template | Devenir dans Spectre |
|---|---|
| `src/Voting.sol`, `test/`, `script/`, `lib/` (submodules), `foundry.toml`, `foundry.lock`, `remappings.txt` | **Conservés**, `solc_version` et pragmas passés de 0.8.28 à **0.8.35** |
| Code Python | Ajouté : `src/spectre/`, `tests/`, `pyproject.toml` |
| CI `fmt → build → test → coverage` | Conservée pour Foundry **+** job Python : `ruff format --check`, `ruff check`, `mypy`, `pytest --cov` |
| Badge de couverture auto-hébergé (branche `badges`) | Conservé, alimenté par `coverage.py` |
| Release auto quand le `CHANGELOG.md` gagne une version | Conservé tel quel |
| Templates issue/PR, `CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT`, `LICENSE` MIT | Conservés, adaptés à Python/Spectre |
| Dependabot `github-actions` | Conservé + écosystème `pip` (uv) |
| `.env.example` (clés Sepolia) | Conservé + `ANTHROPIC_API_KEY` et surcharges de modèles |

## 5. Risques identifiés

| Risque | Mitigation |
|---|---|
| Coût qui dérape (Opus sur gros textes) | `max_tokens` par agent, coût affiché à chaque run, effort réglable |
| Évolution des modèles / paramètres | Un seul fichier de config ; tests qui vérifient qu'on n'envoie pas `temperature` à Sonnet/Opus |
| Refus de sécurité (`stop_reason: refusal`) | Détection et message clair plutôt qu'un texte vide |
| Tests dépendants du réseau / d'une clé | Faux modèles LangChain en CI ; tests réels marqués `@pytest.mark.live` et désactivés par défaut |
| Fuite de la clé API | `.env` ignoré par git, jamais de clé dans les logs |

## 6. Organisation du travail (agents de développement)

Le projet est mené par plusieurs agents Claude Code, chacun avec sa skill :

| Agent | Skill | Livrable |
|---|---|---|
| Builder | `spectre-builder` | Package `src/spectre/`, CLI |
| Tester | `spectre-tester` | `tests/`, couverture ≥ 90 % |
| DevOps | `spectre-devops` | Conversion du template : CI, docs dépôt, nettoyage Solidity |
| Reviewer | `spectre-reviewer` | Revue finale, liste de corrections |

Socle commun à tous : `spectre-conventions`.
