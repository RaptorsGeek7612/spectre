# Spectre — fiche projet

Spectre est un orchestrateur multi-agents **100 % Claude** en Python : Scout (`claude-haiku-4-5`)
→ Scribe (`claude-sonnet-5-5`) → Warden (`claude-opus-5-5`), orchestré par LangGraph via
`langchain-anthropic`. Package dans `src/spectre/`, CLI `spectre`.

Dépôt **hybride** : il conserve la partie **Foundry** du template (`src/Voting.sol`,
`test/Voting.t.sol`, `script/Voting.s.sol`, `lib/`, `foundry.toml`, `foundry.lock`,
`remappings.txt`, `.gitmodules`, Solidity 0.8.35). **Ne jamais supprimer ces fichiers** ; la CI
les vérifie (job `test`).

## À lire avant de travailler
- `docs/cahier-des-charges.md`, `docs/PDR-architecture.md` (arborescence, signatures, tests, CI),
  `docs/PDR-produit.md` (périmètre par version), `CHANGELOG.md` (historique détaillé).
- Skills du **pipeline de dev** : charger `spectre-conventions` en premier, puis `spectre-builder`,
  `spectre-tester`, `spectre-devops`, `spectre-reviewer` selon le rôle.

## Skills du cerveau de Spectre (`.claude/skills/*`)
`assistant/competences.py` les liste dans le prompt système (hors skills de dev) ; l'outil
`competence(name)` en lit une. Les principaux : `spectre-memoire` (relation, couche persona, pose
des questions avec tact), `spectre-personnalite` (style JARVIS : **propose et attend un oui**
avant toute initiative), `spectre-amitie`, `spectre-developpement-humain` (sans diagnostic),
`spectre-savoirs` (sciences, rigueur ; l'astrologie n'est pas une science), `spectre-creation`
(romans/films/clips/manga, sans plagiat), `spectre-culture`, `spectre-astrologie` (fait culturel),
`spectre-crypto` (**sujet prioritaire** : jamais de clé/phrase, aucune transaction sans un oui, pas
de promesse de gain), `spectre-langage` / `spectre-langage-anglais` (comprendre tout, employer peu),
`spectre-entrepreneur` (parler en chef d'entreprise), `spectre-animaux` (vers vétérinaire pour la
santé), `spectre-jeux-argent` (risques, jeu responsable, crypto ; experte Lexy :
`spectre-strategies-casino`, `spectre-strategies-paris`, `spectre-strategies-financieres`),
`spectre-pub-communication` (Kyra : brief, cadres de rédaction, formats réseaux, droit de la
pub), `spectre-production-audiovisuelle` (Kyra : clips, séries, films, de l'idée à la livraison),
`spectre-post-production-libre` et `spectre-diffusion-marketing` (Kyra : contournements libres
de ce qui ne s'installe pas ici), `spectre-design` (Kyra designer, sur le modèle de Claude Design : cadrage,
système de design, anti-« AI slop », variantes, réglages, vérification par capture ; outils
toolkit `maquette_png`/`maquette_pdf`/`vectoriel`), `spectre-trading` (Simon : histoire, styles, risque,
formation, fiscalité ; outils `marche` et `trading`), `spectre-nature-climat` (Shelby :
biodiversité, climat air/terre/mer ; outil `nature`, module `nature.py`), `spectre-contrats`
et `spectre-contrats-europe-international` (Octavya : tous les contrats, France, UE,
international ; outil `contrat`, module `contracts.py`), `spectre-management` (Spectre :
diriger une équipe en TPE, PME, ETI ou grand groupe, et sa propre équipe d'agents),
`spectre-administration` et `spectre-administration-europe-international` (Spectre : toutes
les administrations, France, UE, international ; outil `administration`, module
`administration.py`),
`spectre-pentest` (Syfer : tous les types de tests d'intrusion, cadre légal strict ; outils
toolkit nmap/subfinder/httpx/trufflehog), `spectre-amelioration` (s'améliorer, lui et ses
agents : toujours le plus sûr, stable et fiable, vérifié avant de proposer). Skills **labo** (Docker à `C:\Users\sherp\labs`) : `labs-biometrie`, `labs-securite` (cibles autorisées), `labs-media` — à
charger **d'office** dès qu'une mission touche biométrie, sécu réseau/web autorisée ou multimédia.

## Commandes (Windows : `uv run`, pas d'activation de venv)
```shell
uv run ruff format --check . ; uv run ruff check .
uv run mypy src                  # si Windows bloque mypy : uv run python -m mypy --no-native-parser src
uv run pytest -m "not live" --cov=spectre --cov-report=term-missing
uv run python -m spectre.assistant --voice   # assistant (uv sync --extra voice --extra vision)
uv run python -m spectre.web ; uv run spectre batch demandes.txt ; uv run spectre eval cas.jsonl --demo
forge fmt --check ; forge build ; forge test   # partie Foundry
```

## Règles essentielles
- Le produit s'appelle **Spectre**. IDs de modèles uniquement dans `src/spectre/config.py`.
- Jamais de `temperature`/`top_p`/`top_k` vers Sonnet 5.5 / Opus 5.5 : régler l'effort. Haiku 4.5 :
  `temperature` OK, pas d'effort. `max_tokens`, pas de prefill, pas de `budget_tokens`.
- **Portail** : toute action de l'assistant passe par `tools.execute` (gouvernance + audit) ;
  niveaux READ/UI/WRITE/DESTRUCTIVE/EXTERNAL/CRITICAL. Un outil peut être réservé à des agents
  (`Tool.agents`) ou à Spectre (`Tool.lead_only`).
- **Moteurs** (`assistant/providers.py`) : alias Claude Code (`haiku`/`sonnet`/`opus`, jamais d'ID),
  `chatgpt` (Codex, `codex.py`), `mistral` (Vibe, `mistral.py`), `cursor`/`antigravity` (CLI,
  `cli_agents.py`), ou `fournisseur:modèle` (OpenAI-compatible, `llm.py`) ; routage + secours dans
  `engines.py`, un moteur par rôle (`config.ROLES`). Agents dans `config.AGENT_*` : hébergés
  (`HOSTED_AGENTS`, moteur par défaut dans `AGENT_DEFAULT_ENGINES` de `spectre/config.py`) =
  Simon (DeepSeek), Shelby, Ysyss, Lexy (Claude Sonnet) ; `agent_engines` déplace un agent. Les
  CLI externes n'ont que les outils MCP de Spectre.
- **Carte des modules** (`assistant/`) : missions `missions.py` (prompt WORKER, `SPECIALTIES`,
  `mission_parallel`) ; entreprises/tâches `company.py` ; automatisation `routines.py` +
  `webhooks.py` (signature obligatoire) + `telegram.py` ; suivi SaaS `saas.py` (clés via
  `write_env_value`) ; apprentissage `learning.py` (FTS5 `events_fts`) ; conseil `board.py` +
  `experiments.py` ; autonomie `trust.py` ; coûts `spend.py` ; agent courant `runctx.py` ; réunions
  `meeting.py` ; dev `devteam.py` (`open_pr` = EXTERNAL) ; notifications `webpush.py` ; briefing
  `brief.py` ; équipe `team.py` ; visio `call.py` (+ `activity`) ; sessions `sessions.py` ; Laya
  `laya.py` ; outils par métier `toolkit.py` (`toolkit`/`finance`/`science`/`paris`, scan local =
  READ, distant = ASK) ; studio de Kyra `media.py` (ComfyUI, `generate_image`/`generate_video`) ; outils ajoutés aux
  agents par Spectre `agent_tools.py` (fiches JSON, jamais de code) ; pièces jointes
  `spectre/attachments.py` (conversation : `workspace/pieces-jointes`, Rédaction : texte extrait) ;
  leçons tirées des erreurs `lessons.py` (aide de Spectre à un agent bloqué : `HELPER` de
  `missions.py`) ; mises à jour hebdomadaires des outils `updates.py` ; paiements préparés
  `payments.py` (QR SEPA ou page marchand, l'utilisateur paie ; catégorie `payment` = ASK) ;
  mémoire `memory.py` (150 faits / 45 000 car. dans le prompt, `compact` la nuit : sauvegarde,
  fusions vérifiées, rien d'effacé, règles et confidences verrouillées, `restore`).
  `voice/engines.py` et `winapi.py` hors couverture (matériel).
- **Logique métier** : les agents respectent toujours les règles de logique métier du projet en
  construction (contraintes, invariants, validations, enchaînement) ; en cas de doute ils le
  signalent plutôt que de contourner (prompt WORKER de `missions.py`).
- Aucun appel réseau dans les tests par défaut (`@pytest.mark.live` pour les vrais appels).
- Ne jamais lire, afficher ni committer une clé API ; `.env` est ignoré par git.
- Licence **GPL-3.0-or-later**.
