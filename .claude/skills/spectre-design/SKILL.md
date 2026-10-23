---
name: spectre-design
description: Le métier de designer pour Spectre (et l'agente Kyra), sur le modèle de Claude Design (Anthropic Labs, 2026) mais avec des outils libres — maquettes et prototypes cliquables en HTML/CSS, slides et présentations, one-pagers, affiches, landing pages, visuels de marque ; questions de cadrage, système de design (tokens couleur, typo, espacements, composants), variantes, réglages (« Tweaks »), anti-« AI slop », vérification par capture, exports PDF, PPTX, SVG, HTML autonome et passage au développement. À charger dès qu'une demande touche une maquette, un prototype, une slide, un deck, une présentation, un one-pager, une affiche, une interface, une charte graphique ou un système de design.
---

# spectre-design — concevoir comme un vrai directeur artistique, avec des outils libres

Claude Design (Anthropic Labs, avril 2026) fait des prototypes, slides et one-pagers par la
conversation : on décrit, il construit une première version, on affine (chat, commentaires,
réglages), il applique le système de design de l'équipe, puis exporte (PDF, PPTX, HTML,
Canva) ou passe le relais au développement. Kyra fait la même chose ici, **en local et en
logiciel libre** : le support de travail est **un fichier HTML/CSS autonome**, rendu par
Chromium, relu par capture, exporté en PDF/PNG/PPTX/SVG. Elle propose, l'utilisateur choisit ;
rien n'est publié ni envoyé sans son oui.

## 1. Cadrer avant de dessiner
**Chercher le contexte d'abord** : charte, logo, captures, site, code existant (fichiers
`theme`, `tokens.css`, variables SCSS : y relever les hex, polices, rayons et espacements
exacts), anciens projets, pièces jointes. Partir de zéro est le **dernier recours**. Une page
web lue en texte ne dit rien de sa mise en page : demander une capture.

**Poser les questions en une seule fois** (une liste numérotée, avec pour chacune « je décide
pour toi » possible), puis attendre. Le nombre dépend de l'ambiguïté :
- demande claire et complète (« un deck de 10 slides depuis ce document, pour la réunion de
  lundi ») → aucune question, on y va et on annonce les hypothèses ;
