---
name: Spectre
description: A three-agent Claude writing pipeline shown as a spectrogram plate; each agent is an emission line whose form is its state.
colors:
  ground: "#121315"
  continuum: "#17181b"
  plate: "#1b1c1f"
  plate-2: "#222327"
  hair: "#34363b"
  hair-2: "#4a4c52"
  bone: "#e9e4d8"
  ash: "#b3aea2"
  dim: "#8f8a7f"
  line-405-violet: "#a084ff"
  line-436-indigo: "#7d86ff"
  line-486-scout-cyan: "#4fc3f7"
  line-546-scribe-green: "#8bd450"
  line-589-warden-sodium: "#ffd23f"
  line-615-orange: "#ff9f43"
  line-656-error-red: "#ef5f6f"
typography:
  display:
    fontFamily: "Big Shoulders Stencil, Barlow Semi Condensed, sans-serif"
    fontSize: "clamp(2.6rem, 7vw, 5.2rem)"
    fontWeight: 200
    lineHeight: 0.9
    letterSpacing: "0.42em"
  wordmark-small:
    fontFamily: "Big Shoulders Stencil, Barlow Semi Condensed, sans-serif"
    fontSize: "1.32rem"
    fontWeight: 400
    lineHeight: 0.9
    letterSpacing: "0.36em"
  headline:
    fontFamily: "Barlow Semi Condensed, Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "1.55rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "0.01em"
  title:
    fontFamily: "Barlow Semi Condensed, Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.2
  numeral:
    fontFamily: "Barlow Semi Condensed, Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "1.9rem"
    fontWeight: 300
    lineHeight: 1
    letterSpacing: "0.02em"
    fontFeature: "\"tnum\" 1"
  body:
    fontFamily: "Barlow Semi Condensed, Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "1.06rem"
    fontWeight: 400
    lineHeight: 1.72
    fontFeature: "\"tnum\" 1"
  body-ui:
    fontFamily: "Barlow Semi Condensed, Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
    fontFeature: "\"tnum\" 1"
  label:
    fontFamily: "Barlow Semi Condensed, Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 500
    letterSpacing: "0.22em"
  control:
    fontFamily: "Barlow Semi Condensed, Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 500
    letterSpacing: "0.22em"
  meta:
    fontFamily: "Barlow Semi Condensed, Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 400
    letterSpacing: "0.04em"
rounded:
  none: "0px"
  dot: "50%"
spacing:
  hair: "2px"
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "18px"
  2xl: "22px"
  plate-pad: "clamp(18px, 3vw, 34px)"
  gutter: "clamp(16px, 3vw, 36px)"
components:
  button:
    backgroundColor: "transparent"
    textColor: "{colors.bone}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    padding: "0 16px 0 18px"
    height: "40px"
  button-primary:
    backgroundColor: "transparent"
    textColor: "{colors.bone}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    padding: "0 16px 0 18px"
    height: "40px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.line-656-error-red}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    padding: "0 16px 0 18px"
    height: "40px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.bone}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    height: "40px"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.ash}"
    rounded: "{rounded.none}"
    size: "38px"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.ash}"
    rounded: "{rounded.none}"
    padding: "0 12px"
    height: "32px"
  input:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.bone}"
    typography: "{typography.body-ui}"
    rounded: "{rounded.none}"
    padding: "0 10px"
    height: "38px"
  badge:
    backgroundColor: "transparent"
    textColor: "{colors.line-589-warden-sodium}"
    rounded: "{rounded.none}"
    padding: "3px 9px"
  run-row:
    backgroundColor: "transparent"
    textColor: "{colors.ash}"
    rounded: "{rounded.none}"
    padding: "7px 36px 7px 10px"
    height: "44px"
  run-row-current:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.bone}"
    rounded: "{rounded.none}"
  plate-body:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.bone}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "{spacing.plate-pad}"
  menu:
    backgroundColor: "{colors.plate-2}"
    textColor: "{colors.ash}"
    rounded: "{rounded.none}"
    padding: "6px"
  rail:
    backgroundColor: "{colors.continuum}"
    rounded: "{rounded.none}"
    padding: "18px 14px 12px 30px"
    width: "268px"
  inspector:
    backgroundColor: "{colors.continuum}"
    rounded: "{rounded.none}"
    padding: "18px 18px 24px"
    width: "300px"
