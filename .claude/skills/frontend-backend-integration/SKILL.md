---
name: frontend-backend-integration
description: "Liaison interface ↔ serveur de Spectre : API JSON, flux d'événements temps réel (cible WebSocket du cahier), synchronisation voix/texte/visuel dans une seule conversation. Utiliser pour tout échange navigateur-serveur."
---

# Frontend-Backend Integration — Spectre

## Contrat de conversation unique
- Côté serveur : `service.chat(text, channel)` publie `{"type": "message", "role", "text",
  "channel"}` ; la voix (`chat(..., channel="voice")`) et le texte passent par le même `brain.ask`.
- Côté client : un seul fil ; l'étiquette de canal est un détail d'affichage.
- Une image jointe est rattachée au message en cours (`pieces-jointes`), donc à la même conversation.

## Temps réel
Le flux d'événements actuel est la référence. Pour passer en WebSocket : mêmes messages JSON,
reconnexion automatique avec reprise depuis le dernier identifiant reçu, authentification au
handshake (cookie + Origin), messages bornés en taille.

## Tests
Un test qui envoie un message voix puis un texte et vérifie un seul fil et une seule session.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
