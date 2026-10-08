"""Generate Spectre's logo: a Corinthian helmet with a crest of seven emission lines.

Run: `uv run python tools/make_logo.py`. Writes `static/logo.svg` (full, animated), `static/favicon.svg`
and the small `<symbol id="mark">` inlined in `index.html` and `assistant.html`. The PNG app icons
(`static/icons/`) are rasterised from `favicon.svg` with a headless browser at 32, 180, 192 and 512 px.

The helmet follows a sculpted Corinthian silhouette (brow band with a Greek key, eye with a scan line,
long pointed cheek guards, flared neck guard, riveted rim); its technical side is a sensor disc at the
temple and engraved circuit buses carrying a cyan pulse. The crest uses Spectre's seven wavelengths;
in the small mark the 486, 546 and 589 nm bands carry the Scout, Scribe and Warden classes.
"""

from __future__ import annotations

import math
import random
import re
from pathlib import Path

BANDS = ["#a084ff", "#7d86ff", "#4fc3f7", "#8bd450", "#ffd23f", "#ff9f43", "#ef5f6f"]
BONE, CYAN = "#e9e4d6", "#4fc3f7"
CX, CY = 214, 214  # crest arc centre, on the dome


def pt(r, a):
    return CX + r * math.cos(math.radians(a)), CY + r * math.sin(math.radians(a))


def bezier(p0, p1, p2, p3, t):
    u = 1 - t
    x = u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]
    return x, y


def crest(per_band=58, seed=7):
    return (
        strands(30, seed + 1, 3.4, 0.32, shift=-2.5, cls="")
        + strands(per_band, seed, 1.25, None, cls="hair")
        + strands(6, seed + 2, 0.9, 0.3, colour="#ffffff", shift=1.5, cls="hair")
    )


def strands(per_band, seed, width, alpha, colour=None, shift=0.0, cls="hair"):
    """A tall feathered plume, after the tattoo reference: it rises from the sheath, curls forward
    at the top and falls lower at the back; strands gather into pointed locks like feathers."""
    rnd, out = random.Random(seed), []
    root = ((152, 104), (192, 80), (252, 80), (292, 110))  # top edge of the sheath
    # outline in proportion with the helmet: as wide as the dome (brow to neck), its height about
    # 60 % of the helmet's, like the reference
    tip = ((102, 68), (98, -58), (318, -58), (384, 214))  # the back falls lower, along the neck
    locks = 30
    total = per_band * len(BANDS)
    for i in range(total):
        band = i * len(BANDS) // total
        t = (i + rnd.random()) / total
        lock = (round(t * locks) + rnd.uniform(-0.18, 0.18)) / locks  # strands gather into locks
        x1, y1 = bezier(*root, min(1.0, max(0.0, t + rnd.uniform(-0.015, 0.015))))
        x2, y2 = bezier(*tip, min(1.0, max(0.0, lock)))
        reach = 1 - 0.1 * abs(math.sin(lock * locks * math.pi))  # notched, feathery edge
        x2, y2 = x1 + (x2 - x1) * reach + shift * 2, y1 + (y2 - y1) * reach + abs(shift) * 3
        if not cls:  # the shadow layer stays a little inside the outline
            x2, y2 = x1 + (x2 - x1) * 0.92, y1 + (y2 - y1) * 0.92
        # rise straight out of the sheath, then curl forward at the tip, like windblown horsehair
        dx, dy = x2 - x1, y2 - y1
        c1x, c1y = x1 + dx * 0.15, y1 + dy * 0.45 - 10
        curl = 22 * (1 - t) + 6  # the front locks curl the most
        c2x, c2y = x2 + curl + rnd.uniform(-4, 4), y2 + 18 + rnd.uniform(-4, 4)
        op = alpha if alpha is not None else 0.6 + 0.4 * rnd.random()
        out.append(
            f'<path class="{cls}" d="M{x1:.1f} {y1:.1f} C{c1x:.1f} {c1y:.1f} {c2x:.1f} {c2y:.1f} {x2:.1f} {y2:.1f}" '
            f'stroke="{colour or BANDS[band]}" stroke-width="{width}" stroke-opacity="{op:.2f}" '
            f'style="--d:{band * 0.12 + t * 0.4:.2f}s"/>'
        )
    return "".join(out)


