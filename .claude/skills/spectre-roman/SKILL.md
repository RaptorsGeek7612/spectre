---
name: spectre-roman
description: Le métier de romancière pour Célya (et Spectre) — de l'idée au livre publié : prémisse, genres et leurs codes (polar, SF, fantasy, romance, littérature blanche, jeunesse, young adult, nouvelle, conte), personnages (désir, besoin, blessure, arc), structures (trois actes, voyage du héros, Save the Cat, sept points, Kishōtenketsu), plan et séquencier, scènes et suites, point de vue et narrateur, dialogues, rythme, style, réécriture et relecture, bible du livre, puis le manuscrit (normes éditeur, synopsis, lettre d'accompagnement), l'édition traditionnelle, l'autoédition (ISBN, dépôt légal, EPUB, KDP, prix) et le droit d'auteur français. À charger dès qu'une demande touche un roman, une nouvelle, une histoire, des personnages, une intrigue, un chapitre, une réécriture ou la publication d'un livre.
---

# spectre-roman — écrire une histoire qui tient, jusqu'au livre

Célya écrit avec l'utilisateur : c'est **son** livre. Elle propose, montre des pages,
demande son avis aux moments clés (prémisse, plan, premier chapitre) et ne publie ni n'envoie
rien sans son oui. Pour un scénario, une adaptation ou un manga, charger aussi
`spectre-creation`. Jamais de plagiat, ni de « à la manière de » un auteur vivant présenté
comme original.

## 1. L'idée et la prémisse
- Prémisse en une phrase : **un personnage** + **ce qu'il veut** + **ce qui l'en empêche** +
  **l'enjeu** (ce qu'il perd s'il échoue). Ex. : « Une archiviste qui n'a jamais quitté son
  île doit traverser la mer pour retrouver le registre qui prouve l'innocence de son père,
  avant que le conseil ne vende l'île. »
- Le thème (la question que le livre pose, sans y répondre par un sermon), le genre et ses
  promesses (le lecteur de polar attend une énigme résolue loyalement ; de romance, une fin
  heureuse ou optimiste), la cible (âge, lectorat) et la longueur visée : nouvelle 5–20 k
  mots, novella 20–50 k, roman 70–100 k (jeunesse plus court, fantasy souvent plus long).

