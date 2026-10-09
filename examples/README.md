# Examples

Ce dépôt est hybride : exemples **Spectre** (Python) d'abord, puis exemples **Foundry**
(contrat `Voting`, Solidity 0.8.35).

## Spectre — ligne de commande

Prérequis : `uv sync` et une clé dans `.env` (`ANTHROPIC_API_KEY=sk-ant-...`).

```shell
# Texte final seul (stdout)
uv run spectre "Explique la relativité restreinte en trois paragraphes simples"

# + tableau des coûts par agent (stderr)
uv run spectre "Explique la relativité restreinte simplement" --costs

# Demande lue depuis un fichier
uv run spectre --file demande.txt --costs

# Résultat complet en JSON (brief, draft, final_text, usage, total_cost_usd)
uv run spectre "Rédige un court article sur LangGraph" --json > resultat.json

# Warden à l'effort maximal pour ce run uniquement (bash ; en PowerShell : $env:SPECTRE_WARDEN_EFFORT="max")
SPECTRE_WARDEN_EFFORT=max uv run spectre "Relis ce contrat de prestation" --costs
```

## Spectre — lots, évaluation, agents ajoutés

```shell
uv run spectre batch examples/demandes.example.txt --direct     # trois demandes, une par une
uv run spectre eval examples/cas.example.jsonl --demo           # vérifie le fichier de cas
cp examples/spectre-agents.example.toml spectre-agents.toml     # ajoute un traducteur après Warden
```

## Spectre — bibliothèque

```python
from spectre import SpectreError, run

try:
    result = run("Explique la relativité restreinte simplement")
except SpectreError as exc:  # refus, sortie vide, erreur API, clé absente...
    raise SystemExit(f"Échec : {exc}")

print(result.brief)  # plan de Scout
print(result.draft)  # brouillon de Scribe
print(result.final_text)  # texte corrigé par Warden
print(f"Coût total : {result.total_cost_usd} $")
```

## Spectre — faux modèles (sans réseau ni clé)

`build_graph(models=...)` accepte n'importe quel modèle de chat LangChain : c'est ainsi que les
tests tournent sans appel réseau.

```python
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from spectre import build_graph


def fake(text: str, model: str) -> GenericFakeChatModel:
    message = AIMessage(
        content=text,
        usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        response_metadata={"stop_reason": "end_turn", "model_name": model},
    )
    return GenericFakeChatModel(messages=iter([message]))


graph = build_graph(
    models={
        "scout": fake("Brief : public débutant, 3 paragraphes.", "claude-haiku-4-5"),
        "scribe": fake("Brouillon de l'article...", "claude-sonnet-5-5"),
        "warden": fake("Article final corrigé.", "claude-opus-5-5"),
    }
)
state = graph.invoke({"request": "Explique la relativité restreinte simplement"})
print(state["final_text"])  # "Article final corrigé."
print(state["usage"])  # une ligne UsageRecord par agent
```

## Deploying the Voting contract

[`script/Voting.s.sol`](../script/Voting.s.sol) deploys the contract with no constructor arguments and logs its address.

### Locally (Anvil)

```shell
anvil                                                        # in one terminal
forge script script/Voting.s.sol --rpc-url http://127.0.0.1:8545 \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --broadcast
```

Expected output:

```
== Return ==
voting: contract Voting 0x5FbDB2315678afecb367f032d93F642f64180aa3

== Logs ==
  Voting deployed at: 0x5FbDB2315678afecb367f032d93F642f64180aa3
```

### To Sepolia

```shell
cp .env.example .env
# edit .env: set SEPOLIA_RPC_URL, PRIVATE_KEY, ETHERSCAN_API_KEY
set -a && source .env && set +a

forge script script/Voting.s.sol \
  --rpc-url sepolia \
  --private-key $PRIVATE_KEY \
  --broadcast \
  --verify
```

Expected output:

```
##### sepolia
✅  [Success] Hash: 0xabc123...def456
Contract Address: 0x1234567890abcdef1234567890abcdef12345678
Block: 6942069
Paid: 0.00123456 ETH (123456 gas * 10 gwei)

Starting contract verification...
Waiting for verification result...
Contract successfully verified

Transactions saved to: broadcast/Voting.s.sol/11155111/run-latest.json
```

Look the address up at `https://sepolia.etherscan.io/address/<the address above>` — with `--verify`, the source code is already attached — or interact with it directly:

```shell
VOTING=<the deployed address>
cast send $VOTING "addVoter(address)" $(cast wallet address --private-key $PRIVATE_KEY) --rpc-url sepolia --private-key $PRIVATE_KEY
cast call $VOTING "workflowStatus()(uint8)" --rpc-url sepolia
```

## Driving the full workflow with cast

Once deployed, register voters, run proposals/voting, and read state with `cast`:

```shell
RPC=http://127.0.0.1:8545
KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
VOTING=<deployed address>

cast send $VOTING "addVoter(address)" $(cast wallet address --private-key $KEY) --rpc-url $RPC --private-key $KEY
cast send $VOTING "startProposalsRegistering()" --rpc-url $RPC --private-key $KEY
cast send $VOTING "addProposal(string)" "Plant more trees" --rpc-url $RPC --private-key $KEY
cast call $VOTING "workflowStatus()(uint8)" --rpc-url $RPC
```

## Reading the test suite as usage examples

[`test/Voting.t.sol`](../test/Voting.t.sol) doubles as executable documentation for every function's expected behavior (who can call it, in which workflow phase, and what it reverts on) — including a fuzz test for proposal registration.
