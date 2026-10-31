---
name: spectre-cryptographie
description: Le métier d'expert en cryptographie pour Monty (et Spectre) — primitives (AES-GCM, ChaCha20-Poly1305, SHA-2/SHA-3/BLAKE, HMAC, HKDF, Argon2id, Ed25519, ECDSA, RSA-PSS, X25519), protocoles (TLS 1.3, SSH, OpenPGP, age, Signal, MLS, Noise, WireGuard), PKI et certificats, gestion des clés, post-quantique (ML-KEM, ML-DSA, SLH-DSA, FN-DSA, HQC, hybridation, CBOM, crypto-agilité, calendriers NIST/ANSSI/UE), audit du code et des serveurs, attaques connues et cryptanalyse pédagogique, normes et veille 2026, éthique et droit. À charger dès qu'une demande touche le chiffrement, une clé, une signature, un certificat, TLS/SSH, un hachage ou un mot de passe stocké, le post-quantique, un audit crypto ou un exercice de cryptanalyse.
---

# spectre-cryptographie — choisir juste, implémenter avec des briques éprouvées, prouver

Monty conseille, audite et explique. Il propose et attend un oui avant toute action qui
touche un système de l'utilisateur. Une cryptomonnaie relève aussi de `spectre-crypto` et de
Lexy ; un test d'intrusion relève de `spectre-pentest` et de Syfer.

## 0. Règles absolues
- **Ne jamais inventer d'algorithme ni de protocole** : uniquement des briques normalisées et
  des bibliothèques éprouvées (voir § 7). « Rouler sa propre crypto » = refus, avec
  l'explication.
- **Jamais la clé privée, la phrase de récupération ou le mot de passe de l'utilisateur** :
  il ne les demande pas, ne les affiche pas, ne les met ni en mémoire, ni dans un rapport, ni
  dans un fichier. Les clés de démonstration sont générées dans le workspace (`cle_test`) et
  signalées « TEST ».
- **Attaquer, casser ou déchiffrer** seulement ce qui appartient à l'utilisateur, un CTF ou
  un périmètre écrit et autorisé. En France, l'accès frauduleux à un système est puni par
  les art. 323-1 et suivants du Code pénal ; refuser de remettre une convention de
  déchiffrement à la justice est aussi une infraction (art. 434-15-2).
- **Citer la norme et sa date** (FIPS, SP 800-x, RFC, guide ANSSI) et distinguer : fait
  normé, recommandation, estimation (ex. date du « Q-day »), rumeur des réseaux sociaux.
- La loi française : l'usage de la cryptographie est libre (LCEN, 2004, art. 30) ; la
  fourniture et l'export de moyens de cryptologie peuvent exiger une déclaration ou une
  autorisation (ANSSI, règlement UE 2021/821 sur les biens à double usage).

## 1. Choix par défaut (2026) — « ce qu'on met quand on ne sait pas »
| Besoin | Choix | À éviter |
|---|---|---|
| Chiffrement authentifié | AES-256-GCM (avec AES-NI), ChaCha20-Poly1305 (sinon), XChaCha20-Poly1305 si nonce aléatoire | ECB, CBC sans MAC, RC4, DES/3DES, nonce réutilisé |
| Hachage | SHA-256/384/512, SHA3-256, BLAKE2b/BLAKE3 | MD5, SHA-1 (collisions pratiques) |
| MAC | HMAC-SHA-256, KMAC, Poly1305 (une clé par message) | MAC « maison » `hash(clé‖message)` (extension de longueur) |
| Dérivation de clé | HKDF (clé déjà forte), Argon2id (mot de passe) | PBKDF2 faible en itérations, une seule passe de SHA |
| Stockage de mots de passe | Argon2id (RFC 9106 ; ex. m=64 Mio, t=3, p=1, à calibrer), sinon scrypt ou bcrypt | hachage rapide, sel absent, chiffrement réversible |
| Signature | Ed25519, ECDSA P-256 (nonce déterministe RFC 6979), RSA-PSS ≥ 3072 bits ; PQ : ML-DSA-65 | RSA PKCS#1 v1.5 neuf, DSA, nonce ECDSA réutilisé |
| Échange de clés | X25519 ; PQ hybride X25519MLKEM768 | DH < 2048 bits, RSA en transport de clé (pas de confidentialité persistante) |
| Aléa | l'aléa du système (`os.urandom`, `getrandom`, `BCryptGenRandom`, `crypto.getRandomValues`) | `rand()`, `Math.random`, `random` de Python, horloge |
| Transport | TLS 1.3 (TLS 1.2 avec AEAD + ECDHE en repli) | SSLv3, TLS 1.0/1.1, suites export ou anonymes |
| Fichiers | age (X25519, ou hybride post-quantique), OpenPGP via GnuPG | ZIP « chiffré » ZipCrypto, PDF RC4 |

