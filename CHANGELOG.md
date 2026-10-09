# Changelog

Toutes les évolutions notables de ce projet sont documentées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet adhère au
[versionnage sémantique](https://semver.org/lang/fr/).

## [Unreleased]

## [0.5.0] - 2026-10-09

### Added

- `spectre batch FICHIER` : plusieurs demandes d'un coup. Par défaut via l'API Message Batches
  (50 % moins cher, asynchrone) avec un lot par étape pour toutes les demandes, reprise
  automatique après une interruption (état enregistré après chaque étape) ; `--direct` les
  traite tout de suite une par une. Résultats en JSON Lines.
- `spectre eval CAS` : évaluation sur des cas de test, contrôles automatiques (mots, termes
  présents ou absents, validation par Warden, coût maximal) et, avec `--judge`, critères notés
  par un juge ; rapport, `--json`, code de sortie 1 si un cas échoue, `--demo` sans clé.
- Agents branchables sans code : `spectre-agents.toml` (ou `SPECTRE_AGENTS_FILE`) ajoute des
  agents après Scout, Scribe ou Warden, qui lisent et réécrivent un texte de la chaîne.
- Mise en cache des prompts (`SPECTRE_PROMPT_CACHE`, désactivée par défaut) : la partie que
  Scribe et Warden relisent à chaque tour de révision est marquée pour le cache.
- Coûts : tokens lus et écrits en cache comptés au bon prix (lecture 0,10 à 0,20 $/M, écriture
  1,25 × l'entrée), remise de 50 % des lots, colonnes « Cache » dans `--costs` quand il sert.
- Exemples : `examples/spectre-agents.example.toml`, `demandes.example.txt`,
  `cas.example.jsonl`.

### Changed

- Les nœuds sont génériques (`spectre.steps.Step` + `nodes.make_node`) : ce que lit et écrit
  chaque agent est décrit une seule fois et partagé par le graphe et le mode lots.

## [0.4.0] - 2026-10-09

### Added

- Verdict de Warden : après son texte corrigé, Warden écrit `=== VERDICT ===` et un objet
  JSON `{"approved": ..., "issues": [...]}` (`spectre.verdict`). Un verdict absent ou illisible
  vaut approbation : le texte n'est jamais perdu.
- Boucle de révision : si Warden rejette le texte, Scribe le réécrit avec la liste des points à
  changer, puis Warden relit de nouveau, dans la limite de `SPECTRE_MAX_REVISIONS` tours (1 par
  défaut, de 0 à 5). `run(..., max_revisions=)` et `build_graph(..., max_revisions=)`.
- `SpectreResult.approved`, `.issues` et `.revisions`, aussi dans `--json`. Un avertissement
  sur stderr signale un texte non validé après le dernier tour.
- CLI : `--stream` affiche en direct sur stderr le travail de chaque agent, tours de révision
  compris (sans la ligne du verdict) ; `--revisions N`.
- Interface web : les tours de révision s'affichent (Scribe et Warden repartent d'un texte
  vide, avec un message), les coûts additionnent tous les tours et la ligne du verdict n'est
  jamais diffusée.

## [0.3.8] - 2026-10-09

### Fixed

- Barre de la page Assistant sur téléphone : avec le bouton caméra, le micro n'était plus au
  centre (six boutons). La caméra passe à gauche du micro et le bouclier des validations, déjà
  présent dans l'en-tête, quitte la barre : cinq boutons, micro au centre.

## [0.3.7] - 2026-10-09

### Added

- Voix depuis le téléphone : sur la page Assistant ouverte depuis un autre appareil, le bouton
  micro enregistre avec le micro de cet appareil (arrêt automatique après une pause, 25 s au
  plus), Spectre transcrit et répond, et sa voix est jouée sur l'appareil, pas sur le PC.
  Nouvelle route `POST /api/assistant/voice` (PCM 16 kHz mono 16 bits, réponse avec le texte
  entendu, la réponse et un WAV).
- Caméra du téléphone : bouton dans la barre de la page Assistant (depuis un autre appareil,
  quand la reconnaissance des visages est active) ; une image toutes les 2 s, analysée comme
  celles de la caméra du PC, avec un aperçu visible ; arrêt au second appui ou en quittant la
  page. Route `POST /api/assistant/frame` (JPEG), `FaceEngine.embeddings_jpeg()`, verrou sur
  le moteur de visages. Aucune image n'est gardée.
- `tools\spectre-assistant.ps1 --silent` : démarrage avec la session Windows (raccourci dans le
  dossier Démarrage), sans ouvrir de page ; il attend jusqu'à 90 s que Tailscale soit connecté
  pour que le téléphone y ait accès dès l'ouverture de session.
- `PiperTTS.render()` produit la voix sans la jouer ; la reconnaissance et la synthèse sont
  protégées par un verrou, car le micro du PC et le téléphone peuvent parler en même temps.

## [0.3.6] - 2026-10-09

### Added

- Accès depuis le téléphone, de partout, par Tailscale : quand Tailscale est installé et qu'un
  mot de passe est défini, `tools\spectre-assistant.cmd` publie Spectre en HTTPS sur le réseau
  privé (`tailscale serve`) sans rien ouvrir sur Internet. Le délai est limité : si Serve n'est
  pas encore activé, Spectre démarre en local seulement.
- `--allow-host NOM` (`spectre-assistant`) : nom d'hôte accepté derrière un relais, en plus de
  localhost ; un mot de passe est alors obligatoire.
- `tools\spectre-password.cmd` choisit le mot de passe de l'interface (variable utilisateur
  `SPECTRE_WEBUI_PASSWORD`), sans l'écrire dans le dépôt.

