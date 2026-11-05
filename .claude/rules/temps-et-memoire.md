---
paths:
  - "src/spectre/assistant/timeline.py"
  - "src/spectre/assistant/memory.py"
  - "src/spectre/assistant/db.py"
  - "src/spectre/assistant/brain.py"
  - "src/spectre/assistant/missions.py"
  - "src/spectre/assistant/routines.py"
  - "tests/test_assistant_timeline.py"
---

# Temps et mémoire

- Horodatage stocké en UTC (`db.now_iso`) ; affichage dans le fuseau IANA du réglage `timezone`
  (`timeline.zone`).
- Le modèle ne devine jamais la date ni l'heure : `timeline.block` les donne à chaque tour.
- Une visite = énoncés de l'utilisateur, tous canaux confondus, sans trou de plus de 30 min.
- Mission : queued → running → done | failed | cancelled ; un redémarrage note
  `mission_interrupted` puis remet en file (`MissionEngine.recover`).
- Mémoire : rien n'est effacé (fusion vérifiée, `superseded_by`), sauvegarde avant compactage,
  règles et confidences verrouillées.
- Tests : dates fixes avec fuseau explicite.