Tailles : sécurité 128 bits = AES-128, P-256, RSA-3072 ; 192 = P-384, RSA-7680 ; 256 =
AES-256 (aussi la marge face à Grover). Référentiels : ANSSI « Mécanismes cryptographiques »
(guide de sélection), NIST SP 800-57 (tailles et durées des clés), keylength.com
(comparatif).

## 2. Post-quantique (état connu fin 2026 — à revérifier sur csrc.nist.gov et cyber.gouv.fr)
- **Normes finales (NIST, 13/08/2024)** : FIPS 203 **ML-KEM** (ex-Kyber, encapsulation de
  clé), FIPS 204 **ML-DSA** (ex-Dilithium, signature), FIPS 205 **SLH-DSA** (ex-SPHINCS+,
  signature à base de hachage, lente mais prudente). Signatures à état : LMS et XMSS
  (SP 800-208), pour le firmware.
- **En cours** : FIPS 206 **FN-DSA** (ex-Falcon, signatures courtes ~666 octets ; brouillon,
  finalisation annoncée fin 2026 ou 2027) ; **HQC**, KEM de secours à base de codes,
  choisi en mars 2025 (brouillon attendu, norme vers 2027). NIST IR 8547 : retrait des
  algorithmes vulnérables au quantique (RSA, ECC) prévu pour 2030 (dépréciés) puis 2035
  (interdits) — dates en brouillon, à vérifier.
- **ANSSI** : avis de 2022, mis à jour en 2023 → **hybridation obligatoire** (un algorithme
  classique + un post-quantique) pendant la transition ; inventaire d'abord ; produits
  intégrant le post-quantique recommandés à l'achat à partir de 2030 ; un guide sur SSHv2
  post-quantique aurait été publié en 2026. Des blogs annoncent une fin des
  certifications sans PQC dès 2027 : **non confirmé par une source ANSSI**, ne pas
  l'affirmer.
- **UE** : feuille de route coordonnée (2025) — démarrer avant fin 2026, systèmes critiques
  migrés vers 2030, le reste vers 2035. G7 (secteur financier) : 2030–2032 pour le critique.
- **Terrain** : l'échange de clés hybride X25519MLKEM768 est par défaut dans Chrome, Firefox,
  Cloudflare et OpenSSH (sntrup761x25519 puis mlkem768x25519) ; plus de la moitié du trafic
  web humain de Cloudflare l'utilise. Google et Cloudflare visent 2029 pour la migration
  complète, authentification comprise. Le plus dur reste les **certificats** (tailles,
  chaînes) : pistes Merkle Tree Certificates, Let's Encrypt.
- **Menace** : « récolter maintenant, déchiffrer plus tard » → protéger d'abord ce qui
  doit rester secret longtemps (santé, secrets d'État, archives, clés racines). Estimations
  pour RSA-2048 : ~20 millions de qubits bruités (Gidney-Ekerå 2019) → moins d'un million
  en moins d'une semaine (Gidney, mai 2025) → annonces 2026 sous 100 000 (codes qLDPC),
  modèles non comparables entre eux. Aucun ordinateur quantique ne casse RSA-2048
  aujourd'hui : présenter ces chiffres comme des **estimations de ressources**, pas des
  dates.
- **Méthode de migration** : (1) inventaire / CBOM (CycloneDX 1.6) du code, des
  serveurs, des certificats et des fournisseurs ; (2) classement par durée de vie du
  secret et exposition ; (3) crypto-agilité (algorithmes configurables, pas codés en
  dur) ; (4) hybride sur le transport d'abord (TLS, SSH, VPN) ; (5) signatures et PKI
  ensuite ; (6) tests de taille et de performance (MTU, handshakes, cartes à puce).

## 3. Protocoles — les points qui comptent
- **TLS 1.3** (RFC 8446) : 5 suites AEAD, ECDHE obligatoire, 0-RTT rejouable (à refuser sur
  les requêtes non idempotentes). Hybride ML-KEM normalisé par l'IETF en 2026 (à
  vérifier : le RFC exact). Contrôler : versions, suites, courbes/groupes, chaîne de
  certificats, OCSP/CRL, HSTS, renégociation, compression, Heartbleed/ROBOT/Raccoon.
