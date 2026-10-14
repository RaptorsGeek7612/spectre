# Hermes Agent face à Spectre : analyse et feuille de route

Analyse du 2026-10-14. Objectif fixé par l'utilisateur : donner à Spectre les capacités de
Hermes Agent (Nous Research) sur les agents et le choix du LLM, plus tout ce qu'il faut à un
système d'agents pour gérer une entreprise, jusqu'au suivi complet d'un SaaS.

## Version analysée

Il n'existe pas de « Hermes Agent 2.0 » : le projet est numéroté en 0.x. La dernière version
stable confirmée est la **v0.21.7** (11 octobre 2026). Le guide de référence de Blake Crosley
annonce une **v0.22.0 « Threshold »** (13 octobre 2026), qu'aucune seconde source ne confirme
encore. L'analyse couvre l'ère v0.20 « Herald » à v0.22.

Sources : la documentation officielle (hermes-agent.nousresearch.com/docs), le guide
blakecrosley.com/guides/hermes et releasebot.io (notes de version).

## Ce que fait Hermes, et où en est Spectre

| Domaine | Hermes Agent | Spectre avant la v0.7 | Spectre v0.7.0 et suite |
|---|---|---|---|
| Choix du LLM | 39 fournisseurs, `/model` à chaud (session, `--global`, `--once`), alias, local llama.cpp/Ollama/LM Studio | Claude via la CLI, ChatGPT (Codex), Mistral (Vibe) seulement | **v0.7.0** : tout point d'accès compatible OpenAI (`fournisseur:modèle`), LM Studio et Ollama en local, `/model`, outils `set_model`/`list_models` |
| Modèle par tâche | `auxiliary.<tâche>` (vision, compression, review, approval…) | Cerveau et exécution seulement | **v0.7.0** : rôles cerveau, exécution, vérificateur, planificateur |
| Secours | Chaîne `fallback_providers`, par tour, sensible aux limites | Repli Claude côté serveur (refus) | **v0.7.0** : `fallback_models` par appel (erreur ou limite d'abonnement) |
| Sous-agents | `delegate_task` en parallèle (10), profondeur, schéma de sortie, pilotage en direct (`steer`/`stop`) | Missions séquentielles, un exécutant par étape, vérification Kaïto | **v0.8.0** : missions en parallèle (1 à 4), orienter (`steer_mission`) et arrêter (`stop_mission`) une mission en cours |
| Agents nommés | Profils et Bots (rôle, modèle, mémoire, compétences, voix), salons de 2 à 6 bots, `message_agent` | Agents créés (nom donné par l'utilisateur, moteur, rôle) | v0.7.0 : moteur au choix pour chaque agent créé ; **v0.8.0** : postes dans l'organigramme d'une entreprise ; **v0.9.0** : `ask_agent` (question à un autre agent) |
| Tableau de tâches | Kanban durable (SQLite), dispatcher, blocage humain, multi-entreprise | Liste des missions | **v0.8.0** : un tableau par entreprise (dépendances, priorités, « à valider »), découpage d'objectif, pilote automatique |
| Tâches planifiées | `cronjob_manage`, langage naturel, modèle par tâche, livraison, reprise après panne | Briefing, rappels, consolidation, visites amicales | **v0.9.0** : routines (horaires en mots ou cron ; mission, question ou rappel ; une seule reprise après panne ; alerte après 3 échecs) |
| Messagerie | 28 plateformes (Telegram, WhatsApp, Slack, e-mail…) | Web, voix, téléphone (Tailscale) | **v0.9.0** : Telegram (jumelage par code, validations depuis Telegram) ; e-mail plus tard |
| Webhooks et A2A | Webhooks signés (GitHub, Stripe…), protocole A2A v1.0 | Aucun | **v0.9.0** : webhooks signés GitHub, Stripe et HMAC (filtres, anti-doublon, prévenir ou lancer une mission) ; A2A plus tard |
| Mémoire | MEMORY.md/USER.md, recherche plein texte des sessions, fournisseurs externes | Mémoire structurée (faits, persona), consolidation nocturne | v0.11.0 : recherche plein texte des conversations |
| Compétences | Auto-création après une tâche, hub, curateur (obsolètes → archive) | Compétences écrites à la main, lues par l'outil `competence` | v0.11.0 : compétences proposées après une mission, validées par toi |
| Sécurité | Approbations intelligentes, liste noire, conteneurs, points de restauration | Portail de gouvernance (niveaux, catégories, budget, audit), corbeille et annulation | Déjà solide ; v0.11.0 : points de restauration |
| Voix | STT/TTS multi-fournisseurs, barge-in, mot d'éveil | Voix locale, mot d'éveil, téléphone | Déjà au niveau |

## Gestion d'entreprise et suivi d'un SaaS (au-delà de Hermes)

Hermes donne les briques (Kanban multi-entreprise, routines, webhooks, connecteurs Linear,
Notion, Stripe en MCP) mais pas de direction d'entreprise intégrée. Le plan pour Spectre :

- **v0.8.0 Équipe** : un organigramme d'agents (direction, finance, marketing, ventes, support,
  produit et technique, juridique et conformité). Les noms restent toujours donnés par
  l'utilisateur. S'y ajoutent un tableau de tâches durable, la délégation en parallèle et le
  pilotage d'une mission en cours.
- **v0.9.0 Automatisation** : routines planifiées (« chaque lundi à 9 h, point des ventes »),
  webhooks entrants signés (Stripe, GitHub), passerelle Telegram, messages entre agents.
- **v0.10.0 Suivi SaaS** :
  - connecteurs en lecture seule : Stripe (MRR, churn, paiements échoués), Supabase
    (inscriptions, santé de la base), disponibilité et latence, erreurs, intégration continue ;
  - tableau de bord des indicateurs (MRR, churn, CAC, LTV) ;
  - alertes et rapport hebdomadaire au « conseil d'administration ».

  Toute action externe (paiement, envoi, publication) passe toujours par ta validation.
- **v0.11.0 Apprentissage** : compétences proposées après les missions, curateur, recherche
  dans les conversations, points de restauration.

## v0.7.0 « Moteurs » en pratique

- Une référence de moteur s'écrit `opus`, `sonnet`, `haiku`, `chatgpt`, `mistral` ou
  `fournisseur:modèle`. Exemples : `lmstudio:google/gemma-4-e4b`, `ollama:qwen3:8b`,
  `openrouter:deepseek/deepseek-chat`, `groq:llama-3.3-70b-versatile`.
- Les fournisseurs intégrés sont LM Studio et Ollama (locaux, sans clé), OpenRouter, Groq,
  Gemini, Mistral (API), DeepSeek, OpenAI, xAI et Anthropic (API). Pour en ajouter un, crée
  `providers.json` dans le dossier de Spectre :
  `[{"id": "...", "base_url": "https://.../v1", "key_env": "MA_CLE"}]`.
- Les clés ne sont jamais écrites dans la configuration. Spectre les lit dans l'environnement
  ou dans `~/.spectre/assistant/.env` (`GROQ_API_KEY=...`), hors du dépôt.
- Tu changes de moteur de trois façons :
  - dans la conversation, avec `/model` (montre tout), `/model <moteur>` (le cerveau),
    `/model <rôle> <moteur>` ou `/model secours <a>, <b>` ;
  - dans la vue « Agents », section « Moteurs » ;
  - en demandant à Spectre, qui utilise ses outils `list_models`, `set_model` et
    `set_fallbacks`.
- Un moteur autre que Claude reçoit le fil récent de la conversation (12 derniers échanges). Ses
  appels d'outils passent par le même portail de gouvernance et le même audit.
- Mesure faite sur ce PC : un modèle de 4 milliards de paramètres dans LM Studio, sur le
  processeur, met de 2 à 5 minutes par tour avec les outils. Il fait un bon moteur de secours,
  pas un cerveau de conversation. Pour la vitesse, mieux vaut un service en ligne (Groq,
  Gemini, OpenRouter, dont certains ont une offre gratuite) ou une carte graphique.
