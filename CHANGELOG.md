# Changelog

Toutes les évolutions notables de ce projet sont documentées dans ce fichier.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet adhère au
[versionnage sémantique](https://semver.org/lang/fr/).

## [Unreleased]

### Added
- **Portraits de l'équipe animés pendant la visio** : à partir de la photo d'un agent, deux
  courtes boucles sont fabriquées sur ce PC (LivePortrait via ComfyUI, `tools/animate_portraits.cmd`)
  — une « parle » (lèvres qui bougent) et une « écoute » discrète (bouche fermée). Dans l'appel,
  le portrait **ne s'anime que quand l'agent a la parole** (boucle « parle ») ; le reste du temps
  il reste la photo fixe, pour que rien ne gigote sans raison. Boucles en fondu enchaîné (lecture
  avant, sans saccade), mouvement volontairement doux pour ne pas déformer le visage. Hors ligne,
  sans les boucles ou en mouvement réduit, la photo ne bouge pas. Une nouvelle photo
  rend ses boucles caduques et les supprime. Les clips sont servis par
  `GET /api/assistant/team/<clé>/clip/<écoute|parle>` (WebM vérifié, 20 Mo max).
- **Couleurs de la vue « Conversation »** : les quatre relevés HUD prennent chacun une raie du
  spectre (Mémoire cyan, Validations violet, Missions bleu, **Cerveau ambre** — écho de l'état
  « réflexion » de l'Orbe), la barre de signal passe en dégradé cyan→violet→rouge et les repères
  d'angle sont teintés — l'UI reprend la palette colorée de l'Orbe sans surcharge.
- **Vue « Conversation » mieux structurée autour de l'Orbe** : la scène est encadrée par de
  fins repères d'angle (dans l'esprit du réticule de l'Orbe), les quatre relevés HUD forment un
  cadre régulier (ceux du bas descendus au tiers inférieur) et le champ de saisie partage la
  même « console » que le dock (même plaque, même filet) — l'ensemble HUD + Orbe + commandes se
  lit comme un seul panneau, homogène sur ordinateur comme sur téléphone.
- **Nouvelle Orbe de l'assistant, bien plus futuriste** (`web/static/orb.js`) : une sphère 3-D
  de particules colorées en rotation (le « cerveau »), triée en profondeur pour paraître pleine,
  des orbites inclinées avec électrons lumineux qui passent devant et derrière, un cœur plasma
  qui irradie, des filaments d'énergie, un oscilloscope circulaire multicolore qui réagit à la
  voix en direct et une surcouche HUD (biseau gradué, arcs, réticule). Palette cyan → turquoise
  → bleu → violet → magenta ; vire vers l'ambre quand Spectre réfléchit. Même interface
  (`setState`, `setLevel`, `spellWord`), le mot SPECTRE à l'éveil et le respect de
  « prefers-reduced-motion » sont conservés.
- **Specs réseaux sociaux 2026 pour Kyra** (`spectre-pub-communication`) : tableau par réseau
  (YouTube long et Shorts, TikTok, Instagram Reels/fil/Stories, Facebook fil/Reels/Stories,
  LinkedIn, X, Pinterest, Snapchat, Threads, Bluesky, fiche Google) — ratio, pixels, durée,
  poids, notes — plus les règles transverses (accroche, sous-titres, vertical d'abord, −14 LUFS,
  publicité vs organique). Chiffres de guides recoupés, à revérifier sur les pages officielles.
- **Ghidra branché pour Syfer (analyse native)** : l'outil `retro` sait maintenant décompiler
  un binaire natif C/C++ via Ghidra (libre, NSA) — `analyze`, `search <terme>`,
  `function <nom>`, `decompile <adresse 0x…>`, `xrefs <adresse>`, `trace <terme>`. Ghidra
  12.1.4 (compatible REA 6.7.0) est installé sous `~/Apps/ghidra` avec un JDK 21 ; le kit
  trouve les deux tout seul et les passe à REA par l'environnement du sous-processus
  (`GHIDRA_INSTALL_DIR`, `JAVA_HOME`, délai de démarrage relevé), sans toucher à
  l'environnement global. Si Ghidra manque, l'analyse native est refusée avec un message clair ;
  les commandes statiques restent disponibles sans lui.
- **Chaque agent Claude réfléchit avec le bon effort** (nouveauté des agents de Claude Code :
  le drapeau `--effort`). Spectre règle maintenant l'effort par modèle et l'applique à tous ses
  agents sur un moteur Claude — cerveau, agents de mission, planificateur, équipe de dev :
  Opus en `high`, Sonnet en `medium` par défaut, réglable par `model_effort` dans les réglages
  (niveaux `low`, `medium`, `high`, `xhigh`, `max`). Haiku 4.5 ne prend pas d'effort : il n'en
  reçoit jamais. Cela applique enfin la règle « régler l'effort, pas la température » sur le vrai
  appel à Claude Code (`claude -p`), qui jusqu'ici laissait l'effort par défaut du CLI.
- **Syfer, expert en rétro-ingénierie** sur la méthode de REA « Reverse Engineer Anything »
  (github.com/morluto/rea, MIT) : compétence `spectre-retro-ingenierie` — base légale vérifiée
  d'abord (interopérabilité L122-6-1 CPI et directive 2009/24/CE, sécurité, jamais de
  contournement de protection), routage de la cible, du résumé au détail, registre des
  constats, observé / déduit / inconnu, reconstruction originale d'une fonctionnalité,
  analyse de malware isolée. Outil `toolkit` `retro` réservé à Syfer : les inspections
  **statiques** de REA (format et archive, ressources d'un .exe, assemblies .NET, binaires Go
  et Rust, fusibles Electron, applis JavaScript/.asar, SQLite, Flutter) ; le fichier n'est
  jamais exécuté, le rapport complet est gardé dans `workspace/retro/` et la réponse en
  donne un aperçu. Débogueurs, Frida, capture d'exécution et adb ne sont pas branchés.
- **Kyra devient designer, sur le modèle de Claude Design** (Anthropic Labs) : compétence
  `spectre-design` — cadrage (chercher le contexte existant, questions en une fois), système
  de design posé d'abord (`DESIGN.md`, variables CSS : couleurs à rôle, typo, espacements,
  composants, interdits), rendu « IA générique » à fuir, 3 variantes et réglages en direct,
  maquettes, prototypes cliquables, slides 1920×1080 et one-pagers en HTML autonome,
  vérification par capture avant de livrer, exports libres, passage au développement, droit
  (jamais la charte d'une autre marque). Trois outils `toolkit` réservés à Kyra :
  `maquette_png` (capture d'une page HTML par Chromium, aux formats paysage/story/fil/carre),
  `maquette_pdf` (page HTML en PDF, une page par slide) et `vectoriel` (SVG en PDF ou PNG avec
  Inkscape).
- **Une mémoire bien plus grande, mais raisonnable** : Spectre a en tête jusqu'à 150 faits
  sur l'utilisateur à chaque échange (au lieu de 40), dans une enveloppe de 45 000 caractères
  (≈ 11 000 tokens) ; les plus fiables d'abord, les autres restent en mémoire et sont retrouvés
  avec `recall`. Réglages `memory_facts` et `memory_chars` (400 faits et 120 000 caractères au
  plus) dans la page Réglages. Le planificateur des missions en reçoit 40 (au lieu de 20).
- **Rangement de la mémoire chaque nuit, sans rien effacer** (`Memory.compact`, après la
  consolidation de 3 h) : sauvegarde de la base d'abord (`sauvegardes/memoire-<date>.db`, les
  7 dernières gardées), puis une relecture (Sonnet) propose de fusionner les doublons et
  d'archiver ce qui est dépassé ; chaque fusion est vérifiée (même catégorie, aucun chiffre ni
  date perdu, texte pas raccourci), 15 fusions et 5 archivages par nuit au plus, rien
  d'archivé qui a été vu dans la semaine. Les règles de l'utilisateur et ses confidences ne
  sont jamais touchées. Les faits fusionnés ou archivés restent en base, restaurables
  (`restore_fact`) ; un compte rendu arrive le matin.

### Fixed
- Connexions SQLite laissées ouvertes : celle du portail des moteurs hébergés (Simon, Shelby,
  Ysyss, Lexy) se ferme désormais avec le moteur ; les tests ferment chaque base qu'ils
  ouvrent. Fin des avertissements « unclosed database » qui apparaissaient au hasard.

## [0.24.0] - 2026-10-18

### Added
- **Paiements préparés par Spectre, faits par l'utilisateur** (module `payments.py`, table
  `payments`) : `prepare_payment` (bénéficiaire, montant, référence, IBAN vérifié par sa clé ou
  page https du marchand) attend toujours la validation ; après le oui, Spectre inscrit le
  paiement au registre, produit un QR code de virement SEPA (norme EPC, lu par les applis
  bancaires ; aussi servi sur `/api/assistant/payments/<id>/qr` pour le téléphone) et/ou ouvre
  la page du marchand. Rien n'est débité sans la confirmation de l'utilisateur dans sa banque ;
  Spectre ne détient aucun identifiant bancaire. `payments`, `mark_paid`, `cancel_payment` ;
  plafond de 10 000 € par paiement.

