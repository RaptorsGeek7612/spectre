# Spectre

[![CI](https://github.com/RaptorsGeek7612/spectre/actions/workflows/ci.yml/badge.svg)](https://github.com/RaptorsGeek7612/spectre/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/RaptorsGeek7612/spectre)](https://github.com/RaptorsGeek7612/spectre/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Coverage (Foundry)](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/RaptorsGeek7612/spectre/badges/coverage.json)](https://github.com/RaptorsGeek7612/spectre/actions/workflows/ci.yml)
[![Coverage (Python)](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/RaptorsGeek7612/spectre/badges/coverage-python.json)](https://github.com/RaptorsGeek7612/spectre/actions/workflows/ci.yml)

**Spectre** est un orchestrateur multi-agents **100 % Claude**, écrit en Python avec
[`langchain-anthropic`](https://python.langchain.com/docs/integrations/chat/anthropic/) et
[LangGraph](https://langchain-ai.github.io/langgraph/). Une demande en texte libre traverse
trois agents spécialisés — **Scout** cadre, **Scribe** rédige, **Warden** vérifie et corrige —
et Spectre affiche le coût réel de chaque étape. Le modèle le plus cher n'intervient qu'une
fois, en dernier, sur un texte déjà préparé.

Le dépôt est **hybride** : il conserve aussi, issu du template
[`template-foundry`](https://github.com/RaptorsGeek7612/template-foundry), le contrat Solidity
`Voting` (Foundry, Solidity 0.8.35) — voir [Contrat Solidity (Foundry)](#contrat-solidity-foundry).

## Fonctionnement

```
            ┌────────────┐     ┌─────────────┐     ┌─────────────┐
 demande ──▶│   Scout    │────▶│   Scribe    │────▶│   Warden    │──▶ texte final
  (START)   │ Haiku 4.5  │brief│ Sonnet 5.5  │draft│  Opus 5.5   │     (END)
            └────────────┘     └─────────────┘     └─────────────┘
                  │                   │                   │
                  └────────── usage (tokens + $) ─────────┘
```

| Agent | Modèle | Rôle | Réglage | Prix entrée / sortie ($/MTok) |
|---|---|---|---|---|
| **Scout** (l'éclaireur) | `claude-haiku-4-5` | Extrait l'intention, le public, les contraintes et un plan | `temperature` 0.2, 1 024 tokens max | 1 / 5 |
| **Scribe** (la plume) | `claude-sonnet-5-5` | Rédige le texte complet à partir de la demande et du brief | effort `medium`, 16 000 tokens max | 2 / 10 |
| **Warden** (le gardien) | `claude-opus-5-5` | Vérifie exactitude, cohérence et style, renvoie la version corrigée | effort `high`, 16 000 tokens max | 4 / 20 |

Sonnet 5.5 et Opus 5.5 n'acceptent pas de `temperature` : leur profondeur de raisonnement se
règle par l'**effort**. Haiku 4.5, à l'inverse, accepte `temperature` mais pas l'effort.

La v0.1 est un pipeline linéaire. La boucle de révision Warden → Scribe est prévue en v0.3
(voir [docs/PDR-produit.md](docs/PDR-produit.md)).

## Installation

Prérequis : Python ≥ 3.11 et [uv](https://docs.astral.sh/uv/).

```shell
git clone https://github.com/RaptorsGeek7612/spectre.git
cd spectre
uv sync                 # crée .venv et installe les dépendances (dev incluses)
cp .env.example .env    # puis renseignez ANTHROPIC_API_KEY
```

La clé est lue depuis l'environnement ou le fichier `.env` (ignoré par git). Ne la commitez jamais.

## Utilisation

### Ligne de commande

```shell
uv run spectre "Explique la relativité restreinte en trois paragraphes simples"
uv run spectre "Explique la relativité restreinte simplement" --costs   # + tableau des coûts (stderr)
uv run spectre --file demande.txt                                      # demande lue depuis un fichier
uv run spectre "Rédige un court article sur LangGraph" --json          # résultat complet en JSON (stdout)
uv run spectre --version
```

Exemple de tableau `--costs` :

```
Agent    Modèle              Entrée  Sortie   Coût
scout    claude-haiku-4-5       210     180   0.0011 $
scribe   claude-sonnet-5-5      420    1350   0.0144 $
warden   claude-opus-5-5       1600    1400   0.0344 $
Total                                         0.0499 $
```

| Option | Effet |
|---|---|
| `request` (positionnel) | La demande |
| `--file PATH` | Lit la demande depuis un fichier (exclusif avec le positionnel) |
| `--costs` | Affiche le tableau des coûts sur stderr |
| `--json` | Écrit le résultat (`brief`, `draft`, `final_text`, `usage`, `total_cost_usd`) en JSON sur stdout |
| `--version` | Affiche la version |

Codes de sortie : `0` succès, `1` erreur Spectre/API (dont clé absente), `2` erreur d'usage,
`130` interruption par Ctrl+C.

### Interface web

```shell
uv run python -m spectre.web            # ouvre http://127.0.0.1:8765/ dans le navigateur
uv run spectre-web                      # même chose (si Windows n'a pas bloqué l'exécutable)
uv run python -m spectre.web --port 9000 --no-browser
```

Une interface complète, sans framework ni build (même principe que Hermes WebUI) : un serveur
Python de la bibliothèque standard et une page HTML/CSS/JS.

- **Chaîne en direct** : les trois agents sont des raies d'émission sur un axe en nanomètres
  (Scout 486 nm, Scribe 546 nm, Warden 589 nm). La forme de la raie dit l'état : pointillée en
  attente, pleine et lumineuse quand l'agent écrit, à mi-hauteur si la réponse est tronquée,
  doublée si un modèle de repli a répondu, barrée en cas d'échec. Le texte s'affiche mot à mot.
- **Lecture** : onglets Texte final, Brouillon, Brief, **Corrections** (ce que Warden a changé,
  en barré/souligné), Demande, Brut ; copie, relance, modification de la demande.
- **Mesures** : tokens, durée, coût et modèle réellement servi pour chaque agent, et le total.
- **Historique** (« plaques » numérotées) : recherche, `#tags`, projets, épingles, archives,
  renommer, dupliquer, supprimer ; export Markdown, JSON ou page HTML autonome à partager ;
  export et import de tout l'historique.
- **Saisie** : dictée vocale (navigateurs compatibles), fichier texte joint, commandes `/`
  (`/nouveau`, `/demo`, `/theme`, `/couts`, `/preset`, `/export`, `/aide`…), palette `Ctrl+K`,
  raccourcis (`Ctrl+Entrée`, `N`, `/`, `J`/`K`, `Échap`).
- **Préréglages** : modèle, effort et limite de tokens par agent (Standard, Économie,
  Qualité max, et les vôtres).
- **Réglages** : thème sombre, clair ou système, taille du texte, touche d'envoi, langue
  (français, anglais), affichage des coûts, notification de fin.
- **Mode démo** : réponses préenregistrées, sans clé ni coût, clairement signalées.
- **Ordinateur, tablette, téléphone** : mise en page adaptée à chaque taille ; installable comme
  une application (PWA).

**Sur téléphone ou tablette** : l'interface n'écoute que sur ce PC par défaut. Pour l'ouvrir au
réseau local, définissez d'abord un mot de passe, puis lancez avec `--host 0.0.0.0` et ouvrez
l'adresse affichée sur l'appareil (même Wi-Fi) :

```shell
# dans .env : SPECTRE_WEBUI_PASSWORD=un-mot-de-passe-solide
uv run python -m spectre.web --host 0.0.0.0
```

Sans mot de passe, Spectre refuse de s'ouvrir au réseau : n'importe qui sur le Wi-Fi pourrait
lancer des exécutions facturées sur votre clé. La clé API n'est jamais envoyée au navigateur.
L'historique est rangé dans `~/.spectre/webui/` (modifiable avec `SPECTRE_WEBUI_STATE_DIR`).

### Assistant vocal

Spectre est aussi un assistant personnel qui répond au nom de **Spectre** : la voix, des actions
sur le PC sous contrôle, une mémoire qui apprend, des initiatives et des missions longues. Le
cerveau est Claude Code en mode non interactif (`claude -p`) : il passe par votre **abonnement**
Claude, sans clé API. La voix est locale et gratuite : mot d'éveil Vosk, transcription
faster-whisper, synthèse Piper (voix d'homme `fr_FR-upmc-medium`, locuteur « pierre », par défaut) avec un timbre d'IA de bord :
« futuriste » (grave, harmonies décalées, résonances métalliques), « androide » (vocodeur),
« hologramme » (chœur scintillant), « vaisseau » (discret) ou « aucun ».

```shell
uv sync --extra voice                              # micro, mot d'éveil, transcription, synthèse
uv run python -m spectre.assistant                 # interface seule (texte)
uv run python -m spectre.assistant --voice         # dis « Spectre » pour lui parler
```

Le premier lancement avec `--voice` télécharge les modèles (environ 200 Mo) dans
`~/.spectre/assistant/models/`. L'interface `assistant.html` affiche l'état de la voix, la
conversation, les actions en attente de validation, les missions, la mémoire (consultable,
corrigeable, oubliable), les initiatives, le journal d'audit et les réglages.

Chaque action passe par un **portail de gouvernance** à trois axes : le niveau de risque (0
lecture → 5 critique), la politique de la catégorie (toujours, demander, jamais) et un budget
(20 actions par minute, 500 par jour). Le plus restrictif l'emporte. Supprimer, remplacer un
fichier, envoyer quelque chose ou toucher au système demande votre validation ; installer un
logiciel, payer ou modifier Spectre est refusé. Les fichiers restent dans les dossiers autorisés,
les écritures sont journalisées et annulables (« annule »), et la suppression passe par la
corbeille de Spectre. Les outils sont exposés au cerveau par un serveur MCP
(`spectre.assistant.mcp_server`) qui partage la base SQLite de l'assistant.

La mémoire stocke des faits datés et sourcés (sujet, prédicat, valeur), renforcés quand ils
reviennent et remplacés quand ils changent ; une vue Markdown en lecture seule est écrite dans
`~/.spectre/assistant/memoire/`. Chaque nuit, Spectre consolide les échanges de la veille ; chaque
matin, il prépare un briefing (météo Open-Meteo, rappels, validations en attente). Les missions
longues sont planifiées, exécutées étape par étape, vérifiées, puis résumées dans un rapport ;
`kind=redaction` confie un texte soigné à Scout, Scribe et Warden.

### Bibliothèque

```python
from spectre import run

result = run("Explique la relativité restreinte simplement")
print(result.final_text)
print(f"{result.total_cost_usd:.4f} $")
for record in result.usage:
    print(record["agent"], record["model"], record["input_tokens"], record["output_tokens"])
```

`build_graph(models=...)` permet d'injecter vos propres modèles de chat (par exemple des faux
modèles LangChain) pour tester sans réseau. Voir [examples/README.md](examples/README.md).

## Configuration

Chaque agent (`SCOUT`, `SCRIBE`, `WARDEN`) est surchargeable par variable d'environnement
(ou dans `.env`) :

| Variable | Effet | Exemple |
|---|---|---|
| `ANTHROPIC_API_KEY` | Clé API Anthropic (obligatoire pour un vrai run) | `sk-ant-...` |
| `ANTHROPIC_WORKSPACE_ID` | ID du workspace, à renseigner seulement si la clé est liée à un utilisateur (`sk-ant-usr...`) plutôt qu'à un workspace | `wrkspc_...` |
| `SPECTRE_<AGENT>_MODEL` | ID du modèle | `SPECTRE_SCRIBE_MODEL=claude-opus-5-5` |
| `SPECTRE_<AGENT>_MAX_TOKENS` | Limite de tokens en sortie | `SPECTRE_WARDEN_MAX_TOKENS=4000` |
| `SPECTRE_<AGENT>_EFFORT` | Effort (`low`, `medium`, `high`, `xhigh`, `max`) — Sonnet/Opus uniquement | `SPECTRE_WARDEN_EFFORT=max` |
| `SPECTRE_TIMEOUT` | Délai d'attente d'un appel HTTP, en secondes (défaut `600`) | `SPECTRE_TIMEOUT=900` |
| `SPECTRE_MAX_RETRIES` | Nombre de nouvelles tentatives sur 429, 5xx ou erreur réseau (défaut `4`) | `SPECTRE_MAX_RETRIES=2` |
| `SPECTRE_FALLBACKS` | Repli automatique en cas de refus (défaut activé ; `0` pour désactiver) | `SPECTRE_FALLBACKS=0` |
| `SPECTRE_WEBUI_PASSWORD` | Mot de passe de l'interface web (obligatoire avec `--host 0.0.0.0`) | `SPECTRE_WEBUI_PASSWORD=...` |
| `SPECTRE_WEBUI_STATE_DIR` | Dossier de l'historique et des réglages de l'interface web | `SPECTRE_WEBUI_STATE_DIR=D:/spectre` |

Un modèle absent de la table de prix donne un coût `None` (avec un avertissement), sans faire
échouer le run.

**Repli en cas de refus.** Les filtres de sécurité de Sonnet 5.5 et d'Opus 5.5 peuvent refuser
une demande légitime. Spectre active alors le repli côté serveur (`fallbacks: "default"`) :
l'API relance la demande sur le modèle de repli recommandé pour ce type de refus, au lieu
d'échouer. Dans `usage`, `model` indique le modèle qui a réellement répondu, et le coût est
calculé à son tarif. Un avertissement est écrit sur stderr.

**Troncature.** Si un agent atteint sa limite `max_tokens`, un avertissement est écrit sur
stderr et la ligne correspondante de `usage` porte `"truncated": true`. Augmentez alors
`SPECTRE_<AGENT>_MAX_TOKENS`.

## Développement

```shell
uv sync
uv run ruff format .                         # formate
uv run ruff format --check . ; uv run ruff check .
uv run mypy src                              # mypy --strict
uv run pytest -m "not live" --cov=spectre --cov-report=term-missing
```

Les tests par défaut n'effectuent **aucun appel réseau** (faux modèles LangChain). Les tests
qui appellent réellement l'API sont marqués `@pytest.mark.live` et s'exécutent explicitement
avec `uv run pytest -m live` (clé requise, facturé).

La CI GitHub Actions comporte deux jobs de test :
- `test` (Foundry) : `forge fmt --check`, `forge build --sizes`, `forge test -vvv`, `forge coverage` ;
- `python` (Spectre) : `ruff format --check`, `ruff check`, `mypy src`, `pytest` (couverture ≥ 90 %).

Elle publie ensuite les deux badges de couverture (`coverage.json` pour Foundry,
`coverage-python.json` pour Python) sur la branche `badges`, et crée automatiquement un tag et
une release quand `CHANGELOG.md` gagne une nouvelle version.

### Arborescence

```
src/spectre/      Package Spectre (config, llm, prompts, state, costs, nodes, graph, errors, cli)
src/spectre/web/  Interface web (serveur, API de l'assistant, pages statiques)
src/spectre/assistant/  Assistant vocal (cerveau, outils, gouvernance, mémoire, missions, voix)
tests/            Tests pytest, sans réseau
src/Voting.sol    Contrat Solidity (Foundry)
test/             Tests Foundry unitaires + fuzz (Voting.t.sol)
script/           Script de déploiement (Voting.s.sol)
lib/              Dépendances Foundry en submodules (forge-std, openzeppelin-contracts)
docs/             Cahier des charges, PDR produit, PDR architecture, brainstorming
examples/         Exemples d'utilisation (Spectre et Foundry)
.claude/skills/   Skills des agents de développement (spectre-*)
pyproject.toml    Métadonnées Python, dépendances, configuration ruff / mypy / pytest
foundry.toml      Configuration Foundry (solc 0.8.35)
```

## Contrat Solidity (Foundry)

Un système de vote on-chain avec liste blanche, construit avec Foundry et le module `Ownable`
d'OpenZeppelin, compilé en **Solidity 0.8.35** (`solc_version` dans `foundry.toml`,
`pragma solidity ^0.8.35;`).

Le contrat `Voting` fait passer les votants par un workflow fixe :

1. `RegisteringVoters` — le propriétaire inscrit les adresses des votants.
2. `ProposalsRegistrationStarted` — les votants inscrits soumettent des propositions.
3. `ProposalsRegistrationEnded`
4. `VotingSessionStarted` — chaque votant inscrit vote une fois.
5. `VotingSessionEnded`
6. `VotesTallied` — le propriétaire dépouille ; la proposition la plus votée gagne.

Seul le propriétaire fait avancer le workflow et inscrit les votants ; seuls les votants inscrits
peuvent proposer, voter ou lire les données de votants et de propositions.

### Installation

Prérequis : [Foundry](https://book.getfoundry.sh/getting-started/installation).

```shell
git clone --recurse-submodules https://github.com/RaptorsGeek7612/spectre.git
# ou, si le dépôt a été cloné sans --recurse-submodules :
git submodule update --init --recursive

forge install   # seulement si lib/ est vide
cp .env.example .env   # renseignez les variables Sepolia pour déployer
```

### Build, tests, formatage

```shell
forge build
forge test
forge test -vvv          # traces détaillées en cas d'échec
forge test --match-test testFuzz_AddProposalIncrementsProposalCount
forge fmt --check
```

### Déploiement local (Anvil)

```shell
anvil                                                        # dans un terminal
forge script script/Voting.s.sol --rpc-url http://127.0.0.1:8545 \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --broadcast
```

(Cette clé privée est celle du compte de test n° 0 bien connu d'Anvil — ne la réutilisez
jamais pour quoi que ce soit de réel.)

### Déploiement sur Sepolia

Foundry ne lit pas `.env` automatiquement — exportez-le d'abord :

```shell
set -a && source .env && set +a

forge script script/Voting.s.sol \
  --rpc-url sepolia \
  --private-key $PRIVATE_KEY \
  --broadcast \
  --verify
```

Pour éviter de garder une clé privée brute dans `.env`, utilisez le keystore chiffré de Foundry :

```shell
cast wallet import deployer --interactive
forge script script/Voting.s.sol --rpc-url sepolia --account deployer --broadcast --verify
```

Voir [examples/README.md](examples/README.md#to-sepolia) pour un exemple complet avec la
sortie attendue.

### Interagir avec un contrat déployé

```shell
cast send <VOTING_ADDRESS> "addVoter(address)" <VOTER_ADDRESS> --rpc-url sepolia --account deployer
cast call <VOTING_ADDRESS> "workflowStatus()(uint8)" --rpc-url sepolia
```

## Documentation

- [Cahier des charges](docs/cahier-des-charges.md)
- [PDR produit](docs/PDR-produit.md)
- [PDR architecture](docs/PDR-architecture.md)
- [Brainstorming](docs/brainstorming.md)
- Foundry Book — https://book.getfoundry.sh/
- OpenZeppelin Contracts — https://docs.openzeppelin.com/contracts/5.x/

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) et
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Licence

MIT — voir [LICENSE](LICENSE).
