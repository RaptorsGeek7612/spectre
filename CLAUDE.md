# Spectre — fiche projet

Spectre est un orchestrateur multi-agents **100 % Claude** en Python : Scout (`claude-haiku-4-5`)
→ Scribe (`claude-sonnet-5-5`) → Warden (`claude-opus-5-5`), orchestré par LangGraph via
`langchain-anthropic`. Package dans `src/spectre/`, CLI `spectre`.

Le dépôt est **hybride** : il conserve la partie **Foundry** du template d'origine — contrat
`src/Voting.sol`, `test/Voting.t.sol`, `script/Voting.s.sol`, submodules `lib/`, `foundry.toml`,
`foundry.lock`, `remappings.txt`, `.gitmodules` — en **Solidity 0.8.35**. **Ne jamais supprimer
ces fichiers.** La CI les vérifie (job `test`) ; forge n'est pas forcément installé localement.

## À lire avant de travailler
- `docs/cahier-des-charges.md` — exigences et critères d'acceptation.
- `docs/PDR-architecture.md` — arborescence, signatures, état, erreurs, tests, CI (à respecter).
- `docs/PDR-produit.md` — périmètre par version (boucle de révision Warden → Scribe depuis la v0.4).
- Skills : `.claude/skills/spectre-conventions` (socle commun, à charger en premier), puis
  selon le rôle `spectre-builder`, `spectre-tester`, `spectre-devops`, `spectre-reviewer`.
- Skill (assistant) : `spectre-crypto` — minage, blockchains, NFT, services crypto et trading ;
  sujet prioritaire, données de marché vérifiées en direct, jamais de phrase de récupération ni
  de clé, aucune transaction sans un oui, pas de promesse de gain.

## Commandes (Windows : `uv run`, pas d'activation de venv)
```shell
uv sync
uv run ruff format --check . ; uv run ruff check .
uv run mypy src                  # si Windows bloque mypy : uv run python -m mypy --no-native-parser src
uv run pytest -m "not live" --cov=spectre --cov-report=term-missing
uv run python -m spectre.web             # interface web (spectre-web.exe peut être bloqué par Windows)
uv run spectre batch demandes.txt       # lots (API Message Batches) ; --direct pour un par un
uv run spectre eval cas.jsonl --demo    # évaluation ; --judge pour les critères
uv run python -m spectre.assistant --voice   # assistant vocal (uv sync --extra voice)

# Partie Foundry
forge fmt --check ; forge build ; forge test
```

## Règles essentielles
- Le produit s'appelle **Spectre**. IDs de modèles uniquement dans `src/spectre/config.py`.
- Jamais de `temperature`/`top_p`/`top_k` vers Sonnet 5.5 / Opus 5.5 : régler l'effort.
  Haiku 4.5 : `temperature` OK, pas d'effort. `max_tokens`, pas de prefill, pas de `budget_tokens`.
- Assistant : moteurs en références (`assistant/providers.py`) : alias Claude Code (`haiku`,
  `sonnet`, `opus`, jamais d'ID), `chatgpt`, `mistral` ou `fournisseur:modèle` (tout point
  d'accès compatible OpenAI, `assistant/llm.py`) ; routage et secours dans
  `assistant/engines.py`, un moteur par rôle (`config.ROLES`) ; agents
  d'exécution des missions externes possibles : `chatgpt` (Codex CLI, `assistant/codex.py`) et
  `mistral` (Vibe CLI, `assistant/mistral.py`), toujours avec les seuls outils MCP de Spectre ;
  noms des sous-agents dans `assistant/config.py` (`AGENT_NAMES` : Gétro, Kaïto, Kyra, Syfer) ; toute
  action passe par `tools.execute` (portail + audit). Entreprises, organigramme, tableau de
  tâches et pilotage des missions : `assistant/company.py` (tables dans `db.SCHEMA`) ; le
  moteur de missions (`missions.py`) lance jusqu'à `mission_parallel` missions à la fois.
  Automatisation : `routines.py` (horaires en mots → `cron:`/`every:`/`once:`, exécutées par
  `Proactive.tick`), `webhooks.py` (`/hooks/<nom>`, signature obligatoire, payload = données)
  et `telegram.py` (long polling, conversations jumelées seulement). Suivi SaaS : `saas.py`
  (sources en lecture seule, clés dans le `.env` de Spectre via `write_env_value`, métriques
  historisées, KPI dérivés, alertes, rapport ; collecte depuis `Proactive.tick`).
  Apprentissage : `learning.py` (compétences proposées puis validées, `skills/<nom>/SKILL.md`,
  curateur, `search_history` sur l'index FTS5 `events_fts`, points de restauration des
  missions via le journal d'annulation). Conseil d'administration : `board.py` (missions
  `board`/`board_review`, avis des postes, arbitrage, réévaluation) et `experiments.py`
  (verdict avant/après sans modèle, réévaluées depuis `Proactive.tick`). Autonomie méritée :
  `trust.py` (dossier → apprenti/confirmé/expert, lu par `Gate.decide` et le pilote auto) ;
  l'agent en cours voyage via `runctx.py` (thread-local → env `SPECTRE_AGENT` du serveur MCP) ;
  coûts : `spend.py` (registre `usage_ledger`, par rôle/agent/département, face au MRR).
  Réunions : `meeting.py` (micro → STT local par morceaux de 30 s, son jamais gardé ;
  mission `meeting` → tâches au tableau, décisions au journal ; outil via kv `meeting_request`).
  Département technique : `devteam.py` (mission `code` : worktree + branche `spectre/…`, Claude
  Code aux outils restreints ou Codex workspace-write, tests + 1 réparation, commit sans push ;
  `open_pr` = action EXTERNAL validée).
  `voice/engines.py` et `winapi.py` sont exclus de la couverture (matériel).
- Aucun appel réseau dans les tests par défaut (`@pytest.mark.live` pour les vrais appels).
- Ne jamais lire, afficher ni committer une clé API ; `.env` est ignoré par git.
