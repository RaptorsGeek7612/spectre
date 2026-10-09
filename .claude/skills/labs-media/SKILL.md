---
name: labs-media
description: Piloter les frameworks multimédia locaux (FFmpeg, OpenCV, Pillow, MoviePy 2.x, scikit-image) du conteneur Docker lab-media, pour traiter/convertir des images et des vidéos et faire du montage. Charger quand une mission demande de la manipulation d'image, de vidéo ou du montage.
---

# labs-media — image / vidéo / montage

Conteneur `lab-media` (python:3.11-slim) : FFmpeg, OpenCV, Pillow, MoviePy 2.x,
scikit-image. Séparé du dépôt Spectre.

## Accès
```shell
cd C:\Users\sherp\labs
docker compose up -d lab-media
# entrées/sorties dans shared\ (monté sur /work/shared)
docker exec -i lab-media bash -lc '<commande>'
```
Partage hôte ↔ conteneur : `C:\Users\sherp\labs\shared` ↔ `/work/shared`.

## FFmpeg (le couteau suisse vidéo/audio)
```shell
# transcoder en H.264
docker exec -i lab-media bash -lc 'ffmpeg -i /work/shared/in.mov -c:v libx264 -crf 20 /work/shared/out.mp4'
# extraire les frames (1 image/s)
docker exec -i lab-media bash -lc 'ffmpeg -i /work/shared/in.mp4 -vf fps=1 /work/shared/frame_%04d.png'
# extraire l'audio en WAV 16 kHz mono (utile pour labs-biometrie voix)
docker exec -i lab-media bash -lc 'ffmpeg -i /work/shared/in.mp4 -ac 1 -ar 16000 /work/shared/audio.wav'
```

## Montage vidéo (MoviePy 2.x)
Script de démo : `video_demo.py` (3 diapos + fondus → MP4 H.264). À adapter.
```shell
docker exec -i lab-media bash -lc 'python /work/shared/video_demo.py /work/shared/montage.mp4'
```
API MoviePy **2.x** (attention, l'API a changé vs 1.x) :
`ImageClip(arr).with_duration(2)`, `clip.with_effects([vfx.CrossFadeIn(0.8)])`,
`concatenate_videoclips(clips, method="compose", padding=-0.8)`,
`video.write_videofile(out, fps=24, codec="libx264", audio=False)`.
Pour du texte, OpenCV (`cv2.putText`) évite les soucis de police de `TextClip`.

## OpenCV / images
`cv2.imread` renvoie du **BGR** ; convertir en RGB pour MoviePy/affichage
(`cv2.cvtColor(img, cv2.COLOR_BGR2RGB)`). Pour du headless, `opencv-python-headless`
est installé (pas de fenêtre GUI).

## Vérifier une sortie
```shell
docker exec -i lab-media bash -lc \
  'ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate -of default=noprint_wrappers=1 /work/shared/out.mp4'
```

Doc frameworks : passer par Context7. Détails env : `C:\Users\sherp\labs\README.md`.
