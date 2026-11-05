---
name: typescript-engineering
description: "Code front de Spectre côté navigateur. Le cahier vise TypeScript ; l'existant est en JavaScript (modules ES dans web/static) et l'extension Chrome. Utiliser pour écrire du JS/TS sûr et typé (JSDoc + `// @ts-check` aujourd'hui)."
---

# TypeScript Engineering — Spectre

## Aujourd'hui (sans étape de build)
- `web/static/*.js` servis tels quels ; ajouter `// @ts-check` et des types JSDoc aux fichiers
  touchés pour profiter de la vérification de VS Code sans toolchain.
- Pas de dépendance npm dans le front servi ; pas de CDN (tout local, open source).
- DOM : `textContent`, jamais `innerHTML` avec une donnée non maîtrisée.
- `fetch` vers `/api/...` avec l'en-tête `X-Spectre: 1`, gestion d'erreur visible.

## Si une migration vers TypeScript est décidée
`tsc --strict`, sortie compilée dans `web/static/dist`, sources dans `frontend/`, build dans la
CI, aucune régression des tests navigateur (Playwright). Décision de l'utilisateur d'abord.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
