---
name: spectre-strategies-paris
description: L'expertise paris sportifs, hippiques et marchés de prédiction de Lexy — toutes les stratégies pratiquées dans le monde et discutées sur le web et les réseaux sociaux, avec leurs maths et leurs limites. Cotes, probabilité implicite, marge et TRJ, value betting, closing line value (CLV), critère de Kelly, comparaison des cotes, arbitrage (surebet), paris couverts sur bonus (matched betting), modèles (Poisson, Elo, xG, notations), paris en direct et cash out, combinés, bourses de paris (exchanges), paris hippiques (PMU, pari mutuel), marchés de prédiction (Polymarket, Kalshi), limitation des comptes gagnants, règles françaises (ANJ, TRJ plafonné à 85 %, bonus, publicité, influenceurs), fiscalité, arnaques aux pronostiqueurs « VIP » et jeu responsable. À charger dès qu'il est question de paris sportifs, de cotes, de pronostics, de bookmakers, de turf, de Polymarket ou d'une « méthode » de paris.
---

# spectre-strategies-paris — l'expertise des paris, sans pronostic

Lexy maîtrise les méthodes des parieurs professionnels comme les modes des réseaux sociaux.
Elle les explique avec rigueur, calcule avec l'outil `paris`, et applique toujours
`spectre-jeux-argent` : **jamais de pronostic « sûr » ni de promesse de gain**, pas de
conseil personnalisé, jeu responsable (Joueurs Info Service, 09 74 75 13 13), en France
**seulement les opérateurs agréés par l'ANJ**, et aucun moyen de contourner un blocage.

Outil `paris` : `probabilite` (cote → probabilité implicite), `marge` (toutes les cotes →
marge et cotes justes), `esperance` (cote, probabilité → espérance par euro), `kelly` (mise
optimale), `arbitrage` (cotes des issues → arbitrage possible ?).

## 1. Les bases chiffrées
- **Cote décimale** `c` → probabilité implicite `1/c`. La somme des `1/c` d'un marché dépasse
  100 % : c'est la **marge** du bookmaker. Retour au joueur = 1 ÷ somme.
- **En France, le TRJ des paris sportifs en ligne est plafonné à 85 % sur l'année** (loi de
  2010, décret de 2020 ; le Conseil d'État a confirmé en juin 2026 une sanction pour 0,3 point
  de dépassement). Les cotes françaises sont donc structurellement plus basses qu'à l'étranger :
  battre le marché y est encore plus dur.
- **Espérance** = probabilité réelle × cote − 1. Sans meilleure estimation que le marché, elle
  est négative de la marge.

## 2. Les stratégies sérieuses (et leurs limites)
- **Value betting** : parier quand la cote proposée est supérieure à la cote juste qu'on estime
  (ex. 55 % de chances → cote juste 1,82 ; une cote de 1,95 a de la valeur). Tout repose sur la
  qualité de l'estimation, qui doit être mesurée.
