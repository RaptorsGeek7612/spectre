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
- Skill (passion de l'utilisateur) : `spectre-crypto` — minage, blockchains, NFT, services crypto
  et trading ; sujet prioritaire, données de marché vérifiées en direct, jamais de phrase de
  récupération ni de clé, aucune transaction sans un oui, pas de promesse de gain.
- Skills (langage) : `spectre-langage` (français parlé par âge : argot Gen Alpha/Z, verlan,
  emprunts, réseaux, plus âgés ; varier ses répliques ; saluer selon l'heure, une fois par jour)
  et `spectre-langage-anglais` (Londres MLE/UK, États-Unis Gen Z/Alpha, Canada/Toronto, faux
  amis) ; comprendre tout, employer peu, jamais de caricature.
- Skill (entreprise) : `spectre-entrepreneur` — dès que l'utilisateur veut créer un SaaS ou une
  entreprise, Spectre parle en chef d'entreprise (marché, offre, prix, MRR/churn/CAC/LTV,
  mise sur le marché, juridique France à vérifier, prochaines étapes).
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
- Assistant : moteurs en références (`assistant/providers.py`) : alias Claude Code (`haiku`,
  `sonnet`, `opus`, jamais d'ID), `chatgpt`, `mistral` ou `fournisseur:modèle` (tout point
  d'accès compatible OpenAI, `assistant/llm.py`) ; routage et secours dans
  `assistant/engines.py`, un moteur par rôle (`config.ROLES`) ; agents
  d'exécution des missions externes possibles : `chatgpt` (Codex CLI, `assistant/codex.py`) et
  `mistral` (Vibe CLI, `assistant/mistral.py`), toujours avec les seuls outils MCP de Spectre ;
  noms des sous-agents dans `assistant/config.py` (`AGENT_NAMES` : Gétro, Kaïto, Kyra, Syfer,
  Octavya, Clarke, Simon) ; toute
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
  `open_pr` = action EXTERNAL validée). Notifications : `webpush.py` (RFC 8291 + VAPID avec
  `cryptography`, clé dans le `.env`) ; briefing par entreprise : `brief.py` ; crypto en lecture
  seule : sources `btc_wallet`/`eth_wallet`/`crypto_price` de `saas.py` (adresses publiques).
  Agents sur outil : `cursor` (Octavya), `antigravity` (Clarke, une femme) dans `cli_agents.py` ;
  Simon (`simon`) travaille sur un modèle hébergé (`AGENT_DEFAULT_ENGINES` de `spectre/config.py`,
  DeepSeek) ; `agent_engines` déplace un agent sur un autre moteur. Équipe : `team.py`
  (moteur, modèle, voix, apparence, photo) ; visio : `call.py` (statuts et répliques depuis la
  table `activity`, sans modèle) et `sessions.py` (sessions Claude Code/Codex/Vibe en lecture
  seule) ; Laya : `laya.py`, outil `laya_decide` réservé à Spectre (`Tool.lead_only`).
  Boîte à outils par métier : `toolkit.py` (outils libres CLI via `toolkit`, calculs via
  `finance`, réservés par `Tool.agents`/`Kit.agents` ; scan local = READ, scan distant = ASK).
  Studio de Kyra : `media.py` (ComfyUI local, `generate_image`/`generate_video` réservés à
  Kyra via `Tool.agents`, tâches `media_jobs` relevées par `Proactive.media`).
  Licence GPL-3.0-or-later.
  `voice/engines.py` et `winapi.py` sont exclus de la couverture (matériel).
- Aucun appel réseau dans les tests par défaut (`@pytest.mark.live` pour les vrais appels).
- Ne jamais lire, afficher ni committer une clé API ; `.env` est ignoré par git.
