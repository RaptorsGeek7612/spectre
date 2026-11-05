---
name: memory-retrieval
description: "Retrouver la bonne information au bon moment dans Spectre : recherche plein texte (FTS5), faits par pertinence, historique des conversations et missions (`search_history`), cible RAG/pgvector. Utiliser pour améliorer le rappel."
---

# Memory Retrieval — Spectre

## Existant
`facts_fts`, `events_fts` (`learning.py`), outil `search_history`, `recall` de la mémoire.
Tokenizer sans accents (`remove_diacritics 2`) : « été » trouve « ete ».

## Méthode
1. Requête FTS5 échappée (guillemets autour des termes saisis), pas de concaténation SQL.
2. Classement : correspondance, puis récence, puis confiance.
3. Résultat court cité avec sa date (fuseau de l'utilisateur via `timeline`).
4. Recherche sémantique (embeddings) seulement si FTS5 échoue sur des cas mesurés ; alors
   modèle d'embedding local libre, index séparé, évaluation avant/après.

## Tests
Jeu de requêtes → identifiants attendus ; aucune régression sur les accents.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