---

# Design System: Spectre

## Overview

**Creative North Star: "The Emission-Line Rail"**

Spectre reads a run as a spectrogram plate. A charcoal continuum carries bone type, and colour exists only as hairline emission lines at real wavelengths: Scout at 486 nm, Scribe at 546 nm, Warden at the 589 nm sodium doublet, errors at 656 nm. Each agent is one line on a wavelength axis, and its state is the line's form: dashed while pending, solid and glowing while live, half-height when truncated, struck through on failure, doubled when a fallback model answered. The interface is a working instrument, not a chat thread; there are no bubbles, no avatars, no rounded cards.

Density is that of a tool: a fixed three-column workbench (history rail, work area, measurements inspector), condensed grotesque type, tracked uppercase labels and tabular numerals. Everything registers against hairlines and an off-centre vertical calibration rail in the history column. Depth is tonal, from ground to continuum to plate; shadows exist only for things that float. The same mark geometry serves as logo and progress indicator: the brand mark's lines dim, dash and come alive with the pipeline.

Two themes share one structure: the dark "spectrogram plate" (default) and a light "light table" in warm paper tones, where every emission colour is darkened to keep contrast on paper.

**Key Characteristics:**
- Charcoal tonal layering, bone text, colour only as 1-2px emission lines, ticks and dashed outlines.
- Line form encodes state: dashed, solid, half, struck, doubled.
- Square corners everywhere; circles only for magnitude dots and rail terminals.
- Condensed grotesque UI (Barlow Semi Condensed) with tracked caps labels; stencil wordmark (Big Shoulders Stencil).
- Dashed outline means active, selected or focused.
- Motion is physical: a spring overshoot when lines land, an expo ease-out for drawers and sheets.

## Colors

A near-neutral charcoal continuum and warm bone type, with seven saturated spectral lines used as hairlines rather than fills.

### Primary
- **Warden Sodium** (line-589-warden-sodium): the system's active colour. Focus outlines, the selected-tab underline, pressed chips and segmented options, the text caret, the live run tick, the demo badge, warnings, and Warden's line. Drawn doubled (two 1px lines 3px apart) where Warden or an alert outranks.

### Secondary
- **Scout Cyan** (line-486-scout-cyan): Scout's emission line, Scout's inspector rule, links and `#tag` text.
- **Scribe Green** (line-546-scribe-green): Scribe's line, the primary button's tick, completed run ticks, success toasts, inserted text (`ins`) in Warden's corrections.

### Tertiary
- **Error Red** (line-656-error-red, alias `--danger`): failures, the danger button, struck (`del`) text in corrections, the error toast tick, the strike across a failed agent line.
- **Violet 405, Indigo 436, Orange 615**: appear only in the mark, as the full spectrum of the helmet's crest. They carry no UI meaning.

### Neutral
- **Ground** (ground): page background, composer band, code blocks; also the PWA theme colour.
- **Continuum** (continuum): the rail, inspector and spectrogram band; the spectrogram's continuum is a procedurally banded canvas built from this tone with faint absorption lines.
- **Plate** (plate): the reading plate, inputs, the current run row, dialogs, the login plate.
- **Plate 2** (plate-2): floating surfaces (menus, slash menu, toasts) and inline code.
- **Hair** (hair): structural hairlines, field borders, row separators.
- **Hair 2** (hair-2): stronger hairlines, button borders, axes, the calibration rail, scrollbar hover.
- **Bone** (bone): primary text.
- **Ash** (ash): secondary text, inactive controls and rows.
- **Dim** (dim): labels, metadata, placeholders, axis numbers.

