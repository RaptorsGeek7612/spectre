---
name: backup-recovery
description: "Définit les sauvegardes, la restauration, la continuité de service et la reprise après incident de Spectre (spectre.db, mémoire, réglages, portraits, clés). Utiliser avant une migration ou après un incident."
---

# Backup & Recovery — Spectre

## À sauvegarder
`~/.spectre/assistant/` : `spectre.db` (+ `-wal`), `config.json`, `sauvegardes/` (mémoire),
`outils-agents/`, `serveurs-mcp/`, portraits et clips, `.env` (à chiffrer : `age`).

## Méthode
- Copie cohérente de SQLite : `sqlite3 spectre.db ".backup 'dest.db'"` (ou API `backup` de
  Python), jamais une copie de fichier pendant l'écriture.
- Rotation : 7 quotidiennes, 4 hebdomadaires ; une copie hors PC chiffrée (choix de l'utilisateur).
- Restauration testée : base restaurée ouverte, `PRAGMA integrity_check` = ok, Spectre relancé.
- Reprise : missions remises en file (`recover`), routines rattrapées une fois.

## Critère du cahier
« Les données restent disponibles après redémarrage » : vérifié par test et par relance réelle.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
