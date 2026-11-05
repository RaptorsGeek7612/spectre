---
name: react-frontend
description: "Interface graphique de Spectre (assistant.html, Orbe, Équipe, Kanban, visio, téléphone). Le cahier vise React ; l'existant est en JS natif. Utiliser pour toute évolution d'interface ou pour préparer une migration vers React."
---

# React Frontend — Spectre

## Existant à respecter
`assistant.html` + `assistant.js` (conversation), `orb.js` (Orbe riche : garder cette version),
`team.js`/`avatars.js`/`call.js` (équipe, visio), `voice.js` (voix navigateur + repli Piper),
`codeview.js`, `sw.js` + manifeste (PWA téléphone). `DESIGN.md` = système de design.

## Règles UI
- Un seul fil de conversation affiché, quel que soit le canal (voix, texte, image).
- Réponse affichée ET prononçable ; une interruption vocale ne crée pas un second fil.
- Accessibilité : contrastes, focus visible, `prefers-reduced-motion`, libellés ARIA.
- Vérifier au navigateur (Playwright MCP) avant de livrer : capture, console sans erreur.

## Migration React (seulement sur décision)
Vite + React + TypeScript dans `frontend/`, build vers `web/static/app/`, écran par écran, mêmes
API ; l'Orbe reste un canvas encapsulé dans un composant.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