def crest_bands():
    out, a0, a1 = [], 202.0, 336.0
    step = (a1 - a0) / len(BANDS)
    for i, colour in enumerate(BANDS):
        x0, y0 = pt(132, a0 + i * step + 0.8)
        x1, y1 = pt(132, a0 + (i + 1) * step - 0.8)
        out.append(
            f'<path d="M{x0:.1f} {y0:.1f} A132 132 0 0 1 {x1:.1f} {y1:.1f}" stroke="{colour}" stroke-width="46"/>'
        )
    return "".join(out)


SHELL = (
    "M150 400 C132 360 116 300 108 252 C100 210 104 160 140 128 C178 96 252 92 296 126 "
    "C330 152 336 204 326 250 C320 292 330 340 352 392 C318 392 280 380 252 362 "
    "C226 346 214 330 206 318 C196 344 178 372 150 400 Z"
)
BAND = "M104 204 C150 178 252 170 332 198 L330 222 C252 194 152 202 106 228 Z"
EYE = "M116 243 C134 226 172 220 203 229 C194 247 160 258 121 256 Z"
GAP = "M101 236 L108 234 C110 268 116 300 128 338 C134 360 142 384 150 400 C136 380 122 350 112 318 C106 296 102 266 101 236 Z"
NASAL = "M104 228 L118 231 L122 298 C121 307 111 308 107 300 Z"
CHEEK_SEAM = "M198 232 C216 252 222 280 214 304 C211 312 208 316 206 318"
BOSS = (252, 262)


def defs():
    return f"""<defs>
<linearGradient id="steel" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="#4a4e57"/><stop offset=".35" stop-color="#2a2d33"/><stop offset=".75" stop-color="#17181c"/><stop offset="1" stop-color="#0c0d0f"/>
</linearGradient>
<linearGradient id="band" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#5a5e68"/><stop offset=".5" stop-color="#2c2f36"/><stop offset="1" stop-color="#15161a"/>
</linearGradient>
<radialGradient id="spec" cx=".32" cy=".2" r=".42">
  <stop offset="0" stop-color="#fff" stop-opacity=".55"/><stop offset=".35" stop-color="#fff" stop-opacity=".12"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
</radialGradient>
<radialGradient id="shade" cx=".78" cy=".78" r=".6">
  <stop offset="0" stop-color="#000" stop-opacity=".55"/><stop offset="1" stop-color="#000" stop-opacity="0"/>
</radialGradient>
<radialGradient id="core" cx=".5" cy=".5" r=".5">
  <stop offset="0" stop-color="#e8fbff"/><stop offset=".3" stop-color="{CYAN}"/><stop offset="1" stop-color="{CYAN}" stop-opacity="0"/>
</radialGradient>
<radialGradient id="eyeglow" cx=".42" cy=".55" r=".6">
  <stop offset="0" stop-color="{CYAN}" stop-opacity=".95"/><stop offset=".6" stop-color="{CYAN}" stop-opacity=".25"/><stop offset="1" stop-color="{CYAN}" stop-opacity="0"/>
</radialGradient>
<pattern id="hatch" width="3.6" height="3.6" patternUnits="userSpaceOnUse" patternTransform="rotate(-38)">
  <line x1="0" y1="0" x2="0" y2="3.6" stroke="#000" stroke-width=".9"/>
</pattern>
<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<clipPath id="shell"><path d="{SHELL}"/></clipPath>
</defs>"""


def greek_key():
    """Meander units placed and rotated along the band's centre curve."""
    curve = ((105, 216), (151, 190), (252, 182), (331, 210))
    out, n = [], 19
    for i in range(n):
        t = 0.06 + 0.88 * i / (n - 1)
        x, y = bezier(*curve, t)
        x2, y2 = bezier(*curve, t + 0.01)
        ang = math.degrees(math.atan2(y2 - y, x2 - x))
        out.append(
            f'<path transform="translate({x:.1f} {y:.1f}) rotate({ang:.1f})" '
            f'd="M-5 4 V-4 H4 V2 H-1 V-1"/>'
        )
    return "".join(out)


