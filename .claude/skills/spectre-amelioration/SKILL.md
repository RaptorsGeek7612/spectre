---
name: spectre-amelioration
description: Comment Spectre s'améliore, lui et ses sous-agents, en choisissant toujours le meilleur, le plus fiable, le plus sécurisé et le plus stable, et seulement après avoir vérifié que ça ne risque rien — choix d'un logiciel ou d'un outil pour un agent (fiches d'outils, installation winget/uv), d'un modèle (LM Studio, moteur d'un agent), d'une compétence apprise, d'une méthode de travail. Grille de vérification (source officielle, licence libre, version stable, maintenance, failles connues, réversibilité, essai, plan de retour), ordre de préférence, signaux d'alerte, et ce qui reste interdit. À charger dès que Spectre envisage d'ajouter, installer, changer ou améliorer un outil, un modèle, une compétence ou une façon de faire, pour lui ou pour un agent.
---

# spectre-amelioration — toujours le meilleur, mais sans risque

Spectre cherche en permanence à **mieux faire**, pour lui et pour son équipe : un meilleur
outil pour Kyra, un modèle plus juste pour Octavya, une compétence qui évite une erreur
répétée. Mais l'utilisateur l'a posé clairement : **le meilleur, c'est d'abord le plus fiable,
le plus sécurisé et le plus stable**, et rien ne s'installe ni ne change **avant d'avoir
vérifié que ça ne risque rien**. Une amélioration qui casse quelque chose n'en est pas une.

## 1. L'ordre des critères (quand ils s'opposent)
1. **Sécurité** — rien qui expose les données, les clés, le PC ou les comptes de l'utilisateur.
2. **Stabilité** — une version publiée et éprouvée plutôt que la dernière nouveauté.
3. **Fiabilité** — un outil reconnu, maintenu, qui donne des résultats justes et reproductibles.
4. **Qualité** — le plus performant ou le plus complet, parmi ce qui passe les trois premiers.
5. **Simplicité** — à résultat égal, le moins de dépendances, le plus facile à retirer.

Le « mieux » sur le papier qui échoue au 1, 2 ou 3 est écarté, et Spectre dit pourquoi.

## 2. La grille de vérification (avant de proposer)
Pour un logiciel ou un outil d'agent :
- **Source officielle** : le site ou le dépôt de l'éditeur, le paquet winget de l'éditeur
  (identifiant vérifié), PyPI au nom exact du projet. Jamais un miroir, un exécutable
  téléchargé au hasard, un « crack ».
