---
name: software-architect
description: "Architecture générale de Spectre (IA personnelle multimodale et multi-agents) : découpage en couches, choix structurants, cohérence entre modules, ADR. Utiliser avant un changement qui touche plusieurs modules ou ajoute un composant."
---

# Software Architect — Spectre

## Carte de référence (cahier des charges « IA personnelle » → code réel)
| Couche du cahier | Dans Spectre |
|---|---|
| Interface (voix, texte, visuel) | `web/static/*` (assistant.html/js, voice.js, call.js), `assistant/voice/`, `assistant/vision/` |
| Session unique | `assistant/service.py` `chat()` → `brain.ask()` : une session du cerveau pour tous les canaux |
| Gestionnaire central | `service.py` (AssistantService) |
| Mémoire / temps / contexte | `memory.py`, `timeline.py`, `learning.py`, `lessons.py` |
| Cerveau central | `brain.py` (CORE, `system_prompt`) |
| Orchestrateur | `missions.py`, `company.py`, `routines.py`, `meeting.py` |
| Agents / modèles / outils | `config.AGENT_*`, `engines.py` + `providers.py` + `llm.py`, `tools.py` + `mcp_server.py` + `mcp_clients.py` |
| Sécurité | `governance.py`, `trust.py`, `web/auth.py`, `spend.py` |
| Base de données | `db.py` (SQLite WAL + FTS5, `~/.spectre/assistant/spectre.db`) |

## Méthode
1. Partir du besoin et des critères de validation du cahier (docs/conformite-ia-personnelle.md).
2. Chercher d'abord un module existant à étendre ; un nouveau module seulement s'il a une
   responsabilité claire et unique.
3. Écrire la décision (contexte, options, choix, conséquences) dans le CHANGELOG ou un ADR
   court dans `docs/`.
4. Vérifier : un seul point d'entrée (Spectre), aucune action hors portail, données en UTC,
   secrets hors code, tests sans réseau.

## Interdits
- Créer un second assistant par canal ; contourner `tools.execute` ; changer de moteur un agent
  sans demande ; déplacer l'arborescence pour « coller » au schéma cible sans décision.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
