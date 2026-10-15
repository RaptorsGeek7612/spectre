# Spectre — PDR Produit (Product Requirements Document)

> Version 0.1 · 2026-10-06

## 1. Problème

Faire produire un texte de qualité par un seul gros modèle coûte cher et ne
garantit pas de relecture. Enchaîner plusieurs modèles « à la main » est
fastidieux, non reproductible, et on ne sait pas combien chaque étape coûte.

## 2. Solution

Spectre : une commande (ou une fonction Python) qui fait passer une demande par
trois agents Claude spécialisés — **Scout** cadre, **Scribe** rédige, **Warden**
vérifie et corrige — et affiche le coût réel de chaque étape.

## 3. Utilisateurs cibles

| Persona | Besoin | Usage |
|---|---|---|
| Développeur Python | Intégrer un pipeline de rédaction fiable dans son code | `from spectre import run` |
| Créateur de contenu technique | Obtenir un texte relu à partir d'une consigne | CLI `spectre "..."` |
| Mainteneur du projet | Faire évoluer agents/modèles sans casser l'existant | Config centralisée, tests sans réseau |

## 4. Parcours utilisateur (v0.1)

```
$ spectre "Explique la relativité restreinte en trois paragraphes simples" --costs

<texte final validé par Warden>

Agent    Modèle              Entrée  Sortie   Coût
scout    claude-haiku-4-5       210     180   0.0011 $
scribe   claude-sonnet-5-5      420    1350   0.0144 $
warden   claude-opus-5-5       1600    1400   0.0344 $
Total                                         0.0499 $
```

## 5. Fonctionnalités et priorités

| Fonctionnalité | Version | Valeur |
|---|---|---|
| Pipeline Scout → Scribe → Warden | 0.1 | Cœur du produit |
| Suivi coût par agent | 0.1 | Transparence, maîtrise budget |
| CLI (`--costs`, `--json`, `--file`) | 0.1 | Utilisable sans écrire de code |
| Config des modèles par variables d'env | 0.1 | Changer de modèle sans toucher au code |
| Boucle de révision Warden → Scribe (max N tours) | 0.2 | Qualité accrue sur textes difficiles |
| Verdict structuré de Warden | 0.2 | Décision automatisable |
| Streaming de la sortie | 0.2 | Confort d'usage |
| Nœuds additionnels branchables | 0.3 | Extensibilité |
| Batch / prompt caching | 0.3 | Réduction des coûts |

## 6. Indicateurs de succès

- Un run complet sur une demande courante coûte **< 0,10 $**.
- **0** erreur API due à un paramètre invalide (testé en CI).
- Couverture de tests ≥ 90 %.
- Ajouter un 4ᵉ agent demande de modifier **≤ 3 fichiers**.

## 7. Hors objectifs

- Remplacer un rédacteur humain sur des sujets sensibles sans relecture.
- Supporter d'autres fournisseurs que Claude pour la chaîne de rédaction (Scout, Scribe,
  Warden). L'assistant, lui, choisit son moteur depuis la v0.7.0.

## 8. Feuille de route

| Jalon | Contenu | Sortie |
|---|---|---|
| v0.1.0 | MVP linéaire, coûts, CLI, CI | Livré le 2026-10-06 |
| v0.1.1 | Repli en cas de refus, signalement des troncatures, corrections d'audit | Livré le 2026-10-07 |
| v0.2.0 | Interface web `spectre-web` (inspirée de Hermes WebUI) : chaîne en direct, historique, préréglages, démo, mobile | Livré le 2026-10-08 |
| v0.3.0 | Assistant vocal Spectre (agent supérieur sur Opus 5.5) : voix locale, sphère HUD, actions gouvernées, mémoire, missions, reconnaissance des visages | Livré le 2026-10-08 |
| v0.3.x | Agents d'exécution Kyra (ChatGPT) et Syfer (Mistral), accès et voix depuis le téléphone (Tailscale) | Livré le 2026-10-09 |
| v0.4.0 | Boucle de révision, verdict structuré, streaming de la CLI | Livré le 2026-10-09 |
| v0.5.0 | Nœuds extensibles (`spectre-agents.toml`), batch (API Message Batches), caching, évaluation | Livré le 2026-10-09 |
| v0.6.x | Agents créés, lanceur et surveillance, amitié, salutations, outil PowerShell | Livré du 2026-10-10 au 2026-10-11 |
| v0.7.0 | Moteurs : n'importe quel LLM par rôle (fournisseur:modèle, LM Studio, Ollama, OpenRouter…), `/model`, moteurs de secours (voir `docs/analyse-hermes.md`) | PR #40 (2026-10-14) |
| v0.8.0 | Équipe d'entreprise : entreprises, organigramme de 8 départements, tableau de tâches durable (dépendances, à valider), découpage d'objectif, pilote automatique, missions en parallèle, orienter et arrêter une mission | PR #41 (2026-10-14) |
| v0.9.0 | Automatisation : routines planifiées (horaires en mots), webhooks entrants signés (GitHub, Stripe, HMAC), passerelle Telegram jumelée, messages entre agents | PR #42 (2026-10-14) |
| v0.10.0 | Suivi SaaS : Stripe, Supabase, disponibilité, GitHub CI, API JSON (erreurs...), saisie ; tableau de bord MRR/ARR/churn/ARPA/LTV/CAC ; alertes ; rapport hebdomadaire | PR #43 (2026-10-14) |
| v0.11.0 | Apprentissage : compétences proposées après les missions (validées par l'utilisateur), curateur, recherche plein texte dans les conversations, points de restauration des missions | PR #44 (2026-10-14) |
| v0.12.0 | Au-delà de Hermes (1/5) : conseil d'administration (avis des départements, arbitrage, note de décision), journal des décisions réévaluées avec les vrais chiffres, expériences mesurées | En cours |
| v0.13.0 | Autonomie méritée par agent (dossier de fiabilité, validations allégées ou retirées) ; coût de l'IA face au revenu | Prévu |
| v0.14.0 | Mode réunion local : écoute, transcription, résumé, tâches et décisions | Prévu |
| v0.15.0 | Département technique : worktree, tests, PR validée | Prévu |
| v0.16.0 | Notifications natives (Web Push), briefing vocal par entreprise, suivi crypto en lecture seule | Prévu |
