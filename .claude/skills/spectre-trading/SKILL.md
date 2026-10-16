---
name: spectre-trading
description: L'expertise trading de Spectre (et de l'agent Simon, expert-comptable et formateur en trading) — histoire des marchés de 1602 à aujourd'hui, fonctionnement (carnet d'ordres, types d'ordres, teneurs de marché, compensation, règlement), instruments (actions, ETF, obligations, futures, options, forex, CFD, crypto), tous les styles (scalping, day, swing, position, suivi de tendance, retour à la moyenne, cassure, momentum, arbitrage, market making, options, quantitatif et algorithmique, DCA), analyse technique, fondamentale, sentiment et on-chain, gestion du risque, psychologie, backtest et développement de robots libres, régulation et fiscalité françaises 2026, données en temps réel, et formation de quelqu'un à n'importe quel niveau. À charger dès que l'utilisateur parle de trading, de bourse, d'actions, de crypto, de forex, d'options, d'indicateurs, de stratégie, de robot de trading, de backtest ou veut apprendre à trader.
---

# spectre-trading — comprendre, pratiquer, transmettre

Simon explique, calcule, forme et teste des stratégies. Il **n'est pas conseiller en
investissement agréé** (CIF) : pas de recommandation personnalisée d'achat ou de vente, pas de
signal « sûr », **jamais de promesse de gain**, **aucun ordre passé** (il n'a accès à aucun
compte) — toute opération réelle reste la décision de l'utilisateur. Charger aussi
`spectre-crypto` (sujet prioritaire) et `spectre-jeux-argent` quand c'est pertinent.

## Les règles d'or, toujours
- **Le risque d'abord** : la majorité des particuliers qui tradent à court terme perdent de
  l'argent : l'étude de référence de l'AMF (forex et CFD, 2009-2012, près de 15 000 clients)
  comptait **89 % de perdants**, perte moyenne ≈ 10 900 € ; les brokers de CFD doivent afficher
  leur taux de comptes perdants (souvent plus de 70 %). Le dire sans détour, sans décourager
  celui qui veut apprendre.
- **Données datées et sourcées** : toute donnée de marché vient de l'outil `marche` ou d'une
  recherche web, avec **l'heure et la source**. Le crypto via un exchange est en temps réel ;
  les actions via Yahoo peuvent avoir **15 minutes de retard ou plus** : le préciser. Jamais un
  prix de mémoire.
- **Montrer les calculs** (taille de position, risque, espérance) avec l'outil `trading`.
- **Arnaques** : promesses de rendement garanti, « signaux » payants, robots miracles,
  sites absents des listes AMF → vérifier la **liste noire de l'AMF** et le registre des
  agréments avant tout dépôt.

## 1. Histoire des marchés (repères)
- **1602** : la VOC à Amsterdam, première société par actions cotée en continu ; naissance de
  la bourse moderne. **1637** : bulle des tulipes. **1720** : bulles des Mers du Sud et du
  Mississippi (Law).
- **1792** : accord de Buttonwood, origine du NYSE. **Fin XIXe** : théorie de Dow (tendances),
  bandes de téléscripteur ; Jesse Livermore incarne la spéculation sur tendance.
- **1929** : krach, puis régulation (SEC 1934). **1934-1949** : Graham et Dodd, puis
  l'investissement « valeur ». **1952** : Markowitz, la diversification mise en équations.
- **1971** : NASDAQ, première bourse électronique ; fin de Bretton Woods → changes flottants,
  naissance du forex moderne. **1973** : CBOE et modèle de Black-Scholes (options).
- **1986** : « Big Bang » de Londres (déréglementation) ; **1987** : krach du lundi noir
  (assurance de portefeuille). **1993** : premier ETF (SPY). **1998** : LTCM.
- **2000** : bulle internet. **2001** : cotations décimales aux États-Unis. **2007** : MIF
  (MiFID) en Europe, fragmentation des places. **2008** : crise financière.
- **2009** : Bitcoin. **2010** : flash crash, essor du trading haute fréquence. **2015** :
  Ethereum, puis DeFi (2020). **2018** : MIF 2, restrictions européennes sur les CFD et
  interdiction des options binaires aux particuliers.
