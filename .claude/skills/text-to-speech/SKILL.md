---
name: text-to-speech
description: "Synthèse vocale de Spectre : Piper local (voix `tts_voice`/`tts_speaker`, effet `tts_effect`, débit `tts_pace`), voix par agent, repli navigateur → Piper. Utiliser pour toute évolution de la voix parlée."
---

# Text to Speech — Spectre

## Existant
Piper côté serveur (modèles dans `~/.spectre/assistant/models/piper/`), effets `voice/fx.py`
(futuriste, vaisseau, aucun), voix par agent `agent_voices`. Côté navigateur `voice.js` retombe
sur Piper si la voix « naturelle » en ligne ne démarre pas sous 1 s.

## Règles
- La réponse affichée est celle prononcée (même texte, nettoyé du Markdown).
- Réponses vocales courtes ; lecture complète sur demande (« Lire en entier »).
- Coupure immédiate quand l'utilisateur parle.
- Alternative avancée (cahier : « Piper, puis alternative avancée ») : kokoro-tts est installé ;
  à évaluer avant de proposer, licence libre vérifiée.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