### Fixed

- Page Rédaction sur téléphone : le bouton micro flottant ne recouvre plus le contenu (il est
  masqué ; l'icône de l'en-tête mène déjà à l'assistant, et ce bouton faisait écouter le PC, pas
  le téléphone) ; le préréglage « Qualité max » n'est plus coupé quand la place le permet.
- Le bouton « Exposer » ne dépasse plus de l'écran sur les téléphones étroits ou avec un texte
  agrandi : le menu des préréglages se resserre à sa place, et sous 380 px la flèche disparaît.
- Un seul micro sur téléphone : celui de l'en-tête (vers l'assistant) ; le bouton de dictée est
  masqué sous 900 px, le clavier du téléphone ayant déjà le sien.

## [0.3.5] - 2026-10-09

### Added

- Deux nouveaux agents d'exécution des missions : **ChatGPT** via Codex CLI (`codex exec`, compte
  ChatGPT) et **Mistral** via Mistral Vibe (`vibe -p`, compte Le Chat ou `MISTRAL_API_KEY`). Ils
  reçoivent les outils de Spectre par MCP (même portail de gouvernance) et la recherche web.
- Réglage `mission_model` : `chatgpt` et `mistral` en plus de `sonnet`, `opus` et `haiku` ;
  `chatgpt_model`, `mistral_model`, `codex_bin` et `vibe_bin`. Pour une seule mission,
  `start_mission` accepte `agent=claude|chatgpt|mistral`, et chaque étape note quel agent l'a faite.
- Spécialités : ChatGPT pour les images, la vidéo et le multimédia ; Mistral pour la cybersécurité
  et les tests d'intrusion (cadre autorisé uniquement). Spectre choisit l'agent selon le sujet.
- Les sous-agents ont un nom : Gétro (Sonnet), Kaïto (Haiku, le vérificateur), Kyra (ChatGPT) et
  Syfer (Mistral). `start_mission` accepte le nom (sans tenir compte des majuscules ni des
  accents) ; les étapes, les rapports et l'interface affichent qui a fait quoi.

### Fixed

- Changer l'agent d'exécution dans les réglages s'applique tout de suite, sans relancer Spectre.

## [0.3.4] - 2026-10-09

### Added

- Sélecteur « Rédaction | Assistant » sous le logo, dans les deux pages, pour passer de l'une à
  l'autre ; sur téléphone, une icône dans l'en-tête fait la même chose.
- `tools/spectre-stop.cmd` arrête l'assistant.

### Changed

- `tools/spectre-assistant.cmd` démarre Spectre en arrière-plan, sans fenêtre de console : fermer
  une fenêtre ou un Ctrl+C ne l'interrompt plus par accident ; s'il tourne déjà, le lanceur ouvre
  simplement l'interface.

## [0.3.3] - 2026-10-09

### Added

- Bouton « Parler à Spectre » sur la page d'accueil, visible quand l'assistant tourne : un clic le
  fait écouter sans le mot d'éveil ; son anneau suit l'état de la voix et le niveau sonore.
- Lanceur Windows `tools/spectre-assistant.cmd` (double-clic) : fenêtre dédiée, journal dans
  `~/.spectre/assistant/spectre.log`.

### Fixed

- L'assistant ne s'interrompt plus brutalement (« forrtl: error (200) ») sur un événement de la
  console : le lanceur désactive le gestionnaire du runtime Intel Fortran des bibliothèques vocales.
