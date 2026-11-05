---
name: agent-design
description: "Conception d'un agent de Spectre : rôle, spécialité (`SPECIALTIES`), compétences, outils autorisés, moteur par défaut, voix et portrait. Le nom est TOUJOURS donné par l'utilisateur. Utiliser pour créer ou revoir un agent."
---

# Agent Design — Spectre

## Fiche d'un agent
- Clé et nom (donné par l'utilisateur, jamais inventé), moteur par défaut
  (`AGENT_DEFAULT_ENGINES`), rôle d'organigramme.
- Spécialité dans `missions.SPECIALTIES[clé]` : métier, compétences à charger d'office,
  outils, limites légales/éthiques, format du compte rendu.
- Outils : liste minimale (`Tool.agents`), kits `toolkit` du métier, fiches `agent_tools`.
- Skill métier `.claude/skills/spectre-<métier>` (frontmatter `name` = dossier, description qui
  dit quand l'utiliser).

## Contrôle qualité
- Le prompt WORKER s'applique (logique métier, signaler plutôt que contourner).
- Test « câblage » (`test_new_agents_and_skills_are_wired`) mis à jour.
- Pas de droit de payer, s'inscrire, publier ou modifier ses permissions.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