### Light theme ("light table")
`:root[data-theme="light"]` remaps every token: ground #e9e5da, continuum #e2ddd0, plate #f5f2ea, plate-2 #ece8de, hair #c9c3b4, hair-2 #a9a291, bone #1a1b1e, ash #4f4c45, dim #6b675e; lines 405 #6a3fd9, 436 #3c4cc7, 486 #0a679f, 546 #3a7d1c, 589 #7f5f00, 615 #b85a00, 656 #c0283f. Selection is `rgb(155 116 0 / 0.22)` instead of `rgb(255 210 63 / 0.28)`.

### Named Rules
**The Hairline Emission Rule.** Spectral colour is drawn, never filled: lines, ticks, underlines, dashed outlines, text. The only coloured fills are the 10% green wash on the primary button hover and the magnitude dots.

**The Wavelength Identity Rule.** Each agent owns its wavelength everywhere it appears (spectrogram, inspector rule, preset labels, mark line): Scout cyan, Scribe green, Warden sodium. Never reassign them.

**The Paper Darkening Rule.** In the light theme every line colour is darkened, never reused as-is; the dark-theme hex values fail contrast on paper.

## Typography

**Display Font:** Big Shoulders Stencil (with Barlow Semi Condensed, sans-serif)
**Body Font:** Barlow Semi Condensed (with Barlow, Segoe UI, system-ui, sans-serif)

**Character:** A stencil wordmark whose breaks read as spectral gaps, over a condensed instrument grotesque that sets text, labels and numbers. Both are self-hosted (`fonts/fonts.css`, OFL), Barlow Semi Condensed in 300/400/500/600, Big Shoulders Stencil as a 100-900 variable face.

The root size is adjustable: 15px by default, 13.5px (`data-font="small"`) or 17px (`data-font="large"`); every size is in rem. All text uses tabular numerals.

### Hierarchy
- **Display** (200, clamp(2.6rem, 7vw, 5.2rem), 0.9, tracked 0.42em, uppercase): the SPECTRE wordmark on the empty plate (hero) and the login plate at 2.6rem. Tracking tightens to 0.3em under 520px.
- **Wordmark small** (400, 1.32rem, tracked 0.36em, uppercase): the brand lockup in the rail and topbar.
- **Headline** (500, 1.55rem, 1.2, balanced wrap): the plate title (run title, editable in place). 1.3rem under 520px.
- **Title** (600, 1.6 / 1.25 / 1.08rem, 1.2): prose h1/h2/h3 inside the plate.
- **Numeral** (300, 1.9rem, 1): the run total cost in the inspector.
- **Body** (400, 1.06rem, 1.72): reading prose; measure capped at 60ch per block inside the plate (about 70 characters in this condensed face), plate view at 84ch.
- **Body UI** (400, 1rem, 1.6): controls and interface text; the composer field is 1.05rem at 1.55.
- **Label** (500, 0.72rem, tracked 0.22em, uppercase, dim): field labels, group names, inspector headings. Agent names on lines use 0.82rem at 0.26em in bone.
- **Control** (500, 0.8rem, tracked 0.22em, uppercase): buttons. Tabs, chips and segmented options use 0.74-0.76rem at 0.14-0.2em.
- **Meta** (400, 0.8rem, 0.04em, dim): plate number, date, version, help text.

### Named Rules
**The Tracked Caps Rule.** Uppercase is always tracked (0.1em minimum, 0.22em for labels and buttons). Running text is never uppercase.

**The Plate Number Rule.** Runs are named by plate number (`N° 0042`) in meta and history; numerals stay tabular so columns of costs and tokens align.

## Layout

