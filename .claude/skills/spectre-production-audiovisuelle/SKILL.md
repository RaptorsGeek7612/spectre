---
name: spectre-production-audiovisuelle
description: Le métier de la production audiovisuelle pour Spectre (et l'agente Kyra, productrice et réalisatrice) — clips, séries et films, du développement à la livraison — pitch, bible de série, scénario au format, dépouillement, découpage technique, storyboard et animatique, plan de travail et budget, grammaire des plans, tournage, montage, son, étalonnage, VFX, sous-titres, livraison (formats, loudness), droit français (auteurs, image, musique, autorisations) et chaîne d'outils libres. À charger dès qu'une demande touche un clip, une série, un film, un court-métrage, une web-série, une animation, un tournage ou un montage.
---

# spectre-production-audiovisuelle — produire un clip, une série, un film

Kyra pense comme une **productrice-réalisatrice** : l'intention d'abord, puis le plan pour
la fabriquer avec les moyens réels (budget, matériel, PC sans carte graphique). Pour l'écriture
du récit lui-même, charger aussi `spectre-creation` ; pour la promo, `spectre-pub-communication`.

## La chaîne de production (toujours dans cet ordre)
1. **Développement** — intention, logline (une phrase : héros, désir, obstacle, enjeu), pitch,
   synopsis, traitement ; pour une série, la **bible**.
2. **Écriture** — séquencier, puis scénario au format (Fountain), réécritures.
3. **Pré-production** — dépouillement, découpage technique, storyboard et animatique, liste de
   plans, plan de travail, budget, casting, repérages, autorisations.
4. **Tournage** (ou génération/animation) — couverture des scènes, son direct, rapports.
5. **Post-production** — dérushage, montage (ours → premier montage → montage final), son,
   musique, étalonnage, VFX, titres, sous-titres.
6. **Livraison** — masters, formats de diffusion, sous-titres, kit promo.
Chaque étape produit un **livrable** dans le workspace ; proposer la suivante et attendre le oui.

## Formats : ce qui change
- **Clip musical** : tout part de la chanson. Écouter, relever le **BPM** et la structure
  (intro, couplets, refrains, pont), faire une **carte des temps forts**. Choisir un concept :
  performance, narratif, conceptuel, ou hybride. Le montage coupe **sur le temps** ; le
  refrain revient avec une image-signature. Tournage en playback (la chanson diffusée sur le
  plateau). Le clip doit tenir même sans le son. Prévoir des déclinaisons verticales 9:16.
- **Série** : la **bible** (concept, ton, univers, personnages et leurs arcs, règles du monde,
  arches de saison, résumé des épisodes), un **pilote** qui pose le monde et la promesse.
  Arcs **horizontaux** (feuilletonnants) et **verticaux** (bouclés par épisode). Structure
  d'épisode : teaser/accroche, actes, cliffhanger. Formats courants : web-série 5-12 min,
  26 min, 52 min. Cohérence de saison : tenir une continuité (personnages, lieux, objets).
- **Film** (court ou long) : structure en trois actes ou parcours du héros, mais au service
  du personnage ; une page de scénario ≈ une minute d'écran. Court-métrage : une idée forte,
  peu de lieux, peu de personnages.

## Pré-production, le cœur du métier
- **Dépouillement** : pour chaque séquence, lieux, jour/nuit, personnages, figurants,
  accessoires, costumes, effets, véhicules, animaux, besoins son.
- **Découpage technique** : chaque plan avec son **échelle** (plan d'ensemble, plan moyen,
  américain, rapproché, gros plan, très gros plan, insert), son **angle** (plongée,
  contre-plongée, niveau des yeux), son **mouvement** (fixe, panoramique, travelling, steadicam,
  épaule, drone), l'objectif, la durée, le son.
- **Storyboard** puis **animatique** (storyboard monté avec le son et les durées) pour valider
  le rythme avant de tourner ou de générer.
- **Plan de travail** : regrouper par lieu et par comédien, pas dans l'ordre du récit.
- **Budget** : au-dessus de la ligne (droits, auteurs, réalisation, acteurs) et en dessous
  (technique, matériel, décors, post-production) + imprévus 10 %.

## Grammaire de l'image et du montage
- **Règle des 180°** et raccords (regard, mouvement, axe) pour que l'espace reste lisible.
- **Couverture** d'une scène : plan large de situation, champs-contrechamps, inserts,
  plans de coupe ; tourner plus que le strict nécessaire.
- **Lumière** : trois points (clé, débouchage, contre-jour) ; la couleur raconte (color script).
- **Montage** : couper sur le mouvement ou sur le regard ; montage alterné ou parallèle ;
  effet Koulechov (le sens naît de l'enchaînement) ; coupes J et L (le son précède ou suit
  l'image) ; le rythme sert l'émotion. Enlever tout ce qui ne fait pas avancer.
- **Son** = la moitié du film : dialogues propres, ambiances, bruitages, musique, mixage.
  Loudness de livraison : **-14 LUFS** pour le web et les plateformes, **-23 LUFS** pour la
  télévision (norme EBU R128).
- **Étalonnage** : d'abord corriger (balance, exposition, raccord entre plans), puis créer
  le look ; garder une cohérence par séquence.
- **Livraison** : 25 images/s pour la télévision française, 24 pour le cinéma ; 16:9 pour le
  web et la TV, 1.85 ou 2.39 pour le cinéma ; un master haute qualité, puis des versions de
  diffusion (H.264/H.265), et un DCP pour une salle (DCP-o-matic, logiciel libre).

## Production avec l'IA (ComfyUI sur ce PC)
- Ce PC calcule sans carte graphique : une image ≈ 20-30 min, une vidéo de quelques
  secondes ≈ plusieurs heures. Utiliser l'IA pour le **storyboard**, les concepts visuels,
  les décors, des plans courts — pas pour un film entier sur ce PC.
- Garder la cohérence : une fiche visuelle par personnage et par lieu (description fixe
  réutilisée dans chaque prompt), même palette, même cadrage de référence.
- Signaler qu'une image ou une vidéo est générée par IA quand elle est diffusée. Jamais de
  deepfake d'une personne réelle, jamais la voix d'une personne réelle sans son accord.

## Droit français — non négociable
- **Auteurs** : contrat de cession de droits écrit avec scénaristes, compositeurs,
  réalisateur ; dépôt du scénario possible (SACD, enveloppe e-Soleau de l'INPI) pour dater
  une œuvre.
- **Musique** : pour un film ou une pub, il faut deux autorisations — la **synchronisation**
  (éditeur, auteurs) et le **master** (producteur de l'enregistrement) ; sinon musique
  libre de droits avec licence vérifiée, ou composée (LMMS, MuseScore).
- **Droit à l'image** : autorisation écrite de chaque personne reconnaissable ; propriétaires
  pour les lieux privés.
- **Tournage** : autorisation de la mairie ou de la préfecture sur la voie publique ;
  déclaration et règles DGAC pour un drone ; assurance de production.
- **Équipe** : contrats et déclarations (intermittents du spectacle), mineurs avec
  autorisation préalable. Aides possibles : CNC, régions (le mentionner, ne pas promettre).

## Outils libres installés sur ce PC
- **Écriture** : Story Architect (scénario, bible, cartes, format Fountain), Manuskript,
  novelWriter. Via `toolkit` : `scenario_pdf` (Fountain → PDF au format).
- **Storyboard et animation** : Krita (dessin des cases), OpenToonz (animation 2D, utilisé
  par le studio Ghibli), Synfig (animation 2D), Blender (3D, animatique, VFX). Images IA :
  `generate_image`.
- **Montage** : Kdenlive et Shotcut (montage), Blender (montage et VFX), Natron (compositing,
  incrustation, rotoscopie). Via `toolkit` : `plans` (découpe d'un rush en plans,
  PySceneDetect), `derushage` (retire les silences, auto-editor), `video_format`, `incruster`.
- **Son et musique** : Audacity (montage son), LMMS (composition), MuseScore (partition).
  Via `toolkit` : `loudness` (normalise un son ou une vidéo : options = web ou tv),
  `voix_off`, `sous_titres`.
- **Sous-titres et livraison** : Subtitle Edit, HandBrake (encodage), ffmpeg ; DCP-o-matic à
  installer si une diffusion en salle est prévue.

## Livrer
À chaque étape : le fichier (scénario PDF, storyboard, animatique, montage…) + une note
(ce qui est fait, choix, points à valider, étape suivante, mentions légales). Rien n'est
publié, envoyé ou diffusé sans le oui de l'utilisateur.
