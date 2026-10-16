---
name: spectre-diffusion-marketing
description: Comment Kyra organise la diffusion d'une campagne avec des logiciels libres qui ne sont pas encore installés sur ce PC — planification des réseaux sociaux (Postiz), emailing (listmonk, Mautic), statistiques (Umami, Matomo) — en attendant qu'ils le soient (méthode manuelle) et quand l'utilisateur voudra les auto-héberger (Docker, prérequis, comptes à créer, délivrabilité). À charger dès qu'une demande touche la publication programmée, une newsletter, une campagne d'emails, l'automatisation marketing ou la mesure d'audience.
---

# spectre-diffusion-marketing — publier, envoyer, mesurer

Ces outils sont des **serveurs** (base de données, plusieurs services) : ils ne sont pas
installés sur ce PC, faute de mémoire (15 Go déjà sollicités par ComfyUI et Spectre). Kyra sait
**travailler sans eux maintenant** et **préparer leur installation** quand l'utilisateur le
décidera. Rien n'est publié ni envoyé sans son oui.

## Maintenant, sans serveur
- **Calendrier éditorial** : un tableau (date, heure, réseau, format, texte, visuel, lien UTM,
  statut) dans le workspace ; l'utilisateur publie à la main ou avec les outils intégrés des
  réseaux (publication programmée native de Meta Business Suite, LinkedIn, YouTube, TikTok).
- **Contenus prêts à publier** : visuels et vidéos déjà déclinés par format (`toolkit`
  video_format / image_format), textes par réseau, sous-titres incrustés, mentions légales.
- **Emailing** : rédiger l'email (objet de 40 caractères environ, pré-en-tête, un seul appel
  à l'action, version texte), l'utilisateur l'envoie depuis l'outil de son choix.
- **Mesure** : liens UTM sur chaque publication ; relever les chiffres des tableaux de bord
  natifs des réseaux.

## Plus tard, auto-hébergé (Docker, labo `C:\Users\sherp\labs` ou un petit serveur)
Toujours lire la documentation officielle à jour avant d'installer ; prévoir des mots de passe
forts et des sauvegardes de la base.
- **Postiz** (AGPL) — planifie et publie sur plus de 15 réseaux, calendrier, assistant IA,
  API utilisable par n8n. Lourd : Next.js, NestJS, PostgreSQL, Redis et un orchestrateur de
  tâches. **Chaque réseau exige une « application développeur »** créée par l'utilisateur
  (clés API Meta, LinkedIn, X, TikTok…) ; certaines demandent une validation de la
  plateforme.
- **listmonk** (AGPL) — newsletters et campagnes, un seul binaire avec PostgreSQL, très
  léger ; Docker Compose officiel dans le dépôt. Il faut un **serveur d'envoi SMTP** (celui de
  l'utilisateur ou un prestataire d'envoi).
- **Mautic** (GPL) — automatisation marketing complète (contacts, segments, scénarios,
  formulaires, emails). PHP et MySQL/MariaDB ; plus exigeant à maintenir.
- **Umami** (MIT) — statistiques web sans cookie, Node.js et PostgreSQL, léger ;
  **Matomo** (GPL) — alternative plus complète à Google Analytics.

## Emailing : la délivrabilité, sinon tout part en spam
- Domaine d'envoi authentifié : enregistrements **SPF**, **DKIM** et **DMARC** dans le DNS.
- Liste propre : consentement (RGPD, particuliers), double confirmation conseillée,
  désinscription en un clic dans chaque email, retrait des adresses en erreur.
- Monter le volume progressivement sur un domaine neuf ; tester le rendu et le score spam avant
  envoi.

## Ordre conseillé quand l'utilisateur voudra s'équiper
1. Umami (léger, utile tout de suite pour mesurer). 2. listmonk (newsletter). 3. Postiz
(quand plusieurs réseaux sont actifs). 4. Mautic (seulement si des scénarios automatisés sont
nécessaires). Proposer, chiffrer le temps et la mémoire nécessaires, attendre le oui.
