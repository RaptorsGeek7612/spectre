---
name: spectre-graphisme
description: Le métier de graphiste pour Charlotte (et Spectre) — brief, recherche et moodboard, logo et identité visuelle (charte, déclinaisons), typographie, grille et mise en page, couleur (CMJN, RVB, Pantone, contrastes WCAG), affiches, flyers, packaging, couvertures de livres, illustration vectorielle, icônes, visuels pour chaque réseau, motion design, prépresse (fonds perdus, 300 dpi, PDF/X), droit (polices, images, marques) ; avec des outils libres (Inkscape, GIMP, Krita, Scribus, FontForge, Typst, VTracer, ImageMagick). À charger dès qu'une demande touche un logo, une identité, une affiche, un print, une couverture, une typo, une palette, une illustration ou un visuel de marque.
---

# spectre-graphisme — du brief au fichier prêt à imprimer

Charlotte conçoit et exécute. Elle propose, montre, puis l'utilisateur choisit : rien n'est
publié, imprimé ni commandé sans son oui. Pour une interface ou une maquette web, charger
aussi `spectre-design` ; pour l'animation, `motion-graphics` et les compétences HyperFrames.

## 1. Le brief (questions en une seule fois)
Pour qui (cible), pour quoi (objectif, message unique), où (supports : print, écran, réseaux,
enseigne, packaging), le ton (3 adjectifs), les contraintes (couleurs imposées, logo existant,
textes, délais, budget d'impression), les références aimées / détestées, les concurrents à
ne pas imiter. Sans réponse : hypothèses explicites, signalées.

## 2. Recherche et pistes
- Moodboard en SVG/HTML (références libres de droits ou créées ici, sources notées).
- **Trois pistes contrastées** (pas trois variantes du même) : une sage, une audacieuse, une
  inattendue ; chacune avec son idée en une phrase.
- Fuir le générique « IA » : pas de dégradé violet-bleu par défaut, pas de pictos clichés,
  pas de mise en page centrée partout. Une idée forte, une hiérarchie claire.

## 3. Logo et identité
- Logo : lisible en 16 px et en noir et blanc, version horizontale + carrée/monogramme +
  favicon ; zone de protection, taille minimale, interdits (déformer, ombrer, recolorer).
- Construction en vectoriel (SVG, Inkscape) ; texte vectorisé pour la version finale.
- Charte : logo, couleurs (HEX, RVB, CMJN, Pantone approchant), typographies (titres, texte),
  grille, iconographie, ton des images, exemples d'application. Livrée en PDF + sources.

## 4. Typographie
- Deux familles maximum (une de titre, une de texte), contrastées mais compatibles ;
  hiérarchie par taille, graisse, espace — pas par la couleur seule.
- **Polices libres seulement** (licence OFL : Google Fonts, Fontshare libres, The League of
  Moveable Type…) ; vérifier la licence avant usage commercial. FontForge (installé) sert à
  ajuster ou créer une police, jamais à modifier une police non libre.
- Texte : 45–75 caractères par ligne, interlignage 1,3–1,5, pas de veuves ni d'orphelines ;
  typographie française (espaces insécables avant ; : ! ?, guillemets « »).

## 5. Couleur
- Palette : 1 couleur dominante, 1 d'accent, des neutres ; 60/30/10. Extraire celle d'une
  image avec `toolkit` name `palette` (options = le nombre de couleurs).
- Écran en RVB, print en **CMJN** (profil FOGRA39 ou ISO Coated v2 en Europe) ; prévenir que
  les couleurs vives d'écran ternissent à l'impression.
- Accessibilité : contraste texte/fond ≥ 4,5:1 (WCAG AA), 3:1 pour les grands titres ; ne
  jamais coder une information par la seule couleur.

## 6. Print et prépresse
- Résolution 300 dpi à la taille finale (150 pour un grand format vu de loin) ; fonds perdus
  3 mm (5 mm pour certains imprimeurs), marges de sécurité 3–5 mm, traits de coupe.
- PDF/X-1a ou PDF/X-4, polices incorporées, noir texte en 100 % K, noir riche pour les aplats.
- Formats courants : A4 210×297, A5 148×210, A3 297×420, carte de visite 85×55, flyer DL
  99×210, affiche 40×60 / 60×80 ; couverture de livre = 1re + dos (épaisseur selon pages et
  papier, à demander à l'imprimeur) + 4e.
- Outils : Scribus (mise en page PAO, PDF/X), Inkscape (vectoriel), `toolkit` name
  `mise_en_page` (une affiche ou une plaquette décrite en Typst → PDF), `vectoriel` (SVG →
  PDF vectoriel ou PNG).

## 7. Images et illustration
- Vectoriser un croquis ou un vieux logo : `toolkit` name `vectoriser` (options couleur ou
  noir) puis nettoyer dans Inkscape.
- Retouche et photo : GIMP ; peinture numérique : Krita ; détourage : `detourage` ;
  agrandissement pour l'impression : `agrandir` ; formats réseaux : `image_format` (story,
  fil, carre, paysage).
- Visuels générés : demander à Kyra (studio ComfyUI) ; toujours vérifier les mains, le texte et
  les logos parasites.

## 8. Réseaux et motion
Décliner chaque visuel par format (9:16, 4:5, 1:1, 16:9), zones sûres respectées (texte hors
des 250 px haut/bas des stories). Animation de logo ou titre : `motion-graphics`, blocs
HyperFrames prêts (glass-shard-title, wireframe-portal-title, canopy-part-title…).

## 9. Droit (France)
- Droit d'auteur : l'utilisateur doit recevoir une **cession de droits** écrite pour un logo
  livré à un client (supports, territoire, durée) — Octavya rédige.
- Marques : vérifier l'antériorité sur la base INPI / EUIPO avant de déposer un logo ; jamais
  de copie d'une marque existante. Images : banques libres (Unsplash, Pexels, Wikimedia en
  vérifiant la licence) ou créées ici ; droit à l'image des personnes.

## 10. Vérifier et livrer
Relire chaque rendu par une capture (`maquette_png` ou export PNG) avant de le montrer ;
contrôler orthographe, contrastes, fonds perdus. Livraison : sources ouvertes (SVG, SLA, KRA,
XCF, TYP), exports (PDF print, PDF écran, PNG, SVG), et une note : polices et leurs licences,
couleurs, ce que l'imprimeur doit savoir.
