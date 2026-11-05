---
name: model-routing
description: "Moteur de routage des modèles de Spectre : un moteur par rôle (cerveau, exécution, vérificateur, planificateur), un par agent, chaîne de secours, choix local/distant selon la puissance. Utiliser pour décider ou modifier quel modèle traite quoi."
---

# Model Routing — Spectre

## Existant
- Rôles `config.ROLES` ; `engines.assign`, `set_fallbacks`, `roles`, `summary` ; `/model` dans
  la conversation ; vue « Agents › Moteurs ».
- Agents hébergés et moteur par défaut : `HOSTED_AGENTS`, `AGENT_DEFAULT_ENGINES`
  (`spectre/config.py`) ; `agent_engines` pour déplacer un agent.

## Politique
1. Spectre (cerveau) décide du modèle ; l'utilisateur garde une seule interface.
2. Par défaut : chaque agent garde son LLM attribué ; changement **uniquement sur demande**.
3. Secours automatique sur erreur ou quota (`fallback_models`), annoncé à l'utilisateur.
4. Local d'abord pour ce qui est privé et court ; distant quand la puissance manque.
5. Coût et durée tracés par rôle (`spend.py`) pour justifier un changement.

## Tests
Router une référence inconnue → erreur claire ; secours déclenché seulement sur échec.

## Toujours
- Charger `spectre-conventions` d'abord ; doc d'une librairie = Context7, pas la mémoire.
- Respecter le portail (`tools.execute`) : aucune action hors gouvernance ni audit.
- Rapport final : fichiers touchés, commandes lancées et leur vrai résultat, écarts, points ouverts.