def bus(points, lanes=3, gap=6.5):
    """Parallel traces offset from a polyline (a PCB bus)."""
    paths = []
    for k in range(lanes):
        off = (k - (lanes - 1) / 2) * gap
        pts = []
        for i, (x, y) in enumerate(points):
            ax, ay = points[max(0, i - 1)]
            bx, by = points[min(len(points) - 1, i + 1)]
            dx, dy = bx - ax, by - ay
            ln = math.hypot(dx, dy) or 1
            pts.append((x - dy / ln * off, y + dx / ln * off))
        paths.append("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts))
    return paths


def circuits():
    cheek = bus([(236, 286), (222, 302), (222, 330), (200, 352), (180, 352)])
    neck = bus([(268, 286), (268, 320), (292, 344), (316, 352)], lanes=2)
    dome = bus([(214, 126), (214, 150), (232, 164), (232, 176)], lanes=2, gap=6)
    out = []
    for d in cheek[1:] + neck + dome:
        out.append(f'<path d="{d}" stroke="{BONE}" stroke-width="1.1" opacity=".45"/>')
    live = cheek[0]
    out.append(
        f'<path d="{live}" stroke="{CYAN}" stroke-width="1.7" opacity=".95" filter="url(#glow)"/>'
    )
    out.append(
        f'<path class="pulse" d="{live}" stroke="#e8fbff" stroke-width="2.2" stroke-dasharray="7 140"/>'
    )
    for d in cheek + neck + dome:
        x, y = d.split(" L")[-1].split()
        out.append(
            f'<circle cx="{x}" cy="{y}" r="2" fill="#0c0d0f" stroke="{BONE}" stroke-width="1"/>'
        )
    return "".join(out)


def boss():
    x, y = BOSS
    parts = [
        f'<circle cx="{x}" cy="{y}" r="27" fill="url(#band)" stroke="{BONE}" stroke-width="2"/>',
        f'<circle cx="{x}" cy="{y}" r="21" fill="none" stroke="#000" stroke-width="2" opacity=".6"/>',
        f'<circle cx="{x}" cy="{y}" r="19" fill="none" stroke="{BONE}" stroke-width="1" opacity=".6"/>',
    ]
    for k in range(16):  # radial vents, like an iris or a turbine
        a = math.radians(k * 22.5)
        parts.append(
            f'<path d="M{x + 11 * math.cos(a):.1f} {y + 11 * math.sin(a):.1f} '
            f'L{x + 18 * math.cos(a + 0.18):.1f} {y + 18 * math.sin(a + 0.18):.1f}" '
            f'stroke="{BONE}" stroke-width="1.2" opacity=".55"/>'
        )
    for k in range(36):
        a = math.radians(k * 10)
        r0 = 28.5 if k % 3 else 27.5
        parts.append(
            f'<path d="M{x + r0 * math.cos(a):.1f} {y + r0 * math.sin(a):.1f} '
            f'L{x + 31.5 * math.cos(a):.1f} {y + 31.5 * math.sin(a):.1f}" stroke="{BONE}" '
            f'stroke-width="0.9" opacity=".55"/>'
        )
    for k in range(4):
        a = math.radians(45 + k * 90)
        parts.append(
            f'<circle cx="{x + 23.5 * math.cos(a):.1f}" cy="{y + 23.5 * math.sin(a):.1f}" r="1.8" fill="{BONE}"/>'
        )
    parts.append(
        f'<circle cx="{x}" cy="{y}" r="9" fill="#08090b" stroke="{BONE}" stroke-width="1.2"/>'
    )
    parts.append(f'<circle class="core" cx="{x}" cy="{y}" r="7" fill="url(#core)"/>')
    parts.append(
        f'<path d="M{x - 20} {y - 14} A24 24 0 0 1 {x + 6} {y - 24}" stroke="#fff" stroke-width="2" opacity=".35" stroke-linecap="round"/>'
    )
    return "".join(parts)


def hatching():
    zones = [
        "M300 150 C330 180 334 230 322 262 C300 250 290 220 296 180 Z",  # back of dome
        "M214 300 C236 318 262 344 300 372 C276 374 246 360 222 342 C214 330 210 318 214 300 Z",  # cheek/neck
        "M118 262 C150 262 186 258 200 250 C206 280 196 310 178 340 C156 320 132 290 118 262 Z",  # under the eye
    ]
    return "".join(f'<path d="{z}" fill="url(#hatch)" opacity=".55"/>' for z in zones)


def rivets():
    pts = [
        (146, 384),
        (166, 360),
        (190, 334),
        (232, 352),
        (262, 370),
        (292, 382),
        (326, 384),
        (334, 340),
        (326, 300),
        (326, 262),
    ]
    return "".join(
        f'<circle cx="{x}" cy="{y}" r="2.1" fill="{BONE}" opacity=".8"/>' for x, y in pts
    )


def helmet_detailed():
    p = [
        defs(),
        f'<path d="{SHELL}" fill="url(#steel)"/>',
        '<g clip-path="url(#shell)" fill="none">',
    ]
    p.append(hatching())
    p.append(f'<path d="{SHELL}" fill="url(#shade)"/>')
    # rim: dark groove then a lighter edge band, all around
    p.append(f'<path d="{SHELL}" stroke="#08090b" stroke-width="22" opacity=".7"/>')
    p.append(f'<path d="{SHELL}" stroke="#3b3f47" stroke-width="16"/>')
    p.append(f'<path d="{SHELL}" stroke="{BONE}" stroke-width="16" opacity=".06"/>')
    # brow band in relief with the Greek key
    p.append(f'<path d="{BAND}" fill="url(#band)" stroke="{BONE}" stroke-width="1.4"/>')
    p.append(f'<g stroke="{BONE}" stroke-width="1" opacity=".8">{greek_key()}</g>')
    p.append(
        '<path d="M108 201 C152 176 252 168 330 195" stroke="#fff" stroke-width="1.5" opacity=".45"/>'
    )
    for d in ("M196 106 C190 140 186 166 184 184", "M264 108 C270 138 272 162 270 178"):
        p.append(f'<path d="{d}" stroke="#000" stroke-width="2.4" opacity=".55"/>')
        p.append(
            f'<path d="{d}" stroke="{BONE}" stroke-width="1" opacity=".5" transform="translate(-1 0)"/>'
        )
    for x, y in ((193, 130), (188, 160), (268, 132), (271, 158)):
        p.append(f'<circle cx="{x}" cy="{y}" r="1.7" fill="{BONE}" opacity=".7"/>')
    p.append(circuits())
    p.append(f'<path d="{CHEEK_SEAM}" stroke="#000" stroke-width="3" opacity=".6"/>')
    p.append(
        f'<path d="{CHEEK_SEAM}" stroke="{BONE}" stroke-width="1.2" opacity=".7" transform="translate(-1.5 -0.5)"/>'
    )
    p.append(
        '<path d="M296 260 C300 300 314 346 334 382" stroke="#000" stroke-width="2.5" opacity=".5"/>'
    )
    p.append(
        '<path d="M293 258 C297 300 311 346 331 382" stroke="#fff" stroke-width="1" opacity=".25"/>'
    )
    # speculars: dome, front edge of the cheek guard, the eyebrow ridge
    p.append(f'<path d="{SHELL}" fill="url(#spec)"/>')
    p.append(
        '<path d="M150 124 C186 102 236 98 272 112" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".28"/>'
    )
    p.append(
        '<path d="M118 268 C124 310 136 352 150 388" stroke="#fff" stroke-width="2" stroke-linecap="round" opacity=".3"/>'
    )
    p.append("</g>")
    p.append(boss())
    p.append(
        '<path d="M99 296 C102 332 116 366 138 394 C142 398 147 401 150 400 C132 372 118 340 110 300 Z" fill="#121316" stroke="#e9e4d6" stroke-width="1.2" stroke-opacity=".55" stroke-linejoin="round"/>'
    )
    p.append(f'<path d="{GAP}" fill="#050506"/>')
    p.append(f'<path d="{NASAL}" fill="url(#band)" stroke="{BONE}" stroke-width="1.4"/>')
    p.append(f'<path d="{EYE}" fill="#030304" stroke="{BONE}" stroke-width="1.6"/>')
    p.append(
        '<path d="M121 252 C152 254 184 246 198 233" fill="none" stroke="#000" stroke-width="3" opacity=".8"/>'
    )
    p.append('<ellipse class="eye" cx="160" cy="241" rx="32" ry="10" fill="url(#eyeglow)"/>')
    p.append(
        '<path class="scan" d="M126 242 C150 238 178 234 196 233" stroke="#e8fbff" stroke-width="1.2" opacity=".9" filter="url(#glow)"/>'
    )
    p.append(
        '<path d="M114 236 C138 218 176 213 206 224" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" opacity=".5"/>'
    )
    p.append(
        '<path d="M116 241 C139 224 175 219 204 229" fill="none" stroke="#000" stroke-width="2" opacity=".55"/>'
    )
    p.append(rivets())
    p.append(
        f'<path d="{SHELL}" fill="none" stroke="{BONE}" stroke-width="3" stroke-linejoin="round"/>'
    )
    p.append(
        f'<path d="M300 130 C332 156 338 206 328 250 C322 292 332 340 354 392" fill="none" stroke="{CYAN}" stroke-width="2" opacity=".55" filter="url(#glow)"/>'
    )
    # crest holder: a plate and posts carrying the plume
    sheath = "M146 122 C188 96 254 94 298 128 L292 110 C252 80 192 80 152 104 Z"
    p.append(
        f'<path d="{sheath}" fill="url(#band)" stroke="{BONE}" stroke-width="2" stroke-linejoin="round"/>'
    )
    p.append(
        '<path d="M154 106 C194 83 252 83 290 112" fill="none" stroke="#fff" stroke-width="1.4" opacity=".4"/>'
    )
    for x, y in ((172, 104), (204, 95), (238, 94), (270, 104)):
        p.append(f'<circle cx="{x}" cy="{y}" r="1.8" fill="{BONE}"/>')
    return "".join(p)


def helmet_small():
    return (
        defs() + f'<path d="{SHELL}" fill="url(#steel)"/><path d="{BAND}" fill="url(#band)"/>'
        f'<path d="{GAP}" fill="#050506"/><path d="{EYE}" fill="#030304"/>'
        f'<ellipse cx="160" cy="241" rx="30" ry="9" fill="url(#eyeglow)"/>'
        f'<circle cx="{BOSS[0]}" cy="{BOSS[1]}" r="22" fill="none" stroke="{BONE}" stroke-width="6"/>'
        f'<circle cx="{BOSS[0]}" cy="{BOSS[1]}" r="7" fill="{CYAN}"/>'
        f'<path d="{SHELL}" fill="none" stroke="{BONE}" stroke-width="9" stroke-linejoin="round"/>'
        f'<path d="M150 120 C190 98 252 98 294 128" fill="none" stroke="{BONE}" stroke-width="10" stroke-linecap="round"/>'
    )


def svg(detail=True):
    crest_g = crest() if detail else crest_bands()
    body = helmet_detailed() if detail else helmet_small()
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="24 20 380 400" role="img" aria-label="Spectre">'
        f'<g class="crest" fill="none" stroke-linecap="round">{crest_g}</g>{body}</svg>'
    )


