---
name: spectre-retro-ingenierie
description: La rétro-ingénierie (reverse engineering) pour Spectre et l'agent Syfer, sur la méthode de REA « Reverse Engineer Anything » (github.com/morluto/rea, MIT) — comprendre un logiciel sans son code source (exécutable Windows, DLL, assembly .NET, binaire Go ou Rust, appli Electron/JavaScript, APK, base SQLite, firmware, site web), router chaque cible vers le bon outil, travailler du résumé au détail, séparer observé / déduit / inconnu, tenir un registre des constats, puis expliquer ou reconstruire une fonctionnalité. Cadre légal français et européen strict (interopérabilité, sécurité, pas de contournement de protection ni de piratage). À charger dès qu'une demande touche une rétro-ingénierie, une décompilation, l'analyse d'un exécutable, d'un malware, d'une appli fermée, d'un format de fichier inconnu ou « comment marche cette fonctionnalité de telle appli ».
---

# spectre-retro-ingenierie — comprendre sans le code source, preuves à l'appui

REA (« Reverse Engineer Anything ») relie un agent à des outils d'analyse (inspections
statiques intégrées, Ghidra/IDA/Hopper pour le natif, observation de navigateur ou d'Electron)
et rend chaque conclusion **avec sa preuve et ses limites**. Syfer en applique la méthode.
Ici, sur ce PC, il dispose de l'outil `toolkit` name `retro` (REA 6.7.0, **inspections
statiques seulement** : le fichier est lu, jamais exécuté). Tout ce qui lance ou instrumente
la cible (débogueur, Frida, capture d'exécution, appareil Android) n'est pas branché : le
proposer dans le compte rendu, l'utilisateur décide.

## 1. Avant de toucher au fichier : le droit
La rétro-ingénierie est **encadrée**. Vérifier et écrire dans le compte rendu sur quoi repose
la mission :
- **Logiciel de l'utilisateur, ou autorisation écrite du titulaire** : tout est permis dans le
  cadre de l'autorisation.
- **Interopérabilité** (art. L122-6-1 IV du Code de la propriété intellectuelle, directive
  2009/24/CE art. 6) : décompiler est permis à l'utilisateur légitime, **seulement** pour
  obtenir les informations nécessaires à l'interopérabilité d'un programme créé
  indépendamment, si elles ne sont pas déjà accessibles, et limité aux parties nécessaires ;
  ces informations ne servent ni à un programme concurrent substantiellement similaire, ni à
  être diffusées à des tiers sans nécessité.
- **Observer, étudier, tester** le fonctionnement pour en comprendre les idées et principes
  (L122-6-1 III) : permis à l'utilisateur légitime, pendant un usage normal.
- **Sécurité** : l'analyse d'un logiciel pour en corriger les failles ou se défendre
  (malware) est légitime ; une faille trouvée chez un tiers se signale (divulgation
  responsable, ANSSI/CERT-FR), elle ne s'exploite pas.
- **Interdit** : contourner une protection technique (DRM, licence, anti-copie — art. L335-3-1
  CPI), produire un crack, un générateur de clés ou une version piratée, recopier le code
  obtenu dans un produit, violer des CGU signées qui l'interdisent valablement, analyser le
  système d'un tiers sans autorisation (art. 323-1 du Code pénal).
- On **réimplémente un comportement**, on ne copie pas le code : le résultat d'une
  décompilation ne donne aucun droit sur le programme d'origine.
En cas de doute, s'arrêter, le dire, et proposer l'avis d'Octavya (juridique).

## 2. Router la cible vers le bon outil
Identifier d'abord ce qu'on a entre les mains : `retro` sans option (`inspect-artifact`) donne
le format, l'architecture, l'empreinte SHA-256, les membres d'une archive et les pistes
suivantes. Ensuite :
| Cible | `retro` options = |
|---|---|
| Fichier inconnu, archive, installeur, ZIP/APK/MSIX | `inspect-artifact` |
| .exe / .dll Windows : icônes, version, manifeste | `inspect-pe-resources` |
| Assembly .NET (C#, VB) | `inspect-managed-artifact`, puis `inspect-managed-members` (types, méthodes, chaînes), `inspect-managed-native-boundaries` (appels natifs) |
| Binaire Go | `inspect-go-binary` (compilateur, modules, réglages) |
| Binaire Rust | `inspect-rust-binary` (dépendances embarquées) |
| Appli Electron (.exe) | `inspect-electron-fuses` (sécurité), puis le dossier `resources/app` ou le `.asar` en `analyze-javascript-application` |
| Appli JavaScript (dossier extrait ou .asar) | `analyze-javascript-application` (modules, imports, IPC, routes) |
| Base SQLite (copie à l'arrêt) | `inspect-sqlite-database` |
| APK Flutter | `identify-flutter-build` |
| Binaire natif C/C++ (pseudo-code, appels) | hors `retro` : Ghidra (libre, NSA) — à installer avec l'accord de l'utilisateur ; le proposer |
| Comportement à l'exécution | hors `retro` : bac à sable du labo (`labs-securite`), avec validation |
Le rapport complet (Evidence JSON) est écrit dans `workspace/retro/` ; la réponse n'en montre
que le début : lire le fichier avec `read_file` pour aller plus loin. Toujours travailler sur
une **copie** du fichier, jamais sur l'installation en service.

## 3. Méthode : du résumé au détail, une hypothèse à la fois
1. **Transformer la demande en liste de questions**, et pour chacune la preuve qu'il faut
   (« comment l'appli stocke ses notes ? » → format du fichier, schéma SQLite, module qui écrit).
2. **Réutiliser** ce qui existe déjà (rapports de `workspace/retro/`, missions passées) :
   ne pas refaire une analyse identique.
3. **Commencer par la vue la plus petite utile** (inventaire, résumé), puis suivre chaque
   question depuis son point d'entrée à travers les données jusqu'au résultat. N'élargir que
   quand la preuve laisse un trou précis.
4. Regarder **ressources et configuration** avec le code (manifestes, plist, schémas) ; ne
   jamais déduire un comportement d'un simple nom de fichier ou d'une chaîne isolée.
5. **Corroborer** avec le type de preuve qui convient : le statique ne prouve pas ce qui se
   passe à l'exécution ; une observation à l'exécution se demande à part.
6. Questions indépendantes → traitables en parallèle (une étape de mission chacune).
7. Tenir un **registre des constats** : pour chaque conclusion, la preuve (commande,
   `evidence_id`, empreinte SHA-256), le niveau de confiance, ce qui a été cherché et pas
   trouvé, ce qui reste inconnu.
Avant de finir, reprendre la liste : chaque question est **répondue, partielle ou ouverte**.
Ne jamais présenter comme complète une enquête dont des questions restent ouvertes.

## 4. Dire ce qu'on sait, et comment on le sait
Chaque phrase du compte rendu est d'un de ces trois types, et le dit :
- **Observé** : lu dans le fichier (citer la preuve).
- **Déduit** : raisonnement à partir d'observations (dire lesquelles).
- **Inconnu** : non établi ; une absence de métadonnées ne prouve pas l'absence de la chose
  (pas de section de dépendances ≠ pas de dépendances ; pas de signature lue ≠ non signé).
Une analyse statique n'a **rien vu s'exécuter**. Une décompilation peut être fausse ou
incomplète : vérifier les conclusions importantes.

## 5. Reconstruire une fonctionnalité (« je veux la même chose dans mon projet »)
Séparer le **comportement observé** (ce que fait l'original, preuves à l'appui) des **choix
de conception** (comment on le refait). Écrire une spécification du comportement, puis une
implémentation **originale** (Gétro ou un développeur), avec des tests qui comparent au
comportement observé. Ne jamais recopier de code, de ressources ni d'éléments de marque.

## 6. Analyse de logiciel malveillant
Uniquement sur une copie, dans un environnement isolé (labo Docker, sans réseau), jamais sur
le PC de l'utilisateur ; pas d'exécution sans validation. Rendre : nature, indicateurs de
compromission (empreintes, domaines, chemins), comportement établi ou supposé, détection et
nettoyage. Ne jamais améliorer, armer ou diffuser un malware.

## 7. Compte rendu
Cible (nom, empreinte SHA-256, format), base légale, questions et statut, constats avec leur
preuve et leur type, limites, prochaines analyses proposées (Ghidra, observation à
l'exécution…) qui attendent le oui de l'utilisateur. Résultats confidentiels.

Sources : README, DISCLAIMER et compétence `reverse-engineer-anything` du dépôt officiel
github.com/morluto/rea (licence MIT) ; Code de la propriété intellectuelle (L122-6-1,
L335-3-1), directive 2009/24/CE, Code pénal (323-1).
