---
name: lm-studio-integration
description: "Connecte Spectre à LM Studio et à ses modèles locaux via son API compatible OpenAI (`lmstudio:<modèle>`), et recommande le bon modèle par agent (`local_models.py`). Utiliser pour brancher, choisir ou dépanner un modèle LM Studio."
---

# LM Studio Integration — Spectre

## Mission
Permettre l'utilisation des modèles locaux servis par LM Studio, sans clé, sans quitter le PC.

## Existant
- Référence `lmstudio:google/gemma-4-e4b` (serveur local LM Studio, port 1234, `/v1`).
- `local_models.py` : `ram_gb()`, `score()`, `ranking()`, `recommend(config, agent)`,
  `installed()` ; outil `set_agent_engine` pour appliquer (sur demande).

## Méthode
1. Vérifier que le serveur LM Studio est démarré (`GET /v1/models`).
2. Choisir selon le besoin de l'agent (`Need` : langue, outils, contexte) et la RAM libre.
3. Tester un tour avec outils ; mesurer la durée.
4. Proposer à l'utilisateur, appliquer seulement après son oui.

## Pièges
Modèle non chargé = erreur 404/400 : le dire clairement. Contexte trop court pour le prompt
système de Spectre : préférer le rôle « secours » ou « vérificateur ».

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
