---
name: temporal-awareness
description: "Gestion du temps de Spectre : date/heure/jour/fuseau IANA donnés par le système, dernière connexion, temps écoulé, état des missions au retour, durées. Utiliser pour tout ce qui dépend de l'heure ou de la chronologie."
---

# Temporal Awareness — Spectre

## Existant
`assistant/timeline.py` : `now(zone)`, `spoken_date`, `elapsed`, `visit` (une visite = suite
d'énoncés sans trou de plus de 30 min, tous canaux), `block` (section du prompt système :
maintenant, conversation précédente et écart, missions en cours / interrompues / terminées /
échouées depuis, routines programmées). Réglage `timezone` (IANA, défaut `Europe/Paris`).

## Règles non négociables
- Le modèle ne devine jamais la date : elle vient de l'horloge système à chaque tour.
- Stockage en UTC (`now_iso`), affichage dans le fuseau de l'utilisateur.
- Distinguer : conversation ancienne / nouvelle, mission en cours / terminée / interrompue
  (`mission_interrupted`) / programmée.
- Durée d'une mission = `updated_at - ts`.

## Critère de validation
« Reconnexion après plusieurs jours » : test `tests/test_assistant_timeline.py` (lundi 14 h →
mercredi 10 h, écart annoncé).

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