### Changed
- **Paiements : validation au lieu d'interdiction.** La catégorie `payment` passe de NEVER à
  ASK : un paiement n'est plus refusé d'office, il attend l'accord explicite de l'utilisateur,
  à chaque fois, pour Spectre comme pour ses agents (même un agent « expert » ou un réglage
  d'autonomie maximal ne le rend jamais automatique).

## [0.23.0] - 2026-10-18

### Added
- **Spectre et ses agents apprennent de leurs erreurs** (module `lessons.py`, table
  `lessons`) : après une mission, les étapes ratées, refaites ou débloquées deviennent des
  leçons courtes pour l'agent concerné, données ensuite avec ses consignes (les plus
  confirmées d'abord) ; un refus avec sa raison devient une leçon pour l'agent qui demandait ;
  outils `lessons`, `learn_lesson`, `forget_lesson`. Une leçon ne peut jamais assouplir une
  règle ni toucher aux secrets.
- **Spectre aide un agent en difficulté** : après deux tentatives refusées, il diagnostique et
  donne une solution pas à pas pour une troisième tentative ; en fin de mission, il propose ce
  qui rendrait l'agent plus performant (outil, compétence, brief), soumis à l'utilisateur.
- **Lexy, experte de toutes les stratégies de jeux, de paris et de finance** (recherches
  web et réseaux sociaux du 18/10/2026) : compétences `spectre-strategies-casino` (avantage
  de la maison de chaque jeu, blackjack, systèmes de mise, crash games, loteries, poker,
  réglementation mondiale, fiscalité), `spectre-strategies-paris` (value, CLV, Kelly,
  arbitrage, matched betting, TRJ 85 %, marchés de prédiction, arnaques aux pronostiqueurs)
  et `spectre-strategies-financieres` (allocations, facteurs, options, crypto, FIRE,
  finfluenceurs, PFU 31,4 %) ; l'outil `paris` calcule aussi l'espérance, la marge et les
  cotes justes, le risque de ruine d'une martingale et l'avantage de la maison.
- **Mises à jour régulières des outils** (module `updates.py`) : chaque semaine, Spectre
  liste les mises à jour winget et uv tool et les annonce ; `tool_updates` (lecture) et
  `update_tools` (validation obligatoire ; versions non stables écartées, Python tenu à sa
  version).

## [0.22.0] - 2026-10-18

### Added
- **Pièces jointes dans la conversation avec Spectre** : trombone, coller (Ctrl+V, captures
  d'écran comprises) et glisser-déposer, jusqu'à 10 fichiers de 15 Mo par message. Les fichiers
  sont gardés dans `workspace/pieces-jointes/` et Spectre les lit lui-même (images, PDF,
  documents) avec l'outil `Read` de Claude Code, limité à ce dossier ; un court fichier texte
  est aussi recopié dans le message pour les autres moteurs.
- **Pièces jointes dans la Rédaction** : en plus du texte, Word (.docx), OpenDocument (.odt),
  PDF et images (lecture par l'OCR Tesseract) ; coller et glisser-déposer. Le serveur extrait le
  texte (`POST /api/attachments`, module `spectre/attachments.py`, dépendance `pypdf`).
- **Spectre équipe ses sous-agents en outils** (fiches d'outils, module `agent_tools.py`) :
  `agent_tool_save` écrit une fiche (programme, arguments avec `{cible}` et `{options}`,
  agents, niveau lecture/écriture/distant) dans `~/.spectre/assistant/outils-agents/`, que
  l'outil `toolkit` lance comme les outils intégrés ; `agent_tool_install` installe le
  programme (winget ou uv tool) ; `agent_tool_delete` retire la fiche ; `installed_programs`
  recense les logiciels déjà installés sur le PC ; `outils_agents` liste ceux de chaque agent.
  Jamais de code Python modifié, jamais de shell ni d'interpréteur ; créer, retirer et
  installer attendent toujours la validation de l'utilisateur.

### Changed
- Une inscription ou un paiement exige toujours l'autorisation explicite de l'utilisateur,
  pour Spectre comme pour ses sous-agents (prompt du cerveau, prompt WORKER) ; un sous-agent
  décide seul des petits choix de son étape.
- Spectre cherche toujours le meilleur pour s'améliorer, lui et ses sous-agents, d'abord le
  plus sécurisé, le plus stable et le plus fiable, vérifié avant de proposer : nouvelle
  compétence `spectre-amelioration` (critères, grille de vérification, protocole, signaux
  d'alerte), rappelée dans le prompt du cerveau, le prompt WORKER et les outils de fiches.

## [0.21.0] - 2026-10-17

### Changed
- **Budget d'actions relevé et réglable** : 60 actions par minute et 3 000 par jour (au lieu
  de 20 et 500), modifiables dans les Réglages (`actions_per_minute`, `actions_per_day`).

### Fixed
- Les actions refusées et les demandes de validation ne comptent plus dans le budget : une
  fois le plafond atteint, chaque refus « budget dépassé » prolongeait le blocage.

## [0.20.0] - 2026-10-16

### Added
- **Le bon modèle LM Studio pour chaque agent, sur demande** : outil `recommend_engine`
  (module `local_models.py` : classe les modèles installés dans LM Studio selon le métier de
  l'agent — outils, vision, code, raisonnement, contexte, vitesse — et la mémoire du PC ;
  écarte les modèles trop lourds, cassés, anciens, trop compressés ou débridés) et outil
  `set_agent_engine` (réservé à Spectre : change le moteur d'un agent nommé, Kyra, Octavya,
  Gétro…, ou le remet sur son moteur d'origine). Règle : chaque agent garde son moteur
  attribué et n'en change que si l'utilisateur le demande.

## [0.19.0] - 2026-10-16

### Added
- **Spectre, expert de toutes les administrations** (France, Europe, international) :
  compétences `spectre-administration` (carte de l'État, des collectivités, de la sécurité
  sociale et de la justice, droits de l'usager CRPA, escalier des recours, démarches par
  domaine, fonction publique, facturation électronique 2026-2027, numérique et arnaques) et
  `spectre-administration-europe-international` (UE, Schengen EES/ETIAS, eIDAS 2, OOTS,
  SOLVIT, CEDH, apostille, fiscalité internationale, systèmes de 15 pays) ; outil
  `administration` (module `administration.py` : annuaire des guichets compétents, fiche
  entreprise Sirene, commune, adresse BAN, TVA VIES, identifiants de tous pays, délais et
  jours fériés), réservé à Spectre. Extra `administration` (python-stdnum, holidays).

### Fixed
- Cerveau : le prompt système est passé par fichier (`--system-prompt-file`). Avec toutes les
  compétences, la commande dépassait 32 767 caractères et Windows la refusait (« Je ne trouve
  pas Claude Code »).

## [0.18.0] - 2026-10-16

### Added
- **Kyra, experte pub et communication** : compétence `spectre-pub-communication` (brief,
  plateforme de marque, AIDA/PAS/BAB/4U/FAB/StoryBrand, déclinaison par réseau, KPI et UTM,
  droit français de la publicité) et outils libres dans `toolkit`, réservés à Kyra :
  `video_info` (ffprobe), `video_format`/`image_format` (FFmpeg/ImageMagick : story, fil,
  carre, paysage), `sous_titres` (Whisper), `incruster` (sous-titres gravés), `detourage`
  (rembg), `voix_off` (Kokoro, voix française), `agrandir` (Real-ESRGAN). Chaque outil crée un
  nouveau fichier à côté de la source et échoue si rien n'a été produit.
- **Kyra, productrice et réalisatrice** (clips, séries, films) : compétence
  `spectre-production-audiovisuelle` (chaîne de production, bible, découpage, storyboard,
  grammaire des plans, montage, son, étalonnage, livraison, droit) et outils `scenario_pdf`
  (Screenplain), `plans` (PySceneDetect), `derushage` (auto-editor), `loudness` (EBU R128).
- Compétences `spectre-post-production-libre` (étalonnage sans DaVinci, storyboard et
  animatique, DCP-o-matic, vidéo IA sur GPU loué, Penpot) et `spectre-diffusion-marketing`
  (Postiz, listmonk, Mautic, Umami : méthode manuelle maintenant, auto-hébergement plus tard).
- **Simon, expert et formateur en trading** : compétence `spectre-trading` (histoire des marchés
  de 1602 à 2026, fonctionnement, instruments, tous les styles, analyse, risque, psychologie,
  backtest, prop firms, régulation et fiscalité 2026, cursus du débutant à l'expert) et outils
  `marche` (prix en temps réel des cryptos via Kraken, cours et indicateurs via Yahoo, carnet
  d'ordres ; toujours datés et sourcés) et `trading` (taille de position, espérance,
  gain/risque, drawdown), réservés à Simon et Lexy.
- **Shelby, experte de la nature et du climat** : compétence `spectre-nature-climat`
  (biodiversité, cinq pressions, état 2026, impacts du climat dans les airs, sur terre, en eau
  douce et en mer, accords, sciences participatives) et outil `nature` (module `nature.py` :
  GBIF et UICN, OBIS, Open-Meteo et ERA5 — espèce, observations, vie marine, météo, écart
  climatique ; datés et sourcés), réservé à Shelby et Ysyss.
- **Octavya, experte de tous les contrats** : compétences `spectre-contrats` (méthode,
  droit commun réformé, commercial, consommation, travail, immobilier, sociétés, SaaS, PI,
  sûretés, jurisprudence 2026) et `spectre-contrats-europe-international` (Rome I, Bruxelles I
  bis, consommateurs et bouton de rétractation, RGPD, Data Act, AI Act, DORA, CVIM, UNIDROIT,
  Incoterms 2020, arbitrage, common law), outil `contrat` (module `contracts.py` : analyser un
  contrat .docx/.txt/.md, comparer deux versions en HTML), réservé à Octavya.
- **Spectre, directeur** : compétence `spectre-management` (diriger selon la taille de
  l'entreprise, attentes réciproques directeur-équipe, entretiens individuels, délégation,
  feedback, recrutement, OKR, EOS, 4DX, RACI, conduite du changement, droit du travail du
  manager, direction de sa propre équipe d'agents), chargée d'office par le cerveau.
- **Syfer, expert de tous les types de pentests** : compétence `spectre-pentest` (méthodologie
  PTES, OWASP WSTG/MASTG, MITRE ATT&CK v19 ; web, API, réseau, Active Directory, cloud, mobile,
  sans-fil, ingénierie sociale, IoT, LLM, red team ; phases, CVSS, rapport, formation ; cadre
  légal strict — cible autorisée, impact minimal, confidentialité) et nouveaux outils `toolkit`
  réservés à Syfer : trufflehog (secrets, local=lecture), nmap, subfinder, httpx (cible
  autorisée, distant=validation).

## [0.17.0] - 2026-10-15

### Added

- Trois agents : Octavya (juridique, sur Cursor), Clarke (finances et assurances, sur
  Antigravity) et Simon (expert-comptable, sur DeepSeek `deepseek-v4-pro` par défaut). Chacun
  a sa spécialité, et Spectre leur confie d'office les missions de leur domaine.
  - Octavya et Clarke travaillent comme Kyra et Syfer (`assistant/cli_agents.py`) : dans leur
    propre dossier, avec les seuls outils de Spectre. Le shell et l'écriture directe de leur
    outil sont coupés quand il le permet.
  - Simon travaille sur un modèle hébergé, avec ta clé `DEEPSEEK_API_KEY`
    (`AGENT_DEFAULT_ENGINES`).
  - Le modèle se choisit dans la liste que donne l'outil lui-même (`cursor-agent
    --list-models`, `agy models`, le cache de Codex, les alias de Vibe) ou le fournisseur.
- Un moteur par agent (`agent_engines`). Un agent peut quitter son outil ou son modèle pour un
  autre moteur, par exemple Octavya sur Claude, et garde son nom et sa spécialité.
- Page Équipe (`assistant/team.py`). Pour chaque agent :
  - son portrait, son département, son outil, son moteur et son modèle, modifiables ;
  - sa voix dans la visio, avec un bouton pour l'écouter ;
  - son dossier, ses étapes, ses jetons et son coût sur 30 jours ;
  - le détail de ses 30 dernières actions, avec la commande et le résultat.
- Visio de l'équipe (`assistant/call.py`, `call.js`), dans l'esprit d'Agent Standup.
  - Chaque agent apparaît à son bureau avec son statut : au travail, attend, a besoin de toi,
    bloqué, a fini. S'y ajoutent ce qu'il fait, depuis combien de temps, ses jetons et ses
    échecs, et des badges pour une commande longue, un silence ou une boucle.
  - Celui qui parle passe en vedette, avec des sous-titres et la voix de chaque agent.
  - L'écran partagé montre la dernière commande et sa vraie sortie.
  - Le tour de table, le compte rendu Markdown et l'arbre de qui a demandé quoi à qui sont
    construits à partir des faits, sans modèle ni jeton.
  - Le tableau des sessions montre les missions de Spectre et les sessions Claude Code, Codex
    et Mistral Vibe du PC, avec leurs sous-agents (`assistant/sessions.py`, en lecture seule).
  - Relecture d'une mission en 1×, 2×, 4× ou 8×, avec des repères : première erreur, étape la
    plus longue, attente de ton accord.
  - Enregistrement vidéo de l'onglet, ou clip de 25 s.
- Trois agents conseil, toutes femmes, hébergés sur Claude Sonnet par défaut (changeable) :
  - Shelby (animalier : comportement, santé, toilettage) ;
  - Ysyss (sciences et être humain : physique, chimie, maths, biologie, astronomie, santé,
    psychologie, langues, sports, arts) ;
  - Lexy (jeux d'argent, paris sportifs, bourse, blockchain et crypto, sans promesse de gain).
  - Outils bornés : `science` (SymPy) pour Ysyss, `paris` (probabilités, Kelly) pour Lexy ;
    bibliothèques Astropy, Skyfield, ccxt, yfinance installées.
  - Nouvelles compétences `spectre-animaux` et `spectre-jeux-argent`.
  - Tous les agents respectent la logique métier du projet en construction (prompt WORKER).
- Des logiciels libres par métier, donnés aux agents à travers le portail (`assistant/toolkit.py`,
  outils `toolkit` et `finance`). Chaque agent ne voit que ceux de son domaine.
  - Syfer : Gitleaks (secrets), Trivy (vulnérabilités), Semgrep (analyse de code), Nuclei (scan
    d'une adresse autorisée, qui demande ta validation).
  - Octavya et les rédacteurs : Vale et LanguageTool (style et grammaire).
  - Tous : Pandoc (conversion de documents), Tesseract (texte d'une image).
  - Clarke et Simon : calculs financiers (mensualité, VAN, TRI, valeur future) via
    numpy-financial, et les bibliothèques installées (QuantLib, chainladder, beancount,
    OpenFisca) pour leurs scripts.
  - Un scan local lit ; sonder une adresse distante attend ton accord.
- Portraits réalistes générés par le studio (bouton « Portrait réaliste (IA) » dans la page
  Équipe) : ComfyUI crée un portrait photoréaliste de l'agent et l'enregistre comme sa photo.
- Le studio de Kyra (`assistant/media.py`) : outils `generate_image` et `generate_video`,
  réservés à Kyra.
  - Les images et les vidéos sont créées sur ce PC par ComfyUI (Z-Image Turbo, Wan 2.2).
    Spectre démarre ComfyUI s'il ne tourne pas.
  - Chaque demande devient une tâche suivie par la boucle proactive : le fichier arrive dans
    `workspace/medias` et tu es prévenu, avec la durée estimée annoncée à l'avance.
  - L'outil `media_jobs` liste les créations.
  - Les fichiers de modèles sont listés dans `COMFY_MODELS`.
- Journal d'activité des agents (table `activity`). Il note chaque mission, chaque étape et
  chaque outil passé par le portail, avec l'agent, la durée et le résultat.
- Portraits manga (par défaut) ou réalistes, qui clignent des yeux et bougent les lèvres avec la
  voix.
  - Un éditeur d'apparence règle la peau, la coiffure, les cheveux, les yeux, la barbe, les
    lunettes, la tenue et le fond, aussi dès la création d'un agent.
  - On peut aussi donner une photo à un agent.
- Voix claires, sans effet, propres à chaque agent : les voix naturelles du navigateur, ou
  celles de Spectre (Piper, dont deux nouvelles voix françaises).
- Laya, l'intuition de Spectre, une compétence réservée à lui seul (`assistant/laya.py`, outil
  `laya_decide`).
  - Laya est un modèle de décision libre (Apache 2.0). Il répond sans jeton à des questions de
    choix, de note ou de oui/non sur un message ou une mission.
  - Il tourne par le paquet `laya` local ou par un serveur `laya-serve`.
  - Les agents ne voient pas cet outil.

### Changed

- Kyra est présentée comme « Codex » et Syfer comme « Vibe ». On peut aussi les nommer `codex`
  et `vibe`.
- Clarke est une femme.
- Licence : GPL 3.0 ou ultérieure (avant : MIT).

### Fixed

- Les menus des pages Rédaction et Assistant défilent sur PC comme sur téléphone, au lieu
  d'être coupés en bas.
- Le serveur web lit toujours le corps d'une requête POST, même quand la route n'en a pas
  besoin. Le corps non lu se collait auparavant à la requête suivante (« {}GET »), par exemple
  après le bouton Parler.

## [0.16.0] - 2026-10-14

### Added

- Notifications natives Web Push (`assistant/webpush.py`, vue Automatisation › Notifications de
  cet appareil).
  - Les alertes, comptes rendus, initiatives et validations en attente arrivent en notification
    sur le téléphone ou le PC, même Spectre fermé. Toucher la notification ouvre Spectre.
  - Chaque message est chiffré pour l'appareil (RFC 8291, aes128gcm) et signé par la clé de
    Spectre (VAPID, RFC 8292), sans service tiers ni nouvelle bibliothèque.
  - La clé est créée une fois et gardée dans `~/.spectre/assistant/.env`. Un appareil
    désinscrit est retiré tout seul. 10 appareils au maximum.
- Briefing vocal par entreprise (`assistant/brief.py`). Le briefing du matin donne pour chaque
  entreprise :
  - le MRR et son évolution sur la semaine, et le churn ;
  - un site hors ligne ;
  - les tâches à valider ou bloquées ;
  - les alertes actives ;
  - les décisions à réévaluer et les expériences qui se terminent dans la semaine.
- Suivi crypto en lecture seule, comme sources du tableau de bord : solde d'une adresse Bitcoin
  (mempool.space), solde d'une adresse Ethereum (Blockscout), cours (CoinGecko).
  - Seules des adresses publiques sont acceptées : jamais de clé privée ni de phrase de
    récupération. Aucune clé d'API n'est nécessaire.
  - Le solde d'un pool de minage se suit avec la source « API JSON ».

### Changed

- `cryptography` est déclarée explicitement dans les dépendances. Elle était déjà installée,
  par dépendance indirecte.

## [0.15.0] - 2026-10-14

### Added

- Département technique (`assistant/devteam.py`, vue Entreprise › Développement, outils
  `set_dev_repo`, `dev_task`, `list_dev_jobs`, `open_pr`, `discard_dev_job`).
  - Pour une entreprise dont le dépôt git est configuré (chemin, commande des tests, branche de
    base ; ce réglage demande ta validation), chaque demande crée une branche
    `spectre/<n>-<sujet>` dans un worktree isolé, hors du dépôt.
  - L'agent du poste Produit et technique y code.
    - Claude Code n'a que Read, Edit, Write, Glob et Grep, plus Bash limité à `git
      status|diff|log` et à la commande des tests.
    - Codex, lui, travaille dans son bac à sable `workspace-write`.
  - Les tests sont lancés. En cas d'échec, l'agent a droit à une tentative de réparation avec la
    sortie des tests.
  - Le travail est commité sur la branche, sans rien pousser.
  - Ouvrir la PR (push et `gh pr create`) est une action externe, qui demande toujours ta
    validation. « Abandonner » supprime la branche et la copie.

### Fixed

- Sous Windows, une commande dont le chemin est entre guillemets se découpe sans garder les
  guillemets.

## [0.14.0] - 2026-10-14

### Added

- Mode réunion local (`assistant/meeting.py`, vue « Réunions », outils `meeting` et
  `list_meetings`).
  - Spectre écoute avec le micro du PC et transcrit sur place (faster-whisper) par morceaux de
    30 secondes. Le son n'est jamais gardé, seul le texte reste, et rien ne quitte le PC.
  - Sa propre voix est mise en sourdine pendant la réunion, pour qu'il ne réponde pas à
    « Spectre ».
  - À l'arrêt, une mission fait le compte rendu : résumé, décisions, tâches et questions
    ouvertes. Une longue réunion est résumée par tranches.
  - Avec une entreprise, les tâches vont à son tableau et les décisions à son journal, à
    réévaluer dans 30 jours.
  - Un enregistrement WAV (16 bits, toute fréquence, mono ou stéréo, 200 Mo maximum) peut
    remplacer le micro.
  - Limite de 4 heures par réunion. Le cerveau lance ou arrête une réunion à la voix.

### Changed

- L'envoi de fichiers bruts accepte une limite par route (`_raw_body(limit)`).

## [0.13.0] - 2026-10-14

### Added

- Autonomie méritée (`assistant/trust.py`, outil `agent_record`, vue Agents › Dossiers et
  coûts).
  - Chaque agent a un dossier : étapes vérifiées ou ratées, tâches validées ou renvoyées par
    l'utilisateur, actions accordées ou refusées, missions annulées (pondérées).
  - Ce dossier donne un niveau, recalculé à chaque fois, avec une annonce à chaque promotion ou
    rétrogradation :
    - apprenti par défaut ;
    - confirmé : sous pilote automatique, ses tâches partent seules ;
    - expert : remplacer ou supprimer un fichier dans les dossiers autorisés ne demande plus de
      validation (toujours journalisé et annulable).
  - Envoyer, payer, installer ou toute action critique demande toujours une validation.
  - Une annulation récente retire le niveau expert.
- Coût de l'IA face au revenu (`assistant/spend.py`, outil `cost_report`, vue Agents et tableau
  de bord de l'entreprise).
  - Chaque appel au modèle est inscrit dans un registre : plan, exécution, vérification,
    rapport, conseil, apprentissage et conversation, avec moteur, agent, mission, entreprise,
    durée, jetons et coût équivalent API.
  - Totaux sur 30 jours par rôle, agent, moteur et département, missions les plus coûteuses, et
    part du MRR.
- Réglage `earned_autonomy` (activé par défaut).

### Changed

- Contexte d'exécution par fil (`assistant/runctx.py`) : l'agent et la mission en cours
  arrivent jusqu'au portail.
  - Les agents CLI reçoivent `SPECTRE_AGENT` et `SPECTRE_MISSION` dans leur serveur d'outils,
    avec un fichier de configuration MCP par fil.
  - L'agent HTTP les reçoit dans le même processus.
- `Reply.tokens` : la CLI Claude et les moteurs HTTP remontent leurs jetons.
- `Gate.decide` prend en compte le niveau de confiance de l'agent.
- Une mission de tâche porte la clé de son entreprise.

## [0.12.0] - 2026-10-14

### Added

- Conseil d'administration (`assistant/board.py`, outil `convene_board`, vue Entreprise ›
  Conseil et expériences).
  - La direction choisit les 2 à 4 départements concernés. Chacun donne son avis, en JSON, sur
    le moteur de l'agent qui tient son poste.
  - La direction arbitre : options, décision, raisons, risques, prochaines étapes et
    l'indicateur qui jugera la décision.
  - Le contexte fourni au conseil réunit l'organigramme, le tableau de bord SaaS et les leçons
    des décisions passées.
  - Une note de décision en Markdown est écrite, et une expérience de mesure est créée
    d'elle-même quand l'indicateur est suivi.
- Journal des décisions (`list_decisions`). À la date prévue, ou avec `review_decision`, la
  direction réévalue la décision avec les vrais chiffres et le verdict de l'expérience : réussie,
  mitigée ou ratée, avec une leçon. Ces leçons nourrissent les conseils suivants.
- Expériences mesurées (`assistant/experiments.py`, outils `start_experiment`,
  `list_experiments`, `stop_experiment`) : une hypothèse, un indicateur, un sens, une variation
  minimale et une durée.
  - Le verdict (confirmée, infirmée ou non concluante) est calculé sans modèle, à partir du
    tableau de bord SaaS.
  - Il est présenté honnêtement comme une lecture avant/après, sans groupe témoin.

## [0.11.0] - 2026-10-14

### Added

- Compétences apprises (`assistant/learning.py`, vue « Apprentissage »).
  - Après une mission dont chaque étape a été vérifiée, un moteur peu coûteux relit le rapport et
    peut proposer une compétence réutilisable : méthode, vérifications, pièges, sans donnée
    personnelle ni secret. Ce moteur se règle avec le nouveau rôle `learning_model` ; vide, c'est
    le vérificateur.
  - Spectre peut aussi en proposer une quand tu lui apprends quelque chose (outil
    `propose_skill`).
  - Rien n'est écrit sans ta validation. Une mise à jour garde la version précédente dans
    `skills/.history/`.
  - Les compétences validées (`~/.spectre/assistant/skills/<nom>/SKILL.md`) sont listées dans le
    prompt du cerveau et dans celui des agents de mission. L'outil `skill` en lit une et compte
    ses usages.
- Curateur, une fois par jour. Une compétence inutilisée depuis 60 jours devient « obsolète » ;
  au bout de 120 jours, elle est archivée dans `skills/.archive/`, d'où on peut la restaurer. Il
  ne supprime jamais rien, et les compétences épinglées sont gardées.
- Recherche dans les conversations passées (outil `search_history`, recherche de la vue
  Apprentissage). Index plein texte FTS5, insensible aux accents, avec les missions en plus. Les
  anciennes conversations sont indexées une fois, au démarrage.
- Points de restauration des missions. Chaque mission note la position du journal d'annulation
  à son début et à sa fin. `rollback_mission` (avec ta validation) ou le bouton « Annuler ses
  changements de fichiers » de la vue Missions défait ses écritures, déplacements et
  suppressions.
- Réglage `learn_from_missions` (activé par défaut).

### Changed

- `actions.undo_row` annule une entrée du journal. `undo_last` et `rollback_mission` s'en servent.

## [0.10.0] - 2026-10-14

### Added

- Suivi SaaS par entreprise (`assistant/saas.py`, section « Tableau de bord » de la vue
  Entreprise). Les sources sont toutes en lecture seule :
  - disponibilité d'un site : vérifiée toutes les 5 minutes, avec le temps de réponse ;
  - Stripe : MRR (abonnements actifs ramenés au mois), abonnés, nouveaux abonnés, résiliations
    et churn sur 30 jours, paiements échoués, encaissé net des remboursements. Une clé
    restreinte en lecture suffit ;
  - Supabase : comptage exact d'une table, et inscriptions sur 7 jours avec une colonne de date
    (requête HEAD avec `Prefer: count=exact`) ;
  - GitHub : dernière CI de la branche par défaut, tickets et PR ouverts ;
  - n'importe quelle API JSON : des nombres choisis par chemin, par exemple
    `errors=data.count` ;
  - chiffres saisis à la main, comme les dépenses marketing pour le CAC.
- Les clés restent dans `~/.spectre/assistant/.env`. Elles ne sont jamais renvoyées par l'API et
  sont effacées avec leur source.
- Indicateurs calculés : ARR, ARPA, LTV (ARPA / churn mensuel), CAC (dépenses marketing /
  nouveaux abonnés), LTV/CAC et disponibilité sur 7 jours.
- Tuiles du tableau de bord : valeur, évolution sur 7 jours (avec signe et flèche, verte ou
  rouge selon que la hausse est bonne ou non) et tendance sur 12 points. Pastilles d'état : site
  en ligne, CI, sources en erreur.
- Alertes : seuil, nombre d'échecs d'affilée, délai avant de réalerter, et message quand la
  situation revient à la normale.
  - Une source « site » crée l'alerte « site indisponible » (2 échecs d'affilée).
  - Une source GitHub crée l'alerte « CI en échec ».
  - Une source Stripe crée l'alerte « paiements échoués ».
- Rapport : outil `saas_report` (indicateurs et évolution, sources en erreur, alertes de la
  semaine). Le bouton « Programmer le rapport du lundi 9h » crée une routine qui le commente en
  chef d'entreprise et propose trois actions.
- Outils `saas_report`, `set_metric`, `add_monitor`, `add_alert`. Collecte en arrière-plan
  depuis la boucle proactive. Historique de 120 jours.

### Changed

- `providers.write_env_value` écrit ou retire une valeur du `.env` de Spectre. La passerelle
  Telegram l'utilise aussi.

## [0.9.0] - 2026-10-14

### Added

- Routines (vue « Automatisation », outils `create_routine`, `list_routines`, `update_routine`,
  `delete_routine`, `run_routine`) : ce que Spectre fait à heure fixe.
  - L'horaire s'écrit en mots : « tous les jours à 9h », « chaque lundi à 9h », « en semaine à
    8h30 », « toutes les 2 heures », « dans 30 minutes », « 2026-11-02 à 14h ». Une expression
    cron est aussi acceptée.
  - Trois types : `mission` (une mission complète, avec un agent et le brief d'une entreprise
    si besoin), `question` (le cerveau répond avec ses outils et tu reçois la réponse) et
    `rappel` (le texte tel quel, sans appel au modèle).
  - Après une panne, une routine en retard ne tourne qu'une fois.
  - Les échecs sont comptés, et tu es prévenu après 3 échecs d'affilée.
  - Pas plus d'une exécution toutes les 5 minutes.
- Webhooks entrants signés (`/hooks/<nom>`, vue Automatisation, outil `list_webhooks`).
  - Signatures vérifiées : GitHub (`X-Hub-Signature-256`), Stripe (`Stripe-Signature`, 5
    minutes de tolérance) ou HMAC générique (`X-Spectre-Signature`). Sans signature valide,
    l'appel est refusé.
  - Filtres d'événements et anti-doublon (renvois). Limites : 30 appels par minute et 1 Mo par
    appel.
  - Deux actions possibles : « me prévenir », avec un résumé sans appel au modèle, ou « lancer
    une mission ». Dans ce cas, l'événement est transmis comme des données, jamais comme des
    instructions.
- Passerelle Telegram : parler à Spectre depuis Telegram, et recevoir ses notifications et ses
  demandes de validation (`/approve N`, `/deny N`, `/status`, `/model`).
  - Le jeton du bot reste dans `~/.spectre/assistant/.env`.
  - Une conversation doit être jumelée par un code à usage unique, valable 10 minutes. Les
    autres conversations et les groupes sont ignorés.
- Messages entre agents (`ask_agent`) : un agent, ou Spectre, pose une question à un autre
  agent. Celui-ci répond sur son propre moteur, avec son rôle et sans outils.

## [0.8.0] - 2026-10-14

### Added

- Entreprises : Spectre t'aide à diriger tes entreprises (vue « Entreprise », outils
  `create_company`, `list_companies`, `company_board`). Chacune a un organigramme de huit
  départements : direction, finance, marketing, ventes, support, produit et technique,
  juridique, opérations. Sur chaque poste, tu places l'agent de ton choix (`set_post`) : un
  agent créé, que tu nommes toujours toi-même, un agent intégré, un moteur, ou le réglage par
  défaut.
- Tableau de tâches durable (`add_task`, `update_task`) : départements, priorités, dépendances
  et statuts (à faire, en cours, à valider, bloquée, faite, annulée).
  - Une tâche lancée (`start_tasks`, bouton « Lancer ») part en mission avec le brief de son
    poste et de l'entreprise.
  - À la fin de la mission, la tâche passe « faite » si chaque étape a été vérifiée, sinon « à
    valider ». Elle passe « bloquée » si la mission échoue.
- La direction découpe un objectif en tâches (`plan_company`, « Découper en tâches »), avec les
  départements et les dépendances. La mission `company_plan` tourne en arrière-plan.
- Pilote automatique par entreprise (`set_autopilot`, désactivé par défaut) : Spectre lance
  lui-même les tâches prêtes.
- Missions en parallèle (`mission_parallel`, 2 par défaut, de 1 à 4).
- Pilotage des missions en cours :
  - `steer_mission` et le bouton « Orienter » donnent une consigne, lue avant l'étape suivante ;
  - `stop_mission` et le bouton « Arrêter » arrêtent une mission : tout de suite si elle est
    en attente, après l'étape en cours sinon.

### Changed

- Une mission garde toutes les clés de son plan (tâche, brief) quand elle enregistre ses
  étapes.

## [0.7.0] - 2026-10-14

### Added

- Moteurs : chaque rôle de l'assistant (cerveau, exécution des étapes, vérificateur,
  planificateur) tourne sur le LLM de ton choix. Une référence de moteur est `opus`, `sonnet`,
  `haiku`, `chatgpt`, `mistral` ou `fournisseur:modèle`, pour tout point d'accès compatible
  OpenAI : LM Studio et Ollama en local, OpenRouter, Groq, Gemini, Mistral (API), DeepSeek,
  OpenAI, xAI, Anthropic (API), et d'autres via `providers.json`. Les clés sont lues dans
  l'environnement ou dans `~/.spectre/assistant/.env`, jamais écrites dans la configuration.
  Inspiré de Hermes Agent (`docs/analyse-hermes.md`).
- Moteurs de secours (`fallback_models`) : quand un moteur échoue ou atteint la limite de
  l'abonnement, les suivants prennent le relais dans l'ordre, pour la conversation, les plans,
  les étapes, la vérification, les rapports et les visites amicales.
- `/model` dans la conversation (`/model`, `/model <moteur>`, `/model <rôle> <moteur>`,
  `/model secours …`), section « Moteurs » dans la vue Agents (rôles, secours, fournisseurs
  et leurs modèles), API `GET/POST /api/assistant/models`.
- Outils du cerveau `list_models`, `set_model` et `set_fallbacks` (catégorie `model`, réversible).
  Le service recharge `config.json` quand le cerveau le modifie.
- Un agent créé peut tourner sur `fournisseur:modèle`.
- Outil `powershell` : Spectre peut utiliser PowerShell 7 sur le PC. L'analyseur de PowerShell
  examine chaque commande sans l'exécuter. La lecture seule (cmdlets `Get-`, `Test-`,
  `Measure-`… sans effet de bord) s'exécute tout de suite dans un `pwsh` neuf et invisible. Le
  reste est de niveau critique et attend ta validation, puis s'exécute dans la console visible du
  module open source PowerShell.MCP (yotsuda, MIT), ou sans console s'il manque.

### Changed

- Un moteur autre que Claude reçoit le fil récent de la conversation ; au retour sur Claude,
  la session repart avec ce fil. Les appels d'outils de ces moteurs passent par le même portail
  de gouvernance et le même audit.
- Le choix du cerveau et des agents d'exécution passe des Réglages à la vue Agents › Moteurs.

## [0.6.8] - 2026-10-10

### Changed

- Dans le dossier de travail des agents (`~/.spectre/assistant/workspace`), réécrire un fichier
  existant ne demande plus de validation : les missions ne s'enlisent plus dans les demandes et
  ne multiplient plus les copies (`_v2`, `00b`…). L'ancienne version est toujours sauvegardée
  dans la corbeille de Spectre (hors de portée des agents) et dans le journal d'annulation, et le
  compte rendu de l'outil indique où. Ailleurs, réécrire un fichier demande toujours ton accord.

## [0.6.7] - 2026-10-10

### Fixed

- L'outil `read_file` coupait tout fichier à 20 000 caractères sans moyen de lire la suite : les
  agents ne pouvaient jamais lire la fin d'un long rapport. Il accepte maintenant `offset` et,
  quand il reste du texte, indique combien et avec quel `offset` relire.

## [0.6.6] - 2026-10-10

### Added

- Surveillance dans le lanceur (`tools/spectre_launcher.py`) : toutes les 30 s, il vérifie que
  Spectre répond. Après deux vérifications sans réponse, il note dans
  `~/.spectre/assistant/watchdog.log` l'heure, la mémoire libre et la fin de `spectre.log`, puis
  relance Spectre. Il laisse tranquille un Spectre arrêté exprès (marque `stopped` posée par le
  lanceur et par `spectre-stop.cmd`, retirée à chaque démarrage), attend 2 minutes après un
  démarrage, et abandonne après 3 relances en une heure (une seule ligne dans le journal).
- `spectre.log` se termine par le code de sortie de Spectre quand il s'arrête : s'il disparaît
  sans cette ligne, c'est qu'il a été tué.

## [0.6.5] - 2026-10-10

### Fixed

- Les missions ne pouvaient pas écrire dans leur dossier de travail
  (`~/.spectre/assistant/workspace`) : tout le dossier interne de Spectre était verrouillé, les
  fichiers finissaient dans le dossier personnel et le vérificateur refusait les étapes. Le
  dossier de travail est maintenant ouvert aux agents, qui reçoivent son chemin complet ; le
  reste du dossier interne reste verrouillé.
- Dans ce dossier, les fichiers que les programmes d'agents lisent comme consignes ou réglages
  (`CLAUDE.md`, `AGENTS.md`, tout fichier ou dossier caché comme `.claude/` ou `.mcp.json`)
  restent interdits en écriture, pour qu'un agent ne puisse pas s'accorder de droits.

## [0.6.4] - 2026-10-10

### Added

- Skill `spectre-crypto` : minage, blockchains, NFT, services crypto (plateformes,
  portefeuilles, DeFi, staking) et trading — données vérifiées en direct, sécurité (jamais de
  phrase de récupération ni de clé), aucune transaction sans accord, pas de promesse de gain.

### Changed

- Salutations (`assistant/greetings.py`) : Spectre salue une seule fois par jour, selon l'heure
  exacte (bonjour, bonsoir, la nuit…). Le jour est gardé en base : même éteint puis rallumé dans
  la journée, il ne redit plus bonjour et lance plutôt la conversation (une question, une
  remarque, une suite à ce qu'il sait de l'utilisateur), puis écoute la réponse.
- Ses répliques varient : à l'arrivée devant la caméra, une réplique fraîche est écrite à chaque
  fois en évitant ses 12 dernières (listes variées si le modèle ne répond pas) ; le briefing du
  matin ne commence plus toujours par « Bonjour » ; ses visites et le cerveau connaissent
  l'heure exacte, le moment de la journée, la règle du salut et la consigne de varier.
- Le téléphone dit aussi la réplique d'arrivée à voix haute.

## [0.6.3] - 2026-10-10

### Added

- Spectre parle aussi sur le téléphone : ses réponses aux messages écrits et ses initiatives
  (dont les visites où il vient discuter, suivies de l'écoute) sont dites à voix haute sur
  l'appareil distant. Le navigateur n'autorise le son qu'après un toucher : ce qui arrive avant
  attend le premier toucher de l'écran. Nouvelle route `POST /api/assistant/speak`.

### Fixed

- Ce que Spectre apprend en dehors de la conversation (page Mémoire, missions, autre
  processus) n'était vu que le lendemain : la conversation du jour reprise gardait la mémoire
  de son début. Il en recommence maintenant une quand sa mémoire a changé, avec un rappel des
  derniers échanges pour garder le fil ; ce qu'il retient lui-même pendant un échange ne la
  relance pas.
- Sur un écran tactile, le son est débloqué quand le doigt se lève (règle des navigateurs).

## [0.6.2] - 2026-10-10

### Added

- Lanceur du téléphone : boutons « Redémarrer » et « Arrêter » (mot de passe, confirmation
  avant l'arrêt) en plus de « Lancer » ; il indique si le PC est sur batterie.
- Avertissements sur le téléphone : bandeau quand le PC est sur batterie (il peut se mettre en
  veille), bandeau quand le PC ne répond plus pendant qu'on utilise Spectre, et page « PC
  injoignable » (veille, éteint, sans réseau, Tailscale coupé) au lieu d'une erreur du
  navigateur. L'état de l'alimentation est dans `/api/assistant/status` (`power`).

### Fixed

- Le journal de Spectre et du lanceur ne se remplit plus de fausses erreurs (connexion fermée
  par le navigateur ou le téléphone pendant un chargement) ; les vraies erreurs restent visibles.

## [0.6.1] - 2026-10-10

### Fixed

- Reconnaissance de la voix plus fiable :
  - Spectre attend 1,4 s de silence (au lieu de 0,9) avant de considérer la phrase finie, et
    1,8 s sur le téléphone : une pause naturelle ne coupe plus la phrase (« Ouvre. »).
  - Les 0,4 s qui précèdent la parole sont gardées : la première syllabe n'est plus perdue.
  - Filtre de voix (VAD) avant la transcription et recherche plus large (beam 5) : sur ce PC,
    trois phrases de test passent de 6 % de mots erronés à aucun, pour environ 3 s par phrase.
  - Le contexte donné au modèle est réduit à une phrase : l'ancienne liste d'applications était
    recopiée comme si elle avait été dite quand l'audio était confus (« Ouvre YouTube, Google
    Chrome, »), et un écho du contexte est ignoré.

### Added

- Réglage « Compréhension de ta voix » : small (rapide), medium ou large-v3-turbo (un peu plus
  précis, 3 à 4 fois plus lents sur ce PC).

## [0.6.0] - 2026-10-10

### Added

- Spectre vient de lui-même parler à l'utilisateur pour mieux le connaître (`befriend_per_day`,
  2 par défaut, 0 à 4 ; `befriend_hours`, 10-21 par défaut) : une question sincère sur un sujet
  qu'il connaît mal (catégories de la mémoire les moins remplies) ou une suite à ce que
  l'utilisateur lui a confié, rédigée par l'agent supérieur sans répéter ses dernières venues.
  Il la dit à voix haute puis écoute pour qu'on lui réponde directement ; elle apparaît aussi
  dans la conversation et les initiatives. La réponse arrive au cerveau avec ce que Spectre
  avait dit, et la consolidation de la nuit en retient les faits durables.
- Garde-fous : jamais pendant une conversation ni dans les 20 minutes qui suivent un échange,
  3 heures au moins entre deux venues (6 si la précédente est restée sans réponse), moment
  imprévisible, rien d'intrusif, pas de culpabilisation ; Spectre reste honnête sur ce qu'il
  est et ne cherche pas à remplacer les proches. Réglages dans « Réglages de l'assistant ».

## [0.5.3] - 2026-10-10

### Fixed

- Spectre pouvait s'arrêter juste après son démarrage quand deux lancements se chevauchaient
  (raccourci, démarrage de Windows, lanceur du téléphone) : sous Windows, deux instances
  pouvaient écouter le même port et se disputer le micro et la caméra. Les serveurs de Spectre
  et du lanceur réservent désormais leur port en exclusivité, et `spectre-assistant.ps1`
  n'autorise qu'un démarrage à la fois et attend un Spectre encore en chargement au lieu d'en
  lancer un second.

## [0.5.2] - 2026-10-10

### Fixed

- Le bouton « Connexion à distance » est aussi visible sur le téléphone (icône en haut de
  l'écran et menu) ; ouvert depuis le téléphone déjà connecté, il le signale.

### Added

- Lanceur toujours allumé (`tools/spectre_launcher.py`, bibliothèque standard seulement,
  127.0.0.1:8764), publié par Tailscale sous `/lanceur/` : quand Spectre est fermé sur le PC,
  le téléphone y est renvoyé automatiquement et peut le relancer avec le mot de passe (5 essais
  puis une minute de blocage). Démarré par `tools/spectre-assistant.ps1`, il survit à
  « Arrêter Spectre ». Le lien du lanceur apparaît dans la fenêtre « Connexion à distance ».

## [0.5.1] - 2026-10-10

### Added

- Assistant : bouton « Connexion à distance » (rail et barre du haut) qui affiche le lien
  Tailscale de Spectre et son QR code à scanner avec le téléphone, l'état de Tailscale, du mot
  de passe et de la publication, et un bouton pour activer `tailscale serve` s'il est inactif
  (seulement avec un mot de passe ; le nom du tailnet est alors accepté sans relancer).
  Le QR code est généré par Spectre (`assistant/qrcode.py`, sans dépendance).
- Assistant : vue « Agents » avec le nom, le moteur et le rôle de chaque agent — Spectre
  (Opus 5.5), Gétro (Sonnet), Kaïto (Haiku, vérificateur), Kyra (ChatGPT via Codex) et Syfer
  (Mistral via Vibe) — puis la chaîne de rédaction Scout, Scribe et Warden ; un outil
  introuvable est signalé.
- Missions : choix de l'agent qui exécute une mission lancée depuis l'interface.
- Agents créés : Spectre peut créer de nouveaux agents (`create_agent`, `list_agents`,
  `delete_agent`) avec un nom, toujours donné par l'utilisateur (Spectre le lui demande et
  n'en invente jamais), un moteur (Opus, Sonnet, Haiku, ChatGPT ou Mistral), un rôle et des
  consignes. Une mission confiée à l'un d'eux tourne sur son moteur avec son rôle ; le plan, la
  vérification par Kaïto et le rapport ne changent pas. Création et suppression aussi depuis la
  vue « Agents » ; supprimer un agent demandé par Spectre passe par ta validation.

## [0.5.0] - 2026-10-09

### Added

- `spectre batch FICHIER` : plusieurs demandes d'un coup. Par défaut via l'API Message Batches
  (50 % moins cher, asynchrone) avec un lot par étape pour toutes les demandes, reprise
  automatique après une interruption (état enregistré après chaque étape) ; `--direct` les
  traite tout de suite une par une. Résultats en JSON Lines.
- `spectre eval CAS` : évaluation sur des cas de test, contrôles automatiques (mots, termes
  présents ou absents, validation par Warden, coût maximal) et, avec `--judge`, critères notés
  par un juge ; rapport, `--json`, code de sortie 1 si un cas échoue, `--demo` sans clé.
- Agents branchables sans code : `spectre-agents.toml` (ou `SPECTRE_AGENTS_FILE`) ajoute des
  agents après Scout, Scribe ou Warden, qui lisent et réécrivent un texte de la chaîne.
- Mise en cache des prompts (`SPECTRE_PROMPT_CACHE`, désactivée par défaut) : la partie que
  Scribe et Warden relisent à chaque tour de révision est marquée pour le cache.
- Coûts : tokens lus et écrits en cache comptés au bon prix (lecture 0,10 à 0,20 $/M, écriture
  1,25 × l'entrée), remise de 50 % des lots, colonnes « Cache » dans `--costs` quand il sert.
- Exemples : `examples/spectre-agents.example.toml`, `demandes.example.txt`,
  `cas.example.jsonl`.

### Changed

- Les nœuds sont génériques (`spectre.steps.Step` + `nodes.make_node`) : ce que lit et écrit
  chaque agent est décrit une seule fois et partagé par le graphe et le mode lots.

## [0.4.0] - 2026-10-09

### Added

- Verdict de Warden : après son texte corrigé, Warden écrit `=== VERDICT ===` et un objet
  JSON `{"approved": ..., "issues": [...]}` (`spectre.verdict`). Un verdict absent ou illisible
  vaut approbation : le texte n'est jamais perdu.
- Boucle de révision : si Warden rejette le texte, Scribe le réécrit avec la liste des points à
  changer, puis Warden relit de nouveau, dans la limite de `SPECTRE_MAX_REVISIONS` tours (1 par
  défaut, de 0 à 5). `run(..., max_revisions=)` et `build_graph(..., max_revisions=)`.
- `SpectreResult.approved`, `.issues` et `.revisions`, aussi dans `--json`. Un avertissement
  sur stderr signale un texte non validé après le dernier tour.
- CLI : `--stream` affiche en direct sur stderr le travail de chaque agent, tours de révision
  compris (sans la ligne du verdict) ; `--revisions N`.
- Interface web : les tours de révision s'affichent (Scribe et Warden repartent d'un texte
  vide, avec un message), les coûts additionnent tous les tours et la ligne du verdict n'est
  jamais diffusée.

## [0.3.8] - 2026-10-09

### Fixed

- Barre de la page Assistant sur téléphone : avec le bouton caméra, le micro n'était plus au
  centre (six boutons). La caméra passe à gauche du micro et le bouclier des validations, déjà
  présent dans l'en-tête, quitte la barre : cinq boutons, micro au centre.

## [0.3.7] - 2026-10-09

### Added

- Voix depuis le téléphone : sur la page Assistant ouverte depuis un autre appareil, le bouton
  micro enregistre avec le micro de cet appareil (arrêt automatique après une pause, 25 s au
  plus), Spectre transcrit et répond, et sa voix est jouée sur l'appareil, pas sur le PC.
  Nouvelle route `POST /api/assistant/voice` (PCM 16 kHz mono 16 bits, réponse avec le texte
  entendu, la réponse et un WAV).
- Caméra du téléphone : bouton dans la barre de la page Assistant (depuis un autre appareil,
  quand la reconnaissance des visages est active) ; une image toutes les 2 s, analysée comme
  celles de la caméra du PC, avec un aperçu visible ; arrêt au second appui ou en quittant la
  page. Route `POST /api/assistant/frame` (JPEG), `FaceEngine.embeddings_jpeg()`, verrou sur
  le moteur de visages. Aucune image n'est gardée.
- `tools\spectre-assistant.ps1 --silent` : démarrage avec la session Windows (raccourci dans le
  dossier Démarrage), sans ouvrir de page ; il attend jusqu'à 90 s que Tailscale soit connecté
  pour que le téléphone y ait accès dès l'ouverture de session.
- `PiperTTS.render()` produit la voix sans la jouer ; la reconnaissance et la synthèse sont
  protégées par un verrou, car le micro du PC et le téléphone peuvent parler en même temps.

## [0.3.6] - 2026-10-09

### Added

- Accès depuis le téléphone, de partout, par Tailscale : quand Tailscale est installé et qu'un
  mot de passe est défini, `tools\spectre-assistant.cmd` publie Spectre en HTTPS sur le réseau
  privé (`tailscale serve`) sans rien ouvrir sur Internet. Le délai est limité : si Serve n'est
  pas encore activé, Spectre démarre en local seulement.
- `--allow-host NOM` (`spectre-assistant`) : nom d'hôte accepté derrière un relais, en plus de
  localhost ; un mot de passe est alors obligatoire.
- `tools\spectre-password.cmd` choisit le mot de passe de l'interface (variable utilisateur
  `SPECTRE_WEBUI_PASSWORD`), sans l'écrire dans le dépôt.

### Fixed

- Page Rédaction sur téléphone : le bouton micro flottant ne recouvre plus le contenu (il est
  masqué ; l'icône de l'en-tête mène déjà à l'assistant, et ce bouton faisait écouter le PC, pas
  le téléphone) ; le préréglage « Qualité max » n'est plus coupé quand la place le permet.
- Le bouton « Exposer » ne dépasse plus de l'écran sur les téléphones étroits ou avec un texte
  agrandi : le menu des préréglages se resserre à sa place, et sous 380 px la flèche disparaît.
- Un seul micro sur téléphone : celui de l'en-tête (vers l'assistant) ; le bouton de dictée est
  masqué sous 900 px, le clavier du téléphone ayant déjà le sien.

## [0.3.5] - 2026-10-09

### Added

- Deux nouveaux agents d'exécution des missions : **ChatGPT** via Codex CLI (`codex exec`, compte
  ChatGPT) et **Mistral** via Mistral Vibe (`vibe -p`, compte Le Chat ou `MISTRAL_API_KEY`). Ils
  reçoivent les outils de Spectre par MCP (même portail de gouvernance) et la recherche web.
- Réglage `mission_model` : `chatgpt` et `mistral` en plus de `sonnet`, `opus` et `haiku` ;
  `chatgpt_model`, `mistral_model`, `codex_bin` et `vibe_bin`. Pour une seule mission,
  `start_mission` accepte `agent=claude|chatgpt|mistral`, et chaque étape note quel agent l'a faite.
- Spécialités : ChatGPT pour les images, la vidéo et le multimédia ; Mistral pour la cybersécurité
  et les tests d'intrusion (cadre autorisé uniquement). Spectre choisit l'agent selon le sujet.
- Les sous-agents ont un nom : Gétro (Sonnet), Kaïto (Haiku, le vérificateur), Kyra (ChatGPT) et
  Syfer (Mistral). `start_mission` accepte le nom (sans tenir compte des majuscules ni des
  accents) ; les étapes, les rapports et l'interface affichent qui a fait quoi.

### Fixed

- Changer l'agent d'exécution dans les réglages s'applique tout de suite, sans relancer Spectre.

## [0.3.4] - 2026-10-09

### Added

- Sélecteur « Rédaction | Assistant » sous le logo, dans les deux pages, pour passer de l'une à
  l'autre ; sur téléphone, une icône dans l'en-tête fait la même chose.
- `tools/spectre-stop.cmd` arrête l'assistant.

### Changed

- `tools/spectre-assistant.cmd` démarre Spectre en arrière-plan, sans fenêtre de console : fermer
  une fenêtre ou un Ctrl+C ne l'interrompt plus par accident ; s'il tourne déjà, le lanceur ouvre
  simplement l'interface.

## [0.3.3] - 2026-10-09

### Added

- Bouton « Parler à Spectre » sur la page d'accueil, visible quand l'assistant tourne : un clic le
  fait écouter sans le mot d'éveil ; son anneau suit l'état de la voix et le niveau sonore.
- Lanceur Windows `tools/spectre-assistant.cmd` (double-clic) : fenêtre dédiée, journal dans
  `~/.spectre/assistant/spectre.log`.

### Fixed

- L'assistant ne s'interrompt plus brutalement (« forrtl: error (200) ») sur un événement de la
  console : le lanceur désactive le gestionnaire du runtime Intel Fortran des bibliothèques vocales.
- Téléphone : le lien « Assistant » du menu ne déborde plus de l'écran.

## [0.3.2] - 2026-10-09

### Changed

- Timbre futuriste plus clair : la doublure à l'octave inférieure et la copie décalée vers le grave
  (le « fond sombre » derrière la voix) sont retirées ; l'harmonique aiguë, le côté métallique et
  la réverbération restent.

## [0.3.1] - 2026-10-09

### Changed

- Nouveau logo : un casque corinthien de Spartiate en trois-quarts, crête de crin aux sept
  couleurs de Spectre, capteur à la tempe et pistes de circuit gravées (logo complet animé sur
  l'accueil, la connexion et la présence de l'assistant ; version simplifiée dans le menu, dont
  les bandes de Scout, Scribe et Warden suivent toujours le pipeline ; favicon et icônes PNG).
  `tools/make_logo.py` remplace `tools/make_icons.py`.
- Voix de l'assistant plus fluide : débit réglable (posé, naturel, vif ; naturel par défaut),
  rythme plus régulier et phrases enchaînées avec une courte respiration.

## [0.3.0] - 2026-10-08

### Added

- Assistant vocal `spectre-assistant` (ou `python -m spectre.assistant`), qui répond au nom de
  Spectre. Spectre est l'agent supérieur, sur Opus 5.5 via Claude Code `claude -p` et
  l'abonnement : il converse, planifie les missions et en rédige les rapports ; les étapes vont
  aux agents d'exécution (Sonnet 5.5), la vérification à Haiku 4.5, la rédaction soignée à
  Scout, Scribe et Warden. Identifiants exacts dans `config.ASSISTANT_MODELS`.
- Voix locale (extra `voice`) : mot d'éveil « Spectre » (Vosk), transcription faster-whisper
  `small` avec vocabulaire d'applis, synthèse Piper (voix d'homme « pierre ») avec un timbre
  d'IA de bord (futuriste, androïde vocodé, hologramme, vaisseau), mots d'arrêt et relance sans
  mot d'éveil. Choix automatique d'un vrai micro (jamais « Mixage stéréo »).
- Sphère vocale façon HUD à la place du dialogue : anneau de particules qui réagit au niveau
  sonore réel, SPECTRE qui s'assemble en particules au réveil, sous-titres, indicateurs, dock.
- Serveur MCP de 20 outils : heure, système, écrans, mémoire, ouverture d'applis et de pages
  (sur l'écran choisi), fichiers (lister, lire, chercher, écrire, déplacer, supprimer, annuler),
  rappels, missions, présence.
- Portail de gouvernance (risque × politique × budget), validations dans l'interface et journal
  d'audit immuable. Écritures journalisées et annulables, corbeille propre à Spectre.
- Mémoire qui apprend (SQLite FTS5, renforcement, remplacement, oubli, correction, miroir
  Markdown), consolidation nocturne, briefing du matin, rappels, missions vérifiées avec rapport.
- Reconnaissance des visages optionnelle (extra `vision`, `--camera`) : OpenCV Zoo YuNet (MIT)
  + SFace (Apache 2.0) + anti-fraude MiniFASNet (Apache 2.0) en local, modèles vérifiés par
  SHA-256 ; enregistrement volontaire, empreintes seulement (aucune photo), accueil au retour,
  présence dans le HUD, outil `who_is_there`.
- La limite d'usage de l'abonnement est annoncée en français avec l'heure de réinitialisation.
- Page `assistant.html` dans l'univers des raies d'émission, liée depuis l'interface principale.

### Changed

- Feuille de route : la boucle de révision et le streaming de la CLI passent en v0.4.0, les
  nœuds extensibles, le batch, le caching et l'évaluation en v0.5.0.

## [0.2.0] - 2026-10-08

### Added

- Interface web `spectre-web` (ou `python -m spectre.web`) : serveur de la bibliothèque standard
  et page HTML/CSS/JS sans build, inspirée de Hermes WebUI. Chaîne des agents en direct (SSE)
  dessinée comme des raies d'émission, onglet Corrections (diff brouillon → texte final),
  inspecteur des tokens et coûts, historique de plaques numérotées (recherche, tags, projets,
  épingles, archives, export Markdown/JSON/HTML, import), préréglages d'agents, mode démo,
  dictée vocale, commandes `/`, palette `Ctrl+K`, thèmes sombre/clair, français/anglais,
  notifications, PWA, mise en page ordinateur/tablette/téléphone.
- Mot de passe facultatif (`SPECTRE_WEBUI_PASSWORD`, cookie signé, limitation des essais),
  obligatoire pour ouvrir l'interface au réseau local (`--host 0.0.0.0`).
- Logo de Spectre : un fantôme formé de sept raies spectrales, généré par `tools/make_icons.py`.
- Préréglages d'agents intégrés (`WEB_PRESETS` dans `config.py`).

## [0.1.1] - 2026-10-07

### Added

- Repli côté serveur en cas de refus de Sonnet 5.5 ou d'Opus 5.5 (`fallbacks: "default"`),
  désactivable avec `SPECTRE_FALLBACKS=0`. `usage` enregistre le modèle qui a réellement
  répondu, et le coût est calculé à son tarif (prix ajoutés pour Opus 4.8, Opus 5, Sonnet 5).
- Champ `truncated` dans chaque ligne de `usage`, à `true` si la limite `max_tokens` est atteinte.
- La CLI renvoie le code `130` avec le message « Interrompu. » sur Ctrl+C, au lieu d'une trace.

### Fixed

- Les tests hors ligne ignorent toutes les variables `ANTHROPIC_*` du shell
  (`ANTHROPIC_WORKSPACE_ID` faisait échouer un test).
- `SPECTRE_TIMEOUT` et `SPECTRE_MAX_RETRIES` sont documentés dans le README et `.env.example`.
- Scout ne termine plus son brief par une question à l'utilisateur : le brief part directement
  au rédacteur (constaté lors d'un essai réel).

### Security

- Actions GitHub de la CI épinglées par SHA de commit.

## [0.1.0] - 2026-10-06

Première version de **Spectre**, construite sur le dépôt
[`template-foundry`](https://github.com/RaptorsGeek7612/template-foundry), dont le contrat
Solidity `Voting` (Foundry) est conservé à côté du package Python. L'historique des versions
0.1.x du template n'est pas repris ici.

### Added

- Pipeline LangGraph linéaire `Scout → Scribe → Warden` à état typé (`SpectreState`) :
  - **Scout** (`claude-haiku-4-5`) produit un brief (intention, public, contraintes, plan) ;
  - **Scribe** (`claude-sonnet-5-5`, effort `medium`) rédige le texte complet ;
  - **Warden** (`claude-opus-5-5`, effort `high`) vérifie et renvoie la version corrigée.
- Registre de modèles centralisé (`spectre/config.py`), surchargeable par variables
  d'environnement `SPECTRE_<AGENT>_MODEL`, `SPECTRE_<AGENT>_MAX_TOKENS`, `SPECTRE_<AGENT>_EFFORT`.
- Limite de sortie de 16 000 tokens pour Scribe et Warden, dont la réflexion (toujours active)
  consomme une partie ; délai d'attente HTTP de 600 s par défaut (`SPECTRE_TIMEOUT`).
- Prise en charge des clés liées à un utilisateur (`sk-ant-usr...`) via `ANTHROPIC_WORKSPACE_ID`.
- Suivi des tokens et du coût en dollars par agent et au total (`usage`, `total_cost_usd`).
- Erreurs explicites nommant l'agent en cas de refus du modèle ou de sortie vide.
- API bibliothèque : `from spectre import run, build_graph`, avec injection de modèles pour
  tester sans réseau.
- CLI `spectre` avec `--file`, `--costs`, `--json` et `--version`.
- Tests pytest sans appel réseau (faux modèles LangChain), tests réels marqués `live`.
- `CLAUDE.md` et skills des agents de développement (`.claude/skills/spectre-*`).
- Documentation : cahier des charges, PDR produit, PDR architecture, brainstorming.
- Dependabot pour l'écosystème `uv` (dépendances Python).

- Job CI `python` : `uv sync --frozen`, `ruff format --check`, `ruff check`, `mypy src` et
  `pytest` (couverture ≥ 90 %), à côté du job Foundry `test`.
- Badge de couverture Python (`coverage-python.json`), publié sur la branche `badges` avec le
  badge Foundry (`coverage.json`).

### Changed

- Contrat `Voting` passé en **Solidity 0.8.35** (`solc_version = "0.8.35"` dans `foundry.toml`,
  `pragma solidity ^0.8.35;`).
- La release automatique attend désormais les deux jobs de test (`test` Foundry et `python`).
- `.env.example` : ajout de `ANTHROPIC_API_KEY` et des surcharges `SPECTRE_*` aux variables
  Sepolia existantes.
- README, CONTRIBUTING, SECURITY, exemples, templates d'issue et de PR mis à jour pour le dépôt
  hybride Spectre + Foundry.
