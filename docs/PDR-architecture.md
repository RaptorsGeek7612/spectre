# Spectre — PDR Architecture (Preliminary Design Review)

> Version 0.1 · 2026-10-06 · Sources vérifiées : doc LangChain/LangGraph (Context7) et doc API Claude, 2026-10.

## 1. Vue d'ensemble

```
            ┌────────────┐     ┌─────────────┐     ┌─────────────┐
 request ──▶│   Scout    │────▶│   Scribe    │────▶│   Warden    │──▶ final_text
  (START)   │ Haiku 4.5  │brief│ Sonnet 5.5  │draft│  Opus 5.5   │     (END)
            └────────────┘     └─────────────┘     └─────────────┘
                  │                   │                   │
                  └──────── usage (tokens + $) ───────────┘  ← reducer: liste additive
```

Graphe LangGraph `StateGraph(SpectreState)` : `START → scout → scribe → warden → END`.

## 2. Stack et versions

| Composant | Version mini | Rôle |
|---|---|---|
| Python | 3.11 | |
| `langchain-core` | 1.5.2 | Messages, faux modèles de test, `reasoning_effort` standard |
| `langchain-anthropic` | 1.5.3 | `ChatAnthropic` |
| `langgraph` | 1.0 | `StateGraph`, `START`, `END` |
| `python-dotenv` | 1.0 | Chargement `.env` |
| Dev : `pytest`, `pytest-cov`, `ruff`, `mypy` | récentes | Qualité |
| Gestionnaire | `uv` | Install, lock, run |

## 3. Arborescence

```
Spectre/
├── src/spectre/
│   ├── __init__.py      # API publique : run, build_graph, SpectreResult, __version__
│   ├── config.py        # Registre des modèles (AgentSpec), prix, lecture env
│   ├── llm.py           # Fabrique ChatAnthropic à partir d'un AgentSpec
│   ├── prompts.py       # Prompts système des 3 agents
│   ├── state.py         # SpectreState (TypedDict) + UsageRecord
│   ├── costs.py         # Extraction usage_metadata → UsageRecord, calcul $
│   ├── nodes.py         # Fabriques de nœuds scout / scribe / warden
│   ├── graph.py         # build_graph(models=None), run(request)
│   ├── errors.py        # SpectreError, AgentRefusalError, EmptyOutputError
│   └── cli.py           # Point d'entrée `spectre`
├── tests/               # pytest, faux modèles, aucun réseau
├── docs/
├── .claude/skills/      # Skills des agents de développement
├── pyproject.toml
├── .env.example
│   # --- Partie Foundry conservée du template (Solidity 0.8.35) ---
├── src/Voting.sol       # contrat (pragma ^0.8.35)
├── test/Voting.t.sol    # tests forge
├── script/Voting.s.sol  # déploiement
├── lib/                 # submodules forge-std, openzeppelin-contracts
└── foundry.toml         # solc_version = "0.8.35", evm_version = "cancun"
```

Note : `src/` contient à la fois le package Python `src/spectre/` et `src/Voting.sol`.
Hatchling ne package que `src/spectre` ; `forge` ne compile que les `.sol`.

## 4. Registre des modèles (`config.py`)

```python
@dataclass(frozen=True)
class AgentSpec:
    name: str  # "scout" | "scribe" | "warden"
    model: str  # ID exact, sans suffixe de date
    max_tokens: int
    temperature: float | None  # None = ne pas envoyer
    effort: str | None  # "low"|"medium"|"high"|"xhigh"|"max" ; None = ne pas envoyer
```

| Agent | `model` | `max_tokens` | `temperature` | `effort` | Prix in / out ($/MTok) |
|---|---|---|---|---|---|
| scout | `claude-haiku-4-5` | 1 024 | 0.2 | — (non supporté) | 1 / 5 |
| scribe | `claude-sonnet-5-5` | 16 000 | — (400 si ≠ défaut) | `medium` | 2 / 10 |
| warden | `claude-opus-5-5` | 16 000 | — (400) | `high` | 4 / 20 |

Règles API à respecter (doc Claude, 2026-09) :
- **Sonnet 5.5 / Opus 5.5** : pas de `temperature`/`top_p`/`top_k` ; pas de `budget_tokens` ; pas de prefill assistant ; réflexion adaptative toujours active, profondeur réglée par `effort` (défaut Opus 5.5 = `medium`, donc on le fixe explicitement).
- **Haiku 4.5** : accepte `temperature` ; **n'accepte pas** `effort`.
- Effort transmis via le paramètre standard `reasoning_effort` de `ChatAnthropic` (langchain-anthropic ≥ 1.5.3).

Surcharges par environnement : `SPECTRE_<AGENT>_MODEL`, `SPECTRE_<AGENT>_MAX_TOKENS`,
`SPECTRE_<AGENT>_EFFORT` (ex. `SPECTRE_WARDEN_EFFORT=max`). Les prix sont dans
une table `PRICING` indexée par ID de modèle ; modèle inconnu → coût `None` +
avertissement (pas de crash).

`llm.py` construit `ChatAnthropic(model=..., max_tokens=..., max_retries=..., timeout=...)`
et n'ajoute `temperature` / `reasoning_effort` que s'ils ne sont pas `None`.

## 5. État (`state.py`)

```python
class UsageRecord(TypedDict):
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


class SpectreState(TypedDict, total=False):
    request: str  # entrée
    brief: str  # sortie Scout
    draft: str  # sortie Scribe
    final_text: str  # sortie Warden
    usage: Annotated[list[UsageRecord], operator.add]  # reducer additif
```

## 6. Nœuds (`nodes.py`)

