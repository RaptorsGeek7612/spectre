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
- `docs/PDR-produit.md` — périmètre par version (v0.1 linéaire, pas de boucle de révision).
- Skills : `.claude/skills/spectre-conventions` (socle commun, à charger en premier), puis
  selon le rôle `spectre-builder`, `spectre-tester`, `spectre-devops`, `spectre-reviewer`.

## Commandes (Windows : `uv run`, pas d'activation de venv)
```shell
uv sync
uv run ruff format --check . ; uv run ruff check .
uv run mypy src                  # si Windows bloque mypy : uv run python -m mypy --no-native-parser src
uv run pytest -m "not live" --cov=spectre --cov-report=term-missing
uv run python -m spectre.web             # interface web (spectre-web.exe peut être bloqué par Windows)
uv run python -m spectre.assistant --voice   # assistant vocal (uv sync --extra voice)

# Partie Foundry
forge fmt --check ; forge build ; forge test
```

## Règles essentielles
- Le produit s'appelle **Spectre**. IDs de modèles uniquement dans `src/spectre/config.py`.
- Jamais de `temperature`/`top_p`/`top_k` vers Sonnet 5.5 / Opus 5.5 : régler l'effort.
  Haiku 4.5 : `temperature` OK, pas d'effort. `max_tokens`, pas de prefill, pas de `budget_tokens`.
- Assistant : modèles en alias Claude Code (`haiku`, `sonnet`, `opus`), jamais d'ID ; toute
  action passe par `tools.execute` (portail + audit). `voice/engines.py` et `winapi.py` sont
  exclus de la couverture (matériel).
- Aucun appel réseau dans les tests par défaut (`@pytest.mark.live` pour les vrais appels).
- Ne jamais lire, afficher ni committer une clé API ; `.env` est ignoré par git.
