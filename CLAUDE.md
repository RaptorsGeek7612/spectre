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
- Skills (pipeline de dev) : `.claude/skills/spectre-conventions` (socle commun, à charger en
  premier), puis selon le rôle `spectre-builder`, `spectre-tester`, `spectre-devops`, `spectre-reviewer`.
- Skill (assistant, mémoire & relation) : `spectre-memoire` — comment Spectre apprend à connaître
  l'utilisateur, s'adapte via la couche `persona` et pose des questions avec tact. À charger dès
  que Spectre converse ou manipule la mémoire.
- Skills (savoirs & création) : `spectre-savoirs` (maths, sciences, physique, biologie,
  astronomie — rigueur, vérification, niveaux de certitude ; l'astrologie n'est pas une science)
  et `spectre-creation` (romans, films, clips, manga — métier narratif/visuel, sans plagiat ;
  œuvres-repères dans `references.md`).
- Skill (divertissement) : `spectre-astrologie` — astrologie comme fait culturel/ludique,
  jamais comme science ni base de décision.
- Skills (caractère & relation) : `spectre-personnalite` (style inspiré de JARVIS : curieux,
  entreprenant, mais **propose et attend un oui** avant toute initiative), `spectre-amitie`
  (amitié, loyauté, respect, sans remplacer les proches) et `spectre-developpement-humain`
  (corps et psychologie de la naissance au grand âge, sans diagnostic).
- Skill (culture) : `spectre-culture` — musique, cinéma, séries, littérature, animation et
  mangas ; recommander selon les goûts, sans divulgâcher, en vérifiant ce qui est récent.
- Ces skills servent aussi au **cerveau de Spectre** : `assistant/competences.py` les liste dans
  son prompt système (hors skills de développement) et l'outil `competence(name)` en lit une.
- Skills (capacités labo, conteneurs Docker à `C:\Users\sherp\labs`) : `labs-biometrie`
  (visage/voix/empreintes), `labs-securite` (suite Kali — cibles autorisées uniquement),
  `labs-media` (FFmpeg/OpenCV/MoviePy). Usage apprentissage/labo.
  **Chargement automatique** : dès qu'une mission touche la biométrie (visage/voix/empreinte),
  la sécurité réseau/web (autorisée) ou le multimédia (image/vidéo/montage), charger d'office
  le skill `labs-*` correspondant **avant d'agir**, sans attendre de demande explicite.

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
- Assistant : modèles en alias Claude Code (`haiku`, `sonnet`, `opus`), jamais d'ID ; agents
  d'exécution des missions externes possibles : `chatgpt` (Codex CLI, `assistant/codex.py`) et
  `mistral` (Vibe CLI, `assistant/mistral.py`), toujours avec les seuls outils MCP de Spectre ;
  noms des sous-agents dans `assistant/config.py` (`AGENT_NAMES` : Gétro, Kaïto, Kyra, Syfer) ; toute
  action passe par `tools.execute` (portail + audit). `voice/engines.py` et `winapi.py` sont
  exclus de la couverture (matériel).
- Aucun appel réseau dans les tests par défaut (`@pytest.mark.live` pour les vrais appels).
- Ne jamais lire, afficher ni committer une clé API ; `.env` est ignoré par git.