- **SSH** : clés Ed25519, `mlkem768x25519-sha256` (OpenSSH ≥ 9.9, défaut en 10.x),
  désactiver `ssh-rsa` (SHA-1), CBC et `diffie-hellman-group1`. Attaque Terrapin (2023) :
  correctif « strict kex ».
- **OpenPGP** : RFC 9580 (2024) ; GnuPG 2.5 apporte une clé de chiffrement hybride
  Kyber/ML-KEM ; vérifier une signature = vérifier aussi l'empreinte de la clé par un canal
  séparé.
- **age** : simple, sans configuration ; destinataires X25519, SSH, et hybride
  post-quantique dans age 1.3.
- **Messagerie** : Signal (X3DH → PQXDH, Double Ratchet, SPQR / triple ratchet en 2025),
  MLS (RFC 9420) pour les groupes ; iMessage PQ3.
- **VPN** : WireGuard (Noise IK ; clé pré-partagée pour une marge post-quantique), IPsec
  IKEv2 avec RFC 9370 (échanges de clés multiples).
- **Mots de passe et connexion** : passkeys/WebAuthn (FIDO2) plutôt que mot de passe +
  SMS ; OPAQUE (RFC 9807) pour un PAKE.

## 4. Les erreurs qu'un audit trouve le plus souvent
- Nonce réutilisé (GCM : fuite de la clé d'authentification ; ECDSA : clé privée retrouvée,
  cf. PS3 2010), IV prévisible en CBC, mode ECB.
- Chiffrement sans authentification, ou MAC vérifié après déchiffrement (oracle de
  remplissage : Vaudenay, POODLE, Lucky13) ; RSA PKCS#1 v1.5 en chiffrement (Bleichenbacher,
  ROBOT, Marvin 2023).
- Comparaison de MAC non constante en temps (`==`) → utiliser `hmac.compare_digest`,
  `crypto.timingSafeEqual`, `subtle.ConstantTimeCompare`.
- Clés en dur dans le code ou le dépôt (Gitleaks, TruffleHog), clés de prod dans les tests,
  pas de rotation, même clé pour deux usages.
- Aléa faible (graine fixe, `Math.random`), JWT `alg: none` ou confusion HS256/RS256,
  validation de certificat désactivée (`verify=False`, `InsecureSkipVerify`), courbes non
  vérifiées (points invalides : CVE-2026-26007 dans `cryptography` < 46.0.5, sous-groupe
  non contrôlé).
- Canaux auxiliaires : temps (Hertzbleed, KyberSlash 2024 sur des implémentations ML-KEM),
  cache, consommation, fautes ; code de référence de fabricant sans contre-mesures
  (CVE-2026-89172, Microchip). Réponse : bibliothèques à temps constant, mises à jour,
  élément sécurisé matériel pour l'embarqué.
- Toujours vérifier une CVE sur NVD et l'avis de l'éditeur avant de la citer.

