---
name: llm-evaluation-cost
description: "Évaluation de la qualité et du coût des modèles dans Spectre : jeux de cas (`spectre eval`), métriques, coût par rôle/agent rapporté au revenu. Utiliser avant de changer de modèle ou pour un rapport de coûts."
---

# LLM Evaluation & Cost — Spectre

## Outils
- `uv run spectre eval cas.jsonl --demo` (`evaluation.py`) : cas → verdict.
- `spend.py` : jetons, coût, durée par moteur et rôle ; `costs.py` : prix du pipeline Claude.
- Tableau coûts/MRR (v0.13) pour l'entreprise.

## Méthode
1. Au moins 10 cas représentatifs (français, outils, mémoire, refus attendus).
2. Critères : exactitude, respect des règles (oui avant action), langue, durée, coût.
3. Comparer deux moteurs sur les mêmes cas ; garder les sorties brutes.
4. Recommandation chiffrée ; l'utilisateur décide.

## Interdits
Pas d'appel réseau dans la CI (`@pytest.mark.live`) ; pas de chiffre de prix inventé : relire
la page officielle et la dater.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