# ---- outputs ------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "spectre" / "web" / "static"
PAGES = (STATIC / "index.html", STATIC / "assistant.html")
VIEWBOX = "24 20 380 400"  # small mark and icons
FULL_VIEWBOX = "40 -80 360 494"  # the full logo, with its tall plume
IDS = ("steel", "band", "spec", "shade", "core", "eyeglow", "hatch", "glow", "shell")
AGENTS = {2: "agent-scout", 3: "agent-scribe", 4: "agent-warden"}  # 486, 546, 589 nm bands
WAVES = ("405", "436", "486", "546", "589", "615", "656")
ANIMATION = """
.hair{stroke-dasharray:260;stroke-dashoffset:260;animation:draw 1.4s cubic-bezier(.2,.7,.2,1) forwards;animation-delay:var(--d)}
@keyframes draw{to{stroke-dashoffset:0}}
.eye{animation:wake 2.6s ease-in-out infinite alternate}
@keyframes wake{0%{opacity:.35}100%{opacity:1}}
.core{animation:core 1.8s ease-in-out infinite alternate;transform-box:fill-box;transform-origin:center}
@keyframes core{0%{opacity:.55;transform:scale(.8)}100%{opacity:1;transform:scale(1.1)}}
.pulse{animation:flow 2.4s linear infinite}
@keyframes flow{from{stroke-dashoffset:147}to{stroke-dashoffset:0}}
.scan{animation:scan 3.2s ease-in-out infinite}
@keyframes scan{0%,100%{opacity:.15;transform:translateY(5px)}50%{opacity:.95;transform:translateY(-3px)}}
@media (prefers-reduced-motion:reduce){.hair{animation:none;stroke-dashoffset:0}.eye,.core,.pulse,.scan{animation:none}}
"""


