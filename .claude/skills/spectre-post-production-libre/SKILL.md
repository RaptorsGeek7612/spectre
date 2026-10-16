---
name: spectre-post-production-libre
description: Comment Kyra fait sans les logiciels qu'on ne peut pas installer ici — étalonnage sans DaVinci Resolve (LUT, Kdenlive, Blender, Natron, ffmpeg), storyboard et animatique sans Storyboarder (Krita puis montage), export cinéma DCP avec DCP-o-matic (installation manuelle), vidéo IA lourde sur un GPU loué (Wan 2.2, LTX-Video) et maquettes Penpot en ligne. À charger dès qu'une demande touche l'étalonnage, un look, une LUT, un storyboard, une animatique, une diffusion en salle ou festival (DCP), ou une vidéo IA trop lourde pour ce PC.
---

# spectre-post-production-libre — les contournements qui marchent

Certains outils ne s'installent pas ici : propriétaires (DaVinci Resolve, Storyboarder sous
EULA), téléchargement protégé (DCP-o-matic), ou trop lourds pour ce PC (vidéo IA, 15 Go de RAM,
pas de carte graphique). Kyra connaît la méthode libre équivalente et la propose. Elle dit
toujours **ce qui est fait sur ce PC**, **ce que l'utilisateur doit faire lui-même** et **ce qui
coûte de l'argent** (avec un oui préalable).

## 1. Étalonnage sans DaVinci Resolve
- **Ordre** : d'abord la **correction** (balance des blancs, exposition, contraste, raccord
  entre plans), ensuite le **look** (l'intention : chaud, froid, désaturé, contrasté).
  Toujours sur une image de référence par séquence.
- **Kdenlive** : effet *Apply LUT* (fichiers `.cube`, `.3dl`, `.dat`, `.m3d`) ; des LUT se
  téléchargent depuis le dialogue de l'effet. Limite signalée par des utilisateurs : traitement
  en 8 bits → risque de **bandes** dans les dégradés (ciels). Pour un rendu exigeant, étalonner
  ailleurs puis finir dans Kdenlive.
- **Blender** (compositeur, espace AgX/Filmic) ou **Natron** (nœuds, 32 bits flottants) pour
  un étalonnage haute précision, puis export en ProRes/DNxHR ou PNG 16 bits vers le montage.
- **Shotcut** : pipeline couleur parfois préféré pour les rendus 10 bits.
- **ffmpeg en lot** (Kyra peut le faire) : appliquer une LUT à toute une vidéo,
  `ffmpeg -i in.mp4 -vf lut3d=look.cube -c:a copy out.mp4`, après validation du look.
- Les LUT doivent être libres ou sous licence vérifiée (CC0 de préférence).
- HDR : si un rendu sort « délavé », appliquer la conversion dans le pipeline du logiciel
  (LUT de conversion) plutôt qu'après l'export.

## 2. Storyboard et animatique sans Storyboarder
- **Storyboarder** (Wonder Unit) n'est pas installé : son installateur est sous licence
  propriétaire et le projet n'est plus maintenu depuis 2024.
- **Méthode Krita** (documentation officielle) : une case par plan, croquis rapides, basse
  résolution pendant l'esquisse (≈ 800×450), plans courts (≤ 10 s). Un modèle de planche
  (gabarit de cases) accélère le travail ; nommer les fichiers `seq01_plan010.png`
  (sauvegardes incrémentales).
- **Ou par l'IA** : `generate_image` pour chaque plan avec une fiche personnage fixe (≈ 20-30
  min par image ici : limiter aux plans clés).
- **Animatique** : les cases montées avec leurs durées et le son (voix témoin, musique) dans
  Kdenlive ou Shotcut ; ou par ffmpeg avec un fichier de durées (concat) pour une version
  rapide. Krita sait aussi importer des images comme trames d'animation
  (*Fichier > Importer des trames d'animation*) pour animer quelques plans.
- **OpenToonz** pour une animatique plus animée (2D), **Blender** pour une prévisualisation 3D
  (caméra, échelle des décors).

## 3. Diffusion en salle ou festival : le DCP
- **DCP-o-matic** (libre, GPL) n'est pas sur winget et son site protège le téléchargement :
  c'est **l'utilisateur** qui l'installe. Lui donner la marche à suivre : aller sur
  dcpomatic.com, rubrique *Download*, choisir *Windows 64 bits*, cliquer « Just let me
  download it » (ou faire un don), lancer l'installateur.
- **Avant d'encoder, lire la fiche technique du festival** (elle prime) : cadence (24 ou
  25 i/s), format (Flat 1.85 ou Scope 2.39), son (stéréo ou 5.1), sous-titres (souvent
  incrustés ou en XML), nommage du DCP, support (disque, transfert).
- **Méthode** : *Fichier > Nouveau*, ajouter le master (haute qualité : ProRes, DNxHR ou
  séquence d'images, son WAV), régler le contenu, *Tâches > Créer le DCP*. Long : plusieurs
  heures pour un long-métrage. Le DCP est un dossier à copier tel quel (disque formaté selon
  la demande du festival).
- Tester si possible le DCP sur un vrai projecteur ou avec le lecteur intégré à DCP-o-matic.

## 4. Vidéo IA trop lourde pour ce PC : un GPU loué
- Sur ce PC (processeur seul), une vidéo de quelques secondes prend plusieurs heures.
  Alternative : **louer un GPU** à l'heure (RunPod, Vast.ai… comptes et paiement de
  l'utilisateur) avec ComfyUI et des modèles ouverts (**Wan 2.2**, **LTX-Video**).
- Ordres de grandeur (à revérifier avant de proposer) : une carte 24 Go fait un plan de
  5 s en 720p en quelques minutes avec LTX-Video ; Wan 2.2 en haute qualité demande 40 à 80 Go
  de mémoire GPU ; quelques dizaines de centimes à quelques euros par plan selon la carte.
- **Méthode économe** : brouillons en basse résolution ou sur le petit modèle, une seule passe
  finale en haute qualité ; éteindre le serveur dès la fin (on paie à l'heure).
- **Toujours** : chiffrer le coût, demander le oui, ne jamais envoyer de données
  personnelles ni de visage d'une personne réelle sans son accord.

## 5. Maquettes et chartes : Penpot
- Pas d'application à installer : Penpot s'utilise **en ligne** (penpot.app, compte gratuit
  de l'utilisateur) ou **auto-hébergé** avec Docker (plusieurs services : à prévoir quand la
  mémoire du PC le permet). Kyra prépare les éléments (couleurs, typographies, textes, visuels)
  et décrit la maquette ; l'utilisateur la monte ou l'importe.

## Règle commune
Annoncer clairement la méthode retenue, le temps, le coût éventuel et ce que l'utilisateur
doit faire ; attendre son oui avant toute dépense, inscription ou envoi de fichiers en ligne.
