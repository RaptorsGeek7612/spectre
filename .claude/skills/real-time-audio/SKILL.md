---
name: real-time-audio
description: "Audio temps réel de Spectre : boucle voix (écoute → cerveau → parole), latence, barge-in, visio avec les agents (`call.py`), Orbe réactive à la voix. Utiliser pour la fluidité de la conversation vocale."
---

# Real-time Audio — Spectre

## Budget de latence visé
Fin de parole → début de réponse < 2 s hors réflexion du modèle : détection de fin de phrase,
transcription, envoi, première phrase synthétisée dès qu'elle est prête.

## Règles
- Flux découpés en phrases ; synthèse de la phrase 1 pendant que la suite arrive.
- Interruption : arrêt de la lecture en < 200 ms, l'énoncé interrompu est noté dans le même fil.
- Visio : animation « talk » seulement quand l'agent parle, photo fixe sinon.
- Orbe : `setLevel` suit le niveau audio, `prefers-reduced-motion` respecté.
- Mesurer avec horodatages (`perf_counter`) et consigner les durées.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
