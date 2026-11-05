---
name: application-security
description: "Sécurité applicative de Spectre : entrées non fiables, sous-processus, chemins, téléversements, web (CSRF, en-têtes, Host), dépendances, scans (gitleaks, semgrep, trivy, ZAP local). Utiliser à chaque changement de code exposé."
---

# Application Security — Spectre

## Contrôles à chaque changement
- Entrées validées (type, taille, liste blanche) ; chemins résolus et confinés
  (`allowed_roots`), pas de `..`.
- Sous-processus : liste d'arguments, pas de shell, délai ; `agent_tools` sans interpréteur.
- Web : Host de confiance (421), Origin + `X-Spectre`, cookies HttpOnly/SameSite, en-têtes CSP,
  COOP, CORP, Permissions-Policy, Server sans version.
- Fichiers téléversés : taille max, type vérifié, stockés hors web, jamais exécutés.

## Scans (outils libres, sur le PC)
`gitleaks detect`, `semgrep --config auto src`, `trivy fs .`, ZAP baseline Docker (passif
seulement : un scan actif déclencherait « mot de passe oublié »). Résultats classés, faux
positifs justifiés.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
