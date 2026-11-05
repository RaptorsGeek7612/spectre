---
name: api-architect
description: "Conception des API HTTP de Spectre (`web/server.py`, `web/assistant_api.py`) : routes REST, flux d'événements, contrats JSON, erreurs, versionnement, sécurité. Utiliser pour ajouter ou modifier une route."
---

# API Architect — Spectre

## Existant
- Serveur `http.server` (`ThreadingHTTPServer`, `web/server.py`), routes `/api/...` dans
  `assistant_api.py`, statiques dans `web/static`. Flux temps réel vers l'interface par
  événements publiés (`service.publish`).
- Auth : `web/auth.py` (mot de passe, cookie de session, en-tête `X-Spectre: 1`, contrôle
  `Origin`/`Host` — un hôte inconnu reçoit 421, protection voulue).

## Règles de conception
- Nom de ressource au pluriel, verbe HTTP juste (GET lecture sans effet de bord).
- Corps JSON validé (types, tailles max) avant tout traitement ; erreurs `{"error": "..."}` en
  français, code HTTP exact (400, 401, 403, 404, 409, 413, 421, 429).
- Toute action côté serveur passe par le portail, pas d'appel direct à `actions.py`.
- Pas de secret dans une réponse ni dans une URL ; pas de chemin absolu renvoyé sans besoin.
- Taille des téléversements bornée ; fichier reçu = non fiable (voir `application-security`).

## Tests
`tests/test_web.py` : client HTTP local, sans réseau externe ; un test par code d'erreur.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