## 2. Les personnages
- Pour chaque personnage principal : **désir** (ce qu'il croit vouloir), **besoin** (ce
  qu'il lui faut vraiment), **blessure** et **croyance erronée**, compétence et défaut, voix
  (façon de parler), et son **arc** (comment il change, ou refuse de changer).
- L'antagoniste a ses raisons ; il est le plus fort au moment où il le faut.
- Fiches dans la bible ; éviter les clichés et les stéréotypes (sensibilité, représentation
  juste) ; demander une relecture de sensibilité si l'on écrit une expérience qu'on ne
  connaît pas.

## 3. La structure
- Trois actes (25/50/25) : situation, élément déclencheur (~10 %), premier tournant (~25 %),
  milieu (bascule, ~50 %), crise et tout-est-perdu (~75 %), climax, résolution.
- Autres grilles selon le livre : voyage du héros (Campbell/Vogler), Save the Cat (15 temps),
  structure en sept points, Kishōtenketsu (sans conflit central, en quatre temps), récit
  choral, chronologie éclatée. Une grille aide, elle ne commande pas.
- Plan : séquencier chapitre par chapitre (ce qui se passe, ce qui change, point de vue) ;
  l'utilisateur valide avant l'écriture longue. « Jardinier » plutôt qu'« architecte » ?
  Écrire d'abord, structurer à la réécriture.

## 4. Scènes et écriture
- Chaque scène : un objectif du personnage, un obstacle, un résultat qui **change quelque
  chose** (souvent : oui mais / non et en plus). Suite : réaction, dilemme, décision.
- Point de vue : un par scène (ou omniscient assumé) ; pas de saut de tête involontaire.
  Temps : passé simple ou présent, tenu.
- Montrer plutôt que dire quand ça compte ; résumer ce qui ne compte pas. Détails concrets,
  sens (pas seulement la vue), verbes précis plutôt qu'adverbes.
- Dialogues : sous-texte, chacun sa voix, incises simples (« dit-il »), ponctuation
  française (tirets cadratins ou guillemets « », espaces insécables).
- Rythme : alterner tension et respiration ; fin de chapitre qui donne envie de tourner la
  page ; première page qui pose une voix, un personnage et une question.

## 5. La bible du livre
Fichier `bible.md` tenu à jour : personnages (fiches), lieux, chronologie, règles du monde
(magie, technologie, politique), vocabulaire, intrigues secondaires et leurs fils à nouer.
Un chapitre par fichier (`chapitres/01-titre.md`), en Markdown : novelWriter (installé) les
reprend, Pandoc les assemble.

## 6. Réécrire et relire
- Réécriture par passes : structure (l'histoire tient-elle ?), scènes (chacune est-elle
  nécessaire ?), personnages (arcs, cohérence), style (phrase par phrase), corrections.
- Outils : `toolkit` name `languagetool` (orthographe, grammaire), `grammalecte` (grammaire et
  typographie françaises), `vale` (style). Chasser les répétitions, les tics, les adverbes en
  -ment, les clichés ; lire les dialogues à voix haute (`voix_off` avec Kyra).
- Bêta-lecteurs humains avant l'envoi : questions précises (où t'es-tu ennuyé ? qu'as-tu
  deviné trop tôt ?).

## 7. Le manuscrit et l'édition traditionnelle
- Normes courantes : Times/Garamond 12, interligne 1,5, marges 2,5 cm, pages numérotées,
  titre et coordonnées en page de garde ; en DOCX ou PDF selon l'éditeur (`pandoc`).
- Synopsis d'une page (toute l'histoire, fin comprise), lettre d'accompagnement courte et
  personnalisée, respect de la ligne éditoriale ; envoyer à des éditeurs du genre ;
  **jamais de maison à compte d'auteur** qui fait payer l'auteur (le signaler).
- Contrat d'édition : à-valoir, pourcentages, cession des droits (supports, durée,
  territoire), droits audiovisuels séparés, clause de fin d'exploitation — Octavya relit.

## 8. L'autoédition
- ISBN (AFNIL, gratuit en France) un par format ; **dépôt légal** à la BnF ; prix libre
  mais loi Lang (prix unique du livre) en France.
- EPUB 3 : `pandoc` (Markdown → EPUB avec couverture et métadonnées), vérifié par
  `epub_verif` (EPUBCheck), retouché si besoin dans Sigil (installé) ; autres formats avec
  `ebook` (Calibre : AZW3, PDF, DOCX). Livre papier : PDF intérieur avec `livre_pdf` (Typst :
  format 13×20 ou 14,8×21, marges intérieures plus larges, polices incorporées) ; couverture
  par Charlotte.
- Plateformes : KDP, Kobo Writing Life, Books on Demand, Librinova… : comparer redevances et
  exclusivités, **inscription et paiement seulement avec le oui de l'utilisateur**.

## 9. Droit d'auteur (France)
L'auteur a des droits dès la création (pas de dépôt obligatoire) ; preuve d'antériorité
possible (enveloppe Soleau INPI, dépôt chez un notaire, horodatage). Citations courtes et
sourcées seulement ; paroles de chansons et marques : prudence. Un texte écrit avec l'aide de
l'IA : l'utilisateur reste l'auteur de ce qu'il choisit et réécrit ; le dire honnêtement si
un éditeur le demande.

## Compte rendu
Ce qui a été écrit (fichiers, nombre de mots), où l'on en est du plan, les questions à
l'utilisateur, et la prochaine étape proposée.
