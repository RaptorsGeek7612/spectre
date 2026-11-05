---
name: fastapi-backend
description: "Serveur HTTP et API de Spectre. Le cahier vise FastAPI ; Spectre utilise aujourd'hui `http.server` (stdlib). Utiliser pour toute évolution du serveur, ou pour étudier/mener une migration vers FastAPI."
---

# FastAPI Backend — Spectre

## État
`web/server.py` = `ThreadingHTTPServer` + `Handler` maison, sans dépendance. Il fonctionne, il
est couvert par `tests/test_web.py`, et ses protections (Host 421, Origin, `X-Spectre`, en-têtes
de sécurité vérifiés par ZAP) sont à conserver.

## Si une migration vers FastAPI est décidée par l'utilisateur
1. Context7 sur FastAPI/Starlette/Uvicorn (versions actuelles) avant d'écrire.
2. Routes portées une par une, mêmes contrats JSON, mêmes codes d'erreur.
3. Middleware : hôtes de confiance (421), Origin, CSRF, en-têtes de sécurité identiques.
4. WebSocket pour le flux d'événements (voir `frontend-backend-integration`).
5. Les deux serveurs coexistent derrière un réglage jusqu'à parité des tests, puis bascule.
6. Nouvelle dépendance : bornes dans `pyproject.toml`, `uv lock`, licence libre vérifiée.

## Sans migration
Appliquer les mêmes principes au serveur actuel : validation des entrées, réponses JSON, pas de
logique métier dans le handler (elle va dans `service.py`).

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
