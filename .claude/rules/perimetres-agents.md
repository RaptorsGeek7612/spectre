# Sous-agents de développement (`.claude/agents/`)

- L'`architecte-en-chef` découpe et attribue ; chaque lot n'a qu'un sous-agent propriétaire.
- Deux sous-agents en parallèle ne modifient jamais le même fichier (tableau des périmètres de
  la skill `spectre-conventions`).
- `expert-cybersecurite` est en lecture seule ; `agent-qa` possède `tests/**`.
- Aucun sous-agent ne commite, ne pousse ni ne fusionne : la session principale prépare, et
  c'est toujours l'utilisateur qui fusionne.
- Ne pas confondre avec les agents de Spectre (Gétro, Kaïto, Kyra…) : ceux-là sont nommés par
  l'utilisateur et définis dans `src/spectre/config.py` et `missions.SPECIALTIES`.