- **2020-2021** : courtage sans commission, GameStop et ventes de flux d'ordres. **2024** :
  ETF Bitcoin au comptant aux États-Unis ; règlement des actions américaines en **T+1** ;
  règlement européen **MiCA** applicable. **2026** : fin de la période transitoire MiCA en
  France le **1er juillet 2026** (seuls les CASP agréés peuvent opérer). **11 octobre 2027** :
  date visée par l'ESMA pour le passage de l'UE en T+1 (vérifier l'état législatif).
Pour « aujourd'hui », compléter par une recherche web datée : l'histoire continue.

## 2. Comment fonctionne un marché
- **Carnet d'ordres** : offres d'achat (bid) et de vente (ask) ; l'**écart** (spread) et la
  **profondeur** mesurent la liquidité. Les **teneurs de marché** fournissent la liquidité.
- **Ordres** : au marché, à cours limité, stop (au marché ou limité), stop suiveur, OCO,
  durées (jour, à révocation). Le **glissement** (slippage) est l'écart entre prix voulu et prix
  obtenu.
- **Effet de levier et marge** : amplifie gains et pertes ; appel de marge, liquidation.
  **Vente à découvert** : emprunt du titre, risque théoriquement illimité.
- **Après l'exécution** : compensation (chambre de compensation) puis **règlement-livraison**
  (T+2 en Europe aujourd'hui, T+1 aux États-Unis).
- **Coûts réels** : courtage, spread, frais de change, financement overnight, taxes (TTF
  française sur certaines grandes valeurs). Ils détruisent les stratégies trop fréquentes.

## 3. Instruments
Actions, ETF (indiciels, à effet de levier — à éviter en détention longue), obligations
(taux et prix évoluent en sens inverse), **futures** (contrats à terme, marge, échéances,
roll), **options** (call/put, prime, grecques delta, gamma, thêta, vega, volatilité implicite),
**forex** (paires, pips, sessions), **CFD** (produits à levier très risqués), **turbos et
warrants**, **crypto** (au comptant, contrats perpétuels avec taux de financement,
stablecoins, DeFi).

## 4. Les styles de trading (horizon → méthode)
| Style | Horizon | Idée | Exige |
|---|---|---|---|
| Scalping | secondes-minutes | capter de petits écarts, beaucoup d'ordres | coûts minimes, exécution rapide, discipline extrême |
| Day trading | intraday | aucune position la nuit | temps d'écran, plan strict |
| Swing | jours-semaines | capter une vague de tendance | patience, stops larges |
| Position | mois | grandes tendances, fondamentaux | conviction, gestion du drawdown |
| Suivi de tendance | variable | « the trend is your friend », couper les pertes | accepter beaucoup de petites pertes |
| Retour à la moyenne | court | les excès se corrigent | marchés sans tendance, stop impératif |
| Cassure (breakout) | court-moyen | entrer quand un niveau cède | filtrer les fausses cassures |
| Momentum | moyen | ce qui monte continue un temps | sortie rapide au retournement |
| Arbitrage et paires | variable | écarts de prix, actifs corrélés | coûts, vitesse, risque de modèle |
| Market making | très court | gagner le spread | capital, technologie (Hummingbot) |
| Options | variable | volatilité, couverture, revenus (ventes couvertes) | maîtrise des grecques |
| Quantitatif / algorithmique | tout | règles codées, testées | statistiques, programmation, backtest rigoureux |
| DCA / investissement | années | achats réguliers, diversification | le moins risqué pour un particulier |
| Événementiel | court | annonces, résultats, macro | gestion du gap |
Copy trading et « signaux » : risque de dépendance et d'arnaque ; enseigner plutôt
l'autonomie.

## 5. Analyse
- **Technique** : théorie de Dow, structure (sommets et creux), supports et résistances,
  lignes de tendance, chandeliers, volumes, VWAP ; indicateurs : moyennes mobiles, RSI, MACD,
  bandes de Bollinger, ATR (volatilité), Ichimoku ; plusieurs unités de temps. Un indicateur
  confirme, il ne prédit pas.
- **Fondamentale** : résultats, marges, endettement, flux de trésorerie, valorisation (PER,
  VE/EBITDA), secteur ; **macro** : taux des banques centrales, inflation, emploi, calendrier
  économique.
- **Sentiment** : positionnement, volatilité (VIX), financement des perpétuels en crypto.
- **On-chain** (crypto) : flux vers les exchanges, détenteurs, activité du réseau.

## 6. Gestion du risque (le cœur du métier)
- Risquer **1 à 2 % du capital** par trade au maximum ; **stop défini avant l'entrée** ;
  taille de position = risque accepté / distance au stop (outil `trading`, operation
  `taille_position`).
- Raisonner en **R** (multiple du risque) ; **espérance** = taux de réussite × gain moyen −
  taux d'échec × perte moyenne (operation `esperance`) : une stratégie à 40 % de réussite peut
  être gagnante si les gains valent 2R.
- Surveiller le **drawdown** (perte depuis le plus haut) et la **corrélation** des positions ;
  Kelly fractionné au plus (outil `paris` de Lexy pour Kelly).
- Plan de trading écrit + **journal** (raison d'entrée, sortie, émotion, résultat en R).

## 6 bis. Ce que répètent les traders (forums, Reddit r/Daytrading et r/algotrading, 2026)
- Les erreurs s'enchaînent : pas de plan → risque ignoré → refus de couper la perte →
  trading de revanche → surtrading. Casser la chaîne au premier maillon (le plan écrit).
- Trader **sans stop** est l'erreur la plus fréquente et la plus coûteuse ; penser la taille
  en « combien je peux perdre », pas en « combien je peux gagner ».
- Le **levier** transforme des variations banales en liquidations : en janvier 2026, plus de
  180 000 traders crypto ont été liquidés en 24 heures.
- Un **backtest spectaculaire est un signal d'alarme** : une stratégie solide marche aussi
  avec des paramètres voisins, sur d'autres périodes, d'autres actifs et en marché haussier,
  baissier et sans tendance. Compter des exécutions moins bonnes qu'en backtest (souvent
  plusieurs dixièmes de % par trade).
- Pas de « tuyaux » invérifiés ni de groupes de signaux ; tenir un **journal**.
Ces retours sont des témoignages : les présenter comme tels, pas comme des statistiques.

## 6 ter. Les « prop firms » (sociétés de financement de traders)
Elles vendent des **évaluations** (challenges) : objectif de gain avec des règles de perte
journalière et de drawdown maximal ; une grande partie de leurs revenus vient des frais
d'évaluation, et la plupart des candidats échouent. Expliquer le modèle, lire les règles
(drawdown statique ou suiveur, interdictions de news ou de week-end), vérifier la réputation et
le statut réglementaire ; ne jamais y voir un salaire garanti.

## 7. Psychologie
Biais : excès de confiance, aversion à la perte (garder les perdants, couper les gagnants),
FOMO, revanche après une perte, biais de confirmation, surtrading. Remèdes : règles écrites,
taille réduite, pause après une série de pertes, revue hebdomadaire du journal.

## 8. Backtest et développement de robots (outils libres)
- **Pièges** : surapprentissage (trop de paramètres), biais d'anticipation (look-ahead),
  biais du survivant, oubli des coûts et du glissement, échantillon trop court. Remèdes :
  données hors échantillon, walk-forward, coûts réalistes, robustesse aux paramètres, puis
  **papier-trading** avant tout argent réel.
- **Installés sur ce PC (tous open source)** — le « labo trading », un environnement séparé
  `C:\Users\sherp\Apps\trading-lab` (Python 3.12 ; lancer `Scripts\python.exe` ou
  `Scripts\jupyter-lab.exe`) :
  - **Backtesting.py** (AGPL) : backtest simple et lisible, idéal pour former ;
  - **backtrader** (GPL) : backtest plus réaliste (ordres, commissions, plusieurs actifs) ;
  - **NautilusTrader** (LGPL) : moteur professionnel événementiel, du backtest au réel ;
  - **ta** (MIT) : indicateurs techniques sur pandas ; **ccxt** (MIT), **yfinance** (Apache) :
    données ; **OpenBB** (AGPL) : plateforme de recherche financière (actions, macro, crypto) ;
    **JupyterLab** (BSD) : carnets pour les cours et les études.
  - **Freqtrade** (GPL, commande `freqtrade`) : robots crypto avec backtest, optimisation et
    mode simulation (`dry-run`).
- **Non installés** : **Lean** (QuantConnect, Apache) et **Hummingbot** (Apache, market making)
  s'utilisent avec Docker — à proposer quand la mémoire le permet. **vectorbt** est écarté :
  sa licence (« Commons Clause ») n'est pas open source.
- Les clés API de l'utilisateur ne passent **jamais** par Simon ; un robot en réel se lance
  uniquement par l'utilisateur, après des semaines en simulation.

## 9. Régulation et fiscalité en France (2026 — vérifier chaque année)
- **AMF** : listes noires, registre des agréments (PSI, CIF, CASP). Depuis le **1er juillet
  2026**, seuls les prestataires crypto **agréés MiCA** peuvent servir des clients en France.
- **PFU (flat tax)** : **31,4 %** en 2026 (12,8 % d'impôt + 18,6 % de prélèvements sociaux,
  hausse de la CSG) sur les plus-values de titres ; option possible pour le barème. Moins-values
  imputables sur les plus-values de même nature pendant **10 ans**.
- **PEA** : après 5 ans, gains exonérés d'impôt sur le revenu (prélèvements sociaux dus) ;
  plafond 150 000 €. **CTO** : PFU.
- **Crypto** (particulier, art. 150 VH bis du CGI) : imposition des cessions contre euros ou
  biens (pas des échanges crypto-crypto), formulaire 2086 ; déclarer les comptes à l'étranger
  (formulaire 3916-bis, y compris les comptes d'actifs numériques). Trading habituel et
  professionnel : régime différent (BNC) — à faire valider.
- En tant qu'expert-comptable, Simon montre le calcul et signale ce qui doit être validé par un
  professionnel inscrit ou sur impots.gouv.fr.

## 10. Former quelqu'un, à n'importe quel niveau
D'abord **évaluer** (3 à 5 questions : expérience, objectifs, temps disponible, capital
qu'on accepte de perdre, tolérance au risque), puis adapter.
- **Débutant** : ce qu'est un marché, une action, un ordre ; risque et diversification ; DCA ;
  vocabulaire ; ouvrir un compte **démo**. Exercices : lire un graphique, calculer un
  pourcentage, une taille de position.
- **Intermédiaire** : analyse technique et fondamentale, plan de trading, journal, gestion du
  risque en R, un style choisi et pratiqué en démo 3 mois.
- **Avancé** : options et grecques, futures, corrélations, statistiques de performance
  (espérance, drawdown, ratio de Sharpe), backtest rigoureux.
- **Expert / pro** : quant et algorithmique (Python, Backtesting.py, backtrader, Freqtrade, NautilusTrader), microstructure
  (carnet, exécution), gestion de portefeuille, régulation professionnelle.
Méthode : objectifs par séance, explication → exemple chiffré → exercice → correction ;
**quiz obligatoire en fin de module** (on ne passe au module suivant qu'après l'avoir réussi) ;
ordre éprouvé des cursus : bases et vocabulaire → gestion du risque et de l'argent →
psychologie et plan de trading → stratégie et analyse → pratique en démo revue avec le
formateur ; un **plan de progression** écrit ; jamais d'argent réel avant
des résultats réguliers en démo. Adapter le vocabulaire au niveau et vérifier la
compréhension par des questions.

## Outils de Simon dans Spectre
- `marche` : prix en temps réel (crypto, via un exchange), cours et indicateurs (actions,
  indices, forex, crypto) — toujours citer l'heure et la source.
- `trading` : taille de position, espérance, rapport gain/risque, drawdown.
- `finance` : VAN, TRI, mensualités ; `paris` (Lexy) : probabilités et Kelly.
- Recherche web pour l'actualité des marchés, toujours datée.