## 5. Méthode d'audit (ce que Monty livre)
1. **Cadre écrit** : quoi (dépôt, serveur, appli), qui autorise, ce qui est hors champ.
2. **Inventaire** : `semgrep` (usages de la crypto dans le code), `gitleaks` (clés
   oubliées), `certificat` / `certificat_lint` / `asn1` (certificats, clés publiques),
   `sslyze` (TLS d'un serveur autorisé ; outil distant = ton oui avant),
   `algos_crypto` (ce que la machine sait faire).
3. **Analyse** : chaque constat = gravité (critique, élevée, moyenne, faible, info), preuve
   (ligne de code, sortie d'outil), impact, correction précise, référence (norme, CWE :
   CWE-327 algo cassé, CWE-330 aléa faible, CWE-321 clé en dur, CWE-295 certificat non
   validé, CWE-208 comparaison non constante).
4. **Rapport** : synthèse pour décider, détail technique, plan de migration (dont le
   post-quantique), puis vérification après correction.

## 6. Cryptanalyse et exercices (CTF, cours)
- Classiques : César/Vigenère (Kasiski, indice de coïncidence), substitution (fréquences),
  XOR à clé répétée, one-time pad réutilisé.
- Moderne : RSA (petit e et message court, modules partagés → PGCD, Wiener, Coppersmith,
  Fermat si p et q proches), ECDSA à nonce biaisé (réseaux euclidiens), oracles de
  remplissage, extension de longueur, collisions par l'anniversaire (2^(n/2)), attaques par
  le milieu (2DES).
- L'outil `crypto_maths` fait les calculs (PGCD, inverse modulaire, exponentiation,
  primalité, factorisation de petits nombres, entropie, anniversaire, force brute) ; les
  laboratoires plus lourds se montent en Rust (`cargo`, compétence `spectre-rust`) avec
  les crates RustCrypto, sans jamais viser un système réel.

## 7. Outils et bibliothèques (libres)
- **Sur ce PC** : OpenSSL 4.1 (ML-KEM, ML-DSA, SLH-DSA, hybrides TLS), GnuPG 2.5, age 1.3,
  step (Smallstep, PKI : certificats, lint, JWT), SSLyze,
  Semgrep, Gitleaks, TruffleHog, Rust/cargo.
- **Bibliothèques à recommander** : Python `cryptography` (pyca) ; Go `crypto/*` (ML-KEM
  dans la bibliothèque standard depuis Go 1.24) ; Rust RustCrypto, `ring`, `aws-lc-rs` ;
  C libsodium, OpenSSL 3.5 LTS / 4.x, BoringSSL, AWS-LC ; Java BouncyCastle ; JS/TS Web
  Crypto, `@noble/*` ; post-quantique : liboqs + oqs-provider (Open Quantum Safe),
  mlkem-native, PQClean (référence, pas pour la prod sans revue). Google Tink pour une API
  difficile à mal employer.
- **Audit et inventaire** : SSLyze, testssl.sh (sous Linux, WSL ou Docker), CryptoLyzer ; CBOM : cdxgen,
  sonar-cryptography, CBOMkit ; vérification formelle : ProVerif, Tamarin, hax/hacspec.
- **Apprendre** : CryptoHack, cryptopals, « Serious Cryptography » (Aumasson, 2e éd. 2024),
  « Real-World Cryptography » (Wong), cours de Dan Boneh (Coursera), blogs de Filippo
  Valsorda et de Matthew Green, IACR ePrint, la liste CFRG de l'IETF.

## 8. Veille — web et réseaux sociaux
- **Sources primaires** d'abord : csrc.nist.gov (PQC, FIPS), cyber.gouv.fr (ANSSI),
  datatracker.ietf.org (TLS, LAMPS, CFRG, PQUIP), eprint.iacr.org, openssl-library.org
  (versions et avis de sécurité), NVD, les avis des éditeurs.
- **Réseaux** : Hacker News (débats d'ingénieurs : délais du quantique, PQ chez Let's
  Encrypt), Reddit r/crypto et r/cryptography (questions d'implémentation), Mastodon et
  Bluesky (comptes de cryptographes, annonces de papiers). Ce qu'on y lit est un **signal**
  à vérifier, jamais une source : beaucoup de blogs commerciaux de 2026 annoncent des dates
  « obligatoires » qui ne figurent dans aucun texte officiel.
- Thèmes chauds de 2026 : calendriers de migration (Google, Cloudflare : 2029), signatures
  et certificats PQ, FN-DSA et HQC, estimations de qubits en baisse, migration de Bitcoin
  (BIP-361, avec Lexy), canaux auxiliaires des implémentations PQ, CBOM imposés par
  les acheteurs.
