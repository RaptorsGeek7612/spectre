---
name: labs-biometrie
description: Piloter les frameworks de biométrie locaux (reconnaissance faciale, vocale, empreintes) du conteneur Docker lab-biometrie. Charger quand une mission demande de comparer/vérifier des visages, des voix ou des empreintes digitales. Usage labo/apprentissage, données possédées ou autorisées uniquement.
---

# labs-biometrie — reconnaissance visage / voix / empreintes

Environnement Docker local (hôte Windows), **séparé du dépôt Spectre**. Usage
labo/apprentissage, sur des données que l'utilisateur possède ou est autorisé à traiter.

## Accès au conteneur
```shell
cd C:\Users\sherp\labs
docker compose up -d lab-biometrie        # démarrer si besoin
# déposer les fichiers d'entrée dans shared\ (monté sur /work/shared)
docker exec -i lab-biometrie bash -lc 'python /work/shared/<script> <args>'
```
Partage hôte ↔ conteneur : `C:\Users\sherp\labs\shared` ↔ `/work/shared`.
Les modèles se téléchargent au 1er appel (prévoir la bande passante).

## Visage
| Script | Modèle | Quand |
|---|---|---|
| `face_demo.py A B [SFace\|Facenet\|ArcFace]` | DeepFace/SFace | rapide, léger |
| `face_demo_insight.py A B` | InsightFace buffalo_l (ArcFace r50) | **haute précision** |

```shell
docker exec -i lab-biometrie bash -lc \
  'python /work/shared/face_demo_insight.py /work/shared/a.png /work/shared/b.png'
```
API Python : `faces = app.get(cv2.imread(path))` → `faces[i].normed_embedding`,
similarité = produit scalaire (cosinus). Seuil ~0.35 (InsightFace).

## Voix (vérification du locuteur)
| Script | Modèle | Quand |
|---|---|---|
| `voice_demo.py A B` | Resemblyzer | léger, poids embarqués, aucun download |
| `voice_demo_speechbrain.py A B` | ECAPA-TDNN (VoxCeleb) | robuste, ~80 Mo |

Audio attendu : **mono 16 kHz**. API : voir `from fp_match import match` côté empreintes
et les scripts pour le motif embed→cosinus.

## Empreintes
Moteur **SourceAFIS 3.18.1** (Java) via pont Python :
```shell
docker exec -i lab-biometrie bash -lc \
  'python /opt/sourceafis/fp_match.py /work/shared/d1.png /work/shared/d2.png [dpi]'
```
Ou en code (`PYTHONPATH=/opt/sourceafis` déjà réglé) :
```python
from fp_match import match
score = match("d1.png", "d2.png")   # >= 40 => même doigt (scans réels ~500 dpi)
```

## Pièges connus
- **OpenCV 5.0 ne livre plus les cascades Haar** → DeepFace doit utiliser
  `detector_backend="yunet"` (déjà réglé dans les scripts).
- torch/torchaudio **doivent** venir de l'index CPU PyTorch (sinon SpeechBrain casse).
- **ECAPA ne discrimine pas les voix synthétiques** (hors-distribution) : pour un vrai
  test négatif, fournir de vrais enregistrements humains 16 kHz.
- Les scores absolus (empreintes, voix) ne sont parlants que sur de vraies données.

Doc frameworks : passer par Context7 plutôt que la mémoire. Détails env : voir
`C:\Users\sherp\labs\README.md`.
