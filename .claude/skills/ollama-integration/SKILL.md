---
name: ollama-integration
description: "Modèles locaux Ollama dans Spectre (`ollama:<modèle>`, API locale compatible OpenAI). Utiliser pour brancher, tester ou recommander un modèle Ollama."
---

# Ollama Integration — Spectre

## Branchement
Référence `ollama:qwen3:8b` (fournisseur intégré, sans clé, `http://127.0.0.1:11434/v1`).
Vérifier que le serveur répond (`/api/tags`) avant de proposer un modèle.

## Réalité de ce PC
CPU seul : un 4B met 2 à 5 min par tour avec outils ; `qwen3:4b` installé = appoint seulement
(lent, répond souvent en anglais). Bon usage : secours, tâches hors ligne courtes, résumés.

## Règles
- Ne change le moteur d'un agent que sur demande de l'utilisateur (`set_agent_engine`).
- Préciser la langue dans le prompt système pour les petits modèles.
- Mesurer (durée, qualité) sur 3 cas avant de recommander.
- Mises à jour de modèles = téléchargements lourds : proposer, attendre le oui.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