Chaque nœud est créé par une fabrique qui reçoit son modèle (injection) :
`make_scout_node(model: BaseChatModel) -> Callable[[SpectreState], dict]`.

| Nœud | Entrée | Messages envoyés | Sortie |
|---|---|---|---|
| scout | `request` | System(SCOUT_PROMPT), Human(request) | `brief`, `usage` |
| scribe | `request`, `brief` | System(SCRIBE_PROMPT), Human(demande + brief) | `draft`, `usage` |
| warden | `request`, `draft` | System(WARDEN_PROMPT), Human(demande + brouillon) | `final_text`, `usage` |

Traitement commun (fonction `_call_agent`) :
1. `ai = model.invoke(messages)`
2. Si `ai.response_metadata.get("stop_reason") == "refusal"` → `AgentRefusalError(agent)`.
3. Texte = concaténation des blocs `text` (`ai.text` ; ignore les blocs `thinking`). Vide → `EmptyOutputError(agent)`.
4. `UsageRecord` depuis `ai.usage_metadata` (`input_tokens`, `output_tokens`) + prix.
5. Si `stop_reason == "max_tokens"` → avertissement `logging` (texte tronqué).

Le prompt de Warden lui demande de **ne renvoyer que le texte final corrigé**,
sans commentaire, pour que `final_text` soit directement exploitable.

## 7. Graphe et API publique (`graph.py`, `__init__.py`)

```python
def build_graph(models: Mapping[str, BaseChatModel] | None = None) -> CompiledStateGraph
def run(request: str, *, models: Mapping[str, BaseChatModel] | None = None) -> SpectreResult
```

- `models=None` → construit les trois `ChatAnthropic` depuis `config` (charge `.env` à ce moment, pas à l'import).
- `models={"scout": fake, ...}` → tests sans réseau.
- `SpectreResult` : dataclass `brief`, `draft`, `final_text`, `usage`, propriété `total_cost_usd`, méthode `to_dict()`.
- `run("")` (vide/espaces) → `ValueError`.

## 8. CLI (`cli.py`)

`argparse`, script `spectre = "spectre.cli:main"`.

| Option | Effet |
|---|---|
| `request` (positionnel, optionnel) | Demande |
| `--file PATH` | Lit la demande depuis un fichier (exclusif avec positionnel) |
| `--costs` | Affiche le tableau des coûts sur stderr |
| `--json` | Écrit `SpectreResult.to_dict()` + `total_cost_usd` en JSON sur stdout |
| `--version` | Version |

Codes de sortie : 0 succès, 1 erreur Spectre/API, 2 erreur d'usage. Clé absente →
message clair (« définissez ANTHROPIC_API_KEY ou créez un fichier .env »), code 1.
Sortie forcée en UTF-8 (Windows).

## 9. Erreurs

| Cas | Comportement |
|---|---|
| 429 / 5xx / réseau | Retries SDK (`max_retries=4`), puis `SpectreError` |
| 400 / 401 / 404 | Pas de retry, `SpectreError` avec agent + message |
| `stop_reason == "refusal"` | `AgentRefusalError` |
| Sortie vide | `EmptyOutputError` |
| Troncature `max_tokens` | Warning, on continue |

## 10. Stratégie de test

- Faux modèles : `langchain_core.language_models.fake_chat_models.GenericFakeChatModel`
  (messages `AIMessage` avec `usage_metadata` et `response_metadata` contrôlés).
- Cas couverts : pipeline complet, ordre des agents, contenu des messages transmis,
  agrégation de l'usage, calcul de coût (dont modèle inconnu), refus, sortie vide,
  surcharges env, `llm.py` n'envoie pas `temperature` à Sonnet/Opus ni `reasoning_effort`
  à Haiku, CLI (texte, `--json`, `--costs`, `--file`, erreurs, clé absente).
- Tests `@pytest.mark.live` (vrais appels) exclus par défaut (`-m "not live"`).
- Couverture ≥ 90 % (gate CI).

## 11. CI (adaptée du template)

Jobs :
- `test` (Foundry, **inchangé**) : `forge fmt --check`, `forge build --sizes`, `forge test -vvv`, `forge coverage`.
- `python` (nouveau) : `astral-sh/setup-uv`, `uv sync --frozen`, `ruff format --check`,
  `ruff check`, `mypy src`, `pytest -m "not live" --cov=spectre --cov-fail-under=90`.
- `coverage-badge` : badge Foundry conservé tel quel (branche `badges`, `coverage.json`) ;
  ajout d'un second badge `coverage-python.json` calculé de la même façon depuis le `lcov.info` de pytest.
- `release` : dépend de `test` **et** `python` ; logique CHANGELOG inchangée.

## 12. Évolution v0.2 (prévue)

- Warden renvoie un verdict structuré (`with_structured_output`) `{approved, issues, final_text}`.
- Arête conditionnelle `warden → scribe` si `approved == False` et `revisions < MAX_REVISIONS`.
- Champ d'état `revisions: int`. Aucun changement d'API publique incompatible.

## 13. Décisions (ADR courtes)

| # | Décision | Raison |
|---|---|---|
| 1 | Effort plutôt que temperature sur Sonnet/Opus | Imposé par l'API (temperature → 400) |
| 2 | Injection des modèles dans `build_graph` | Tests sans réseau, flexibilité |
| 3 | Reducer additif pour `usage` | Chaque nœud ajoute sa ligne sans écraser |
| 4 | Pas de streaming en v0.1 | `max_tokens` ≤ 16 000 reste sous les timeouts HTTP (600 s) ; streaming en v0.2 |
| 5 | `uv` + `pyproject.toml` | Remplace `forge` ; lock reproductible |
| 6 | Noms d'agents Scout/Scribe/Warden | Rôles explicites, indépendants des modèles |