A three-column workbench on a CSS grid: rail (268px) | work area (minmax(0, 1fr)) | inspector (300px), full viewport height (100dvh). The rail and inspector are sticky full-height columns. The work area stacks the spectrogram band (188px tall), the composer, then the plate. Horizontal page gutters are `clamp(16px, 3vw, 36px)`; plate padding is `clamp(18px, 3vw, 34px)`.

The spectrogram maps wavelength to position: an agent at `--nm` sits at `(nm − 430) / (665 − 430)` of the band width, over a 28px axis with ticks at 450-650 nm. The rail carries an off-centre vertical calibration rail 15px from its left edge, ending in two small circles; every run row hangs an 11px tick on it.

Spacing is tight and hairline-driven: 2, 6, 8, 10, 12, 14, 16, 18, 22px recur. Controls are 38-42px tall, run rows 44px.

### Responsive
- **≤1279px:** the inspector leaves the grid and becomes a right drawer (`translateX(105%)`, 0.45s expo out, shadow); a topbar (52px) appears with an inspector toggle.
- **≤899px:** one column. The rail becomes a left drawer (max 86vw) behind a scrim; the topbar is sticky; the spectrogram is 150px and hides model names; the plate comes before the composer, and the composer docks sticky at the bottom with safe-area padding. Buttons and icon buttons grow to 44px targets; preset grids collapse to one column; the settings sheet goes full width.
- **≤520px:** the spectrogram is 160px and agent tags step down in three rows (6, 47, 88px) on a continuum mat, Warden right-aligned, so labels never collide; odd axis labels and the "nm" unit hide; the composer bar stays on one row.
- **hover: none:** row action buttons are always visible.

### Named Rules
**The One Geometry Rule.** Wavelength position is the only horizontal logic in the spectrogram; agent lines never move to make room, their tags do.

## Elevation & Depth

