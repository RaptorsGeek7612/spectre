# Spectre face au cahier des charges « IA personnelle » (v1.0)

Vérification du 2026-11-05. Légende : ✅ conforme · 🟡 partiel ou autre choix technique · ❌ absent.

## Partie 1 — Architecture

| Exigence | État | Où |
|---|---|---|
| Voix, texte et visuel dans **un seul** système conversationnel | ✅ | `service.chat(text, channel)` → `brain.ask` : une session du cerveau pour tous les canaux ; le canal est noté sur chaque message (`events.data.channel`) |
| Gestionnaire central | ✅ | `assistant/service.py` |
| Cerveau central / orchestrateur | ✅ | `brain.py`, `missions.py`, `company.py` |
| Agents spécialisés, modèles LLM, outils MCP | ✅ | `config.AGENT_*`, `engines.py`, `mcp_server.py`, `mcp_clients.py` |
| Système de sécurité | ✅ | `governance.py`, `trust.py`, `web/auth.py` |
| Base de données | 🟡 | SQLite WAL + FTS5 (`db.py`) au lieu de PostgreSQL : un seul PC, zéro service à gérer. Migration possible (skill `database-architect`), sur décision |

## 1.3 — Temps

| Exigence | État | Où |
|---|---|---|
| Date, heure, jour, mois, année, fuseau (IANA) | ✅ | `timeline.block` / `turn_note`, réglage `timezone` |
| Horodatage UTC | ✅ | `db.now_iso` |
| Date de chaque conversation, dernière connexion, temps écoulé | ✅ | `timeline.visit` (visite = pas de trou de plus de 30 min) |
| Durée de chaque mission | ✅ | `updated_at - ts`, donnée au retour |
| Ancienne / nouvelle conversation ; mission en cours, terminée, interrompue, programmée | ✅ | `timeline._missions`, `mission_interrupted`, routines |
| Jamais de date inventée par le modèle | ✅ | horloge système donnée **à chaque tour** (la session reprise garde son prompt du matin) |
| Tâches programmées (APScheduler ou équivalent) | ✅ | `routines.py`, rappels, tâches de nuit |

## 1.4 — Mémoire

| Niveau | État | Où |
|---|---|---|
| Immédiate | ✅ | session du jour, fil récent pour les autres moteurs |
| Long terme | ✅ | `facts` + FTS5, persona, compactage de nuit sans perte |
| Opérationnelle | ✅ | missions, tâches, routines, approbations, audit, comptes rendus d'outils (`mission_report`) |
| Recherche au bon moment | 🟡 | plein texte (FTS5) ; pas encore de recherche sémantique (pgvector) — à évaluer sur cas réels |

## Partie 2 — Priorités

| Fonctionnalité | État |
|---|---|
| P0 Cerveau, synchro voix/texte, temps, mémoire, authentification | ✅ |
| P1 STT (faster-whisper), TTS (Piper), interface, fichiers/images, LLM | ✅ |
| P2 Multi-agents, MCP, automatisations | ✅ |
| P3 Personnalisation, apprentissage par retours | ✅ (`learning.py`, `lessons.py`, `trust.py`) |
| Gestionnaire d'état des missions au retour | ✅ `timeline` + `mission_report` |

## Parties 3 et 4 — Skills et sous-agents Claude Code

- 40 skills de développement dans `.claude/skills/` (liste dans `competences.DEV_ONLY`, cachées
  au cerveau de Spectre) + les 5 skills du pipeline mises à jour.
- 10 sous-agents dans `.claude/agents/` (architecte en chef, backend, frontend, voix, LLM,
  mémoire, multi-agents, cybersécurité en lecture seule, DevOps, QA), périmètres disjoints
  (`spectre-conventions`, `.claude/rules/perimetres-agents.md`).

## Partie 5 — Connecteurs MCP

| Connecteur | État |
|---|---|
| GitHub | ✅ fiche `serveurs-mcp/github.json` (lecture auto, écriture validée) |
| Filesystem | ✅ outils natifs du portail (`allowed_roots`) |
| Browser | ✅ extension Chrome (`browser_pages`), WebSearch/WebFetch |
| Documentation | ✅ Context7 (côté développement) |
| PostgreSQL, Docker, Terminal | ❌ volontairement non activés (« pas tout immédiatement ») ; labos Docker via `lab_run` |