def prefixed(text: str, prefix: str) -> str:
    """Make gradient/filter ids unique per document (the symbol and the icons share a page)."""
    for name in IDS:
        text = text.replace(f'id="{name}"', f'id="{prefix}{name}"').replace(
            f"url(#{name})", f"url(#{prefix}{name})"
        )
    return text


def agent_bands() -> str:
    """Small crest: seven clean arcs; Scout, Scribe and Warden bands animate with the pipeline."""
    out, a0, a1 = [], 202.0, 336.0
    step = (a1 - a0) / len(BANDS)
    for i, colour in enumerate(BANDS):
        x0, y0 = pt(132, a0 + i * step + 0.8)
        x1, y1 = pt(132, a0 + (i + 1) * step - 0.8)
        classes = " ".join(c for c in ("mk-l", f"mk-{WAVES[i]}", AGENTS.get(i, "")) if c)
        out.append(
            f'<path class="{classes}" d="M{x0:.1f} {y0:.1f} A132 132 0 0 1 {x1:.1f} {y1:.1f}" '
            f'stroke="{colour}" style="stroke-width:46"/>'
        )
    return "".join(out)


def logo_svg() -> str:
    """The full, animated mark (hero, login, presence band)."""
    body = prefixed(helmet_detailed(), "lg-")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="'
        + FULL_VIEWBOX
        + '" role="img" aria-label="Spectre">'
        f"<style>{ANIMATION}</style>"
        f'<g fill="none" stroke-linecap="round">{crest()}</g>{body}</svg>\n'
    )


