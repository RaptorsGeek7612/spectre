---
name: identity-secrets-access
description: "Gère les identités, l'authentification, les autorisations, les secrets et les accès aux ressources de Spectre (mot de passe web, sessions, jetons d'extension, clés API, jetons MCP). Utiliser pour tout ce qui authentifie ou stocke un secret."
---

# Identity, Secrets & Access — Spectre

## Existant
- Web : `SPECTRE_WEBUI_PASSWORD` (env Utilisateur Windows), sessions signées par `secret.key`,
  « mot de passe oublié » (code 8 chiffres, 10 min, 5 essais, envoyé hors page).
- Clés API : `~/.spectre/assistant/.env` (hors dépôt), écrites par `write_env_value`.
- MCP : `${NOM}` dans les fiches, jamais la valeur ; extension Chrome : `browser-token`.
- Téléphone : Tailscale (adresse jamais dans le dépôt public).

## Règles
- Jamais lire, afficher, journaliser ni committer un secret ; vérifier un JWT par son champ
  `aud` sans l'afficher.
- Jeton au moindre privilège (GitHub fine-grained, lecture d'abord), date d'expiration notée.
- Rotation : changer `secret.key` ferme toutes les sessions.
- Comparaison de secrets à temps constant (`hmac.compare_digest`).

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