## Partie 6 — Sécurité

Les 10 principes : ✅ (détail dans la skill `security-architecture` et `.claude/rules/securite.md`).
Injection de prompt : 🟡 marquage des pages web et des comptes rendus d'outils comme données +
portail ; un corpus de tests d'injection reste à écrire (skill `prompt-injection-defense`).

## Partie 7 — Organisation du dépôt

🟡 Spectre garde son arborescence (`src/spectre/assistant`, `src/spectre/web`) : le cahier dit
lui-même de ne créer les dossiers qu'au besoin. Correspondance :

| Cible | Spectre |
|---|---|
| `.claude/skills, agents, rules, settings.json` | ✅ identiques |
| `backend/api, core, orchestrator, sessions, security` | `web/`, `assistant/service.py`, `missions.py`, `sessions.py`, `governance.py` |
| `frontend/interface, chat, voice, visual` | `web/static/` (assistant, voice.js, call.js, orb.js) |
| `ai_engine/llm, agents, memory, rag, model_router` | `engines.py`, `llm.py`, `missions.py`, `memory.py`, `learning.py` |
| `voice_engine/stt, tts, audio` | `assistant/voice/` |
| `database/`, `mcp/` | `db.py`, `mcp_server.py`, `mcp_clients.py` |
| `infrastructure/`, `tests/`, `documentation/` | `.github/`, `tools/`, `tests/`, `docs/` |
| `docker-compose.yml` | ❌ Spectre tourne nativement sous Windows (voix, caméra, fenêtres) ; labos Docker à part |
| `.env.example`, `CLAUDE.md`, `README.md` | ✅ |

## Partie 8 — Technologies

| Domaine | Cahier | Spectre |
|---|---|---|
| Backend / API | Python / FastAPI | Python / `http.server` (🟡) |
| Frontend | React + TypeScript | JS natif sans build (🟡) |
| Temps réel | WebSocket | Server-Sent Events (🟡, même rôle) |
| Base / vecteurs / cache | PostgreSQL / pgvector / Redis | SQLite + FTS5, threads (🟡) |
| Local, STT, TTS, agents, MCP, Git | Ollama, faster-whisper, Piper, Python, MCP, GitHub | ✅ (+ LM Studio) |

Ces écarts sont des choix assumés pour un PC unique sans GPU ; chacun a sa skill de migration.
Aucun ne se fait sans décision de l'utilisateur.

## Partie 9 — Critères de validation

| Critère | État | Preuve |
|---|---|---|
| Phrase commencée à la voix, complétée par écrit | ✅ | même `brain.ask` et même session |
| Réponse affichée et prononçable | ✅ | `service.chat` publie, `voice.js`/Piper |
| Interruption vocale sans 2ᵉ conversation | ✅ | barge-in dans la même session |
| Image rattachée à la bonne conversation | ✅ | `pieces-jointes`, message en cours |
| Reconnexion après plusieurs jours : bonne chronologie | ✅ | `tests/test_assistant_timeline.py` |
| Mission interrompue : état réel | ✅ | `recover`, `mission_interrupted` |
| Agent sans droit refusé | ✅ | portail, `Tool.allowed` (tests) |
| Données présentes après redémarrage | ✅ | SQLite, tests sur base rouverte |

## Partie 10 — Contrôle central

✅ Spectre est le seul point d'entrée : il choisit le modèle (`engines`), l'agent
(`start_mission`), les outils (portail), la mémoire, la validation (`governance`) et la reprise
(`recover`). Il relit le travail de ses agents (`mission_report`), voit ce que l'utilisateur ouvre
(`browser_pages`, `desktop_apps`), et chaque outil s'affiche en direct dans l'interface.

## Reste à faire (proposé, non lancé)

1. Corpus de tests d'injection de prompt.
2. Évaluer une recherche sémantique locale si FTS5 rate des cas réels.
3. Connecteurs PostgreSQL / Docker / Terminal : un par un, sur demande.
