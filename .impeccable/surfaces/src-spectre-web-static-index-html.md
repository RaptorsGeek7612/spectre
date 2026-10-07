---
version: 1
slug: "src-spectre-web-static-index-html"
primary_target: "src/spectre/web/static/index.html"
related_targets: []
---

## Scope

Spectre Web UI (`spectre-web`): the working app for the Scout → Scribe → Warden pipeline, plus its
demo mode, which also ships as the public preview page. Mode: **Operate**.

## Audience and task

The author runs requests and reads the reviewed text; demo viewers watch the chain work without a
key. Task: write a request, follow the three agents live, read final text / draft / brief /
Warden's corrections, check tokens and cost, find past runs again. Feature parity with Hermes WebUI
where it applies to Spectre (sessions, live streaming, stop/retry/edit, voice, presets, auth,
themes, settings centre, slash commands, export/import/share, mobile, PWA, notifications).

## Direction contract

THESIS: A run is a spectrogram plate: every agent is an emission line on one off-centre calibrated
rail, and its state is the line's form — solid live, dashed pending, half-height truncated, struck
failed, doubled sodium when a fallback model answered. Refuses the chat-bubble thread.

OWN-WORLD: Charcoal continuum ground (#121315 → #1C1D20 banding), bone text #E9E4D8, ash plates.
Colour exists only as hairline emission lines at real wavelengths: Scout 486 nm cyan, Scribe 546 nm
green, Warden 589 nm sodium yellow (doubled = alert/outranking), 656 nm deep red for errors.
Condensed grotesque, tracked caps for labels; wordmark in Big Shoulders Stencil, wide-tracked,
stencil breaks read as spectral gaps. Dashed outline = active/focused control.

STORY: The viewer sees the rail, the three lines, and understands "three specialists in order" in
one look; types a request, watches lines come alive one after another while text streams; reads the
final text, flips to the corrections as struck-and-replaced errata; sees cost per line.

FIRST VIEWPORT: Left rail column (240px) with the off-centre vertical calibrated rail, plate history
as ticks with plate numbers, search and new-plate on top. Centre: header band with the ghost-of-lines
logo + wordmark; under it the spectrogram band (full width, 180px) holding the three agent lines on
a wavelength axis; under that the composer (request field, preset, demo switch, voice, attach,
send/stop). Below, the plate: tabs Final / Draft / Brief / Corrections / Raw, text in bone on an ash
plate at 70ch. Right inspector (280px): per-agent tokens, cost magnitude dots, served model, timing,
total. Primary action: "Exposer" (send) at the composer's right end.

FORM: Challenger operate-c-emission-line-rail, chosen by the user over the assigned direction
(position 5 of my list, "Plaque spectrale"); seed key 051fa53f. Signature move: the agent emission
lines slide to their wavelength and damp with one overshoot when they go live; the logo's lines are
the same geometry and mirror pipeline progress.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Raises kept from declined challengers

- Lexicon: Warden's corrections render as struck-and-replaced errata.
- Doujin catalogue: every run gets a plate number (N° 0042) used in history and exports.
- Zoo map: one geometry — the logo's lines are the progress indicator.
- Star atlas: tokens/cost also read as dot magnitude on a fixed ramp.
- Emigre specimen: logo/wordmark proofed from 16px favicon to hero size.

## Open decisions

- Persisting run history location: `~/.spectre/webui/` (override `SPECTRE_WEBUI_STATE_DIR`).
- English UI strings as a second language (Hermes ships i18n); French is the default.