- demande ouverte (« un prototype d'appli », « une identité ») → beaucoup de questions
  (jusqu'à une dizaine) : point de départ (charte ou rien ?), public et objectif, format et
  support (écran, impression, téléphone), contenu réel disponible, **nombre de variantes** et
  sur quoi elles portent, fidèle au style existant ou exploratoire, priorité (parcours,
  textes ou visuel), réglages souhaités, contraintes et interdits, délai ;
- petite retouche → aucune question.

## 2. Le système de design (le poser avant tout le reste)
Sans système, le modèle retombe sur ses réflexes génériques : **ce qui n'est pas écrit sera
banal**. Le fixer et l'annoncer avant de produire, dans un fichier `DESIGN.md` du projet
(réutilisé ensuite pour tout le projet) :
1. **Personnalité** : 3 à 5 adjectifs (« sobre, chaleureux, éditorial ») et 3 à 5
   contre-exemples (« pas start-up californienne, pas tableau de bord SaaS »).
2. **Couleurs** : chaque hex avec son rôle (fond, surface, texte, texte secondaire, accent,
   succès, alerte). Couleurs de la marque d'abord ; s'il en manque, les dériver en `oklch()`
   en harmonie avec elles — ne jamais en inventer de nulle part. Une couleur **dominante** et
   un accent franc valent mieux qu'une palette timide et uniforme. Contraste texte ≥ 4,5:1
   (WCAG AA).
3. **Typographie** : polices exactes (libres : Google Fonts / licence OFL), graisses, échelle
   des tailles, interlignage (corps ≈ 1,5–1,6). Contraste fort : graisses extrêmes (200 contre
   800) et sauts de taille ×3 plutôt que 400 contre 600 ou ×1,5. Associations sûres : une
   display + une mono, une serif + une sans géométrique, ou une seule police variable.
4. **Espacements et formes** : unité de base (4 ou 8 px) et son échelle, rayons (boutons,
   cartes), bordures, une ombre au plus.
5. **Composants** : boutons (repos, survol, désactivé), champs, cartes, en-têtes, icônes
   (**une seule famille**, ou aucune).
6. **Mise en page** : grille, largeur max, marges.
7. **Interdits** : « aucune couleur, police ou bordure hors de cette liste ».
Le tout en **variables CSS** (`:root { --bg; --surface; --text; --accent; --font-display… }`).
Tester le système sur un seul composant avant de tout produire. Ajouter à une interface
existante : reprendre exactement son vocabulaire (palette, densité, ombres, états, animations).

## 3. Le rendu « AI slop » à fuir
Ces réflexes trahissent un visuel fait par une IA sans direction ; les éviter sauf si la
marque les impose :
- polices par défaut : Inter, Roboto, Arial, Open Sans, Lato, polices système ;
- dégradé violet/indigo sur fond blanc, dégradés agressifs en fond de page ;
- grands coins arrondis partout, cartes à liseré coloré à gauche, accent sur chaque carte ;
- héros « dégradé + titre + bouton », grille de trois colonnes d'icônes, barre latérale
  icône + libellé façon tableau de bord ;
- emojis comme icônes ; pastille « en ligne » qui clignote ; boîtes dans des boîtes (2 niveaux
  d'imbrication au plus) ; marges énormes partout ;
- illustrations dessinées à la main en SVG (préférer un emplacement réservé propre, puis une
  vraie image : photo libre, ou `generate_image` dans le studio) ;
- **remplissage** : pas de sections, de chiffres ou de faux témoignages inventés pour combler.
  Un vide se règle par la composition, pas par du contenu bidon. Mille non pour un oui.
Une police distinctive utilisée avec décision, une couleur dominante, une composition qui
surprend : c'est ce qui fait la différence.

## 4. Construire
- **Un seul fichier HTML autonome** par livrable (CSS dans `<style>`, polices par lien Google
  Fonts ou locales), dans le dossier de la mission ; `text-wrap: pretty`, grilles CSS.
- Montrer tôt : une première version avec ses hypothèses écrites (« comme un designer junior
  devant sa directrice artistique »), des emplacements réservés là où manque la matière, puis
  itérer. Une révision importante = une copie versionnée (`affiche-v2.html`), pas un écrasement.
- **Prototype** : pas d'écran-titre ; centré ou adaptatif ; interactions en transitions CSS
  ou un peu de JavaScript ; cibles tactiles ≥ 44 px ; liens relatifs entre pages.
- **Animation** : peu mais bien — une entrée de page orchestrée (apparitions décalées avec
  `animation-delay`) vaut mieux que dix micro-effets ; respecter `prefers-reduced-motion`.
- **Accessibilité** : contrastes AA, ordre de lecture logique, `alt` sur les images, focus
  visible.

## 5. Variantes et réglages (« Tweaks »)
- Proposer **au moins 3 variantes** sur plusieurs axes (mise en page, couleur, typo, ton),
  de la plus sage à la plus audacieuse, pour pouvoir **mélanger** : « la mise en page de B
  avec les couleurs de A ».
- Variantes statiques (couleur, typo, un élément) : côte à côte sur une même planche HTML.
  Parcours et interactions : un prototype cliquable où chaque option est un réglage.
- **Réglages** : un petit panneau « Tweaks » (en bas à droite, masquable) qui modifie en
  direct les variables CSS — accent, police, densité, rayon, clair/sombre. En ajouter deux ou
  trois par défaut si l'utilisateur n'en demande pas ; noter les valeurs retenues dans
  `DESIGN.md`.

## 6. Slides et présentations
- Canevas **1920×1080** (16:9), chaque slide une `<section>` de taille fixe ; impression
  une page par slide (`@page { size: 1920px 1080px; margin: 0 }`,
  `section { break-after: page }`).
- Numérotation à partir de 1 (« slide 5 » = la 5ᵉ, jamais l'index 4).
- Texte ≥ 24 px à l'écran (viser bien plus), ≥ 12 pt à l'impression ; une idée par slide,
  texte léger ; une ou deux couleurs de fond pour tout le deck, une autre pour les
  ouvertures de partie ; image en plein cadre quand elle porte le propos.
- Notes de l'orateur seulement si on les demande.
- Exports : PDF (`maquette_pdf`) ; PPTX éditable par `pandoc` depuis un Markdown structuré
  (`# Titre` par slide, options = `deck.pptx`, et `--reference-doc` pour le gabarit si
  l'utilisateur en a un) ; LibreOffice Impress pour retoucher.

## 7. Vérifier avant de rendre (jamais livrer à l'aveugle)
1. Rendre : `toolkit` name `maquette_png` (options = paysage, story, fil ou carre) → capture.
2. Relire la capture : débordements, textes coupés ou chevauchés, contrastes, alignements,
   hiérarchie, respect strict du `DESIGN.md`, aucun motif de la section 3.
3. Corriger, re-capturer, jusqu'à ce que ce soit propre. Kaïto vérifie ensuite d'un œil neuf :
   celui qui a fait le travail juge mal le sien.
4. Rendre compte **très brièvement** : ce qui est livré, les fichiers, les hypothèses, les
   réserves, la suite possible.

## 8. Exports et passage au développement
| Besoin | Outil (libre) |
|---|---|
| PDF imprimable ou à envoyer | `toolkit` `maquette_pdf` (Chromium) |
| Capture PNG, visuel pour réseau | `maquette_png` (paysage, story, fil, carre), puis `image_format` |
| Logo, pictos, affiche vectorielle | SVG → `vectoriel` (Inkscape ; options = pdf ou png) |
| Présentation PowerPoint éditable | `pandoc` (Markdown → .pptx), retouche LibreOffice Impress |
| Mise en page print (brochure, magazine) | Scribus, PDF/X pour l'imprimeur |
| Fichier à partager hors ligne | le HTML autonome lui-même |
| Passage au développement | un dossier : le HTML, `DESIGN.md`, les variables CSS, les assets, et la liste des composants et états — Gétro ou un développeur le reprend en une instruction |

## 9. Droit et éthique — non négociable
- **Ne pas recopier** l'interface, la charte, le logo ou les éléments de marque distinctifs
  d'une entreprise tierce : on s'en inspire (une famille esthétique), on crée un design
  original. Seule exception : la marque de l'utilisateur lui-même.
- Polices, images, icônes et musiques sous licence libre ou acquise (vérifier la licence ;
  OFL pour les polices) ; citer les crédits.
- Pas de visage réel généré ou retouché sans mention (« Image virtuelle », « Image
  retouchée ») ni sans autorisation ; pas de faux avis, faux chiffres ou faux logos clients.
- Une pub ou une page commerciale suit aussi `spectre-pub-communication` (mentions légales).

Sources : annonce officielle d'Anthropic (anthropic.com/news/claude-design-anthropic-labs),
guide officiel « Prompting for frontend aesthetics » (Claude Cookbook) ; le reste est tiré
d'analyses publiques non officielles de Claude Design, recoupées et adaptées aux outils libres.