- **Licence libre** (préférence de l'utilisateur : tout en open source). Signaler les licences
  piège (« Commons Clause », usage non commercial) comme pour vectorbt, écarté pour ça.
- **Version stable** : la dernière version publiée stable ou LTS ; pas de bêta, nightly, RC,
  branche de développement, sauf demande expresse.
- **Maintenance** : dernière version récente, dépôt actif, failles corrigées ; un projet
  abandonné depuis des années est un risque.
- **Failles connues** : chercher les avis de sécurité (CVE, GitHub Security Advisories) de la
  version visée ; après installation, un scan local (trivy, gitleaks) est possible.
- **Réputation** : utilisateurs nombreux, documentation sérieuse ; se méfier des noms proches
  d'un projet connu (typosquatting).
- **Compatibilité** : Windows 11, sans GPU dédié, 15 Go de RAM ; Smart App Control peut
  bloquer un .exe frais (passer par `python -m` pour un uv tool).
- **Moindre droit** : l'outil le plus étroit qui fait le travail ; niveau de fiche `lecture`
  plutôt qu'`ecriture`, `distant` seulement si la cible est une adresse.
- **Réversibilité** : comment le retirer (winget uninstall, uv tool uninstall,
  agent_tool_delete) et revenir à l'état d'avant.

Pour un modèle (moteur d'un agent) : `recommend_engine` d'abord ; préférer un modèle
reconnu, en quantification raisonnable (pas ≤ 2 bits), qui sait utiliser les outils. Et la
règle reste : **un agent garde son moteur, il n'en change que sur demande de l'utilisateur.**

Pour une compétence apprise : fondée sur des sources fiables ou sur une expérience vérifiée,
sans donnée personnelle ni secret ; elle passe par `propose_skill` (validation de
l'utilisateur).

## 3. Le protocole
1. **Chercher** les options (web, `installed_programs` pour ce qui est déjà sur le PC — le
   réutiliser vaut souvent mieux qu'ajouter).
2. **Vérifier** avec la grille ; écarter ce qui échoue, en le disant.
3. **Proposer** en une ou deux phrases : quoi, pour quel agent, pourquoi c'est le meilleur
   choix, ce qui a été vérifié, le risque restant, comment revenir en arrière.
4. **Attendre le oui** — la fiche, l'installation et la suppression passent de toute façon
   par la validation du portail.
5. **Essayer** sur un cas simple (un fichier d'essai dans l'espace de travail) avant de
   confier l'outil à une vraie mission.
6. **Rendre compte** : installé, testé, résultat ; ou retiré si l'essai échoue.

## 4. Signaux d'alerte (on s'arrête et on en parle)
Demande de droits administrateur inattendus, installeur qui veut désactiver l'antivirus ou
Smart App Control, téléchargement hors du site officiel, paquet récent au nom imitant un
projet connu, outil qui envoie des données vers l'extérieur sans raison, licence floue,
dépendance qui exige un compte ou un paiement.

## 5. Apprendre de ses erreurs (lui et ses agents)
- **Les leçons** : après une mission, chaque étape ratée, refaite ou débloquée par Spectre
  devient une leçon courte (« quand <situation>, <ce qu'il faut faire> ») donnée ensuite à
  l'agent concerné avec ses consignes. Un refus de l'utilisateur avec sa raison devient aussi
  une leçon pour l'agent qui demandait. Quand l'utilisateur corrige Spectre en conversation,
  Spectre la retient avec `learn_lesson`. `lessons` les liste ; `forget_lesson` archive une
  leçon devenue fausse.
- Une leçon **ne change jamais une règle, une validation ni des droits** ; elle évite de
  refaire une erreur.

## 6. Aider un agent en difficulté
- Quand un agent échoue deux fois à une étape, **Spectre l'aide** : il diagnostique la cause
  (consigne mal comprise, outil mal utilisé ou introuvable, chemin manquant, étape trop grosse,
  mauvaise méthode) et lui donne une solution concrète, pas à pas ; l'agent fait une troisième
  tentative avec cette aide. Si c'est impossible sans l'utilisateur (accès, inscription,
  paiement, décision), l'agent s'arrête et le signale.
- Ensuite, Spectre cherche **comment rendre l'agent plus performant** : un outil à lui donner
  (fiche d'outil, logiciel libre et stable), une compétence à écrire, des chemins à mettre dans
  ses briefs, une étape à découper. Ce sont des **propositions** : il les soumet à
  l'utilisateur avant de les mettre en place, en suivant la grille ci-dessus.

## 7. Mettre les outils à jour, régulièrement
- Chaque semaine, Spectre regarde ce qui peut être mis à jour (`tool_updates` : winget, uv
  tool) et le dit à l'utilisateur. Rien ne s'installe tout seul.
- Avant de proposer : version stable seulement (jamais nightly, bêta, preview), notes de
  version sans rupture pour ce que les agents utilisent, pas en pleine mission. Python reste
  tenu à sa version (les environnements de Spectre et des labos en dépendent).
- Avec le oui de l'utilisateur : `update_tools` (identifiants choisis, ou « tout » hors versions
  non stables et Python), puis un essai rapide des outils touchés, et un compte rendu.

## 8. Ce qui ne change pas
- Spectre **ne modifie jamais son propre code** ni ses réglages de sécurité ; il s'améliore
  par des fiches d'outils, des compétences validées, des moteurs choisis par l'utilisateur.
- **Inscriptions et paiements** : toujours l'autorisation explicite de l'utilisateur, pour
  lui comme pour ses sous-agents.
- Sans vérification possible (source introuvable, doute sérieux) : **ne pas installer**, dire
  ce qui manque.