def symbol() -> str:
    """The small mark as an inline <symbol id="mark"> (menu, header)."""
    body = prefixed(helmet_small(), "mk-")
    return (
        f'<symbol id="mark" viewBox="{VIEWBOX}">'
        f'<g fill="none" stroke-linecap="butt">{agent_bands()}</g>{body}</symbol>'
    )


def favicon() -> str:
    body = prefixed(helmet_small(), "fv-")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="13" fill="#121315"/>'
        f'<svg x="5" y="3" width="54" height="58" viewBox="{VIEWBOX}">'
        f'<g fill="none">{crest_bands()}</g>{body}</svg></svg>\n'
    )


def main() -> None:
    (STATIC / "logo.svg").write_text(logo_svg(), encoding="utf-8")
    (STATIC / "favicon.svg").write_text(favicon(), encoding="utf-8")
    pattern = re.compile(r'<symbol id="mark" viewBox="[^"]*">.*?</symbol>', re.DOTALL)
    for page in PAGES:
        html = page.read_text(encoding="utf-8")
        if not pattern.search(html):
            raise SystemExit(f"symbole #mark introuvable dans {page.name}")
        page.write_text(pattern.sub(lambda _m: symbol(), html, count=1), encoding="utf-8")
    print("logo.svg, favicon.svg and the #mark symbols written in", STATIC)


if __name__ == "__main__":
    main()
