---
name: database-architect
description: "Architecture des données de Spectre (SQLite WAL + FTS5 aujourd'hui, PostgreSQL + pgvector en cible possible) : schémas, index, migrations, intégrité, horodatage UTC. Utiliser pour toute nouvelle table ou requête lourde."
---

# Database Architect — Spectre

## Existant
- Un fichier `~/.spectre/assistant/spectre.db`, SQLite en WAL, partagé entre le service et le
  process MCP (`db.py`). Tables clés : `events` (journal immuable, `ts` UTC, `data` JSON avec
  `channel`), `facts` (+ `facts_fts`), `missions`, `approvals`, `audit`, `routines`, `reminders`,
  `kv`, `tasks`, `task_events`.
- Recherche plein texte FTS5 (`events_fts`, `facts_fts`, tokenizer `unicode61 remove_diacritics 2`).

## Règles
- Horodatage : toujours `now_iso()` (UTC, secondes). Conversion en fuseau IANA seulement à
  l'affichage (`timeline.py`).
- Migrations idempotentes dans `SCHEMA` ; jamais de perte : on ajoute des colonnes, on ne supprime pas.
- Requêtes paramétrées uniquement (`?`) ; colonnes dynamiques seulement depuis une liste fixe
  (`# noqa: S608` justifié).
- Index pour chaque filtre fréquent ; vérifier avec `EXPLAIN QUERY PLAN`.
- Une écriture = une transaction courte (contention WAL entre process).

## PostgreSQL / pgvector (cible du cahier)
Pas de migration sans décision de l'utilisateur. Si elle est décidée : couche d'accès unique,
schéma porté table par table, `timestamptz`, `pgvector` pour les embeddings, tests sur les deux
moteurs pendant la transition, sauvegarde avant bascule (`backup-recovery`).

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