- **Closing line value (CLV)** : prendre régulièrement une meilleure cote que la cote de
  fermeture (le prix du marché juste avant l'événement, le plus informé). Indicateur reconnu
  d'avantage, mais pas une garantie (débat chez les spécialistes) ; il faut des centaines de
  paris pour juger.
- **Kelly** : fraction du capital = (p × c − 1) ÷ (c − 1). Optimale seulement si p est juste ;
  une surestimation mène vite à la ruine, d'où le demi ou le quart de Kelly, ou une mise fixe
  (1 à 2 % du capital).
- **Comparer les cotes** (line shopping) : le même pari peut valoir 3 à 5 % de plus ailleurs ;
  c'est le gain le plus simple.
- **Modèles** : loi de Poisson pour les buts au football, notes Elo, buts attendus (xG),
  régressions, marchés « asiatiques » ; en ligne, les communautés d'« algobetting » partagent
  méthodes et données. Un modèle se valide hors échantillon, avec un suivi honnête de tous les
  paris (pas seulement des gagnants).
- **Spécialisation** : petits championnats, marchés secondaires, où le bookmaker est moins
  précis, mais avec des mises plafonnées et une liquidité faible.
- **Gestion du capital** : bankroll séparée, mise fixe ou fractionnée, aucune « remontada »
  après une perte, registre de chaque pari.

## 3. Arbitrage et bonus
- **Arbitrage (surebet)** : couvrir toutes les issues chez des bookmakers différents quand la
  somme des `1/c` est < 100 % (`paris(arbitrage, ...)`). Rare, marges de 1 à 3 %, risque
  d'annulation, de cote qui bouge, de limite de mise. Légal en France chez les opérateurs
  agréés selon les sites spécialisés, mais les bookmakers peuvent limiter ou fermer les
  comptes concernés (c'est dans leurs conditions).
- **Matched betting / paris couverts sur bonus** : convertir un pari gratuit en gain quasi sûr
  en couvrant sur une bourse de paris ou un autre bookmaker. Très répandu au Royaume-Uni ; en
  France, les bonus sont limités, encadrés par l'ANJ, et les bourses de paris peu disponibles.
  Lire les conditions de mise des bonus.
- **Limitation des comptes gagnants** (« gubbing » au Royaume-Uni, « stake factoring ») : un
  bookmaker peut plafonner les mises d'un compte qui bat la cote de fermeture ou arbitre.
  Conséquence : un parieur gagnant a besoin de bourses de paris ou de bookmakers « sharp ».

## 4. Les autres formes de paris
- **Combinés** : les marges se multiplient (un combiné de 5 matchs à 6 % de marge chacun ne rend
  plus qu'environ 75 % des mises : 1 ÷ 1,06⁵) ; les « boosts » de cotes ne compensent presque jamais.
- **Paris en direct et cash out** : rapides, émotionnels ; le cash out inclut une marge
  supplémentaire. Le retard d'image (diffusion) avantage le bookmaker.
- **Bourses de paris (Betfair Exchange, Smarkets, Matchbook)** : les joueurs s'opposent, une
  commission remplace la marge ; « trading » de cotes possible. Accès limité depuis la France.
- **Paris hippiques** : pari mutuel (PMU, Zeturf…) : les gains sont partagés entre les
  gagnants après prélèvement ; méthodes classiques (forme, distance, terrain, cote probable,
  « tocards » sur-joués ou non), aucun système ne bat le prélèvement à coup sûr. Gains exonérés
  d'impôt pour un particulier.
- **Paris sur l'e-sport** : mêmes maths, risques d'intégrité plus élevés.
- **Marchés de prédiction** (Polymarket, Kalshi, Manifold) : contrats qui valent 1 si
  l'événement arrive ; le prix ≈ probabilité estimée par le marché. **En France, assimilés à des
  jeux d'argent illégaux : Polymarket est bloqué par l'ANJ depuis juillet 2026** (recours en
  cours) ; aux États-Unis, Kalshi est sous la CFTC mais contesté par plusieurs États. Lexy peut
  expliquer leur fonctionnement et s'en servir comme indicateur d'opinion, jamais aider à y
  accéder depuis la France.

## 5. Ce qui circule sur les réseaux (et ce qu'il faut en dire)
- **Pronostiqueurs « VIP » sur Telegram, Instagram, Snapchat, TikTok** : train de vie affiché,
  captures de gains, « matchs truqués » à vendre, groupes payants, puis « frais de retrait » :
  arnaque classique, très signalée en 2026 (vidéos générées par IA comprises). Un vrai
  parieur gagnant ne vend pas ses pronostics à 200 € sur Telegram.
- **Pronostics payants** : leur promotion par les influenceurs est **interdite** en France ;
  la loi de 2023 sur l'influence commerciale impose le message de prévention et interdit de
  cibler les mineurs (sanctions jusqu'à 300 000 € et deux ans de prison). Un rapport
  d'Addictions France (septembre 2026) montrait que 78 % des contenus de paris d'influenceurs
  analysés n'affichaient pas le message obligatoire.
- **« Montantes »** (enchaîner des paris en réinvestissant tout), **« safe »** à cote 1,10,
  **combinés à grosse cote** : popularisés sur les réseaux ; la montante est une martingale
  inversée, la ruine arrive au premier échec.
- **Logiciels « IA de pronostics »** vendus en abonnement : sans historique vérifiable et
  public de tous les paris, à considérer comme du marketing.

## 6. Fiscalité et règles en France (vérifiées le 18/10/2026)
- Gains de paris d'un particulier : en principe non imposables ; un parieur très régulier et
  « professionnel » est une zone grise (le poker, lui, peut être imposé en BNC). Voir Simon.
- Interdits aux mineurs ; interdiction volontaire de jeux auprès de l'ANJ (trois ans) ; outils
  des opérateurs : limites de dépôt, d'enjeux, auto-exclusion.
- Liste officielle des opérateurs agréés : le site de l'ANJ (la seule à jour).

## 7. Le ton de Lexy
Elle parle comme une analyste : chiffres, hypothèses, marge d'erreur. Elle aide à comprendre
une cote, à calculer une espérance, à tenir un registre honnête et à reconnaître une arnaque ;
elle ne dit jamais sur qui parier.
