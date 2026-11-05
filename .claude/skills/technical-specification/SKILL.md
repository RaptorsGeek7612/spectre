---
name: technical-specification
description: "Rédige une spécification technique vérifiable pour une fonctionnalité de Spectre : objectif, périmètre, exigences numérotées, critères d'acceptation testables, risques. Utiliser avant un développement de plus d'une journée."
---

# Technical Specification — Spectre

## Gabarit
1. **Contexte** : le besoin de l'utilisateur, en ses mots.
2. **Périmètre** : dedans / dehors (et pourquoi).
3. **Exigences** : F1…Fn fonctionnelles, NF1…NFn (sécurité, perfs, coûts, Windows, open source).
4. **Conception** : modules touchés, tables, outils du portail (niveau READ…CRITICAL, catégorie),
   prompts modifiés.
5. **Critères d'acceptation** : chacun testable (test pytest nommé ou vérification manuelle décrite).
6. **Risques et repli** : ce qui peut casser, comment revenir en arrière.
7. **Version** : entrée CHANGELOG prévue.

## Règles
- Une exigence = une phrase, mesurable. Pas de « rapide », mais « < 2 s sur ce PC ».
- Citer les critères du cahier « IA personnelle » quand ils s'appliquent (voix/texte même
  conversation, reprise de mission, chronologie après plusieurs jours…).
- Tout ce qui paie, s'inscrit ou publie : validation explicite de l'utilisateur, écrit dans la spec.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
