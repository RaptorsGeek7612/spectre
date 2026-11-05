---
name: speech-to-text
description: "Reconnaissance vocale de Spectre : faster-whisper local (`stt_model`), mot d'éveil, choix du micro, transcription des réunions et des vidéos. Utiliser pour modifier l'écoute."
---

# Speech to Text — Spectre

## Existant
`voice/listen.py`, `voice/loop.py`, `voice/engines.py` (hors couverture : matériel) ; réglages
`stt_model` (small/medium/large-v3-turbo), `mic_device`, `wake_word`. Réunions (`meeting.py`)
et vidéos sans sous-titres (`videos.py`) passent aussi par Whisper. Tout reste sur le PC.

## Règles
- Langue forcée au français sauf demande ; ponctuation conservée.
- Un énoncé vocal entre dans la même conversation que le texte (`chat(channel="voice")`).
- Silence/bruit : ne rien envoyer au cerveau sous un seuil de confiance.
- Barge-in : la parole de l'utilisateur coupe la synthèse, sans créer de nouveau fil.
- Tests : la logique (seuils, découpe) est testée avec de faux segments, sans micro.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