- Téléphone : le lien « Assistant » du menu ne déborde plus de l'écran.

## [0.3.2] - 2026-10-09

### Changed

- Timbre futuriste plus clair : la doublure à l'octave inférieure et la copie décalée vers le grave
  (le « fond sombre » derrière la voix) sont retirées ; l'harmonique aiguë, le côté métallique et
  la réverbération restent.

## [0.3.1] - 2026-10-09

### Changed

- Nouveau logo : un casque corinthien de Spartiate en trois-quarts, crête de crin aux sept
  couleurs de Spectre, capteur à la tempe et pistes de circuit gravées (logo complet animé sur
  l'accueil, la connexion et la présence de l'assistant ; version simplifiée dans le menu, dont
  les bandes de Scout, Scribe et Warden suivent toujours le pipeline ; favicon et icônes PNG).
  `tools/make_logo.py` remplace `tools/make_icons.py`.
- Voix de l'assistant plus fluide : débit réglable (posé, naturel, vif ; naturel par défaut),
  rythme plus régulier et phrases enchaînées avec une courte respiration.

## [0.3.0] - 2026-10-08

### Added

- Assistant vocal `spectre-assistant` (ou `python -m spectre.assistant`), qui répond au nom de
  Spectre. Spectre est l'agent supérieur, sur Opus 5.5 via Claude Code `claude -p` et
  l'abonnement : il converse, planifie les missions et en rédige les rapports ; les étapes vont
  aux agents d'exécution (Sonnet 5.5), la vérification à Haiku 4.5, la rédaction soignée à
  Scout, Scribe et Warden. Identifiants exacts dans `config.ASSISTANT_MODELS`.
- Voix locale (extra `voice`) : mot d'éveil « Spectre » (Vosk), transcription faster-whisper
  `small` avec vocabulaire d'applis, synthèse Piper (voix d'homme « pierre ») avec un timbre
  d'IA de bord (futuriste, androïde vocodé, hologramme, vaisseau), mots d'arrêt et relance sans
  mot d'éveil. Choix automatique d'un vrai micro (jamais « Mixage stéréo »).
- Sphère vocale façon HUD à la place du dialogue : anneau de particules qui réagit au niveau
  sonore réel, SPECTRE qui s'assemble en particules au réveil, sous-titres, indicateurs, dock.
