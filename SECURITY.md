# Politique de sécurité

Spectre est une bibliothèque et une CLI qui appellent l'API Anthropic avec **votre** clé.
Il n'existe pas de service hébergé ni de programme de bug bounty, mais les problèmes de
sécurité méritent d'être signalés.

## Signaler une vulnérabilité

Utilisez de préférence un [signalement privé GitHub](https://docs.github.com/fr/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(onglet **Security** du dépôt), ou contactez le mainteneur directement. N'ouvrez une issue
publique que pour un problème sans risque d'exploitation. **Ne joignez jamais de clé API**
à un signalement.

## Clé API Anthropic

- La clé est lue depuis `ANTHROPIC_API_KEY` (environnement ou fichier `.env`). `.env` est
  ignoré par git ; seul `.env.example`, sans secret, est versionné.
- Spectre ne doit jamais journaliser, afficher ni inclure la clé dans une sortie (`--json`,
  messages d'erreur, logs). Tout chemin qui l'exposerait est une vulnérabilité.
- La CI n'utilise pas de clé : les tests par défaut tournent sans réseau.

## Contrat Solidity `Voting`

Le contrat Foundry du dépôt est un exemple, sans déploiement mainnet à protéger. Une faille dans
sa logique, ou dans l'outillage de déploiement (fuite de `PRIVATE_KEY`, de l'URL RPC ou de la
clé Etherscan), reste à signaler. Préférez le keystore chiffré de Foundry
(`cast wallet import`) à une clé privée brute dans `.env`.

## Fuite de secrets

Si une clé a été commitée, poussée ou collée dans une issue :

1. **Révoquez-la immédiatement** dans la [console Anthropic](https://console.anthropic.com/)
   et créez-en une nouvelle — réécrire l'historique git ne suffit pas. Pour une clé privée de
   wallet, transférez les fonds vers un nouveau wallet et abandonnez l'ancien.
2. Vérifiez l'usage et la facturation associés à la clé révoquée.
3. Purgez ensuite le secret de l'historique si nécessaire.

## Injection de prompt

Spectre transmet le texte de la demande (et les sorties intermédiaires de Scout et Scribe)
aux modèles suivants. Un contenu non fiable — fichier passé via `--file`, page web copiée,
saisie d'un tiers — peut contenir des instructions qui détournent les agents.

- Traitez `final_text` comme une donnée non fiable : ne l'exécutez pas, ne l'injectez pas
  tel quel dans du HTML, du SQL ou un shell.
- Ne placez aucun secret dans une demande : il serait envoyé à l'API et pourrait ressortir
  dans le texte final.
- Warden relit et corrige le texte, mais ce n'est pas une barrière de sécurité.
- Les coûts sont plafonnés par `max_tokens` par agent ; surveillez-les (`--costs`) si
  Spectre est exposé à des entrées externes.

Un contournement des prompts système permettant d'exfiltrer des données ou de dépasser ces
limites est à signaler comme une vulnérabilité.
