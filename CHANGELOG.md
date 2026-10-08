# Changelog

Toutes les évolutions notables de ce projet sont documentées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet adhère au
[versionnage sémantique](https://semver.org/lang/fr/).

## [Unreleased]

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
