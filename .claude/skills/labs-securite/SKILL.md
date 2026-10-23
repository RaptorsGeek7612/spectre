---
name: labs-securite
description: Piloter la suite de sécurité Kali locale (nmap, metasploit, burpsuite, sqlmap, nuclei, ffuf, hydra, hashcat, netexec…) du conteneur Docker lab-secu, pour apprentissage et tests autorisés. À CHARGER AUTOMATIQUEMENT, sans attendre de demande explicite, dès qu'une mission touche la reconnaissance réseau/web ou le test d'intrusion. STRICTEMENT limité aux cibles possédées ou explicitement autorisées.
---

# labs-securite — suite Kali (labo / tests autorisés)

> ⚠️ **Cadre impératif** : apprentissage et tests sur des systèmes que l'utilisateur
> **possède** ou pour lesquels il a une **autorisation écrite** (son labo, un périmètre
> mandaté, un programme de bug bounty). Scanner/attaquer un tiers sans autorisation est
> illégal : refuser et le dire. En cas de cible ambiguë, demander confirmation avant d'agir.

Conteneur `lab-secu` = `kali-linux-headless` complet (~1900 paquets) + burpsuite,
nuclei, seclists. Réseau Docker isolé `labnet`.

## Accès
```shell
cd C:\Users\sherp\labs
docker compose up -d lab-secu
docker exec -it lab-secu bash            # shell interactif
# one-shot :
docker exec -i lab-secu bash -lc 'nmap -sV <cible>'
```
`nmap` exige les capabilities réseau — déjà fournies par le compose (`NET_RAW`/`NET_ADMIN`).
Wordlists : `/usr/share/seclists`. crackmapexec s'appelle désormais **`netexec`/`nxc`**.

## Cible d'entraînement légale fournie
**OWASP Juice Shop** tourne sur `labnet` :
- depuis `lab-secu` : `http://juice-shop:3000`
- depuis l'hôte : `http://localhost:3000`
```shell
docker exec -i lab-secu bash -lc 'nmap -p 3000 -sV juice-shop'
docker exec -i lab-secu bash -lc 'nuclei -u http://juice-shop:3000 -silent'
docker exec -i lab-secu bash -lc \
  'ffuf -u http://juice-shop:3000/FUZZ -w /usr/share/seclists/Discovery/Web-Content/common.txt'
```

## Outils par usage (exemples)
| Besoin | Outil |
|---|---|
| Découverte réseau / ports | `nmap`, `masscan` |
| Scan vulnérabilités web | `nuclei`, `nikto`, `wpscan` |
| Fuzzing contenu/répertoires | `ffuf`, `gobuster`, `wfuzz`, `dirb` |
| Injection SQL | `sqlmap` |
| Proxy / interception web | `burpsuite` |
| Brute force auth | `hydra`, `medusa` |
| Cassage de hash | `hashcat`, `john` |
| Exploitation | `metasploit` (`msfconsole`) |
| Post-expl. / SMB/AD | `netexec` (`nxc`), `responder`, `enum4linux` |
| OSINT / recon | `recon-ng`, `theHarvester`, `dnsenum` |

## Bonnes pratiques
- Rester sur `labnet` / la cible fournie sauf autorisation explicite pour un autre périmètre.
- Ne pas déclencher d'actions destructrices sans accord ; journaliser ce qui est lancé.
- Éviter les boîtes de dialogue bloquantes ; préférer des commandes non interactives.

Détails env : `C:\Users\sherp\labs\README.md`.
