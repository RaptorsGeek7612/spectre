---
name: system-design
description: "Conception détaillée d'un composant de Spectre : responsabilités, interfaces, flux de données, états, erreurs, concurrence (threads, process MCP). Utiliser pour dessiner un module avant de le coder."
---

# System Design — Spectre

## Livrable attendu (avant le code)
- Responsabilité en une phrase, entrées/sorties, dépendances autorisées.
- Machine à états si le composant a un cycle de vie (ex. missions : queued → running → done |
  failed | cancelled ; interrompue = `mission_interrupted` puis queued).
- Flux : qui appelle quoi, sur quel thread/process (le serveur MCP tourne dans un autre process
  et partage `spectre.db` : tout état partagé passe par la base, jamais par la mémoire Python).
- Erreurs : lesquelles sont attendues, comment elles remontent (`ActionError`, notifications).
- Données : tables, index, horodatage UTC (`db.now_iso`), migration idempotente
  (`CREATE TABLE IF NOT EXISTS`, `ALTER` gardé).
- Tests : contrat testé sans réseau, cas limites listés.

## Points de vigilance propres à Spectre
- Threads démons (`missions`, `routines`, `proactive`) : `stop()` propre, pas d'attente active.
- Windows : chemins, encodage UTF-8 explicite, sous-processus sans console.
- Budgets d'actions (60/min, 3000/j) et coûts (`spend.py`) à respecter.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
