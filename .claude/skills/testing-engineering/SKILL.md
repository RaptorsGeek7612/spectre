---
name: testing-engineering
description: "Conçoit et exécute les tests de Spectre : unitaires, intégration, système, sécurité et performance (pytest, faux CLI/modèles, sans réseau, couverture ≥ 90 % en CI). Utiliser pour écrire ou réparer des tests."
---

# Testing Engineering — Spectre

## Cadre
- `uv run --no-sync pytest -m "not live" -q` ; CI : `--cov=spectre --cov-fail-under=90`.
- Faux : `tests/test_assistant_brain.FakeCLI`, base temporaire `Database(tmp_path / "spectre.db")`,
  fixture autouse `close_databases`. Réseau interdit hors `@pytest.mark.live`.
- Matériel hors couverture : `voice/engines.py`, `winapi.py`.

## Méthode
1. Tester le contrat (cahier, spec), pas l'implémentation.
2. Un test par critère de validation du cahier « IA personnelle » (voix puis texte = une
   conversation, reconnexion après plusieurs jours, mission interrompue, agent non autorisé
   refusé, données présentes après redémarrage).
3. Cas d'erreur et limites systématiques ; dates fixes et fuseau explicite.
4. Un test qui échoue pour un bug réel ne se masque pas : bug rapporté (fichier:ligne).

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