- Serveur MCP de 20 outils : heure, système, écrans, mémoire, ouverture d'applis et de pages
  (sur l'écran choisi), fichiers (lister, lire, chercher, écrire, déplacer, supprimer, annuler),
  rappels, missions, présence.
- Portail de gouvernance (risque × politique × budget), validations dans l'interface et journal
  d'audit immuable. Écritures journalisées et annulables, corbeille propre à Spectre.
- Mémoire qui apprend (SQLite FTS5, renforcement, remplacement, oubli, correction, miroir
  Markdown), consolidation nocturne, briefing du matin, rappels, missions vérifiées avec rapport.
- Reconnaissance des visages optionnelle (extra `vision`, `--camera`) : OpenCV Zoo YuNet (MIT)
  + SFace (Apache 2.0) + anti-fraude MiniFASNet (Apache 2.0) en local, modèles vérifiés par
  SHA-256 ; enregistrement volontaire, empreintes seulement (aucune photo), accueil au retour,
  présence dans le HUD, outil `who_is_there`.
- La limite d'usage de l'abonnement est annoncée en français avec l'heure de réinitialisation.
- Page `assistant.html` dans l'univers des raies d'émission, liée depuis l'interface principale.

### Changed

- Feuille de route : la boucle de révision et le streaming de la CLI passent en v0.4.0, les
  nœuds extensibles, le batch, le caching et l'évaluation en v0.5.0.

## [0.2.0] - 2026-10-08

### Added

- Interface web `spectre-web` (ou `python -m spectre.web`) : serveur de la bibliothèque standard
  et page HTML/CSS/JS sans build, inspirée de Hermes WebUI. Chaîne des agents en direct (SSE)
  dessinée comme des raies d'émission, onglet Corrections (diff brouillon → texte final),
  inspecteur des tokens et coûts, historique de plaques numérotées (recherche, tags, projets,
  épingles, archives, export Markdown/JSON/HTML, import), préréglages d'agents, mode démo,
  dictée vocale, commandes `/`, palette `Ctrl+K`, thèmes sombre/clair, français/anglais,
  notifications, PWA, mise en page ordinateur/tablette/téléphone.
- Mot de passe facultatif (`SPECTRE_WEBUI_PASSWORD`, cookie signé, limitation des essais),
  obligatoire pour ouvrir l'interface au réseau local (`--host 0.0.0.0`).
- Logo de Spectre : un fantôme formé de sept raies spectrales, généré par `tools/make_icons.py`.
- Préréglages d'agents intégrés (`WEB_PRESETS` dans `config.py`).

## [0.1.1] - 2026-10-07

### Added

- Repli côté serveur en cas de refus de Sonnet 5.5 ou d'Opus 5.5 (`fallbacks: "default"`),
  désactivable avec `SPECTRE_FALLBACKS=0`. `usage` enregistre le modèle qui a réellement
  répondu, et le coût est calculé à son tarif (prix ajoutés pour Opus 4.8, Opus 5, Sonnet 5).
- Champ `truncated` dans chaque ligne de `usage`, à `true` si la limite `max_tokens` est atteinte.
- La CLI renvoie le code `130` avec le message « Interrompu. » sur Ctrl+C, au lieu d'une trace.

### Fixed

- Les tests hors ligne ignorent toutes les variables `ANTHROPIC_*` du shell
  (`ANTHROPIC_WORKSPACE_ID` faisait échouer un test).
- `SPECTRE_TIMEOUT` et `SPECTRE_MAX_RETRIES` sont documentés dans le README et `.env.example`.
- Scout ne termine plus son brief par une question à l'utilisateur : le brief part directement
  au rédacteur (constaté lors d'un essai réel).

### Security

- Actions GitHub de la CI épinglées par SHA de commit.

## [0.1.0] - 2026-10-06

Première version de **Spectre**, construite sur le dépôt
[`template-foundry`](https://github.com/RaptorsGeek7612/template-foundry), dont le contrat
Solidity `Voting` (Foundry) est conservé à côté du package Python. L'historique des versions
0.1.x du template n'est pas repris ici.

### Added

- Pipeline LangGraph linéaire `Scout → Scribe → Warden` à état typé (`SpectreState`) :
  - **Scout** (`claude-haiku-4-5`) produit un brief (intention, public, contraintes, plan) ;
  - **Scribe** (`claude-sonnet-5-5`, effort `medium`) rédige le texte complet ;
  - **Warden** (`claude-opus-5-5`, effort `high`) vérifie et renvoie la version corrigée.
- Registre de modèles centralisé (`spectre/config.py`), surchargeable par variables
  d'environnement `SPECTRE_<AGENT>_MODEL`, `SPECTRE_<AGENT>_MAX_TOKENS`, `SPECTRE_<AGENT>_EFFORT`.
- Limite de sortie de 16 000 tokens pour Scribe et Warden, dont la réflexion (toujours active)
  consomme une partie ; délai d'attente HTTP de 600 s par défaut (`SPECTRE_TIMEOUT`).
- Prise en charge des clés liées à un utilisateur (`sk-ant-usr...`) via `ANTHROPIC_WORKSPACE_ID`.
- Suivi des tokens et du coût en dollars par agent et au total (`usage`, `total_cost_usd`).
- Erreurs explicites nommant l'agent en cas de refus du modèle ou de sortie vide.
- API bibliothèque : `from spectre import run, build_graph`, avec injection de modèles pour
  tester sans réseau.
- CLI `spectre` avec `--file`, `--costs`, `--json` et `--version`.
- Tests pytest sans appel réseau (faux modèles LangChain), tests réels marqués `live`.
- `CLAUDE.md` et skills des agents de développement (`.claude/skills/spectre-*`).
- Documentation : cahier des charges, PDR produit, PDR architecture, brainstorming.
- Dependabot pour l'écosystème `uv` (dépendances Python).

- Job CI `python` : `uv sync --frozen`, `ruff format --check`, `ruff check`, `mypy src` et
  `pytest` (couverture ≥ 90 %), à côté du job Foundry `test`.
- Badge de couverture Python (`coverage-python.json`), publié sur la branche `badges` avec le
  badge Foundry (`coverage.json`).

### Changed

- Contrat `Voting` passé en **Solidity 0.8.35** (`solc_version = "0.8.35"` dans `foundry.toml`,
  `pragma solidity ^0.8.35;`).
- La release automatique attend désormais les deux jobs de test (`test` Foundry et `python`).
- `.env.example` : ajout de `ANTHROPIC_API_KEY` et des surcharges `SPECTRE_*` aux variables
  Sepolia existantes.
- README, CONTRIBUTING, SECURITY, exemples, templates d'issue et de PR mis à jour pour le dépôt
  hybride Spectre + Foundry.