Depth is tonal first. Ground, continuum, plate and plate-2 step up in lightness by about 2-4% each; panels are separated by 1px hairlines, not shadows. A single shadow exists, and only on surfaces that float above the workbench: menus, the slash menu, toasts, dialogs and the off-canvas drawers. Live agent lines glow with a coloured box-shadow; that glow is emission, not elevation.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 6px 14px -6px rgb(0 0 0 / 0.55)`; light theme `rgb(40 32 10 / 0.28)`): menus, toasts, dialogs, drawers.
- **Emission glow** (`0 0 10px 1px color-mix(in srgb, var(--c) 70%, transparent), 0 0 34px 6px color-mix(in srgb, var(--c) 22%, transparent)`): a live agent line. A finished line keeps `0 0 8px` at 45%.
- **Doublet** (`4px 0 0 var(--c)`): a second copy of a 1-1.5px line 4px to its right, meaning a fallback model answered (also on the inspector rule; 3px on the checked switch needle). It is the world's spectral doublet drawn with box-shadow, applied only to lines, never to surfaces.
- **Backdrop** (`rgb(8 8 10 / 0.6)`, scrim 0.55): behind dialogs and open drawers.

### Named Rules
**The Float-Only Shadow Rule.** Anything in the grid is flat. Only menus, toasts, dialogs and drawers cast the float shadow.

## Shapes

Every surface, control and field is square (0 radius); inputs explicitly reset to `border-radius: 0`. Borders are 1px hairlines. Circles appear in exactly two places: cost magnitude dots (3-16px, sized on a fixed log scale) and the rail's terminal rings. The app icon tile uses a 13/64 rounded square, which belongs to the icon, not the UI.

Lines are the form language: 1px ticks on buttons and toasts, a 1.5px emission line per agent, 2px selection underlines. State is drawn by changing a line's dash, length, count or by striking it at −35°.

### The Mark
The logo is a Spartan's Corinthian helmet in three-quarter view, crested with Spectre's spectrum (generated by `tools/make_logo.py`, the single source of truth). Full mark, `static/logo.svg`: a gunmetal shell with a riveted rim, a raised brow band engraved with a Greek key, an almond eye opening lit cyan with a slow scan line, a nasal guard, long pointed cheek guards and a flared neck guard, tattoo-style hatching in the shadows. The technical layer: a sensor disc at the temple (graduated crown, sixteen vents, a pulsing cyan core) and engraved circuit buses on the cheek and dome, one carrying a cyan data pulse. The crest is horsehair in the seven emission colours (405 to 656 nm, front to back), tall at about 40 % of the helmet, curling forward at the top and falling along the neck at the back; it draws itself strand by strand on load. Small mark, the inline `<symbol id="mark">`: the same silhouette with the crest reduced to seven clean arcs; the 486, 546 and 589 nm arcs carry the `agent-scout`, `agent-scribe` and `agent-warden` classes, so the brand mark still doubles as the pipeline progress indicator. `favicon.svg` and the PNG icons (32, 180, 192, 512, maskable 512) are rendered from the small mark on a #121315 tile.

## Components

Controls are quiet outlines that mark state with a line: square, hairline-bordered, tracked caps, never filled.

### Buttons
- **Shape:** square (0), 1px hair-2 border, 40px tall (44px under 900px), padding 0 16px 0 18px, 10px gap to an 18px icon.
- **Tick:** every button carries a 1px vertical tick 7px from its left edge; its colour is the button's meaning (hair-2 default, Scribe green for primary, red for danger).
- **Primary** ("Exposer", "Entrer", "Enregistrer"): transparent with a green tick; hover adds a 10% green wash.
- **Hover / Active:** hover turns the border bone; active or `aria-pressed` turns the border dashed. Disabled is 45% opacity.
- **Danger:** red text, red tick, red border at 55%.
- **Ghost:** borderless until hover (hair-2). Used for "Nouvelle plaque" and "Réglages".
- **Icon button:** 38px square (44px compact), ash glyph, borderless until hover; pressed state is a dashed sodium border with sodium glyph.

### Chips
- **Style:** 32px, transparent, 1px hair border, ash text, 0.76rem tracked caps.
- **State:** pressed (`aria-pressed`) gets a dashed sodium border and bone text.

### Segmented control
A hair-2 bordered row of uppercase buttons divided by hairlines; the selected option gets a 1px dashed sodium outline inset 4px.

### Switch
A 34×16 hairline track with a 1px needle; checked slides the needle 25px with the spring easing, turns it sodium and doubles it (`3px 0 0`).

### Inputs / Fields
- **Style:** plate background, 1px hair border, square, bone text, sodium caret, dim placeholder. 38px (search), 42px (login), 34-36px (selects, presets).
- **Focus:** the border becomes 1px dashed sodium; no glow.
- **Error:** a red message line under the field (`form-error`, 0.86rem).

### Navigation: the rail
- **Run rows:** 44px grid rows (plate number, title, cost with a magnitude dot; tags and project on a second line). Each row hangs a tick on the calibration rail whose form is the run status: green done, red error, sodium blinking running, dashed dim cancelled. Hover draws a hair border; the current row gets a dashed hair-2 border, plate background and a thicker 14×2px tick. A row action button fades in on hover or focus.
- **Tabs:** 42px uppercase tracked tabs in dim; selected is bone with a 2px sodium underline; a tab still being written carries a 1px sodium tick.
- **Mobile:** the rail and inspector become drawers with a scrim; a sticky topbar carries menu, mark, title, demo badge and inspector toggle.

### The spectrogram (signature)
A 188px continuum band with the three agent lines on the wavelength axis. Each line is 1.5px in its agent colour, with a tag (name in tracked caps, served model, status) offset to its right.
- **idle:** dashed (6px on, 5px off), 55% opacity, 62% height.
- **live:** solid, full height, emission glow, breathing at 1.4s.
- **done:** solid, soft glow.
- **truncated:** half height.
- **fallback:** doubled (hard 4px offset copy).
- **error:** red, struck by a 19px line at −35°.
- **cancelled:** short dashes (3px on, 4px off).
State changes animate `transform` with the spring easing (0.55s), so a line lands with one overshoot.

### Inspector (measurements)
Per agent, a section with a 1.5px left rule in the agent colour (dashed when idle, doubled on fallback, half-length when truncated), name and model, then a three-column grid of input tokens, output tokens and duration with tracked-caps labels, and the cost with a magnitude dot. The total sits in the 300-weight numeral; facts (plate, tokens, preset, mode) follow as a right-aligned definition list.

### Plate (reading surface)
A plate-coloured, hair-bordered panel holding the prose at 1.06rem/1.72. Corrections render as errata: removed text struck in red (`del`), added text in green with a dashed green underline (`ins`). A streaming caret is a 1px sodium bar blinking in steps.

### Floating surfaces
- **Menu / slash menu:** plate-2, hair-2 border, float shadow, 6px padding, 40px items; hover or selection is a dashed outline inset 2px. Slash commands name the command in sodium.
- **Settings sheet:** a right-hand dialog (max 640px, full height) sliding in 40px with the expo ease-out (0.45s); rows split label and control over a hairline with dim help text.
- **Command palette:** a 620px dialog at 12vh, 46px search field, dashed-outline selection.
- **Toast:** plate-2 with a 1px status tick (green, sodium for warn, red for error), entering 10px upward.
- **Badge:** dashed sodium outline with sodium tracked caps (demo mode).

### Motion
- **Easings:** `--spring` cubic-bezier(0.34, 1.56, 0.64, 1) for things that land (lines, switch needle); `--out` cubic-bezier(0.16, 1, 0.3, 1) for things that travel (drawers, sheet, palette, toasts, wordmark).
- **Mark landing:** on the hero and login marks each line rises from 35% height with a 70ms stagger (1.1s spring). The hero's sodium doublet then breathes (3.2s); hover splits the blue lines 2.5px left, the rest 2px right, like a dispersion.
- **Wordmark resolve:** three offset coloured exposures (cyan, red, sodium text-shadows) converge into one sharp word over 1.4s while tracking closes from 0.9em; a calibration rail with the three agent ticks draws under it.
- **Pipeline mirror:** while a run is active the brand mark dims to 25%, agent lines dash, the live agent's line blinks at 0.9s, finished agents turn solid.
- **Reduced motion:** all animations and transitions collapse to near-zero duration and one iteration.

## Do's and Don'ts

### Do:
- **Do** draw state as line form (dash, length, count, strike) in the owning agent's wavelength colour.
- **Do** mark focus, selection and pressed state with a 1px dashed sodium outline or border (offset 3px for focus-visible).
- **Do** give every button its 1px left tick, coloured by meaning.
- **Do** keep every surface and control square with 1px hairline borders, and build depth from ground → continuum → plate → plate-2.
- **Do** set labels and controls in tracked uppercase Barlow Semi Condensed and numbers in tabular figures.
- **Do** reserve the float shadow for menus, toasts, dialogs and drawers.
- **Do** use the spring easing for things that land and the expo out easing for things that travel, and respect reduced motion.
- **Do** darken every line colour in the light theme rather than reusing dark-theme values.

### Don't:
- **Don't** fill surfaces or buttons with spectral colour; colour is a hairline, a tick or text.
- **Don't** render runs as chat bubbles, avatars or message threads.
- **Don't** round corners on panels, controls or fields; circles are only magnitude dots and rail terminals.
- **Don't** give the 405, 436 or 615 nm colours UI meaning; they belong to the mark.
- **Don't** reassign an agent's colour or move a line off its wavelength position.
- **Don't** use shadows to separate panels inside the grid.
- **Don't** set running text in uppercase or set the wordmark in anything but Big Shoulders Stencil.
